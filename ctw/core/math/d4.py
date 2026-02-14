"""
D4 dihedral symmetry group operations and island canonicalization.

No module-level dependencies on ctw.core.models; canonicalize_island
uses a deferred import to create model objects at call time.
"""

import hashlib
import numpy as np

from .rotations import rotate_points_int


# The 8 elements of the D4 group (dihedral group of the square):
# 4 rotations x 2 mirror states
D4_ELEMENTS = [
    (0, False), (90, False), (180, False), (270, False),
    (0, True),  (90, True),  (180, True),  (270, True),
]


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
