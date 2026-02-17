"""Data classes for layout analysis."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class MapContext:
    """Comprehensive map information aggregating all analysis results."""

    # Map metadata (from XML)
    map_name: str = ""
    map_version: str = ""
    objective: str = ""
    teams: List[Dict] = field(default_factory=list)

    # Layout info
    bounding_box: Optional[Tuple[float, float, float, float]] = None  # min_x, max_x, min_z, max_z
    map_center: Optional[Tuple[float, float]] = None
    total_blocks: int = 0

    # Islands summary
    island_count: int = 0
    islands: List[Dict] = field(default_factory=list)

    # Skeleton summary
    total_nodes: int = 0
    total_edges: int = 0
    total_endpoints: int = 0
    total_junctions: int = 0
    unique_canonical_shapes: int = 0

    # POI summary
    poi_assignments: Dict = field(default_factory=dict)

    # Build region
    build_region: Optional[Dict] = None
