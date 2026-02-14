"""
ctw.core.geom — Shapely/polygon geometry operations.

Dependency tier: standalone (may import from ctw.core.math in the future).
"""

from .polygons import (
    reflect_polygon_x,
    reflect_polygon_z,
    rotate_polygon_180,
    rotate_polygon_90,
    polygon_iou,
)

__all__ = [
    "reflect_polygon_x",
    "reflect_polygon_z",
    "rotate_polygon_180",
    "rotate_polygon_90",
    "polygon_iou",
]
