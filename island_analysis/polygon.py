"""
Island polygon construction using union-of-blocks approach.

Converts each block to a unit square polygon, unions them into an exact
boundary (with concavities and holes), and simplifies.

Provides two modes:
  - build_island_polygon: per-island polygon construction
  - build_island_polygons_canonical: canonical-consistent construction where
    all symmetrically identical islands share the same polygon
"""

import logging

import numpy as np
from typing import Any, Optional

from .datatypes import IslandPolygon
from .detection import find_island_holes
from common.geometry import world_blocks_to_shapely

logger = logging.getLogger('ctw')


def build_island_polygon(
    island: IslandPolygon,
    buffer_distance: float = 0.0,
    simplify_tolerance: float = 0.0,
    detect_holes: bool = True
) -> None:
    """
    Build polygon boundary using union-of-blocks approach.

    This method creates exact polygonal representation by:
    1. Converting each block to a unit square polygon
    2. Computing the union of all squares (exact boundary with concavities/holes)
    3. Optionally smoothing with buffer-unbuffer operation
    4. Simplifying with topology-preserving algorithm

    Always sets island.simplified_polygon to the exact (buffer=0, simplify=0) polygon
    so downstream code always has access to the true block shape.  When
    buffer_distance > 0 or simplify_tolerance > 0, also sets island.smoothed_polygon
    to the result of applying those parameters.

    Sets island.simplified_polygon, island.hull_vertices, and (optionally)
    island.smoothed_polygon.

    Args:
        island: IslandPolygon object
        buffer_distance: Buffer distance for smoothing (0 = no smoothing)
        simplify_tolerance: Tolerance for Douglas-Peucker simplification (0 = no simplification)
        detect_holes: Whether to preserve internal holes
    """
    from shapely.geometry import Polygon

    if len(island.blocks) < 3:
        return

    if detect_holes:
        island.holes = find_island_holes(island)

    # Always build the exact polygon (no buffer, no simplification).
    exact_polygon = _build_union_polygon(island.blocks, 0.0, 0.0)
    if exact_polygon is None:
        return

    if isinstance(exact_polygon, Polygon) and not exact_polygon.is_empty:
        island.hull_vertices = np.array(exact_polygon.exterior.coords[:-1])
        island.simplified_polygon = _extract_polygon_coords(exact_polygon)

    # Optionally build the smoothed/simplified variant.
    if buffer_distance > 0 or simplify_tolerance > 0:
        smooth_polygon = _build_union_polygon(
            island.blocks, buffer_distance, simplify_tolerance
        )
        if smooth_polygon is not None and isinstance(smooth_polygon, Polygon) and not smooth_polygon.is_empty:
            island.smoothed_polygon = _extract_polygon_coords(smooth_polygon)


def build_island_polygons_canonical(
    islands: list[IslandPolygon],
    buffer_distance: float = 0.0,
    simplify_tolerance: float = 0.0,
    detect_holes: bool = True,
    allow_mirror: bool = True
) -> None:
    """
    Build island polygons using canonical shapes for consistency.

    Canonically identical islands (related by D4 symmetry) are grouped
    together.  Polygons are built from world-space blocks for each island.

    Always sets island.simplified_polygon to the exact (buffer=0, simplify=0) polygon.
    When buffer_distance > 0 or simplify_tolerance > 0, also sets island.smoothed_polygon.

    Args:
        islands: List of IslandPolygon objects
        buffer_distance: Buffer distance for smoothing (0 = no smoothing)
        simplify_tolerance: Tolerance for Douglas-Peucker simplification (0 = no simplification)
        detect_holes: Whether to preserve internal holes
        allow_mirror: Allow mirror in D4 canonicalization
    """
    from shapely.geometry import Polygon
    from .canonicalize import canonicalize_island

    want_smooth = buffer_distance > 0 or simplify_tolerance > 0

    # Step 1: Canonicalize all islands and group by canonical_key
    groups: dict[str, list[tuple[IslandPolygon, Any]]] = {}

    for island in islands:
        if len(island.blocks) < 3:
            continue

        if detect_holes:
            island.holes = find_island_holes(island)

        canonical = canonicalize_island(
            island.id, island.blocks, allow_mirror=allow_mirror
        )
        key = canonical.canonical_key
        if key not in groups:
            groups[key] = []
        groups[key].append((island, canonical))

    # Step 2: Build polygon per island in world space.
    #
    # The canonical grouping above identifies equivalent shapes, but the
    # polygon must be built from world-space blocks.
    # Reason: to_original() correctly maps block INDEX coordinates but NOT
    # polygon BOUNDARY coordinates.  Block (x,z) occupies [x, x+1]×[z, z+1];
    # the "+1" extent direction is axis-aligned in world space but gets
    # rotated if we build the polygon in canonical space and transform back.
    for key, group in groups.items():
        for island, canonical in group:
            # Always compute the exact polygon.
            exact_polygon = _build_union_polygon(island.blocks, 0.0, 0.0)
            if exact_polygon is None:
                continue

            if isinstance(exact_polygon, Polygon) and not exact_polygon.is_empty:
                island.hull_vertices = np.array(exact_polygon.exterior.coords[:-1])
                island.simplified_polygon = _extract_polygon_coords(exact_polygon)

            # Optionally compute the smoothed/simplified variant.
            if want_smooth:
                smooth_polygon = _build_union_polygon(
                    island.blocks, buffer_distance, simplify_tolerance
                )
                if smooth_polygon is not None and isinstance(smooth_polygon, Polygon) and not smooth_polygon.is_empty:
                    island.smoothed_polygon = _extract_polygon_coords(smooth_polygon)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _extract_polygon_coords(polygon: Any) -> dict:
    """
    Extract exterior and hole coordinates from a Shapely Polygon.

    Returns a dict with closed rings (first coord == last coord).
    """
    exterior = [
        [round(float(x), 1), round(float(z), 1)]
        for x, z in polygon.exterior.coords
    ]
    holes = [
        [[round(float(x), 1), round(float(z), 1)] for x, z in ring.coords]
        for ring in polygon.interiors
    ]
    return {'exterior': exterior, 'holes': holes}


def _build_union_polygon(
    blocks: np.ndarray,
    buffer_distance: float,
    simplify_tolerance: float,
) -> Optional[Any]:
    """
    Build a simplified Shapely polygon from block coordinates.

    Creates unit squares at each block position in world space, unions them,
    optionally smooths, and simplifies. Returns the polygon or None if fewer
    than 3 blocks.

    Polygon construction is delegated to :func:`~common.geometry.world_blocks_to_shapely`
    so that the "+1 extent" per block is applied exactly once, in world space.

    8-connected islands with diagonal-only block connections create unit-square
    unions that touch at a single point.  Shapely's make_valid() splits these
    into a MultiPolygon.  When that happens the largest sub-polygon (by area) is
    kept and the tiny pinch-point fragments are discarded.
    """
    from shapely.validation import make_valid

    if len(blocks) < 3:
        return None

    polygon = world_blocks_to_shapely(blocks)

    if not polygon.is_valid:
        polygon = make_valid(polygon)

    if buffer_distance > 0:
        polygon = polygon.buffer(buffer_distance).buffer(-buffer_distance)
        if not polygon.is_valid:
            polygon = make_valid(polygon)

    if simplify_tolerance > 0:
        polygon = polygon.simplify(simplify_tolerance, preserve_topology=True)

    if polygon.geom_type == 'MultiPolygon':
        sub = max(polygon.geoms, key=lambda g: g.area)
        logger.debug(
            f"    MultiPolygon ({len(polygon.geoms)} parts) — keeping largest "
            f"({sub.area:.0f} of {polygon.area:.0f} total area)"
        )
        polygon = sub

    return polygon
