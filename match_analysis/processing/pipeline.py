"""Post-processing orchestrator for match analysis.

Runs after match processing is complete and reads from the already-populated
database to produce derived tables for clustering and analysis.

Tables produced:
  - wool_spawn_baselines        (once per map)
  - life_segment_region_visits  (once per match)
  - life_segment_summary        (once per match)
  - life_segment_skeleton_features  (once per match)
  - wool_carry_chains           (once per match)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb as _duckdb

from match_analysis.processing._helpers import _get_map_slug
from match_analysis.processing.wool_baselines import populate_wool_spawn_baselines
from match_analysis.processing.carry_chains import build_wool_carry_chains
from match_analysis.processing.segment_features import build_life_features, build_y_features
from match_analysis.processing.region_visits import build_region_visits


def run_post_processing(
    conn: '_duckdb.DuckDBPyConnection',
    match_id: int,
) -> None:
    """Run all post-processing steps for a match in order.

    Steps:
      0. Schema migrations (ensure traffic graph tables exist)
      1. populate_wool_spawn_baselines  (idempotent, per-map)
      2. build_region_visits            (per-match)
      3. build_life_features            (per-match)
      4. build_y_features               (per-match)
      5. build_wool_carry_chains        (per-match)
    """
    from match_analysis.database.schema import migrate_traffic_graph_tables

    map_slug = _get_map_slug(conn, match_id)
    print(f"Post-processing match {match_id} (map: {map_slug})")

    print("Step 0/5: ensure schema tables exist")
    migrate_traffic_graph_tables(conn=conn)

    print("Step 1/5: wool spawn baselines")
    populate_wool_spawn_baselines(conn, map_slug)

    print("Step 2/5: region visits")
    build_region_visits(conn, match_id)

    print("Step 3/5: life segment features")
    build_life_features(conn, match_id)

    print("Step 4/5: Y-level features")
    build_y_features(conn, match_id)

    print("Step 5/5: wool carry chains")
    build_wool_carry_chains(conn, match_id)
