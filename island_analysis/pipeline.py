"""Geometric pipeline for island analysis (Stages 1–2).

This module owns the two structural stages that belong strictly within
island_analysis: island detection (with parquet enrichment) and polygon
construction.  Nothing from skeleton_analysis, xml_analysis, or
map_analysis is imported here.
"""

import logging

import pandas as pd

from .datatypes import IslandPolygon

logger = logging.getLogger('ctw')


# ---------------------------------------------------------------------------
# Layout type → filename mapping
# ---------------------------------------------------------------------------

LAYOUT_FILES = {
    'bedrock': 'layout_bedrock.parquet',
    'y0': 'layout_y0.parquet',
    'top': 'layout_top_surface.parquet',
    'density': 'layout_vertical_density.parquet',
}


# ---------------------------------------------------------------------------
# Stage 1: Island detection
# ---------------------------------------------------------------------------

def detect_and_enrich(
    df: pd.DataFrame,
    connectivity: int = 8,
    min_island_size: int = 10,
) -> tuple[pd.DataFrame, list[IslandPolygon]]:
    """Detect islands and enrich the DataFrame with an island_id column.

    Returns the updated DataFrame (with island_id per block row) and the list
    of IslandPolygon objects. Does not write to disk — callers are responsible
    for persisting the enriched DataFrame.
    """
    from island_analysis import detect_islands

    logger.debug(f"  Detecting islands ({connectivity}-connectivity, min_size={min_island_size})...")
    islands = detect_islands(
        df,
        x_col='world_x',
        z_col='world_z',
        connectivity=connectivity,
        min_island_size=min_island_size,
    )
    logger.debug(f"    Found {len(islands)} islands")

    island_assignments = []
    for island in islands:
        for x, z in island.blocks:
            island_assignments.append({
                'world_x': int(round(x)),
                'world_z': int(round(z)),
                'island_id': island.id,
            })
    if island_assignments:
        island_df = pd.DataFrame(island_assignments)
        df = df.drop(columns=['island_id'], errors='ignore')
        df = df.merge(island_df, on=['world_x', 'world_z'], how='left')
        df['island_id'] = df['island_id'].fillna(0).astype(int)

    return df, islands


# ---------------------------------------------------------------------------
# Stage 2: Polygon construction
# ---------------------------------------------------------------------------

def build_polygons(
    islands: list[IslandPolygon],
    canonical: bool = False,
    buffer_distance: float = 0.0,
    simplify_tolerance: float = 1.0,
    detect_holes: bool = True,
) -> None:
    """Build simplified polygons for all islands (mutates each IslandPolygon in-place)."""
    from island_analysis import (
        build_island_polygon,
        build_island_polygons_canonical,
    )

    if canonical:
        logger.debug(f"  Building polygons (canonical mode, simplify={simplify_tolerance})...")
        build_island_polygons_canonical(
            islands,
            buffer_distance=buffer_distance,
            simplify_tolerance=simplify_tolerance,
            detect_holes=detect_holes,
        )
    else:
        logger.debug(f"  Building polygons (union mode, simplify={simplify_tolerance})...")
        for island in islands:
            build_island_polygon(
                island,
                buffer_distance=buffer_distance,
                simplify_tolerance=simplify_tolerance,
                detect_holes=detect_holes,
            )
