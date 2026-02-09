"""
Skeleton analysis data types.

Re-exports all skeleton model classes from ctw.core.models for backward
compatibility.

All coordinate conventions:
- Mask/skeleton space: (r, c) where r = row (z-axis), c = column (x-axis)
- World space: (x, z) as used in Minecraft coordinates
- Canonical space: world coords transformed via D4 symmetry, translated so minX=minZ=0
"""

from ctw.core.models import (
    CanonicalTransform,
    CanonicalIsland,
    RasterMask,
    SkeletonPixels,
    GraphNode,
    GraphEdge,
    SkeletonGraph,
    IslandResult,
)

# Re-export rotate_points for any code that imported _rotate_points from here
from ctw.core.geometry import rotate_points as _rotate_points

__all__ = [
    "CanonicalTransform",
    "CanonicalIsland",
    "RasterMask",
    "SkeletonPixels",
    "GraphNode",
    "GraphEdge",
    "SkeletonGraph",
    "IslandResult",
]
