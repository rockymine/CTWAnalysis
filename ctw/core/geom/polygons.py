"""
Polygon transform and comparison utilities (Shapely-based).

Dependency tier: standalone (only uses numpy and shapely).
"""

import numpy as np
from typing import List


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
