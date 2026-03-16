"""Orchestrate per-match processing: extract events and insert into DuckDB.

The pipeline is split into two phases so that extraction can run in parallel
across multiple worker processes while all DB writes remain serial (DuckDB
only allows one writer at a time, and even read-only connections are blocked
while a write connection is open):

  _fetch_all_match_meta(match_ids, conn) -> dict[int, dict]
      Bulk-loads metadata (file path, map info, spawn centers) for a list of
      match IDs using a single read-only connection owned by the caller.

  extract_match_data(match_id, meta) -> dict
      Reads the parquet file and runs all CPU-bound extraction + classification
      in memory.  Receives pre-loaded metadata so it never opens the DB.

  insert_match_data(conn, data)
      Takes the result dict from extract_match_data and writes everything to
      the database through a single caller-owned write connection.

  process_match(match_id)
      Convenience wrapper: loads metadata, extracts, inserts.  Used for
      single-match processing and as the serial fallback in process-all.
"""

import json
import time
from pathlib import Path
from typing import Any

import pandas as pd
import duckdb

from match_analysis.processing.extractors import (
    extract_life_segments,
    build_segment_lookup,
    extract_combat_events,
    extract_position_events,
    extract_wool_events,
)
from match_analysis.processing.team_extractor import extract_team_segments


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


_classifier_cache: dict[str, Any] = {}


def _get_classifier(map_slug: str) -> 'PositionClassifier | None':
    """Build a PositionClassifier for the given map, or None if data missing.

    Results are cached in-process by map_slug — reading the JSON files once
    per map slug instead of once per match call.
    """
    if map_slug in _classifier_cache:
        return _classifier_cache[map_slug]

    context_path = Path(f'output/{map_slug}/map_context.json')
    graph_path = Path(f'output/{map_slug}/map_graph.json')
    if not context_path.exists() or not graph_path.exists():
        _classifier_cache[map_slug] = None
        return None

    from match_analysis.processing.position_classifier import PositionClassifier

    with open(context_path) as f:
        map_context = json.load(f)
    with open(graph_path) as f:
        map_graph = json.load(f)

    classifier = PositionClassifier(map_context, map_graph)
    _classifier_cache[map_slug] = classifier
    return classifier


def _compute_log_interval(position_df: pd.DataFrame) -> int:
    """Infer log interval (2s or 5s) from median inter-sample gap."""
    if len(position_df) > 1:
        sorted_pos = position_df.sort_values(['player_id', 'segment_idx', 'timestamp'])
        dts = sorted_pos.groupby(['player_id', 'segment_idx'])['timestamp'].diff().dropna()
        median_gap = float(dts[dts > 0].median()) if len(dts[dts > 0]) > 0 else 2.0
        return 5 if median_gap >= 4.0 else 2
    return 2


def _fetch_all_match_meta(
    match_ids: list[int],
    conn: 'duckdb.DuckDBPyConnection',
) -> dict[int, dict]:
    """Bulk-load metadata for a list of match IDs from an open connection.

    Returns a dict mapping match_id -> metadata dict with keys:
        match_file, map_id, map_slug, map_name, spawn_centers
    """
    if not match_ids:
        return {}

    placeholders = ', '.join('?' * len(match_ids))
    rows = conn.execute(
        f"SELECT mat.match_id, mat.match_file, m.map_id, m.map_slug, m.map_name "
        f"FROM matches mat "
        f"JOIN maps m ON mat.map_id = m.map_id "
        f"WHERE mat.match_id IN ({placeholders})",
        match_ids,
    ).fetchall()

    # Load all spawn centers in one query, keyed by map_id
    map_ids = list({row[2] for row in rows})
    spawns_by_map: dict[int, list[dict]] = {}
    if map_ids:
        spawn_ph = ', '.join('?' * len(map_ids))
        spawn_rows = conn.execute(
            f"SELECT map_id, x, z, min_x, min_z, max_x, max_z, team "
            f"FROM map_spawns WHERE map_id IN ({spawn_ph})",
            map_ids,
        ).fetchall()
        for map_id, x, z, min_x, min_z, max_x, max_z, team_raw in spawn_rows:
            team = team_raw.removesuffix('-team') if team_raw else team_raw
            entry = {
                'team': team,
                'x': float(x),
                'z': float(z),
                'bounds_2d': {
                    'min_x': float(min_x), 'min_z': float(min_z),
                    'max_x': float(max_x), 'max_z': float(max_z),
                },
            }
            spawns_by_map.setdefault(map_id, []).append(entry)

    result: dict[int, dict] = {}
    for match_id, match_file_raw, map_id, map_slug, map_name in rows:
        result[match_id] = {
            'match_file':    str(Path(match_file_raw.replace('\\', '/'))),
            'map_id':        map_id,
            'map_slug':      map_slug,
            'map_name':      map_name,
            'spawn_centers': spawns_by_map.get(map_id, []),
        }
    return result


def extract_match_data(match_id: int, meta: dict) -> dict:
    """Extract and classify all data for a match without touching the database.

    Parameters
    ----------
    match_id:
        The match to process.
    meta:
        Pre-loaded metadata dict (from _fetch_all_match_meta).  Must contain
        keys: match_file, map_id, map_slug, map_name, spawn_centers.

    Returns a dict containing all DataFrames and metadata needed by
    insert_match_data(), plus 'start_time' for processing-time bookkeeping.
    """
    start_time = time.time()

    match_file    = meta['match_file']
    map_id        = meta['map_id']
    map_slug      = meta['map_slug']
    map_name      = meta['map_name']
    spawn_centers = meta['spawn_centers']

    print(f"\nExtracting match {match_id} ({map_name})")

    if not spawn_centers:
        print(f"  Warning: No spawns in map_spawns for map_id={map_id}"
              " — team segments will be marked 'unknown'")

    # Read parquet once — all extractors share this DataFrame
    raw_df = pd.read_parquet(match_file)

    life_segments_df = extract_life_segments(raw_df)
    print(f"  {len(life_segments_df)} life segments, "
          f"{life_segments_df['position_count'].sum()} positions")

    # Save legacy trajectory parquet (kept for back-compat, not read anywhere)
    output_file = Path(f'match_analysis/trajectories/{match_id}.parquet')
    output_file.parent.mkdir(parents=True, exist_ok=True)
    life_segments_df.to_parquet(output_file, index=False)

    find_segment_idx = build_segment_lookup(life_segments_df)

    combat_df   = extract_combat_events(raw_df, find_segment_idx)
    wool_df     = extract_wool_events(raw_df, find_segment_idx)
    position_df = extract_position_events(raw_df, find_segment_idx)

    # Spatial annotation via PositionClassifier
    spatial_cols = ['location_type', 'island_id',
                    'nearest_node_1', 'nearest_node_2',
                    'nearest_island_1', 'nearest_island_2',
                    'nearest_graph_node']
    classifier = _get_classifier(map_slug)
    if classifier is not None and len(position_df) > 0:
        xs = position_df['x'].values.astype(float)
        zs = position_df['z'].values.astype(float)
        bulk = classifier.classify_bulk(xs, zs)
        for col in spatial_cols:
            position_df[col] = bulk[col]
    else:
        for col in spatial_cols:
            position_df[col] = None

    team_df      = extract_team_segments(raw_df, spawn_centers)
    log_interval = _compute_log_interval(position_df)

    return {
        'match_id':         match_id,
        'map_id':           map_id,
        'map_slug':         map_slug,
        'map_name':         map_name,
        'log_interval':     log_interval,
        'start_time':       start_time,
        'life_segments_df': life_segments_df,
        'combat_df':        combat_df,
        'wool_df':          wool_df,
        'position_df':      position_df,
        'team_df':          team_df,
    }


def insert_match_data(
    conn: 'duckdb.DuckDBPyConnection',
    data: dict,
) -> None:
    """Write extracted match data to DuckDB.

    Must be called with a single write connection — DuckDB does not support
    concurrent writers, so callers must serialise calls to this function.
    """
    match_id         = data['match_id']
    log_interval     = data['log_interval']
    start_time       = data['start_time']
    life_segments_df = data['life_segments_df']
    combat_df        = data['combat_df']
    wool_df          = data['wool_df']
    position_df      = data['position_df']
    team_df          = data['team_df']

    # Delete child tables first to avoid FK constraint violations when
    # re-inserting life_segments (child tables reference segment_id FK)
    seg_subquery = "(SELECT segment_id FROM life_segments WHERE match_id = ?)"
    conn.execute(f"DELETE FROM life_segment_summary WHERE segment_id IN {seg_subquery}", [match_id])
    conn.execute(f"DELETE FROM life_segment_skeleton_features WHERE segment_id IN {seg_subquery}", [match_id])
    conn.execute(f"DELETE FROM life_segment_traffic_features WHERE segment_id IN {seg_subquery}", [match_id])
    conn.execute("DELETE FROM life_segment_region_visits WHERE match_id = ?", [match_id])

    n = _bulk_insert(conn, 'life_segments', match_id, life_segments_df,
                     ['match_id', 'player_id', 'segment_idx',
                      'start_timestamp', 'end_timestamp', 'duration',
                      'outcome', 'spawn_x', 'spawn_z',
                      'position_count', 'kill_count',
                      'wool_touches', 'wool_captures'])
    print(f"  Inserted {n} life segments")

    n = _bulk_insert(conn, 'combat_events', match_id, combat_df,
                     ['match_id', 'timestamp', 'event_type', 'player_id',
                      'victim_id', 'x', 'y', 'z', 'held_item', 'segment_idx'],
                     nullable_int_cols=['segment_idx', 'victim_id', 'held_item'])
    print(f"  Inserted {n} combat events")

    n = _bulk_insert(conn, 'wool_events', match_id, wool_df,
                     ['match_id', 'timestamp', 'event_type', 'player_id',
                      'wool_id', 'x', 'y', 'z', 'segment_idx'],
                     nullable_int_cols=['segment_idx', 'wool_id'])
    print(f"  Inserted {n} wool events")

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
    print(f"  Inserted {n} position events")

    n = _bulk_insert(
        conn, 'player_team_segments', match_id, team_df,
        ['match_id', 'player_id', 'team',
         'start_timestamp', 'end_timestamp', 'spawn_x', 'spawn_z'],
        nullable_int_cols=['end_timestamp'])
    print(f"  Inserted {n} team segments")

    processing_time = time.time() - start_time

    conn.execute(
        "INSERT INTO processing_log (match_id, step, status, duration) "
        "VALUES (?, 'team_assignment', 'success', ?)",
        [match_id, processing_time],
    )
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
        "INSERT INTO processing_log (match_id, step, status, duration) "
        "VALUES (?, 'trajectory_extraction', 'success', ?)",
        [match_id, processing_time],
    )

    print(f"  Done in {processing_time:.2f}s")


def process_match(match_id: int) -> None:
    """Process a single match: extract all events and insert into DuckDB.

    Convenience wrapper around extract_match_data + insert_match_data.
    Used for single-match processing and as the serial fallback in process-all.
    """
    # Read metadata with a short-lived read-only connection, then close it
    # before opening the write connection (DuckDB exclusive file lock).
    conn_r = duckdb.connect('match_analysis/metadata.db', read_only=True)
    try:
        meta_map = _fetch_all_match_meta([match_id], conn_r)
    finally:
        conn_r.close()

    if match_id not in meta_map:
        print(f"Match {match_id} not found in database")
        return

    try:
        data = extract_match_data(match_id, meta_map[match_id])
    except Exception as e:
        print(f"\nError extracting match {match_id}: {e}")
        import traceback
        traceback.print_exc()
        _log_failure(match_id, str(e))
        return

    conn_w = duckdb.connect('match_analysis/metadata.db')
    try:
        insert_match_data(conn_w, data)
    except Exception as e:
        print(f"\nError inserting match {match_id}: {e}")
        import traceback
        traceback.print_exc()
        conn_w.execute(
            "INSERT INTO processing_log (match_id, step, status, error_message) "
            "VALUES (?, 'trajectory_extraction', 'failed', ?)",
            [match_id, str(e)],
        )
    finally:
        conn_w.close()


def _log_failure(match_id: int, error_message: str) -> None:
    """Write a failed processing_log entry. Opens its own connection."""
    try:
        conn = duckdb.connect('match_analysis/metadata.db')
        try:
            conn.execute(
                "INSERT INTO processing_log (match_id, step, status, error_message) "
                "VALUES (?, 'trajectory_extraction', 'failed', ?)",
                [match_id, error_message],
            )
        finally:
            conn.close()
    except Exception:
        pass  # Best-effort; don't mask the original error
