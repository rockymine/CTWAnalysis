"""
ctw.core.models — shared dataclasses for CTW Analysis.

Dependency tier: imports from ctw.core.math (via skeleton.py for rotate_points).
Does NOT import from ctw.core.geom.
"""

from .island import Island
from .skeleton import (
    CanonicalTransform,
    CanonicalIsland,
    RasterMask,
    SkeletonPixels,
    GraphNode,
    GraphEdge,
    SkeletonGraph,
    IslandResult,
)
from .context import MapContext

# Re-export builder functions for backward compatibility with
# code that does `from ctw.core.models import build_map_context`.
# New code should import from ctw.core.builders directly.
from ctw.core.builders.context import build_map_context, build_skeleton_dicts

__all__ = [
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
    # backward compat re-exports
    "build_map_context",
    "build_skeleton_dicts",
]
