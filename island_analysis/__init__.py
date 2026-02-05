"""
Islands sub-package.

Island detection, triangulation, statistics, classification, and visualization.
"""

from .datatypes import Island
from .detection import detect_islands, find_island_holes
from .triangulation import triangulate_island_union, triangulate_islands_canonical
from .statistics import compute_island_statistics, classify_islands
from .visualization import (
    plot_islands,
    plot_island_triangulation,
    plot_triangulation_detail,
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
    # Triangulation
    "triangulate_island_union",
    "triangulate_islands_canonical",
    # Statistics
    "compute_island_statistics",
    "classify_islands",
    # Visualization
    "plot_islands",
    "plot_island_triangulation",
    "plot_triangulation_detail",
    "plot_island_comparison",
    "plot_island_statistics",
    "create_island_report",
]
