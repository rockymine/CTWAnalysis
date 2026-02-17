"""
Skeleton analysis sub-package.

Provides island skeletonization and graph extraction with D4 symmetry
canonicalization and deterministic edge walking.
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
from . import builder
from . import exporter

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
    # Modules
    "builder",
    "exporter",
    # Functions
    "canonicalize_island",
    "rasterize_island",
    "compute_skeleton",
    "compute_pixel_degrees",
    "extract_nodes",
    "extract_edges",
    "process_island",
    "process_all_islands",
]
