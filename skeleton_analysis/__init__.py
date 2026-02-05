"""
Skeleton analysis sub-package.

Provides island skeletonization and graph extraction with D4 symmetry
canonicalization, deterministic edge walking, and intra-island pathfinding.
"""

from .datatypes import (
    CanonicalTransform,
    CanonicalIsland,
    RasterMask,
    SkeletonPixels,
    GraphNode,
    GraphEdge,
    SkeletonGraph,
    IslandResult,
)

from .canonicalize import canonicalize_island
from .rasterize import rasterize_island
from .skeletonize import compute_skeleton
from .nodes import compute_pixel_degrees, extract_nodes
from .edges import extract_edges
from .pipeline import process_island, process_all_islands
from .pathfinding import (
    run_pathfinding_analysis,
    analyze_island_paths,
    load_skeleton_graph,
    load_edge_pixels,
    get_edge_detail,
    get_path_detail,
)

__all__ = [
    # Data types
    "CanonicalTransform",
    "CanonicalIsland",
    "RasterMask",
    "SkeletonPixels",
    "GraphNode",
    "GraphEdge",
    "SkeletonGraph",
    "IslandResult",
    # Functions
    "canonicalize_island",
    "rasterize_island",
    "compute_skeleton",
    "compute_pixel_degrees",
    "extract_nodes",
    "extract_edges",
    "process_island",
    "process_all_islands",
    # Pathfinding
    "run_pathfinding_analysis",
    "analyze_island_paths",
    "load_skeleton_graph",
    "load_edge_pixels",
    "get_edge_detail",
    "get_path_detail",
]
