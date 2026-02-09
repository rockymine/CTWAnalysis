"""
Rasterization: convert canonical integer points to a boolean mask.

Convention: mask[r, c] where r = z-coordinate (row), c = x-coordinate (column).
"""

import numpy as np
from ctw.core.models import RasterMask


def rasterize_island(
    canonical_points: np.ndarray,
    padding: int = 1
) -> RasterMask:
    """
    Convert canonical integer points to a boolean mask.

    Args:
        canonical_points: Nx2 array of (x, z) integer coordinates with min=0
        padding: Number of empty pixels to add around the tight bounding box

    Returns:
        RasterMask with boolean mask and coordinate mapping
    """
    pts = canonical_points.astype(int)

    max_x = pts[:, 0].max()
    max_z = pts[:, 1].max()

    height = max_z + 1 + 2 * padding  # rows = z-axis
    width = max_x + 1 + 2 * padding   # cols = x-axis

    mask = np.zeros((height, width), dtype=bool)

    for x, z in pts:
        r = z + padding
        c = x + padding
        mask[r, c] = True

    origin = np.array([-padding, -padding], dtype=float)

    return RasterMask(
        mask=mask,
        padding=padding,
        origin=origin
    )
