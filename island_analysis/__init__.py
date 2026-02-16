"""
Islands sub-package.

Island detection, polygon construction, statistics, classification, and visualization.
"""

from .datatypes import Island
from .detection import detect_islands, find_island_holes
from .polygon import build_island_polygon, build_island_polygons_canonical
from .statistics import compute_island_statistics, classify_islands
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
    # Detection
    "detect_islands",
    "find_island_holes",
    # Polygon construction
    "build_island_polygon",
    "build_island_polygons_canonical",
    # Statistics
    "compute_island_statistics",
    "classify_islands",
    # Visualization
    "plot_islands",
    "plot_island_polygons",
    "plot_island_detail",
    "plot_island_comparison",
    "plot_island_statistics",
    "create_island_report",
]
