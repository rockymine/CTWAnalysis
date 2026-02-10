"""
Pure 2D rotation functions for multiples of 90 degrees.

No dependencies on other ctw.core modules.
"""

import numpy as np


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
