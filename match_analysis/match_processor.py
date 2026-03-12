"""Orchestrate per-match processing: extract events and insert into DuckDB."""

import json
import time
from pathlib import Path

import pandas as pd
import duckdb

from match_analysis.extractors import (
    extract_life_segments,
    build_segment_lookup,
    extract_combat_events,
    extract_position_events,
    extract_wool_events,
)
from match_analysis.team_extractor import (
    load_spawns_from_db,
    extract_team_segments,
)


def _bulk_insert(conn, table: str, match_id: int, df: pd.DataFrame,
                  columns: list[str], nullable_int_cols: list[str] = ()) -> int:
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


def _get_classifier(map_slug: str) -> 'PositionClassifier | None':
    """Build a PositionClassifier for the given map, or None if data missing."""
    context_path = Path(f'output/{map_slug}/map_context.json')
    graph_path = Path(f'output/{map_slug}/map_graph.json')
    if not context_path.exists() or not graph_path.exists():
        return None

    from match_analysis.position_classifier import PositionClassifier

    with open(context_path) as f:
        map_context = json.load(f)
    with open(graph_path) as f:
        map_graph = json.load(f)

    return PositionClassifier(map_context, map_graph)


def process_match(match_id: int) -> None:
    """Process a single match: extract all events and insert into DuckDB.

    Reads the raw parquet once, runs all extractors (life segments, combat,
    wool, position, team), annotates positions with spatial data, and
    bulk-inserts everything into the analysis database.
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
        life_segments_df = extract_life_segments(raw_df)

        print(f"Found {len(life_segments_df)} life segments")
        print(f"  Players: {life_segments_df['player_id'].nunique()}")
        print(f"  Total positions: {life_segments_df['position_count'].sum()}")
        print(f"  Total kills: {life_segments_df['kill_count'].sum()}")
        print(f"  Total wool captures: {life_segments_df['wool_captures'].sum()}")

        output_file = Path(f'match_analysis/trajectories/{match_id}.parquet')
        output_file.parent.mkdir(parents=True, exist_ok=True)

        life_segments_df.to_parquet(output_file, index=False)

        print(f"Saved life segment metadata to {output_file}")

        # Delete child tables first to avoid FK constraint violations when
        # re-inserting life_segments (child tables reference segment_id FK)
        conn.execute("DELETE FROM life_segment_features WHERE segment_id IN "
                     "(SELECT segment_id FROM life_segments WHERE match_id = ?)", [match_id])
        conn.execute("DELETE FROM life_segment_region_visits WHERE match_id = ?", [match_id])

        n = _bulk_insert(conn, 'life_segments', match_id, life_segments_df,
                         ['match_id', 'player_id', 'segment_idx',
                          'start_timestamp', 'end_timestamp', 'duration',
                          'outcome', 'spawn_x', 'spawn_z',
                          'position_count', 'kill_count',
                          'wool_touches', 'wool_captures'])
        print(f"Inserted {n} life segments into database")

        # Build segment lookup once — shared by combat, position, wool extractors
        find_segment_idx = build_segment_lookup(life_segments_df)

        # Extract and insert combat events
        combat_df = extract_combat_events(raw_df, find_segment_idx)
        n = _bulk_insert(conn, 'combat_events', match_id, combat_df,
                         ['match_id', 'timestamp', 'event_type', 'player_id',
                          'victim_id', 'x', 'y', 'z', 'held_item', 'segment_idx'],
                         nullable_int_cols=['segment_idx', 'victim_id', 'held_item'])
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
                        'nearest_island_1', 'nearest_island_2',
                        'nearest_graph_node']
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
             'nearest_island_1', 'nearest_island_2',
             'nearest_graph_node'],
            nullable_int_cols=['segment_idx', 'island_id',
                               'nearest_node_1', 'nearest_node_2',
                               'nearest_island_1', 'nearest_island_2',
                               'nearest_graph_node'])
        print(f"Inserted {n} position events into database")

        # Extract and insert team segments
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

        # Compute log_interval from median inter-sample gap
        if len(position_df) > 1:
            sorted_pos = position_df.sort_values(['player_id', 'segment_idx', 'timestamp'])
            dts = sorted_pos.groupby(['player_id', 'segment_idx'])['timestamp'].diff().dropna()
            median_gap = float(dts[dts > 0].median()) if len(dts[dts > 0]) > 0 else 2.0
            log_interval = 5 if median_gap >= 4.0 else 2
        else:
            log_interval = 2

        conn.execute(
            """
            UPDATE matches
            SET processed = TRUE,
                processed_at = CURRENT_TIMESTAMP,
                processing_time = ?,
                log_interval = ?
            WHERE match_id = ?
            """,
            [processing_time, log_interval, match_id],
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
