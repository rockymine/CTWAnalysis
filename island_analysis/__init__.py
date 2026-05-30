"""
Islands sub-package.

Island detection, polygon construction, statistics, classification, and visualization.
"""

from .datatypes import Island, IslandPolygon, IslandBlocks, CanonicalIsland
from .detection import detect_islands, find_island_holes
from .canonicalize import canonicalize_island
from .polygon import build_island_polygon, build_island_polygons_canonical
from .statistics import compute_island_statistics, classify_islands
from .profile import (
    IslandFeatures,
    IslandRasterStrategy,
    IslandProfile,
    profile_islands,
    save_profiles,
    load_profiles,
)
from .visualization import (
    plot_islands,
    plot_island_polygons,
    plot_island_detail,
    plot_island_comparison,
    plot_island_statistics,
    create_island_report,
)

__all__ = [
    # Datatypes
    "Island",
    "IslandPolygon",
    "IslandBlocks",
    "CanonicalIsland",
    # Detection
    "detect_islands",
    "find_island_holes",
    # Canonicalization
    "canonicalize_island",
    # Polygon construction
    "build_island_polygon",
    "build_island_polygons_canonical",
    # Statistics
    "compute_island_statistics",
    "classify_islands",
    # Spatial profiling
    "IslandFeatures",
    "IslandRasterStrategy",
    "IslandProfile",
    "profile_islands",
    "save_profiles",
    "load_profiles",
    # Visualization
    "plot_islands",
    "plot_island_polygons",
    "plot_island_detail",
    "plot_island_comparison",
    "plot_island_statistics",
    "create_island_report",
]
