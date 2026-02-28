"""
Skeleton analysis data types.

All coordinate conventions:
- Mask/skeleton space: (r, c) where r = row (z-axis), c = column (x-axis)
- World space: (x, z) as used in Minecraft coordinates
- Canonical space: world coords transformed via D4 symmetry, translated so minX=minZ=0

Coordinate transforms and space converters are centralised in
:mod:`common.geometry.transforms`; this module re-exports them for
backward compatibility.
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Re-export coordinate transforms from the canonical location so that all
# existing ``from .datatypes import CanonicalTransform, RasterMask`` imports
# continue to work without modification.
# ---------------------------------------------------------------------------
from common.geometry.transforms import (  # noqa: F401  (re-export)
    _rotate_points,
    CanonicalTransform,
    RasterMask,
    raster_to_world_path,
    raster_to_world_point,
)

# Re-export CanonicalIsland from island_analysis (moved there; skeleton_analysis
# re-exports for backward compatibility).
from island_analysis.datatypes import CanonicalIsland  # noqa: F401  (re-export)


@dataclass
class SkeletonPixels:
    """Raw skeleton pixel data with no processing."""
    mask: np.ndarray                 # (H, W) bool skeleton mask
    pixel_coords: np.ndarray         # Px2 array of (r, c) skeleton pixel coordinates


@dataclass
class GraphNode:
    """A node in the skeleton graph. Pure geometry — no POI semantic fields."""
    node_id: int
    rc: tuple[int, int]              # (r, c) position in mask space
    degree: int                      # Pixel degree in skeleton
    node_type: str                   # 'endpoint' or 'junction'


@dataclass
class GraphEdge:
    """An edge in the skeleton graph."""
    edge_id: int
    src: int                         # Source node_id
    dst: int                         # Destination node_id
    pixel_path: np.ndarray           # Ordered Px2 array of (r, c) along skeleton


@dataclass
class SkeletonGraph:
    """Complete skeleton graph for one island."""
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    skeleton_pixels: SkeletonPixels  # Reference to underlying skeleton


@dataclass
class IslandSkeleton:
    """Complete result for one island through the skeleton pipeline.

    Pure geometry — no POI, no team. Renamed from IslandResult.
    """
    island_id: int
    canonical: CanonicalIsland
    raster: RasterMask
    skeleton: SkeletonPixels
    graph: SkeletonGraph


# ---------------------------------------------------------------------------
# POI annotation types (live here to avoid circular imports with map_analysis)
# ---------------------------------------------------------------------------

@dataclass
class NodeAnnotation:
    """POI context for one skeleton node. Decoupled from GraphNode geometry."""
    node_id: int
    poi_type: str   # 'spawn' or 'wool'
    poi_color: str  # team color (for spawn) or wool color


@dataclass
class IslandGraph:
    """Contextualized island graph = skeleton geometry + team + POI annotations.

    Produced during assembly. The skeleton field is read-only (not mutated
    after IslandSkeleton is built). POI context is carried separately in
    node_annotations.
    """
    island_id: int
    team: Optional[str]
    skeleton: Optional[IslandSkeleton]
    node_annotations: dict  # int (node_id) -> NodeAnnotation


# ---------------------------------------------------------------------------
# Backward-compatibility alias
# ---------------------------------------------------------------------------

#: Alias for code that still references the old name.
IslandResult = IslandSkeleton
