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


def _bulk_insert(conn, table: str, match_id: int, df: pd.DataFrame,
                  columns: list[str], nullable_int_cols: list[str] = ()):
    """Delete previous rows for match_id, then bulk-insert df into table.

    Args:
        conn: DuckDB connection.
        table: Target table name.
        match_id: Match ID (used for DELETE and added as column).
        df: DataFrame to insert.
        columns: Column names for INSERT (must include 'match_id').
        nullable_int_cols: Columns to cast to pandas Int64 (nullable integer).

    Returns:
        Number of rows inserted.
    """
    conn.execute(f"DELETE FROM {table} WHERE match_id = ?", [match_id])
    if len(df) == 0:
        return 0
    df['match_id'] = match_id
    for col in nullable_int_cols:
        df[col] = df[col].astype('Int64')
    col_list = ', '.join(columns)
    conn.execute(f"INSERT INTO {table} ({col_list}) SELECT {col_list} FROM df")
    return len(df)


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



def extract_life_segments_from_match(df: pd.DataFrame) -> pd.DataFrame:
    """Extract life segments from raw match DataFrame.

    Life segment = spawn -> death (or match end).
    Uses event_type codes:
    - 2: SPAWN (start of life)
    - 4: DEATH (end of life)
    - 1: MATCH_END (alternative end if no death)

    Args:
        df: Raw match DataFrame (from pd.read_parquet).

    Returns DataFrame with one row per life segment containing:
    - player_id, segment_idx
    - start_timestamp, end_timestamp, duration
    - outcome ('death' or 'match_end')
    - Event counts (kills, wool_touches, wool_captures, position_count)
    """
    sorted_df = df.sort_values(['player_id', 'timestamp'])

    # Build spawn/death tables with per-player ordinal index
    spawns = sorted_df[sorted_df['event_type'] == 2].copy()
    deaths = sorted_df[sorted_df['event_type'] == 4].copy()

    if len(spawns) == 0:
        return pd.DataFrame(columns=[
            'player_id', 'segment_idx', 'start_timestamp', 'end_timestamp',
            'duration', 'outcome', 'spawn_x', 'spawn_z',
            'position_count', 'kill_count', 'wool_touches', 'wool_captures',
        ])

    spawns['segment_idx'] = spawns.groupby('player_id').cumcount()
    deaths['segment_idx'] = deaths.groupby('player_id').cumcount()

    # Pair nth spawn with nth death per player
    segments = spawns[['player_id', 'segment_idx', 'timestamp', 'x', 'z']].rename(
        columns={'timestamp': 'start_timestamp', 'x': 'spawn_x', 'z': 'spawn_z'},
    )
    death_times = deaths[['player_id', 'segment_idx', 'timestamp']].rename(
        columns={'timestamp': 'end_timestamp'},
    )
    segments = segments.merge(death_times, on=['player_id', 'segment_idx'], how='left')

    # Segments without a death end at the player's last event
    last_ts = sorted_df.groupby('player_id')['timestamp'].last()
    no_death = segments['end_timestamp'].isna()
    segments.loc[no_death, 'end_timestamp'] = (
        segments.loc[no_death, 'player_id'].map(last_ts)
    )
    segments['outcome'] = no_death.map({True: 'match_end', False: 'death'})
    segments['duration'] = (
        segments['end_timestamp'] - segments['start_timestamp']
    ).astype(float)

    # Assign segment_idx to all events via merge_asof (backward = last spawn ≤ ts)
    events = sorted_df[sorted_df['event_type'].isin([3, 5, 6, 7])].copy()
    if len(events) > 0:
        spawn_keys = spawns[['player_id', 'timestamp', 'segment_idx']].sort_values(
            'timestamp',
        )
        events = events.sort_values('timestamp')
        events = pd.merge_asof(
            events, spawn_keys,
            on='timestamp', by='player_id', direction='backward',
            suffixes=('', '_seg'),
        )
        # Aggregate event counts per segment
        counts = events.groupby(['player_id', 'segment_idx'])['event_type'].agg(
            kill_count=lambda x: (x == 3).sum(),
            position_count=lambda x: (x == 5).sum(),
            wool_touches=lambda x: (x == 6).sum(),
            wool_captures=lambda x: (x == 7).sum(),
        ).reset_index()
        segments = segments.merge(counts, on=['player_id', 'segment_idx'], how='left')
    else:
        for col in ['kill_count', 'position_count', 'wool_touches', 'wool_captures']:
            segments[col] = 0

    # Fill NaN counts (segments with no matching events)
    for col in ['kill_count', 'position_count', 'wool_touches', 'wool_captures']:
        segments[col] = segments[col].fillna(0).astype(int)

    # Cast to final types
    segments['player_id'] = segments['player_id'].astype(int)
    segments['start_timestamp'] = segments['start_timestamp'].astype(int)
    segments['end_timestamp'] = segments['end_timestamp'].astype(int)

    return segments[['player_id', 'segment_idx', 'start_timestamp', 'end_timestamp',
                     'duration', 'outcome', 'spawn_x', 'spawn_z',
                     'position_count', 'kill_count', 'wool_touches', 'wool_captures']]


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


def extract_combat_events(
    df: pd.DataFrame, find_segment_idx,
) -> pd.DataFrame:
    """Extract kill and death events, each assigned to a life segment.

    Args:
        df: Raw match DataFrame (from pd.read_parquet).
        find_segment_idx: Callable from _build_segment_lookup().

    Returns:
        DataFrame with columns: player_id, timestamp, event_type,
        victim_id, x, y, z, segment_idx.
    """
    combat = df[df['event_type'].isin([3, 4])].copy()

    if len(combat) == 0:
        return pd.DataFrame(columns=[
            'player_id', 'timestamp', 'event_type',
            'victim_id', 'x', 'y', 'z', 'segment_idx',
        ])

    combat['segment_idx'] = combat.apply(
        lambda r: find_segment_idx(int(r['player_id']), r['timestamp']), axis=1
    )
    # Ensure victim_id column exists (some parquet schemas omit it)
    if 'victim_id' not in combat.columns:
        combat['victim_id'] = None

    return combat[['player_id', 'timestamp', 'event_type',
                    'victim_id', 'x', 'y', 'z', 'segment_idx']]


def extract_position_events(
    df: pd.DataFrame, find_segment_idx,
) -> pd.DataFrame:
    """Extract position events (type 5), each assigned to a life segment.

    Args:
        df: Raw match DataFrame (from pd.read_parquet).
        find_segment_idx: Callable from _build_segment_lookup().

    Returns:
        DataFrame with columns: player_id, timestamp, x, y, z, segment_idx.
    """
    positions = df[df['event_type'] == 5].copy()

    if len(positions) == 0:
        return pd.DataFrame(columns=[
            'player_id', 'timestamp', 'x', 'y', 'z', 'segment_idx',
        ])

    positions['segment_idx'] = positions.apply(
        lambda r: find_segment_idx(int(r['player_id']), r['timestamp']), axis=1
    )

    return positions[['player_id', 'timestamp', 'x', 'y', 'z', 'segment_idx']]


def extract_wool_events(
    df: pd.DataFrame, find_segment_idx,
) -> pd.DataFrame:
    """Extract wool touch/capture events (types 6/7), each assigned to a life segment.

    Args:
        df: Raw match DataFrame (from pd.read_parquet).
        find_segment_idx: Callable from _build_segment_lookup().

    Returns:
        DataFrame with columns: player_id, timestamp, event_type,
        wool_id, x, y, z, segment_idx.
    """
    wool = df[df['event_type'].isin([6, 7])].copy()

    if len(wool) == 0:
        return pd.DataFrame(columns=[
            'player_id', 'timestamp', 'event_type',
            'wool_id', 'x', 'y', 'z', 'segment_idx',
        ])

    wool['segment_idx'] = wool.apply(
        lambda r: find_segment_idx(int(r['player_id']), r['timestamp']), axis=1
    )
    if 'wool_id' not in wool.columns:
        wool['wool_id'] = None

    return wool[['player_id', 'timestamp', 'event_type',
                 'wool_id', 'x', 'y', 'z', 'segment_idx']]


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

        # Read parquet once — all extractors share this DataFrame
        raw_df = pd.read_parquet(match_file)

        print("Extracting life segments...")
        life_segments_df = extract_life_segments_from_match(raw_df)

        print(f"Found {len(life_segments_df)} life segments")
        print(f"  Players: {life_segments_df['player_id'].nunique()}")
        print(f"  Total positions: {life_segments_df['position_count'].sum()}")
        print(f"  Total kills: {life_segments_df['kill_count'].sum()}")
        print(f"  Total wool captures: {life_segments_df['wool_captures'].sum()}")

        output_file = Path(f'match_analysis/trajectories/{match_id}.parquet')
        output_file.parent.mkdir(parents=True, exist_ok=True)

        life_segments_df.to_parquet(output_file, index=False)

        print(f"Saved life segment metadata to {output_file}")

        n = _bulk_insert(conn, 'life_segments', match_id, life_segments_df,
                         ['match_id', 'player_id', 'segment_idx',
                          'start_timestamp', 'end_timestamp', 'duration',
                          'outcome', 'spawn_x', 'spawn_z',
                          'position_count', 'kill_count',
                          'wool_touches', 'wool_captures'])
        print(f"Inserted {n} life segments into database")

        # Build segment lookup once — shared by combat, position, wool extractors
        find_segment_idx = _build_segment_lookup(life_segments_df)

        # Extract and insert combat events
        combat_df = extract_combat_events(raw_df, find_segment_idx)
        n = _bulk_insert(conn, 'combat_events', match_id, combat_df,
                         ['match_id', 'timestamp', 'event_type', 'player_id',
                          'victim_id', 'x', 'y', 'z', 'segment_idx'],
                         nullable_int_cols=['segment_idx', 'victim_id'])
        print(f"Inserted {n} combat events into database")

        # Extract and insert wool events
        wool_df = extract_wool_events(raw_df, find_segment_idx)
        n = _bulk_insert(conn, 'wool_events', match_id, wool_df,
                         ['match_id', 'timestamp', 'event_type', 'player_id',
                          'wool_id', 'x', 'y', 'z', 'segment_idx'],
                         nullable_int_cols=['segment_idx', 'wool_id'])
        print(f"Inserted {n} wool events into database")

        # Extract and insert position events
        position_df = extract_position_events(raw_df, find_segment_idx)

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
            n_island = (bulk['location_type'] == 'island').sum()
            n_build = (bulk['location_type'] == 'build_region').sum()
            n_void = (bulk['location_type'] == 'void').sum()
            print(f"Spatial annotation: {n_island} island, "
                  f"{n_build} build, {n_void} void")
        else:
            for col in spatial_cols:
                position_df[col] = None

        n = _bulk_insert(
            conn, 'position_events', match_id, position_df,
            ['match_id', 'timestamp', 'player_id', 'x', 'y', 'z',
             'segment_idx', 'location_type', 'island_id',
             'nearest_node_1', 'nearest_node_2',
             'nearest_island_1', 'nearest_island_2'],
            nullable_int_cols=['segment_idx', 'island_id',
                               'nearest_node_1', 'nearest_node_2',
                               'nearest_island_1', 'nearest_island_2'])
        print(f"Inserted {n} position events into database")

        # Extract and insert team segments
        from match_analysis.team_extractor import (
            load_spawns_from_db, extract_team_segments,
        )

        spawn_centers = load_spawns_from_db(conn, map_id)

        if not spawn_centers:
            print(f"Warning: No spawns in map_spawns for map_id={map_id}")
            print("  Team segments will be marked 'unknown'")

        team_df = extract_team_segments(raw_df, spawn_centers)
        n = _bulk_insert(
            conn, 'player_team_segments', match_id, team_df,
            ['match_id', 'player_id', 'team',
             'start_timestamp', 'end_timestamp', 'spawn_x', 'spawn_z'],
            nullable_int_cols=['end_timestamp'])
        print(f"Inserted {n} team segments into database")

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
