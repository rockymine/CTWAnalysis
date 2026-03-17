#!/usr/bin/env python3
"""Migration: Remove skeleton tables, slim position_events, rework traffic schema.

Run once against an existing metadata.db:
    python scripts/migrate_skeleton_removal.py

Safe to re-run — IF NOT EXISTS guards and DROP ... IF EXISTS prevent re-creation errors.
"""

import duckdb
from pathlib import Path


def run_migration(db_path: str = 'match_analysis/metadata.db') -> None:
    """Apply the skeleton-removal schema migration."""
    if not Path(db_path).exists():
        print(f"Database not found at {db_path}. Nothing to migrate.")
        return

    conn = duckdb.connect(db_path)
    try:
        _migrate(conn)
    finally:
        conn.close()
    print("Migration complete.")


def _migrate(conn: duckdb.DuckDBPyConnection) -> None:
    # ── 1. Drop the backward-compat view (references skeleton tables) ────────
    conn.execute("DROP VIEW IF EXISTS life_segment_features")
    print("  Dropped view: life_segment_features")

    # ── 2. Drop skeleton-derived tables ─────────────────────────────────────
    conn.execute("DROP TABLE IF EXISTS life_segment_skeleton_features")
    print("  Dropped table: life_segment_skeleton_features")

    conn.execute("DROP TABLE IF EXISTS life_segment_region_visits")
    print("  Dropped table: life_segment_region_visits")

    conn.execute("DROP TABLE IF EXISTS life_segment_summary")
    print("  Dropped table: life_segment_summary")

    # ── 3. Drop skeleton node columns from position_events ──────────────────
    _drop_column_if_exists(conn, 'position_events', 'nearest_node_1')
    _drop_column_if_exists(conn, 'position_events', 'nearest_node_2')
    _drop_column_if_exists(conn, 'position_events', 'nearest_island_1')
    _drop_column_if_exists(conn, 'position_events', 'nearest_island_2')
    _drop_column_if_exists(conn, 'position_events', 'nearest_graph_node')
    print("  Dropped skeleton columns from position_events")

    # ── 4. Rework life_segment_traffic_features to minimal schema ────────────
    conn.execute("DROP TABLE IF EXISTS life_segment_traffic_features")
    conn.execute("""
        CREATE TABLE life_segment_traffic_features (
            segment_id     INTEGER PRIMARY KEY,
            snapped_sequence TEXT,
            max_attack_depth FLOAT,
            death_region   TEXT,
            FOREIGN KEY (segment_id) REFERENCES life_segments(segment_id)
        )
    """)
    print("  Recreated table: life_segment_traffic_features (new schema)")

    # ── 5. Add spatial_classified flag to matches ────────────────────────────
    conn.execute(
        "ALTER TABLE matches ADD COLUMN IF NOT EXISTS spatial_classified BOOLEAN DEFAULT FALSE"
    )
    print("  Added column: matches.spatial_classified")


def _drop_column_if_exists(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    column: str,
) -> None:
    """Drop a column from a table if it currently exists."""
    exists = conn.execute(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_name = ? AND column_name = ?",
        [table, column],
    ).fetchone()[0]
    if exists:
        conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        print(f"  Dropped column: {table}.{column}")
    else:
        print(f"  Skipped (not found): {table}.{column}")


if __name__ == '__main__':
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else 'match_analysis/metadata.db'
    run_migration(db)
