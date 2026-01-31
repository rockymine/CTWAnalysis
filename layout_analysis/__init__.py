"""
Layout Analysis Package

Provides tools for analyzing Minecraft world layouts from Anvil region files.
Supports extraction of Y0 layer, top surface, and density-based point sets.
Also provides island detection and triangulation for map topology analysis.
"""

from .extractors import Y0LayerExtractor, TopSurfaceExtractor, VerticalDensityExtractor, LowestBedrockExtractor
from .region_reader import RegionReader
from .plotting import save_point_plot
from .utils import nibble, decode_block_id, decode_block_data, get_block_index
from .islands import (
    Island,
    detect_islands,
    triangulate_island_union,
    triangulate_islands_canonical,
    find_island_holes,
    compute_island_statistics,
    classify_islands,
    plot_islands,
    plot_island_triangulation,
    plot_triangulation_detail,
    plot_island_comparison,
    plot_island_statistics,
    create_island_report,
)

__version__ = "1.0.0"

__all__ = [
    # Extractors
    "Y0LayerExtractor",
    "TopSurfaceExtractor",
    "VerticalDensityExtractor",
    "LowestBedrockExtractor",
    "RegionReader",
    "save_point_plot",
    # Utils
    "nibble",
    "decode_block_id",
    "decode_block_data",
    "get_block_index",
    # Island detection
    "Island",
    "detect_islands",
    "triangulate_island_union",
    "triangulate_islands_canonical",
    "find_island_holes",
    "compute_island_statistics",
    "classify_islands",
    # Island visualization
    "plot_islands",
    "plot_island_triangulation",
    "plot_triangulation_detail",
    "plot_island_comparison",
    "plot_island_statistics",
    "create_island_report",
]
