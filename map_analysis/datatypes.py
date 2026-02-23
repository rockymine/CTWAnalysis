"""Data classes for map analysis pipeline."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from island_analysis.datatypes import Island
from skeleton_analysis.datatypes import IslandResult


@dataclass
class IslandGeometryResult:
    """Pipeline result of the island geometry step (run_island_geometry).

    Carries all in-memory objects produced by island detection, polygon
    construction, and skeleton computation.  Passed directly to assemble_map()
    so that no intermediate JSON file needs to be read back by the pipeline.
    The islands.json artifact written by run_island_geometry is for human
    inspection and for the symmetry step only.
    """
    islands: List[Island]
    skeleton_results: List[IslandResult]
    canonical_groups: Dict[str, List[int]]
    df: Any                                      # pd.DataFrame
    island_output_dir: Path
    map_center_pt: Optional[Tuple[float, float]]


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
