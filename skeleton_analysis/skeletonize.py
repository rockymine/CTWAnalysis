"""
Skeletonization: compute pixel skeleton from boolean mask.

Minimal mode: no pruning, no smoothing, no simplification.
"""

import numpy as np
from skimage.morphology import skeletonize as skimage_skeletonize, medial_axis

from ctw.core.models import RasterMask, SkeletonPixels


def compute_skeleton(
    raster: RasterMask,
    method: str = 'thinning'
) -> SkeletonPixels:
    """
    Compute pixel skeleton from boolean mask.

    Args:
        raster: RasterMask with the island's boolean mask
        method: 'thinning' (Zhang-Suen) or 'medial_axis'

    Returns:
        SkeletonPixels with raw skeleton data
    """
    if method == 'thinning':
        skel_mask = skimage_skeletonize(raster.mask)
    elif method == 'medial_axis':
        skel_mask, _ = medial_axis(raster.mask, return_distance=True)
    else:
        raise ValueError(f"Unknown skeleton method: {method}. Use 'thinning' or 'medial_axis'.")

    skel_mask = skel_mask.astype(bool)

    # Extract pixel coordinates as (r, c)
    pixel_coords = np.argwhere(skel_mask)  # Nx2 array of (r, c)

    return SkeletonPixels(
        mask=skel_mask,
        pixel_coords=pixel_coords
    )
