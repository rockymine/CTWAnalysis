"""
Shared geometry utilities for CTW Analysis.

Pure math functions: rotations, D4 symmetry, coordinate conversions,
neighbor offsets, center classification, polygon transforms, and
JSON serialization helpers.

This module has NO imports from ctw.core.models to avoid circular
dependencies. Functions that create model objects (e.g. canonicalize_island)
use deferred imports.
"""

import hashlib
import numpy as np
from typing import Dict, List, Tuple, Optional


# ---------------------------------------------------------------------------
# Rotation functions
# ---------------------------------------------------------------------------

def rotate_points(points: np.ndarray, degrees: int) -> np.ndarray:
    """Rotate 2D points by given degrees (must be multiple of 90).

    Args:
        points: Nx2 array of (x, z) coordinates (float).
        degrees: Rotation angle, must be 0/90/180/270.

    Returns:
        Rotated Nx2 array (float copy).
    """
    d = degrees % 360
    if d == 0:
        return points.copy()
    elif d == 90:
        return np.column_stack([-points[:, 1], points[:, 0]])
    elif d == 180:
        return -points.copy()
    elif d == 270:
        return np.column_stack([points[:, 1], -points[:, 0]])
    else:
        raise ValueError(f"Rotation must be a multiple of 90, got {degrees}")


def rotate_points_int(points: np.ndarray, degrees: int) -> np.ndarray:
    """Rotate integer 2D points by a multiple of 90 degrees. Exact.

    Args:
        points: Nx2 array of (x, z) integer coordinates.
        degrees: Rotation angle, must be 0/90/180/270.

    Returns:
        Rotated Nx2 integer array.
    """
    d = degrees % 360
    if d == 0:
        return points.copy()
    elif d == 90:
        return np.column_stack([-points[:, 1], points[:, 0]])
    elif d == 180:
        return -points.copy()
    elif d == 270:
        return np.column_stack([points[:, 1], -points[:, 0]])
    else:
        raise ValueError(f"Rotation must be a multiple of 90, got {degrees}")


# ---------------------------------------------------------------------------
# D4 symmetry group
# ---------------------------------------------------------------------------

# The 8 elements of the D4 group (dihedral group of the square):
# 4 rotations x 2 mirror states
D4_ELEMENTS = [
    (0, False), (90, False), (180, False), (270, False),
    (0, True),  (90, True),  (180, True),  (270, True),
]


# ---------------------------------------------------------------------------
# Canonical key / lexicographic comparison
# ---------------------------------------------------------------------------

def lex_compare(a: np.ndarray, b: np.ndarray) -> int:
    """Lexicographic comparison of two 2D integer arrays (same shape).

    Returns -1 if a < b, 0 if equal, 1 if a > b.
    """
    for i in range(len(a)):
        if a[i, 0] < b[i, 0]:
            return -1
        if a[i, 0] > b[i, 0]:
            return 1
        if a[i, 1] < b[i, 1]:
            return -1
        if a[i, 1] > b[i, 1]:
            return 1
    return 0


def compute_canonical_key(sorted_points: np.ndarray) -> str:
    """Hash sorted integer points to a canonical string key.

    Uses SHA-256 of the raw bytes, truncated to 16 hex characters.
    """
    data = sorted_points.astype(np.int32).tobytes()
    return hashlib.sha256(data).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Island canonicalization (D4)
# ---------------------------------------------------------------------------

def canonicalize_island(
    island_id: int,
    blocks: np.ndarray,
    allow_mirror: bool = True,
):
    """Find the D4-canonical orientation of an island.

    Uses pure integer arithmetic: block coordinates are rounded to int,
    then D4 transforms are applied exactly (no floating-point centering).

    Algorithm:
      1. Round blocks to integers
      2. Try all D4 transforms (mirror, then rotate)
      3. For each: shift so min=0, sort lexicographically
      4. Pick the transform producing the smallest sorted result
      5. Hash the result -> canonical_key

    Args:
        island_id: Island identifier.
        blocks: Nx2 array of (x, z) world coordinates.
        allow_mirror: If True, consider mirror transforms (full D4).
                      If False, only rotations (C4 subgroup).

    Returns:
        CanonicalIsland with canonical_points, key, and transform.
    """
    from ctw.core.models import CanonicalIsland, CanonicalTransform

    blocks_float = blocks.astype(float)
    blocks_int = np.round(blocks_float).astype(int)

    elements = D4_ELEMENTS if allow_mirror else D4_ELEMENTS[:4]

    best_sorted = None
    best_transform = None
    best_points = None

    for rotation, mirror in elements:
        pts = blocks_int.copy()
        if mirror:
            pts[:, 0] = -pts[:, 0]
        pts = rotate_points_int(pts, rotation)

        min_vals = pts.min(axis=0)
        pts = pts - min_vals

        order = np.lexsort((pts[:, 1], pts[:, 0]))
        sorted_pts = pts[order]

        if best_sorted is None or lex_compare(sorted_pts, best_sorted) < 0:
            best_sorted = sorted_pts
            best_points = pts
            best_transform = CanonicalTransform(
                rotation=rotation,
                mirror=mirror,
                translation=-min_vals.astype(float),
                world_center=np.zeros(2),
            )

    canonical_key = compute_canonical_key(best_sorted)

    return CanonicalIsland(
        island_id=island_id,
        canonical_points=best_points,
        canonical_key=canonical_key,
        transform=best_transform,
        world_blocks=blocks_float,
    )


# ---------------------------------------------------------------------------
# Neighbor offsets
# ---------------------------------------------------------------------------

# Neighbor offsets for 8-connectivity (clockwise from top-left)
NEIGHBOR_OFFSETS_8 = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
]

# Neighbor offsets for 4-connectivity
NEIGHBOR_OFFSETS_4 = [
    (-1, 0), (0, -1), (0, 1), (1, 0),
]


# ---------------------------------------------------------------------------
# Map center computation
# ---------------------------------------------------------------------------

def compute_map_center(layout_df) -> Tuple[float, float]:
    """Compute the geometric center of all blocks in the layout.

    Args:
        layout_df: DataFrame with world_x and world_z columns.

    Returns:
        (center_x, center_z) tuple.
    """
    x_col = 'world_x' if 'world_x' in layout_df.columns else 'x'
    z_col = 'world_z' if 'world_z' in layout_df.columns else 'z'

    min_x = layout_df[x_col].min()
    max_x = layout_df[x_col].max()
    min_z = layout_df[z_col].min()
    max_z = layout_df[z_col].max()

    return ((min_x + max_x + 1) / 2.0, (min_z + max_z + 1) / 2.0)


# ---------------------------------------------------------------------------
# Center classification
# ---------------------------------------------------------------------------

def classify_center(bbox: Tuple[float, float, float, float]) -> Dict:
    """Classify the geometric map center based on bounding box dimensions.

    In Minecraft's block coordinate system, a block at integer (x, z) occupies
    the area [x, x+1) x [z, z+1).  The bounding box stores min/max block indices,
    so the full extent is [min_x, max_x+1) x [min_z, max_z+1).

    The center type depends on whether each dimension spans an odd or even
    number of blocks:
        - odd x odd   -> single block center
        - even x odd  -> 2x1 center line (horizontal)
        - odd x even  -> 1x2 center line (vertical)
        - even x even -> 2x2 center area

    Returns dict with keys: center_x, center_z, type, description, blocks
    """
    min_x, max_x, min_z, max_z = bbox
    width_x = max_x - min_x
    width_z = max_z - min_z

    center_x = (min_x + max_x) / 2.0
    center_z = (min_z + max_z) / 2.0

    odd_x = (int(width_x) % 2 == 1)
    odd_z = (int(width_z) % 2 == 1)

    if odd_x and odd_z:
        center_type = "single_block"
        description = "Single block center"
        bx = int(center_x - 0.5)
        bz = int(center_z - 0.5)
        blocks = [(bx, bz)]
    elif not odd_x and odd_z:
        center_type = "2x1_line"
        description = "2x1 center line (along X axis)"
        bx1 = int(center_x - 1)
        bx2 = int(center_x)
        bz = int(center_z - 0.5)
        blocks = [(bx1, bz), (bx2, bz)]
    elif odd_x and not odd_z:
        center_type = "1x2_line"
        description = "1x2 center line (along Z axis)"
        bx = int(center_x - 0.5)
        bz1 = int(center_z - 1)
        bz2 = int(center_z)
        blocks = [(bx, bz1), (bx, bz2)]
    else:
        center_type = "2x2_area"
        description = "2x2 center area"
        bx1 = int(center_x - 1)
        bx2 = int(center_x)
        bz1 = int(center_z - 1)
        bz2 = int(center_z)
        blocks = [(bx1, bz1), (bx2, bz1), (bx1, bz2), (bx2, bz2)]

    return {
        "center_x": center_x,
        "center_z": center_z,
        "type": center_type,
        "description": description,
        "blocks": blocks,
        "map_width_x": int(width_x),
        "map_width_z": int(width_z),
    }


def classify_island_center(
    islands: list,
    map_center: Tuple[float, float],
) -> None:
    """Set has_center and distance_to_center on each island.

    An island only gets has_center=True if the geometric map center
    actually lies on the island -- i.e. at least one of the center
    block(s) is present in the island's block set.

    The center type depends on the bounding box dimensions (odd/even):
      - odd  x odd  -> 1 center block
      - even x odd  -> 2 center blocks (2x1)
      - odd  x even -> 2 center blocks (1x2)
      - even x even -> 4 center blocks (2x2)
    """
    if not islands:
        return

    cx, cz = map_center
    cx_is_half = (cx % 1 != 0)
    cz_is_half = (cz % 1 != 0)

    center_blocks = set()
    if cx_is_half and cz_is_half:
        center_blocks.add((int(cx - 0.5), int(cz - 0.5)))
    elif not cx_is_half and cz_is_half:
        bz = int(cz - 0.5)
        center_blocks.add((int(cx) - 1, bz))
        center_blocks.add((int(cx), bz))
    elif cx_is_half and not cz_is_half:
        bx = int(cx - 0.5)
        center_blocks.add((bx, int(cz) - 1))
        center_blocks.add((bx, int(cz)))
    else:
        for dx in (-1, 0):
            for dz in (-1, 0):
                center_blocks.add((int(cx) + dx, int(cz) + dz))

    for island in islands:
        cx_i, cz_i = island.center
        dist = np.sqrt((cx_i - map_center[0]) ** 2 + (cz_i - map_center[1]) ** 2)
        island.distance_to_center = float(dist)

        block_set = set(map(tuple, island.blocks))
        if center_blocks & block_set:
            island.has_center = True


# ---------------------------------------------------------------------------
# Polygon transforms (for symmetry analysis)
# ---------------------------------------------------------------------------

def reflect_polygon_x(poly_coords: List[List[float]], center_x: float) -> np.ndarray:
    """Reflect polygon coordinates across x = center_x."""
    pts = np.array(poly_coords)
    pts[:, 0] = 2 * center_x - pts[:, 0]
    return pts


def reflect_polygon_z(poly_coords: List[List[float]], center_z: float) -> np.ndarray:
    """Reflect polygon coordinates across z = center_z."""
    pts = np.array(poly_coords)
    pts[:, 1] = 2 * center_z - pts[:, 1]
    return pts


def rotate_polygon_180(poly_coords: List[List[float]], cx: float, cz: float) -> np.ndarray:
    """Rotate polygon coordinates 180 degrees around (cx, cz)."""
    pts = np.array(poly_coords)
    pts[:, 0] = 2 * cx - pts[:, 0]
    pts[:, 1] = 2 * cz - pts[:, 1]
    return pts


def rotate_polygon_90(poly_coords: List[List[float]], cx: float, cz: float) -> np.ndarray:
    """Rotate polygon coordinates 90 degrees CCW around (cx, cz)."""
    pts = np.array(poly_coords)
    dx = pts[:, 0] - cx
    dz = pts[:, 1] - cz
    new_pts = np.empty_like(pts)
    new_pts[:, 0] = cx + dz
    new_pts[:, 1] = cz - dx
    return new_pts


def polygon_iou(poly_a_coords, poly_b_coords) -> float:
    """Compute IoU (Intersection over Union) between two polygons using Shapely.

    Returns 0.0 on any error or degenerate geometry.
    """
    try:
        from shapely.geometry import Polygon
        from shapely.validation import make_valid

        pa = Polygon(poly_a_coords)
        pb = Polygon(poly_b_coords)

        if not pa.is_valid:
            pa = make_valid(pa)
        if not pb.is_valid:
            pb = make_valid(pb)

        if pa.is_empty or pb.is_empty:
            return 0.0

        intersection = pa.intersection(pb).area
        union = pa.union(pb).area

        if union < 1e-6:
            return 0.0
        return intersection / union
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# JSON serialization helper
# ---------------------------------------------------------------------------

def json_default(obj):
    """JSON serializer for numpy types.

    Use as: json.dump(data, f, default=json_default)
    """
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
