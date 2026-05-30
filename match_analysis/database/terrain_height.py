"""Populate map_terrain_height from per-map layout parquets.

Usage
-----
Call ``populate_terrain_height(map_id, output_dir, conn)`` for each map after
running ``ctw run --map NAME`` (which produces ``layout_top_surface.parquet``,
``layout_lowest_solid.parquet``, and populates ``island_id`` in the clustering
layer parquet).

The function filters to island cells only (``island_id > 0`` in the clustering
layer) and inserts ``(map_id, world_x, world_z, surface_y, lowest_y)`` rows.
Build-region and void cells are excluded by construction — their
``height_above_terrain`` is semantically NULL at query time.
"""

import logging
from pathlib import Path

import pandas as pd

from layout_analysis.map_layout_config import get_map_layout

logger = logging.getLogger('ctw')

# Layer name (from map_layouts.json) → raw layout parquet filename.
# For configured maps the actual clustering parquet is layout_decided.parquet;
# this mapping is used as a fallback for unconfigured maps.
_LAYER_TO_PARQUET: dict[str, str] = {
    'bedrock': 'layout_bedrock.parquet',
    'y0': 'layout_y0.parquet',
    'lowest_solid': 'layout_lowest_solid.parquet',
    'top_surface': 'layout_top_surface.parquet',
}


def _find_clustering_parquet(output_dir: Path, map_slug: str) -> Path | None:
    """Return the parquet file that has ``island_id`` written into it.

    Priority order:
    1. ``layout_decided.parquet`` — written by island detection for all
       configured maps (the most common case).
    2. Layer-specific file from ``map_layouts.json`` config — covers
       configured maps where ``layer == 'y0'`` with no exclusions (island
       detection writes back to ``layout_y0.parquet`` directly in that case).
    3. ``layout_bedrock.parquet`` — default for unconfigured maps running
       with ``--island-layout bedrock`` (the CLI default).
    4. ``layout_y0.parquet`` — last-resort fallback.
    """
    # 1. Decided layer (most configured maps)
    decided = output_dir / 'layout_decided.parquet'
    if decided.exists():
        return decided

    # 2. Layer from config
    cfg = get_map_layout(map_slug)
    if cfg is not None:
        layer_name = cfg.layer
        filename = _LAYER_TO_PARQUET.get(layer_name)
        if filename:
            candidate = output_dir / filename
            if candidate.exists():
                return candidate

    # 3. Bedrock fallback (unconfigured maps)
    bedrock = output_dir / 'layout_bedrock.parquet'
    if bedrock.exists():
        return bedrock

    # 4. Y0 last resort
    y0 = output_dir / 'layout_y0.parquet'
    if y0.exists():
        return y0

    return None


def populate_terrain_height(map_id: int, output_dir: Path, conn) -> int:
    """Populate ``map_terrain_height`` for one map from layout parquets.

    Reads:
    - The clustering layer parquet (whichever file has ``island_id`` from
      island detection) to determine the island footprint.
    - ``layout_top_surface.parquet`` for ``surface_y`` values.
    - ``layout_lowest_solid.parquet`` for ``lowest_y`` values (optional).

    Only cells where ``island_id > 0`` are inserted.  Existing rows for
    ``map_id`` are deleted before insertion.

    Args:
        map_id: Primary key in the ``maps`` table.
        output_dir: Path to the map's output directory (e.g. ``output/arabia``).
        conn: Open DuckDB connection with write access.

    Returns:
        Number of rows inserted (0 on failure or nothing to insert).
    """
    output_dir = Path(output_dir)
    map_slug = output_dir.name

    # --- 1. Island footprint ---
    clustering_path = _find_clustering_parquet(output_dir, map_slug)
    if clustering_path is None:
        logger.warning(
            f"  [{map_slug}] No clustering layer parquet found in {output_dir}; "
            "run 'ctw run --map NAME' first"
        )
        return 0

    df_cluster = pd.read_parquet(clustering_path)
    if 'island_id' not in df_cluster.columns:
        logger.warning(
            f"  [{map_slug}] {clustering_path.name} has no island_id column; "
            "run 'ctw run --map NAME' first to populate island detection"
        )
        return 0

    island_cells = (
        df_cluster[df_cluster['island_id'] > 0][['world_x', 'world_z']]
        .drop_duplicates()
        .copy()
    )
    if island_cells.empty:
        logger.warning(
            f"  [{map_slug}] No island cells (island_id > 0) found in "
            f"{clustering_path.name}"
        )
        return 0

    logger.debug(
        f"  [{map_slug}] Island footprint: {len(island_cells)} cells "
        f"from {clustering_path.name}"
    )

    # --- 2. Surface heights ---
    top_surface_path = output_dir / 'layout_top_surface.parquet'
    if not top_surface_path.exists():
        logger.warning(
            f"  [{map_slug}] layout_top_surface.parquet not found; "
            "run 'ctw layout --map NAME' (with optional --skip-non-solid) first"
        )
        return 0

    df_surface = pd.read_parquet(
        top_surface_path, columns=['world_x', 'world_z', 'y']
    ).rename(columns={'y': 'surface_y'})

    # --- 3. Lowest solid heights (optional) ---
    lowest_solid_path = output_dir / 'layout_lowest_solid.parquet'
    if lowest_solid_path.exists():
        df_lowest = pd.read_parquet(
            lowest_solid_path, columns=['world_x', 'world_z', 'y']
        ).rename(columns={'y': 'lowest_y'})
    else:
        logger.debug(
            f"  [{map_slug}] layout_lowest_solid.parquet not found; "
            "lowest_y will be NULL"
        )
        df_lowest = None

    # --- 4. Join to island footprint ---
    df = island_cells.merge(df_surface, on=['world_x', 'world_z'], how='inner')
    if df_lowest is not None:
        df = df.merge(df_lowest, on=['world_x', 'world_z'], how='left')
    else:
        df['lowest_y'] = None

    if df.empty:
        logger.warning(
            f"  [{map_slug}] No island cells matched layout_top_surface after join"
        )
        return 0

    # --- 5. Insert into DB ---
    conn.execute("DELETE FROM map_terrain_height WHERE map_id = ?", [map_id])

    rows = [
        (
            map_id,
            int(row.world_x),
            int(row.world_z),
            int(row.surface_y),
            None if pd.isna(row.lowest_y) else int(row.lowest_y),
        )
        for row in df.itertuples()
    ]
    conn.executemany(
        "INSERT INTO map_terrain_height "
        "(map_id, world_x, world_z, surface_y, lowest_y) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )

    logger.debug(f"  [{map_slug}] Inserted {len(rows)} terrain height rows")
    return len(rows)
