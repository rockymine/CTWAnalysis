"""
Island data types.
"""

import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass, field


@dataclass
class Island:
    """Represents a detected island in the map."""
    id: int
    blocks: np.ndarray  # Nx2 array of (x, z) coordinates
    center: Tuple[float, float]  # Centroid
    area: int  # Number of blocks
    bounding_box: Tuple[int, int, int, int]  # (min_x, max_x, min_z, max_z)
    hull_vertices: np.ndarray = None  # Convex hull vertices
    simplified_polygon: Optional[dict] = None  # {exterior: [[x,z],...], holes: [...]}
    holes: List[np.ndarray] = field(default_factory=list)  # Internal air pockets
    skeleton_result: Optional[object] = None  # IslandResult from skeleton pipeline
    has_spawn: bool = False
    has_wool: bool = False
    has_center: bool = False
    distance_to_center: float = 0.0
    team: Optional[str] = None  # Team id if spawn island
