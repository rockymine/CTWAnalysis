"""Data classes for map analysis pipeline."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from common.geometry import BoundingBox, Point2D
from island_analysis.datatypes import Island, IslandPolygon
from skeleton_analysis.datatypes import IslandSkeleton, IslandGraph, NodeAnnotation


@dataclass
class IslandAnalysis:
    """Pipeline result of the island geometry step (run_island_geometry).

    Carries all in-memory objects produced by island detection, polygon
    construction, and skeleton computation.  Passed directly to assemble_map()
    so that no intermediate JSON file needs to be read back by the pipeline.
    The islands.json artifact written by run_island_geometry is for human
    inspection and for the symmetry step only.

    islands contains IslandPolygon objects (pure geometry, no XML fields).
    The fully contextualized Island objects (with team/spawn/wool) are
    constructed during assemble_map() after XML annotation.
    """
    islands: list[IslandPolygon]
    skeletons: list[IslandSkeleton]
    canonical_groups: dict[str, list[int]]
    df: Any                                      # pd.DataFrame
    island_output_dir: Path
    map_center_pt: Optional[Point2D]


# Backward-compatibility alias — callers using the old name continue to work.
IslandGeometryResult = IslandAnalysis


@dataclass
class MapContext:
    """Comprehensive map information aggregating all analysis results."""

    # Map metadata (from XML)
    map_name: str = ""
    map_version: str = ""
    objective: str = ""
    teams: list[dict] = field(default_factory=list)

    # Layout info
    bounding_box: Optional[BoundingBox] = None
    map_center: Optional[Point2D] = None
    total_blocks: int = 0

    # Islands summary
    island_count: int = 0
    islands: list[dict] = field(default_factory=list)

    # Skeleton summary
    total_nodes: int = 0
    total_edges: int = 0
    total_endpoints: int = 0
    total_junctions: int = 0
    unique_canonical_shapes: int = 0

    # POI summary
    poi_assignments: dict = field(default_factory=dict)

    # Build region
    build_region: Optional[dict] = None
