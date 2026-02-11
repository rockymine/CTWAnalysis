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

        # Fetch all combat events (kills, deaths, wool) for this player+match
        all_combat = conn.execute(
            "SELECT timestamp, event_type, x, z, segment_idx "
            "FROM combat_events "
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
        wool_events = combat[combat['event_type'].isin([6, 7])]

        # trace_events = positions + kills + wool (matching old format)
        trace_parts = []
        if len(pos) > 0:
            trace_parts.append(pos[['timestamp', 'x', 'z']].assign(event_type=5))
        if len(kills) > 0:
            trace_parts.append(kills[['timestamp', 'x', 'z', 'event_type']])
        if len(wool_events) > 0:
            trace_parts.append(wool_events[['timestamp', 'x', 'z', 'event_type']])

        if trace_parts:
            trace_events = pd.concat(trace_parts, ignore_index=True).sort_values('timestamp')
        else:
            trace_events = pd.DataFrame(columns=['timestamp', 'x', 'z', 'event_type'])

        segments.append({
            'trace_events': trace_events,
            'positions': pos,
            'kills': kills,
            'wool_events': wool_events,
            'spawn_x': float(row.spawn_x),
            'spawn_z': float(row.spawn_z),
            'outcome': row.outcome,
            'start_time': row.start_timestamp,
            'end_time': row.end_timestamp,
        })

    return segments


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
