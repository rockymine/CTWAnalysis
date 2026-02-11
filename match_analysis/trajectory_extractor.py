"""Extract life segments from raw match parquet files."""

import json
import pandas as pd
import duckdb
from pathlib import Path
import time


EVENT_TYPES = {
    0: "MATCH_START",
    1: "MATCH_END",
    2: "SPAWN",
    3: "KILL",
    4: "DEATH",
    5: "POSITION",
    6: "WOOL_TOUCH",
    7: "WOOL_CAPTURE",
}

_SPATIAL_COLUMNS = [
    'location_type', 'island_id',
    'nearest_node_1', 'nearest_node_2',
    'nearest_island_1', 'nearest_island_2',
]


def _get_classifier(map_slug: str):
    """Build a PositionClassifier for the given map, or None if data missing."""
    context_path = Path(f'output/{map_slug}/island_analysis/map_context.json')
    graph_path = Path(f'output/{map_slug}/map_graph.json')
    if not context_path.exists() or not graph_path.exists():
        return None

    from match_analysis.position_classifier import PositionClassifier

    with open(context_path) as f:
        map_context = json.load(f)
    with open(graph_path) as f:
        map_graph = json.load(f)

    return PositionClassifier(map_context, map_graph)


def _migrate_position_events_columns(conn):
    """Add spatial columns to position_events if they don't exist yet."""
    existing = {
        row[0] for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'position_events'"
        ).fetchall()
    }
    type_map = {'location_type': 'TEXT'}
    for col in _SPATIAL_COLUMNS:
        if col not in existing:
            col_type = type_map.get(col, 'INTEGER')
            conn.execute(
                f"ALTER TABLE position_events ADD COLUMN {col} {col_type}"
            )


def extract_life_segments_from_match(match_file: str) -> pd.DataFrame:
    """Extract life segments from raw match parquet.

    Life segment = spawn -> death (or match end).
    Uses event_type codes:
    - 2: SPAWN (start of life)
    - 4: DEATH (end of life)
    - 1: MATCH_END (alternative end if no death)

    Returns DataFrame with one row per life segment containing:
    - player_id, segment_idx
    - start_timestamp, end_timestamp, duration
    - outcome ('death' or 'match_end')
    - Event counts (kills, wool_touches, wool_captures)
    - All position records for this segment
    """
    df = pd.read_parquet(match_file)

    life_segments = []

    for player_id in df['player_id'].dropna().unique():
        player_df = df[df['player_id'] == player_id].sort_values('timestamp')

        spawn_events = player_df[player_df['event_type'] == 2]
        death_events = player_df[player_df['event_type'] == 4]

        for segment_idx, spawn_row in enumerate(spawn_events.itertuples()):
            start_time = spawn_row.timestamp

            # Find next death after this spawn
            next_deaths = death_events[death_events['timestamp'] > start_time]

            if len(next_deaths) > 0:
                end_time = next_deaths.iloc[0]['timestamp']
                outcome = 'death'
            else:
                end_time = player_df['timestamp'].iloc[-1]
                outcome = 'match_end'

            segment_events = player_df[
                (player_df['timestamp'] >= start_time)
                & (player_df['timestamp'] <= end_time)
            ]

            if len(segment_events) == 0:
                continue

            kill_count = len(segment_events[segment_events['event_type'] == 3])
            wool_touches = len(segment_events[segment_events['event_type'] == 6])
            wool_captures = len(segment_events[segment_events['event_type'] == 7])

            positions = segment_events[segment_events['event_type'] == 5]

            life_segments.append({
                'player_id': int(player_id),
                'segment_idx': segment_idx,
                'start_timestamp': int(start_time),
                'end_timestamp': int(end_time),
                'duration': float(end_time - start_time),
                'outcome': outcome,
                'spawn_x': float(spawn_row.x),
                'spawn_z': float(spawn_row.z),
                'position_count': len(positions),
                'kill_count': kill_count,
                'wool_touches': wool_touches,
                'wool_captures': wool_captures,
                'positions': positions.to_dict('records'),
            })

    return pd.DataFrame(life_segments)


def _build_segment_lookup(life_segments_df: pd.DataFrame):
    """Build a lookup function that maps (player_id, timestamp) to segment_idx.

    Returns a callable: find_segment_idx(player_id, timestamp) -> int | None
    """
    seg_lookup = {}
    for row in life_segments_df.itertuples():
        seg_lookup.setdefault(row.player_id, []).append(
            (row.start_timestamp, row.end_timestamp, row.segment_idx)
        )

    def find_segment_idx(player_id, ts):
        for start, end, idx in seg_lookup.get(player_id, []):
            if start <= ts <= end:
                return idx
        return None

    return find_segment_idx


def extract_combat_events(match_file: str, life_segments_df: pd.DataFrame) -> pd.DataFrame:
    """Extract kill and death events, each assigned to a life segment.

    Args:
        match_file: Path to raw match parquet file.
        life_segments_df: DataFrame from extract_life_segments_from_match().

    Returns:
        DataFrame with columns: player_id, timestamp, event_type,
        victim_id, x, y, z, segment_idx.
    """
    df = pd.read_parquet(match_file)
    combat = df[df['event_type'].isin([3, 4])].copy()

    if len(combat) == 0:
        return pd.DataFrame(columns=[
            'player_id', 'timestamp', 'event_type',
            'victim_id', 'x', 'y', 'z', 'segment_idx',
        ])

    find_segment_idx = _build_segment_lookup(life_segments_df)
    combat['segment_idx'] = combat.apply(
        lambda r: find_segment_idx(int(r['player_id']), r['timestamp']), axis=1
    )
    # Ensure victim_id column exists (some parquet schemas omit it)
    if 'victim_id' not in combat.columns:
        combat['victim_id'] = None

    return combat[['player_id', 'timestamp', 'event_type',
                    'victim_id', 'x', 'y', 'z', 'segment_idx']]


def extract_position_events(match_file: str, life_segments_df: pd.DataFrame) -> pd.DataFrame:
    """Extract position events (type 5), each assigned to a life segment.

    Args:
        match_file: Path to raw match parquet file.
        life_segments_df: DataFrame from extract_life_segments_from_match().

    Returns:
        DataFrame with columns: player_id, timestamp, x, y, z, segment_idx.
    """
    df = pd.read_parquet(match_file)
    positions = df[df['event_type'] == 5].copy()

    if len(positions) == 0:
        return pd.DataFrame(columns=[
            'player_id', 'timestamp', 'x', 'y', 'z', 'segment_idx',
        ])

    find_segment_idx = _build_segment_lookup(life_segments_df)
    positions['segment_idx'] = positions.apply(
        lambda r: find_segment_idx(int(r['player_id']), r['timestamp']), axis=1
    )

    return positions[['player_id', 'timestamp', 'x', 'y', 'z', 'segment_idx']]


def process_match(match_id: int):
    """Process a single match: extract life segments and save to parquet.

    This is Phase 1 - basic extraction only.
    Later phases will add position classification, phase segmentation,
    and role detection.
    """
    start_time = time.time()
    conn = duckdb.connect('match_analysis/metadata.db')

    try:
        result = conn.execute(
            "SELECT mat.match_file, m.map_id, m.map_slug, m.map_name "
            "FROM matches mat "
            "JOIN maps m ON mat.map_id = m.map_id "
            "WHERE mat.match_id = ?",
            [match_id],
        ).fetchone()

        if not result:
            print(f"Match {match_id} not found in database")
            return

        match_file_raw, map_id, map_slug, map_name = result
        # Normalize stored path to current platform (handles legacy backslash paths)
        match_file = str(Path(match_file_raw.replace('\\', '/')))
        print(f"\nProcessing match {match_id} ({map_name})")
        print(f"File: {match_file}")

        print("Extracting life segments...")
        life_segments_df = extract_life_segments_from_match(match_file)

        print(f"Found {len(life_segments_df)} life segments")
        print(f"  Players: {life_segments_df['player_id'].nunique()}")
        print(f"  Total positions: {life_segments_df['position_count'].sum()}")
        print(f"  Total kills: {life_segments_df['kill_count'].sum()}")
        print(f"  Total wool captures: {life_segments_df['wool_captures'].sum()}")

        output_file = Path(f'match_analysis/trajectories/{match_id}.parquet')
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Save metadata only (positions column dropped - will be used in later phases)
        metadata_df = life_segments_df.drop(columns=['positions'])
        metadata_df.to_parquet(output_file, index=False)

        print(f"Saved life segment metadata to {output_file}")

        # Clear any previous segments for this match (supports reprocessing)
        conn.execute(
            "DELETE FROM life_segments WHERE match_id = ?", [match_id]
        )

        # Bulk insert life segments into DuckDB
        metadata_df['match_id'] = match_id
        conn.execute("""
            INSERT INTO life_segments
                (match_id, player_id, segment_idx,
                 start_timestamp, end_timestamp, duration, outcome,
                 spawn_x, spawn_z,
                 position_count, kill_count, wool_touches, wool_captures)
            SELECT match_id, player_id, segment_idx,
                   start_timestamp, end_timestamp, duration, outcome,
                   spawn_x, spawn_z,
                   position_count, kill_count, wool_touches, wool_captures
            FROM metadata_df
        """)

        print(f"Inserted {len(metadata_df)} life segments into database")

        # Extract and insert combat events
        combat_df = extract_combat_events(match_file, life_segments_df)
        conn.execute(
            "DELETE FROM combat_events WHERE match_id = ?", [match_id]
        )
        combat_df['match_id'] = match_id
        combat_df['segment_idx'] = combat_df['segment_idx'].astype('Int64')
        combat_df['victim_id'] = combat_df['victim_id'].astype('Int64')
        conn.execute("""
            INSERT INTO combat_events
                (match_id, timestamp, event_type, player_id,
                 victim_id, x, y, z, segment_idx)
            SELECT match_id, timestamp, event_type, player_id,
                   victim_id, x, y, z, segment_idx
            FROM combat_df
        """)
        print(f"Inserted {len(combat_df)} combat events into database")

        # Extract and insert position events
        position_df = extract_position_events(match_file, life_segments_df)

        # Inline migration: add spatial columns to existing databases
        _migrate_position_events_columns(conn)

        conn.execute(
            "DELETE FROM position_events WHERE match_id = ?", [match_id]
        )
        position_df['match_id'] = match_id
        position_df['segment_idx'] = position_df['segment_idx'].astype('Int64')

        # Spatial annotation via PositionClassifier
        spatial_cols = ['location_type', 'island_id',
                        'nearest_node_1', 'nearest_node_2',
                        'nearest_island_1', 'nearest_island_2']
        classifier = _get_classifier(map_slug)
        if classifier is not None and len(position_df) > 0:
            import numpy as np
            xs = position_df['x'].values.astype(float)
            zs = position_df['z'].values.astype(float)
            bulk = classifier.classify_bulk(xs, zs)
            for col in spatial_cols:
                position_df[col] = bulk[col]
            # Cast nullable int columns
            for col in spatial_cols[1:]:
                position_df[col] = position_df[col].astype('Int64')
            n_island = (bulk['location_type'] == 'island').sum()
            n_build = (bulk['location_type'] == 'build_region').sum()
            n_void = (bulk['location_type'] == 'void').sum()
            print(f"Spatial annotation: {n_island} island, "
                  f"{n_build} build, {n_void} void")
        else:
            for col in spatial_cols:
                position_df[col] = None

        conn.execute("""
            INSERT INTO position_events
                (match_id, timestamp, player_id, x, y, z, segment_idx,
                 location_type, island_id,
                 nearest_node_1, nearest_node_2,
                 nearest_island_1, nearest_island_2)
            SELECT match_id, timestamp, player_id, x, y, z, segment_idx,
                   location_type, island_id,
                   nearest_node_1, nearest_node_2,
                   nearest_island_1, nearest_island_2
            FROM position_df
        """)
        print(f"Inserted {len(position_df)} position events into database")

        # Extract and insert team segments
        from match_analysis.team_extractor import (
            load_spawns_from_db, extract_team_segments,
        )

        spawn_centers = load_spawns_from_db(conn, map_id)

        if not spawn_centers:
            print(f"Warning: No spawns in map_spawns for map_id={map_id}")
            print("  Team segments will be marked 'unknown'")

        team_df = extract_team_segments(match_file, spawn_centers)

        # Auto-create table for existing databases (migration)
        conn.execute(
            "CREATE SEQUENCE IF NOT EXISTS seq_team_segment_id START 1"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS player_team_segments (
                team_segment_id INTEGER PRIMARY KEY
                    DEFAULT nextval('seq_team_segment_id'),
                match_id INTEGER NOT NULL,
                player_id INTEGER NOT NULL,
                team TEXT NOT NULL,
                start_timestamp BIGINT NOT NULL,
                end_timestamp BIGINT,
                spawn_x FLOAT,
                spawn_z FLOAT,
                FOREIGN KEY (match_id) REFERENCES matches(match_id)
            )
        """)

        conn.execute(
            "DELETE FROM player_team_segments WHERE match_id = ?", [match_id]
        )

        if len(team_df) > 0:
            team_df['match_id'] = match_id
            team_df['end_timestamp'] = team_df['end_timestamp'].astype('Int64')
            conn.execute("""
                INSERT INTO player_team_segments
                    (match_id, player_id, team,
                     start_timestamp, end_timestamp,
                     spawn_x, spawn_z)
                SELECT match_id, player_id, team,
                       start_timestamp, end_timestamp,
                       spawn_x, spawn_z
                FROM team_df
            """)

        print(f"Inserted {len(team_df)} team segments into database")

        team_time = time.time() - start_time
        conn.execute(
            """
            INSERT INTO processing_log (match_id, step, status, duration)
            VALUES (?, 'team_assignment', 'success', ?)
            """,
            [match_id, team_time],
        )

        processing_time = time.time() - start_time

        conn.execute(
            """
            UPDATE matches
            SET processed = TRUE,
                processed_at = CURRENT_TIMESTAMP,
                processing_time = ?
            WHERE match_id = ?
            """,
            [processing_time, match_id],
        )

        conn.execute(
            """
            INSERT INTO processing_log (match_id, step, status, duration)
            VALUES (?, 'trajectory_extraction', 'success', ?)
            """,
            [match_id, processing_time],
        )

        print(f"\nSuccessfully processed in {processing_time:.2f}s")

    except Exception as e:
        print(f"\nError processing match {match_id}: {e}")
        import traceback
        traceback.print_exc()

        conn.execute(
            """
            INSERT INTO processing_log (match_id, step, status, error_message)
            VALUES (?, 'trajectory_extraction', 'failed', ?)
            """,
            [match_id, str(e)],
        )

    finally:
        conn.close()
