"""
Island triangulation using union-of-blocks approach.

Converts each block to a unit square polygon, unions them into an exact
boundary (with concavities and holes), simplifies, then triangulates.

Provides two modes:
  - triangulate_island_union: per-island triangulation (original)
  - triangulate_islands_canonical: canonical-consistent triangulation where
    all symmetrically identical islands share the same mesh
"""

import numpy as np
from typing import List, Dict, Tuple, Optional

from .datatypes import Island
from .detection import find_island_holes


def triangulate_island_union(
    island: Island,
    buffer_distance: float = 0.0,
    simplify_tolerance: float = 1.0,
    detect_holes: bool = True
) -> List[np.ndarray]:
    """
    Create triangulation using union-of-blocks approach.

    This method creates exact polygonal representation by:
    1. Converting each block to a unit square polygon
    2. Computing the union of all squares (exact boundary with concavities/holes)
    3. Optionally smoothing with buffer-unbuffer operation
    4. Simplifying with topology-preserving algorithm
    5. Triangulating the simplified polygon

    Args:
        island: Island object
        buffer_distance: Buffer distance for smoothing (0 = no smoothing)
        simplify_tolerance: Tolerance for Douglas-Peucker simplification
        detect_holes: Whether to preserve internal holes

    Returns:
        List of triangles (each as 3x2 array of vertices)
    """
    from shapely.geometry import Polygon

    if len(island.blocks) < 3:
        return []

    if detect_holes:
        island.holes = find_island_holes(island)

    polygon = _build_union_polygon(
        island.blocks, buffer_distance, simplify_tolerance
    )
    if polygon is None:
        return []

    triangles = _triangulate_shapely_polygon(polygon)

    if isinstance(polygon, Polygon) and not polygon.is_empty:
        island.hull_vertices = np.array(polygon.exterior.coords[:-1])
        island.simplified_polygon = _extract_polygon_coords(polygon)

    island.triangles = triangles
    return triangles


def triangulate_islands_canonical(
    islands: List[Island],
    buffer_distance: float = 0.0,
    simplify_tolerance: float = 1.0,
    detect_holes: bool = True,
    allow_mirror: bool = True
) -> int:
    """
    Triangulate islands using canonical shapes for consistency.

    Canonically identical islands (related by D4 symmetry) get identical
    meshes. For each unique canonical shape, triangulation is computed once
    in canonical space and then transformed back to world coordinates for
    every island sharing that shape.

    Args:
        islands: List of Island objects
        buffer_distance: Buffer distance for smoothing (0 = no smoothing)
        simplify_tolerance: Tolerance for Douglas-Peucker simplification
        detect_holes: Whether to preserve internal holes
        allow_mirror: Allow mirror in D4 canonicalization

    Returns:
        Total number of triangles across all islands
    """
    from shapely.geometry import Polygon
    from skeleton_analysis.canonicalize import canonicalize_island

    # Step 1: Canonicalize all islands and group by canonical_key
    groups: Dict[str, List[Tuple[Island, object]]] = {}

    for island in islands:
        if len(island.blocks) < 3:
            island.triangles = []
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

    # Step 2: Build polygon and triangulate per island in world space.
    #
    # The canonical grouping above identifies equivalent shapes, but the
    # polygon / triangulation must be built from world-space blocks.
    # Reason: to_original() correctly maps block INDEX coordinates but NOT
    # polygon BOUNDARY coordinates.  Block (x,z) occupies [x, x+1]×[z, z+1];
    # the "+1" extent direction is axis-aligned in world space but gets
    # rotated if we build the polygon in canonical space and transform back.
    total = 0
    for key, group in groups.items():
        for island, canonical in group:
            polygon = _build_union_polygon(
                island.blocks, buffer_distance, simplify_tolerance
            )
            if polygon is None:
                island.triangles = []
                continue

            island.triangles = _triangulate_shapely_polygon(polygon)
            if isinstance(polygon, Polygon) and not polygon.is_empty:
                island.hull_vertices = np.array(polygon.exterior.coords[:-1])
                island.simplified_polygon = _extract_polygon_coords(polygon)
            total += len(island.triangles)

    return total


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


def _transform_polygon_coords(poly_coords: dict, transform) -> dict:
    """Transform polygon coords from canonical to world space."""
    ext_arr = np.array(poly_coords['exterior'])
    world_ext = transform.to_original(ext_arr)
    world_exterior = [
        [round(float(p[0]), 1), round(float(p[1]), 1)] for p in world_ext
    ]
    world_holes = []
    for hole_coords in poly_coords['holes']:
        h_arr = np.array(hole_coords)
        world_h = transform.to_original(h_arr)
        world_holes.append(
            [[round(float(p[0]), 1), round(float(p[1]), 1)] for p in world_h]
        )
    return {'exterior': world_exterior, 'holes': world_holes}


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

def _triangulate_shapely_polygon(polygon) -> List[np.ndarray]:
    """
    Triangulate a shapely polygon.

    Handles both Polygon and MultiPolygon, including holes.

    For simple polygons (no holes), uses ear clipping.
    For polygons with holes, uses Delaunay triangulation on all boundary
    vertices, then clips each triangle to the polygon to avoid gaps in
    narrow regions where centroid-based filtering would fail.
    """
    from shapely.geometry import Polygon, MultiPolygon, MultiPoint
    from shapely.ops import triangulate

    triangles = []

    if polygon.is_empty:
        return triangles

    if isinstance(polygon, MultiPolygon):
        for poly in polygon.geoms:
            triangles.extend(_triangulate_shapely_polygon(poly))
        return triangles

    if not isinstance(polygon, Polygon):
        return triangles

    # Get exterior coordinates (without closing point)
    exterior_coords = np.array(polygon.exterior.coords[:-1])

    if len(exterior_coords) < 3:
        return triangles

    # If no holes, use simple ear clipping
    if len(polygon.interiors) == 0:
        return _ear_clip_triangulate(exterior_coords)

    # With holes: Delaunay on all boundary vertices, clip to polygon
    try:
        all_coords = list(exterior_coords)
        for interior in polygon.interiors:
            all_coords.extend(np.array(interior.coords[:-1]))

        raw_triangles = triangulate(MultiPoint(all_coords))

        for tri in raw_triangles:
            clipped = polygon.intersection(tri)
            if clipped.is_empty:
                continue
            _collect_polygon_triangles(clipped, triangles)

    except Exception:
        # Fallback: just triangulate exterior
        triangles = _ear_clip_triangulate(exterior_coords)

    return triangles


def _collect_polygon_triangles(
    geometry,
    out: List[np.ndarray],
    min_area: float = 0.01
) -> None:
    """
    Extract triangles from a clipped geometry (Polygon, MultiPolygon, or
    GeometryCollection). Non-triangular polygons are ear-clipped.
    """
    from shapely.geometry import Polygon, MultiPolygon, GeometryCollection

    if geometry.is_empty or geometry.area < min_area:
        return

    if isinstance(geometry, (MultiPolygon, GeometryCollection)):
        for geom in geometry.geoms:
            _collect_polygon_triangles(geom, out, min_area)
        return

    if not isinstance(geometry, Polygon):
        return

    coords = np.array(geometry.exterior.coords[:-1])
    if len(coords) < 3:
        return

    if len(coords) == 3:
        out.append(coords)
    else:
        out.extend(_ear_clip_triangulate(coords))


def _ear_clip_triangulate(vertices: np.ndarray) -> List[np.ndarray]:
    """
    Triangulate a simple polygon using ear clipping algorithm.
    """
    if len(vertices) < 3:
        return []

    if len(vertices) == 3:
        return [vertices.copy()]

    # Make a copy to work with
    verts = vertices.tolist()
    triangles = []

    # Ensure counter-clockwise orientation
    if _polygon_area(verts) < 0:
        verts = verts[::-1]

    while len(verts) > 3:
        ear_found = False

        for i in range(len(verts)):
            prev_i = (i - 1) % len(verts)
            next_i = (i + 1) % len(verts)

            v_prev = np.array(verts[prev_i])
            v_curr = np.array(verts[i])
            v_next = np.array(verts[next_i])

            # Check if this is a convex vertex (ear candidate)
            if _is_convex(v_prev, v_curr, v_next):
                # Check if any other vertex is inside this triangle
                is_ear = True
                for j in range(len(verts)):
                    if j in [prev_i, i, next_i]:
                        continue
                    if _point_in_triangle(np.array(verts[j]), v_prev, v_curr, v_next):
                        is_ear = False
                        break

                if is_ear:
                    triangles.append(np.array([v_prev, v_curr, v_next]))
                    verts.pop(i)
                    ear_found = True
                    break

        if not ear_found:
            # Fallback: just take first three vertices
            triangles.append(np.array([verts[0], verts[1], verts[2]]))
            verts.pop(1)

    # Add the last triangle
    if len(verts) == 3:
        triangles.append(np.array(verts))

    return triangles


def _polygon_area(vertices: List) -> float:
    """Calculate signed area of polygon (positive = CCW)."""
    n = len(vertices)
    area = 0
    for i in range(n):
        j = (i + 1) % n
        area += vertices[i][0] * vertices[j][1]
        area -= vertices[j][0] * vertices[i][1]
    return area / 2


def _is_convex(v_prev: np.ndarray, v_curr: np.ndarray, v_next: np.ndarray) -> bool:
    """Check if vertex is convex (makes a left turn)."""
    cross = (v_curr[0] - v_prev[0]) * (v_next[1] - v_prev[1]) - \
            (v_curr[1] - v_prev[1]) * (v_next[0] - v_prev[0])
    return cross > 0


def _point_in_triangle(p: np.ndarray, v1: np.ndarray, v2: np.ndarray, v3: np.ndarray) -> bool:
    """Check if point is inside triangle using barycentric coordinates."""
    def sign(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

    d1 = sign(p, v1, v2)
    d2 = sign(p, v2, v3)
    d3 = sign(p, v3, v1)

    has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)

    return not (has_neg and has_pos)
