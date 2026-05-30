"""
Feature extraction for Minecraft map analysis.

Extracts map features that are not captured by the standard layout layers:
- Resource blocks (iron, gold, diamond blocks) at all Y levels
- Chest locations and their inventory contents
- Tile entities (mob spawners, …) with full NBT configuration fields
"""

from .resource_blocks import ResourceBlockExtractor
from .chests import ChestExtractor, detect_double_chests
from .tile_entities import TileEntityExtractor
from .zone_classifier import ZoneClassifier

__all__ = [
    "ResourceBlockExtractor",
    "ChestExtractor",
    "detect_double_chests",
    "TileEntityExtractor",
    "ZoneClassifier",
]
