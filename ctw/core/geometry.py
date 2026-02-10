"""
Backward-compatibility shim for ctw.core.geometry.

All symbols have moved to their respective tier subpackages:
    ctw.core.math       — rotations, D4 group, offsets, canonicalization
    ctw.core.minecraft   — map center, center classification
    ctw.core.geom        — polygon transforms, IoU
    ctw.core.builders    — json_default

This module re-exports everything so that existing ``from ctw.core.geometry
import ...`` statements continue to work.
"""

# math tier
from ctw.core.math import (
    rotate_points,
    rotate_points_int,
    D4_ELEMENTS,
    lex_compare,
    compute_canonical_key,
    canonicalize_island,
    NEIGHBOR_OFFSETS_8,
    NEIGHBOR_OFFSETS_4,
)

# minecraft tier
from ctw.core.minecraft import (
    compute_map_center,
    classify_center,
    classify_island_center,
)

# geom tier
from ctw.core.geom import (
    reflect_polygon_x,
    reflect_polygon_z,
    rotate_polygon_180,
    rotate_polygon_90,
    polygon_iou,
)

# builders tier
from ctw.core.builders import json_default

__all__ = [
    "rotate_points",
    "rotate_points_int",
    "D4_ELEMENTS",
    "lex_compare",
    "compute_canonical_key",
    "canonicalize_island",
    "NEIGHBOR_OFFSETS_8",
    "NEIGHBOR_OFFSETS_4",
    "compute_map_center",
    "classify_center",
    "classify_island_center",
    "reflect_polygon_x",
    "reflect_polygon_z",
    "rotate_polygon_180",
    "rotate_polygon_90",
    "polygon_iou",
    "json_default",
]
