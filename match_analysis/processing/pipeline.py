"""Post-processing orchestrator for match analysis.

Runs after match processing is complete.  Currently performs wool carry chain
analysis only.  Skeleton-based features (region_visits, life_segment_summary,
life_segment_skeleton_features) were removed — see PIPELINE.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb as _duckdb

from match_analysis.processing.carry_chains import build_wool_carry_chains


def run_post_processing(
    conn: '_duckdb.DuckDBPyConnection',
    match_id: int,
) -> None:
    """Run post-processing for a match.

    Currently only runs wool carry chain analysis.
    """
    print(f"Post-processing match {match_id}")
    print("Step 1/1: wool carry chains")
    build_wool_carry_chains(conn, match_id)
