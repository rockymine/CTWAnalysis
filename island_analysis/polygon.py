"""
Island polygon construction using union-of-blocks approach.

Converts each block to a unit square polygon, unions them into an exact
boundary (with concavities and holes), and simplifies.

Provides two modes:
  - build_island_polygon: per-island polygon construction
  - build_island_polygons_canonical: canonical-consistent construction where
    all symmetrically identical islands share the same polygon
"""

import numpy as np
from typing import List, Dict, Tuple, Optional

from .datatypes import Island
from .detection import find_island_holes


def build_island_polygon(
    island: Island,
    buffer_distance: float = 0.0,
    simplify_tolerance: float = 1.0,
    detect_holes: bool = True
) -> None:
    """
    Build polygon boundary using union-of-blocks approach.

    This method creates exact polygonal representation by:
    1. Converting each block to a unit square polygon
    2. Computing the union of all squares (exact boundary with concavities/holes)
    3. Optionally smoothing with buffer-unbuffer operation
    4. Simplifying with topology-preserving algorithm

    Sets island.simplified_polygon and island.hull_vertices.

    Args:
        island: Island object
        buffer_distance: Buffer distance for smoothing (0 = no smoothing)
        simplify_tolerance: Tolerance for Douglas-Peucker simplification
        detect_holes: Whether to preserve internal holes
    """
    from shapely.geometry import Polygon

    if len(island.blocks) < 3:
        return

    if detect_holes:
        island.holes = find_island_holes(island)

    polygon = _build_union_polygon(
        island.blocks, buffer_distance, simplify_tolerance
    )
    if polygon is None:
        return

    if isinstance(polygon, Polygon) and not polygon.is_empty:
        island.hull_vertices = np.array(polygon.exterior.coords[:-1])
        island.simplified_polygon = _extract_polygon_coords(polygon)


def build_island_polygons_canonical(
    islands: List[Island],
    buffer_distance: float = 0.0,
    simplify_tolerance: float = 1.0,
    detect_holes: bool = True,
    allow_mirror: bool = True
) -> None:
    """
    Build island polygons using canonical shapes for consistency.

    Canonically identical islands (related by D4 symmetry) are grouped
    together.  Polygons are built from world-space blocks for each island.

    Args:
        islands: List of Island objects
        buffer_distance: Buffer distance for smoothing (0 = no smoothing)
        simplify_tolerance: Tolerance for Douglas-Peucker simplification
        detect_holes: Whether to preserve internal holes
        allow_mirror: Allow mirror in D4 canonicalization
    """
    from shapely.geometry import Polygon
    from skeleton_analysis.canonicalize import canonicalize_island

    # Step 1: Canonicalize all islands and group by canonical_key
    groups: Dict[str, List[Tuple[Island, object]]] = {}

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
            polygon = _build_union_polygon(
                island.blocks, buffer_distance, simplify_tolerance
            )
            if polygon is None:
                continue

            if isinstance(polygon, Polygon) and not polygon.is_empty:
                island.hull_vertices = np.array(polygon.exterior.coords[:-1])
                island.simplified_polygon = _extract_polygon_coords(polygon)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _extract_polygon_coords(polygon) -> dict:
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
    simplify_tolerance: float
):
    """
    Build a simplified Shapely polygon from block coordinates.

    Creates unit squares at each block position, unions them, optionally
    smooths, and simplifies. Returns the polygon or None if fewer than
    3 blocks.
    """
    from shapely.geometry import box
    from shapely.ops import unary_union
    from shapely.validation import make_valid

    if len(blocks) < 3:
        return None

    squares = []
    for x, z in blocks:
        square = box(x, z, x + 1, z + 1)
        squares.append(square)

    polygon = unary_union(squares)

    if not polygon.is_valid:
        polygon = make_valid(polygon)

    if buffer_distance > 0:
        polygon = polygon.buffer(buffer_distance).buffer(-buffer_distance)
        if not polygon.is_valid:
            polygon = make_valid(polygon)

    if simplify_tolerance > 0:
        polygon = polygon.simplify(simplify_tolerance, preserve_topology=True)

    return polygon
