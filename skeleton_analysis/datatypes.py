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
from typing import List, Tuple, Optional, Dict

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


@dataclass
class CanonicalIsland:
    """An island in its canonical (symmetry-normalized) orientation."""
    island_id: int
    canonical_points: np.ndarray     # Nx2 int coords, min=0
    canonical_key: str               # Hash of sorted canonical_points
    transform: CanonicalTransform    # Maps world <-> canonical
    world_blocks: np.ndarray         # Original Nx2 world coords (reference)


@dataclass
class SkeletonPixels:
    """Raw skeleton pixel data with no processing."""
    mask: np.ndarray                 # (H, W) bool skeleton mask
    pixel_coords: np.ndarray         # Px2 array of (r, c) skeleton pixel coordinates


@dataclass
class GraphNode:
    """A node in the skeleton graph."""
    node_id: int
    rc: Tuple[int, int]              # (r, c) position in mask space
    degree: int                      # Pixel degree in skeleton
    node_type: str                   # 'endpoint' or 'junction'
    poi_type: Optional[str] = None   # 'spawn', 'wool', or None
    poi_color: Optional[str] = None  # team color (spawn) or wool color


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
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    skeleton_pixels: SkeletonPixels  # Reference to underlying skeleton


@dataclass
class IslandResult:
    """Complete result for one island through the skeleton pipeline."""
    island_id: int
    canonical: CanonicalIsland
    raster: RasterMask
    skeleton: SkeletonPixels
    graph: SkeletonGraph
