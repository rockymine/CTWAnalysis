"""
Build region extraction from CTW map XML and block data.

Determines where players can build over the void between islands using:
1. XML <apply> elements with deny(void) filters and region references
2. Block 36 at y=0 in layout_y0.parquet (fallback for maps without XML regions)

Core math:
  deny(void) applied to region R means "in R, you cannot build over void."
  buildable_area = map_bounds - R  (area where deny(void) does NOT apply)
  buildable_void = buildable_area - island_blocks
"""

import os
from typing import List, Dict, Optional

import numpy as np
import pandas as pd
from shapely.geometry import box, Polygon, MultiPolygon
from shapely.ops import unary_union
from shapely.validation import make_valid


def extract_build_region(
    map_data,
    map_bounds,
    y0_parquet_path: str,
    island_polygons: List,
) -> Optional[dict]:
    """
    Extract the buildable void region for a map.

    Args:
        map_data: Parsed MapData from XML (has .regions, .apply_rules)
        map_bounds: (min_x, max_x, min_z, max_z) bounding box
        y0_parquet_path: Path to layout_y0.parquet for block-36 fallback
        island_polygons: List of Shapely polygons for each island

    Returns:
        Dict with build region info, or None if no build region found.
    """
    # Convert bounding box: map_bounds is (min_x, max_x, min_z, max_z)
    # Shapely bounds format: (min_x, min_z, max_x, max_z)
    PAD = 10
    shapely_bounds = (
        map_bounds[0] - PAD,
        map_bounds[2] - PAD,
        map_bounds[1] + PAD,
        map_bounds[3] + PAD,
    )

    # Try XML-based extraction first
    build_allowed = _extract_from_xml(map_data, shapely_bounds)

    source = "xml"
    if build_allowed is None or build_allowed.is_empty:
        # Fallback to block 36
        build_allowed = _extract_block36_region(y0_parquet_path)
        source = "block_36"

    if build_allowed is None or build_allowed.is_empty:
        return None

    # Subtract island blocks to get buildable void
    island_union = _safe_union(island_polygons)
    buildable_void = build_allowed.difference(island_union)
    buildable_void = _ensure_valid(buildable_void)

    if buildable_void.is_empty:
        return None

    # Simplify for storage
    buildable_void = buildable_void.simplify(0.5, preserve_topology=True)

    return {
        'source': source,
        'polygons': _geometry_to_coords(build_allowed),
        'buildable_void': _geometry_to_coords(buildable_void),
        'buildable_void_area': round(float(buildable_void.area), 1),
    }


def _extract_from_xml(map_data, shapely_bounds) -> Optional:
    """
    Find deny(void) apply rules and compute the buildable area.

    buildable_area = map_bounds_box - union(deny_void_regions)
    """
    if not hasattr(map_data, 'apply_rules') or not map_data.apply_rules:
        return None

    deny_void_regions = _find_deny_void_regions(
        map_data.apply_rules, map_data.regions, shapely_bounds
    )

    if not deny_void_regions:
        return None

    universe = box(*shapely_bounds)
    deny_union = _safe_union(deny_void_regions)

    # buildable_area = everywhere MINUS deny(void) regions
    build_allowed = universe.difference(deny_union)
    return _ensure_valid(build_allowed)


def _find_deny_void_regions(apply_rules, regions_dict, shapely_bounds) -> List:
    """
    Scan apply rules for deny(void) patterns and resolve their regions.

    Checks block, block-place, block-break, and use attributes for
    "void" substring (covers deny(void), block-place-void-filter, etc.)
    """
    deny_regions = []

    for rule in apply_rules:
        # Check if any filter attribute references void
        is_void_rule = False
        for attr_val in [rule.block_filter, rule.block_place_filter,
                         rule.block_break_filter, rule.use_filter]:
            if attr_val and 'void' in attr_val.lower():
                is_void_rule = True
                break

        if not is_void_rule:
            continue

        # Resolve the region
        region_geom = _resolve_apply_region(rule, regions_dict, shapely_bounds)
        if region_geom and not region_geom.is_empty:
            deny_regions.append(region_geom)

    return deny_regions


def _resolve_apply_region(rule, regions_dict, shapely_bounds):
    """Resolve an apply rule's region to a Shapely geometry."""
    from .regions import EverywhereRegion

    # Inline region takes precedence
    if rule.inline_region is not None:
        return rule.inline_region.to_shapely_2d(shapely_bounds, regions_dict)

    # Named region reference
    if rule.region_id and rule.region_id in regions_dict:
        return regions_dict[rule.region_id].to_shapely_2d(
            shapely_bounds, regions_dict
        )

    # No region specified = everywhere (PGM default)
    return EverywhereRegion().to_shapely_2d(shapely_bounds)


def _extract_block36_region(y0_parquet_path: str):
    """
    Build a region from block 36 (invisible piston head) at y=0.

    Block 36 acts as an implicit build platform.
    """
    if not os.path.exists(y0_parquet_path):
        return None

    try:
        df = pd.read_parquet(y0_parquet_path)
    except Exception:
        return None

    if 'block_id' not in df.columns:
        return None

    block36 = df[df['block_id'] == 36]
    if block36.empty:
        return None

    x_col = 'world_x' if 'world_x' in block36.columns else 'x'
    z_col = 'world_z' if 'world_z' in block36.columns else 'z'

    squares = []
    for _, row in block36.iterrows():
        x, z = float(row[x_col]), float(row[z_col])
        squares.append(box(x - 0.5, z - 0.5, x + 0.5, z + 0.5))

    if not squares:
        return None

    region = unary_union(squares)
    return _ensure_valid(region)


def _safe_union(geoms) -> Polygon:
    """Union a list of geometries, skipping empty/invalid ones."""
    valid = [g for g in geoms if g is not None and not g.is_empty]
    if not valid:
        return Polygon()
    result = unary_union(valid)
    return _ensure_valid(result)


def _ensure_valid(geom):
    """Ensure geometry is valid."""
    if geom is None:
        return Polygon()
    if not geom.is_valid:
        geom = make_valid(geom)
    return geom


def _geometry_to_coords(geom) -> list:
    """Convert Shapely geometry to list of polygon coord dicts."""
    from shapely.geometry import GeometryCollection

    if geom is None or geom.is_empty:
        return []

    polygons = []
    if isinstance(geom, Polygon):
        polygons = [geom]
    elif isinstance(geom, MultiPolygon):
        polygons = list(geom.geoms)
    elif isinstance(geom, GeometryCollection):
        polygons = [g for g in geom.geoms if isinstance(g, Polygon)]
    else:
        return []

    result = []
    for poly in polygons:
        if poly.is_empty:
            continue
        exterior = [
            [round(float(x), 1), round(float(z), 1)]
            for x, z in poly.exterior.coords
        ]
        holes = [
            [[round(float(x), 1), round(float(z), 1)] for x, z in ring.coords]
            for ring in poly.interiors
        ]
        result.append({'exterior': exterior, 'holes': holes})

    return result
