"""
Island data types.
"""

import numpy as np
from typing import Optional
from dataclasses import dataclass, field

from common.geometry import BoundingBox, Point2D


@dataclass
class Island:
    """Represents a detected island in the map."""
    id: int
    blocks: np.ndarray  # Nx2 array of (x, z) coordinates
    center: Point2D
    area: int  # Number of blocks
    bounding_box: BoundingBox
    hull_vertices: Optional[np.ndarray] = None  # Convex hull vertices
    simplified_polygon: Optional[dict] = None  # {exterior: [[x,z],...], holes: [...]}
    holes: list[np.ndarray] = field(default_factory=list)  # Internal air pockets
    skeleton_result: Optional[object] = None  # IslandResult from skeleton pipeline
    has_spawn: bool = False
    has_wool: bool = False
    has_center: bool = False
    distance_to_center: float = 0.0
    team: Optional[str] = None  # Team id if spawn island
