"""
Island data types — layered hierarchy from raw blocks to contextualized island.
"""

import numpy as np
from typing import Optional
from dataclasses import dataclass, field

from common.geometry import BoundingBox, Point2D
from common.geometry.transforms import CanonicalTransform


@dataclass
class IslandBlocks:
    """Minimal island from block detection. Pure intrinsic geometry.

    Produced by detect_islands(); no polygon, no skeleton, no XML.
    """
    id: int
    blocks: np.ndarray      # Nx2 array of (x, z) world coordinates
    center: Point2D
    area: int               # Number of blocks
    bounding_box: BoundingBox


@dataclass
class IslandPolygon(IslandBlocks):
    """Island with polygon outline and map-center classification.

    All fields derivable from block geometry alone — no XML.
    Produced by detect_islands() + build_polygons(); consumed by the skeleton
    pipeline, symmetry analysis, and assembly.
    """
    hull_vertices: Optional[np.ndarray] = None
    simplified_polygon: Optional[dict] = None   # {exterior: [[x,z],...], holes: [[x,z],...]}
    smoothed_polygon: Optional[dict] = None     # same shape; only set when buffer>0 or simplify>0
    holes: list = field(default_factory=list)   # list[np.ndarray] internal air pockets
    has_center: bool = False
    distance_to_center: float = 0.0


@dataclass
class Island(IslandPolygon):
    """Fully contextualized island — polygon geometry + XML-derived semantic fields.

    Produced during assembly (assemble_map) when XML data is combined with geometry.
    """
    has_spawn: bool = False
    has_wool: bool = False
    team: Optional[str] = None          # team id if spawn island
    is_observer_island: bool = False    # True when this island holds the observer spawn


@dataclass
class CanonicalIsland:
    """D4-canonical form of an island.

    Represents a pure geometric property of the island shape.
    Moved here from skeleton_analysis; canonical form is an island-geometry
    concept, not a skeleton concept.
    """
    island_id: int
    canonical_points: np.ndarray  # Nx2 int coords, min=0
    canonical_key: str            # sha256[:16] of sorted canonical_points
    transform: CanonicalTransform # maps world <-> canonical
    world_blocks: np.ndarray      # Nx2 original world coords (reference copy)
