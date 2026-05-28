"""
Layout Analysis Package

Provides tools for analyzing Minecraft world layouts from Anvil region files.
Supports extraction of Y0 layer, top surface, bedrock, and solid-layer point sets.
Also provides island detection and polygon construction for map topology analysis.
"""

from .extractors import (
    Y0LayerExtractor,
    TopSurfaceExtractor,
    LowestBedrockExtractor,
    LowestSolidLayerExtractor,
    VerticalSegmentsExtractor,
)
from .region_reader import RegionReader
from .visualization import save_point_plot
from .utils import nibble, decode_block_id, decode_block_data, get_block_index
from .features import ResourceBlockExtractor, ChestExtractor

__version__ = "1.0.0"

__all__ = [
    # Extractors
    "Y0LayerExtractor",
    "TopSurfaceExtractor",
    "LowestBedrockExtractor",
    "LowestSolidLayerExtractor",
    "VerticalSegmentsExtractor",
    "RegionReader",
    "save_point_plot",
    # Utils
    "nibble",
    "decode_block_id",
    "decode_block_data",
    "get_block_index",
    # Feature extractors
    "ResourceBlockExtractor",
    "ChestExtractor",
]
