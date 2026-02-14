"""
Skeleton analysis sub-package.

Provides island skeletonization and graph extraction with D4 symmetry
canonicalization, deterministic edge walking, and intra-island pathfinding.

Data types are re-exported from ctw.core.models for backward compatibility.
"""

from ctw.core.models.skeleton import (
    CanonicalTransform,
    CanonicalIsland,
    RasterMask,
    SkeletonPixels,
    GraphNode,
    GraphEdge,
    SkeletonGraph,
    IslandResult,
)

from ctw.core.math.d4 import canonicalize_island
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
    # Data types (from ctw.core.models)
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
