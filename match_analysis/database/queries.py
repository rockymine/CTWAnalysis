"""Match data service — life segment extraction and DB queries."""

import duckdb
import pandas as pd
from pathlib import Path


DB_PATH = 'match_analysis/metadata.db'


def get_match_file(match_id: int) -> tuple[str, str]:
    """Look up match file path and map slug from the database.

    Returns:
        (match_file, map_slug) tuple.  The match_file path is normalized
        to the current platform's separator convention.

    Raises:
        ValueError: If match_id not found in database.
    """
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        result = conn.execute(
            "SELECT mat.match_file, m.map_slug "
            "FROM matches mat "
            "JOIN maps m ON mat.map_id = m.map_id "
            "WHERE mat.match_id = ?",
            [match_id],
        ).fetchone()
    finally:
        conn.close()

    if not result:
        raise ValueError(f"Match {match_id} not found in database")

    # Normalize stored path to current platform (handles legacy backslash paths)
    match_file = str(Path(result[0].replace('\\', '/')))
    return match_file, result[1]


def get_match_map_slug(match_id: int) -> str:
    """Look up the map slug for a match.

    Raises:
        ValueError: If match_id not found in database.
    """
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        result = conn.execute(
            "SELECT m.map_slug "
            "FROM matches mat "
            "JOIN maps m ON mat.map_id = m.map_id "
            "WHERE mat.match_id = ?",
            [match_id],
        ).fetchone()
    finally:
        conn.close()

    if not result:
        raise ValueError(f"Match {match_id} not found in database")
    return result[0]


def extract_player_life_segments(
    match_id: int,
    player_id: int,
) -> list[dict]:
    """Extract life segments for a single player from the database.

    Each life segment spans from a SPAWN event to the next DEATH or end of
    match.  For each segment the trace events (kills, positions, wool events)
    are collected from the database tables.

    Args:
        match_id: Match ID in the database.
        player_id: Player ID to extract segments for.

    Returns:
        List of segment dicts, each containing:
            trace_events, positions, kills, wool_events (DataFrames),
            spawn_x, spawn_z, outcome, start_time, end_time.
    """
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        # Fetch life segments
        seg_rows = conn.execute(
            "SELECT segment_idx, start_timestamp, end_timestamp, outcome, "
            "       spawn_x, spawn_z "
            "FROM life_segments "
            "WHERE match_id = ? AND player_id = ? "
            "ORDER BY segment_idx",
            [match_id, player_id],
        ).fetchdf()

        if len(seg_rows) == 0:
            return []

        # Fetch all position events for this player+match in one query
        all_positions = conn.execute(
            "SELECT timestamp, x, z, segment_idx "
            "FROM position_events "
            "WHERE match_id = ? AND player_id = ? "
            "ORDER BY timestamp",
            [match_id, player_id],
        ).fetchdf()

        # Fetch combat events (kills, deaths) for this player+match
        all_combat = conn.execute(
            "SELECT timestamp, event_type, x, z, segment_idx "
            "FROM combat_events "
            "WHERE match_id = ? AND player_id = ? "
            "ORDER BY timestamp",
            [match_id, player_id],
        ).fetchdf()

        # Fetch wool events (touch/capture) for this player+match
        all_wool = conn.execute(
            "SELECT timestamp, event_type, x, z, segment_idx "
            "FROM wool_events "
            "WHERE match_id = ? AND player_id = ? "
            "ORDER BY timestamp",
            [match_id, player_id],
        ).fetchdf()

    finally:
        conn.close()

    segments = []
    for row in seg_rows.itertuples():
        seg_idx = row.segment_idx

        # Filter events for this segment
        pos = all_positions[all_positions['segment_idx'] == seg_idx]
        combat = all_combat[all_combat['segment_idx'] == seg_idx]

        kills = combat[combat['event_type'] == 3]
        wool = all_wool[all_wool['segment_idx'] == seg_idx]

        # trace_events = positions + kills + wool (matching old format)
        trace_parts = []
        if len(pos) > 0:
            trace_parts.append(pos[['timestamp', 'x', 'z']].assign(event_type=5))
        if len(kills) > 0:
            trace_parts.append(kills[['timestamp', 'x', 'z', 'event_type']])
        if len(wool) > 0:
            trace_parts.append(wool[['timestamp', 'x', 'z', 'event_type']])

        if trace_parts:
            trace_events = pd.concat(trace_parts, ignore_index=True).sort_values('timestamp')
        else:
            trace_events = pd.DataFrame(columns=['timestamp', 'x', 'z', 'event_type'])

        segments.append({
            'trace_events': trace_events,
            'positions': pos,
            'kills': kills,
            'wool_events': wool,
            'spawn_x': float(row.spawn_x),
            'spawn_z': float(row.spawn_z),
            'outcome': row.outcome,
            'start_time': row.start_timestamp,
            'end_time': row.end_timestamp,
        })

    return segments


def get_kill_death_pairs(
    match_id: int | None = None,
    match_ids: list[int] | None = None,
) -> pd.DataFrame:
    """Return paired kill/death positions by joining kill events with death events.

    Each row represents one kill: the killer's position (from the kill event,
    type 3) and the victim's position (from the matching death event, type 4).
    Team assignments are resolved via player_team_segments using the kill
    timestamp.

    Args:
        match_id: Single match ID to query.
        match_ids: List of match IDs to query (used for overlay mode).

    Returns:
        DataFrame with columns: match_id, killer_id, victim_id, kill_x, kill_z,
        death_x, death_z, killer_team, victim_team, timestamp.
    """
    base_query = (
        "SELECT k.match_id, k.player_id AS killer_id, k.victim_id, "
        "       k.x AS kill_x, k.z AS kill_z, "
        "       d.x AS death_x, d.z AS death_z, "
        "       kt.team AS killer_team, vt.team AS victim_team, "
        "       k.timestamp "
        "FROM combat_events k "
        "JOIN combat_events d "
        "  ON k.match_id = d.match_id "
        "  AND k.victim_id = d.player_id "
        "  AND k.timestamp = d.timestamp "
        "LEFT JOIN player_team_segments kt "
        "  ON k.match_id = kt.match_id "
        "  AND k.player_id = kt.player_id "
        "  AND k.timestamp >= kt.start_timestamp "
        "  AND (kt.end_timestamp IS NULL OR k.timestamp <= kt.end_timestamp) "
        "LEFT JOIN player_team_segments vt "
        "  ON d.match_id = vt.match_id "
        "  AND d.player_id = vt.player_id "
        "  AND d.timestamp >= vt.start_timestamp "
        "  AND (vt.end_timestamp IS NULL OR d.timestamp <= vt.end_timestamp) "
        "WHERE k.event_type = 3 AND d.event_type = 4 "
        "  AND k.victim_id IS NOT NULL"
    )

    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        if match_ids is not None:
            placeholders = ', '.join(['?'] * len(match_ids))
            result = conn.execute(
                f"{base_query} AND k.match_id IN ({placeholders}) "
                f"ORDER BY k.match_id, k.timestamp",
                match_ids,
            ).fetchdf()
        else:
            result = conn.execute(
                f"{base_query} AND k.match_id = ? "
                f"ORDER BY k.timestamp",
                [match_id],
            ).fetchdf()
    finally:
        conn.close()

    return result


def resolve_match_ids(match_arg: str | list[int], map_slug: str) -> list[int] | None:
    """Resolve a match CLI argument to a list of match IDs.

    Handles the 'ALL' sentinel (queries DB for all processed matches on the
    given map) or passes through the already-parsed list[int].

    Args:
        match_arg: 'ALL' or list[int] from _match_arg parser.
        map_slug: Map slug to filter by when match_arg is 'ALL'.

    Returns:
        List of match IDs, or None if 'ALL' yielded no results.
    """
    if match_arg == 'ALL':
        conn = duckdb.connect(DB_PATH, read_only=True)
        try:
            rows = conn.execute(
                "SELECT mat.match_id FROM matches mat "
                "JOIN maps m ON mat.map_id = m.map_id "
                "WHERE m.map_slug = ? AND mat.processed = TRUE "
                "ORDER BY mat.match_id",
                [map_slug],
            ).fetchall()
        finally:
            conn.close()
        match_ids = [r[0] for r in rows]
        if not match_ids:
            return None
        print(f"Found {len(match_ids)} processed matches for map '{map_slug}'.")
        return match_ids
    return match_arg


def validate_match_ids(match_ids: list[int], map_slug: str) -> list[int]:
    """Filter match IDs to only those belonging to the given map.

    Prints warnings for missing or mismatched matches.

    Args:
        match_ids: List of match IDs to validate.
        map_slug: Expected map slug.

    Returns:
        List of valid match IDs (may be empty).
    """
    valid = []
    for match_id in match_ids:
        try:
            db_map_slug = get_match_map_slug(match_id)
        except ValueError as e:
            print(f"Error: {e}")
            continue
        if db_map_slug != map_slug:
            print(f"Skipping match {match_id}: map is '{db_map_slug}', not '{map_slug}'")
            continue
        valid.append(match_id)
    return valid


def get_region_visits_with_paths(
    match_id: int,
    segment_id: int | None = None,
) -> pd.DataFrame:
    """Return life_segment_region_visits with node path data for a match.

    Includes entry_node, exit_node, bridge_node_1/2, and node_path parsed
    from JSON to Python lists.

    Args:
        match_id: Match ID in the database.
        segment_id: Optional segment ID to filter to a single segment.

    Returns:
        DataFrame with all visit columns.
    """
    import json as _json
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        where = "WHERE match_id = ?"
        params: list = [match_id]
        if segment_id is not None:
            where += " AND segment_id = ?"
            params.append(segment_id)
        df = conn.execute(
            f"SELECT * FROM life_segment_region_visits {where} ORDER BY segment_id, visit_idx",
            params,
        ).fetchdf()
    finally:
        conn.close()
    if 'node_path' in df.columns:
        df['node_path'] = df['node_path'].apply(
            lambda v: _json.loads(v) if v is not None else []
        )
    return df


def get_match_player_ids(match_id: int) -> list[int]:
    """Return sorted list of unique player IDs for a match from the database."""
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        rows = conn.execute(
            "SELECT DISTINCT player_id FROM life_segments "
            "WHERE match_id = ? ORDER BY player_id",
            [match_id],
        ).fetchall()
    finally:
        conn.close()
    return [int(r[0]) for r in rows]
