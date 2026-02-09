"""
ctw.core — shared geometry and model foundations.

Provides:
    ctw.core.geometry   Shared math, D4 symmetry, coordinate conversions.
    ctw.core.models     Island, MapContext, and skeleton dataclasses.
"""

from .geometry import (
    # Rotation
    rotate_points,
    rotate_points_int,
    # D4 symmetry
    D4_ELEMENTS,
    lex_compare,
    compute_canonical_key,
    canonicalize_island,
    # Neighbor offsets
    NEIGHBOR_OFFSETS_8,
    NEIGHBOR_OFFSETS_4,
    # Map center / classification
    compute_map_center,
    classify_center,
    classify_island_center,
    # Polygon transforms
    reflect_polygon_x,
    reflect_polygon_z,
    rotate_polygon_180,
    rotate_polygon_90,
    polygon_iou,
    # JSON
    json_default,
)

from .models import (
    # Island
    Island,
    # Skeleton types
    CanonicalTransform,
    CanonicalIsland,
    RasterMask,
    SkeletonPixels,
    GraphNode,
    GraphEdge,
    SkeletonGraph,
    IslandResult,
    # MapContext
    MapContext,
    build_map_context,
    build_skeleton_dicts,
)

__all__ = [
    # geometry
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
    "build_map_context",
    "build_skeleton_dicts",
]
