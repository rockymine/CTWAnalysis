"""
Skeleton analysis dataclasses.

Coordinate conventions:
- Mask/skeleton space: (r, c) where r = row (z-axis), c = column (x-axis)
- World space: (x, z) as used in Minecraft coordinates
- Canonical space: world coords transformed via D4 symmetry, with minX=minZ=0

Dependency tier: imports from ctw.core.math (for rotate_points).
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

from ctw.core.math import rotate_points


@dataclass
class CanonicalTransform:
    """Encodes the D4 transformation between world and canonical space.

    The forward transform (to_canonical) applies:
      1. If mirror: flip X axis
      2. Apply rotation (0/90/180/270)
      3. Add translation (so minX=minZ=0)

    The reverse transform (to_original) undoes these steps.

    world_center is unused (kept at zeros) since the integer-based
    canonicalization doesn't use float centering.
    """
    rotation: int                    # 0, 90, 180, 270 degrees
    mirror: bool                     # Whether X is flipped before rotation
    translation: np.ndarray          # 2-vector added after rotation (= -min_vals)
    world_center: np.ndarray         # unused, kept for compatibility (zeros)

    def to_canonical(self, points: np.ndarray) -> np.ndarray:
        """Transform world (x, z) points to canonical space."""
        pts = np.round(points).astype(int)
        if self.mirror:
            pts = pts.copy()
            pts[:, 0] = -pts[:, 0]
        pts = rotate_points(pts.astype(float), self.rotation)
        pts = pts + self.translation
        return np.round(pts).astype(int)

    def to_original(self, points: np.ndarray) -> np.ndarray:
        """Transform canonical (x, z) points back to world space."""
        pts = points.astype(float) - self.translation
        pts = rotate_points(pts, -self.rotation % 360)
        if self.mirror:
            pts[:, 0] = -pts[:, 0]
        return pts


@dataclass
class CanonicalIsland:
    """An island in its canonical (symmetry-normalized) orientation."""
    island_id: int
    canonical_points: np.ndarray     # Nx2 int coords, min=0
    canonical_key: str               # Hash of sorted canonical_points
    transform: CanonicalTransform    # Maps world <-> canonical
    world_blocks: np.ndarray         # Original Nx2 world coords (reference)


@dataclass
class RasterMask:
    """Boolean mask for a rasterized island.

    Convention: mask[r, c] where r corresponds to z-axis, c to x-axis.
    """
    mask: np.ndarray                 # (H, W) bool
    padding: int                     # Padding applied around tight bbox
    origin: np.ndarray               # (x, z) of mask[0, 0] in canonical coords

    def rc_to_canonical(self, r: int, c: int) -> Tuple[int, int]:
        """Convert mask (r, c) to canonical (x, z)."""
        x = c + int(self.origin[0])
        z = r + int(self.origin[1])
        return (x, z)

    def canonical_to_rc(self, x: int, z: int) -> Tuple[int, int]:
        """Convert canonical (x, z) to mask (r, c)."""
        r = z - int(self.origin[1])
        c = x - int(self.origin[0])
        return (r, c)


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
