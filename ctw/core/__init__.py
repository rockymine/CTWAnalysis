"""
ctw.core — shared geometry and model foundations.

Tiered subpackages (dependency direction: left -> right):

    math        No deps (rotations, D4, offsets)
    minecraft   Standalone (map center, block semantics)
    geom        Standalone (polygon transforms, IoU)
    models      Imports math (Island, skeleton types, MapContext)
    builders    Imports models (context builders, JSON serialization)

Backward-compatible shims:
    ctw.core.geometry   re-exports from math + minecraft + geom + builders
    ctw.core.models     re-exports everything (is now a package)
"""

# -- math tier --
from .math import (
    rotate_points,
    rotate_points_int,
    D4_ELEMENTS,
    lex_compare,
    compute_canonical_key,
    canonicalize_island,
    NEIGHBOR_OFFSETS_8,
    NEIGHBOR_OFFSETS_4,
)

# -- minecraft tier --
from .minecraft import (
    compute_map_center,
    classify_center,
    classify_island_center,
)

# -- geom tier --
from .geom import (
    reflect_polygon_x,
    reflect_polygon_z,
    rotate_polygon_180,
    rotate_polygon_90,
    polygon_iou,
)

# -- models tier --
from .models import (
    Island,
    CanonicalTransform,
    CanonicalIsland,
    RasterMask,
    SkeletonPixels,
    GraphNode,
    GraphEdge,
    SkeletonGraph,
    IslandResult,
    MapContext,
)

# -- builders tier --
from .builders import (
    json_default,
    build_map_context,
    build_skeleton_dicts,
)

__all__ = [
    # math
    "rotate_points",
    "rotate_points_int",
    "D4_ELEMENTS",
    "lex_compare",
    "compute_canonical_key",
    "canonicalize_island",
    "NEIGHBOR_OFFSETS_8",
    "NEIGHBOR_OFFSETS_4",
    # minecraft
    "compute_map_center",
    "classify_center",
    "classify_island_center",
    # geom
    "reflect_polygon_x",
    "reflect_polygon_z",
    "rotate_polygon_180",
    "rotate_polygon_90",
    "polygon_iou",
    # models
    "Island",
    "CanonicalTransform",
    "CanonicalIsland",
    "RasterMask",
    "SkeletonPixels",
    "GraphNode",
    "GraphEdge",
    "SkeletonGraph",
    "IslandResult",
    "MapContext",
    # builders
    "json_default",
    "build_map_context",
    "build_skeleton_dicts",
]
