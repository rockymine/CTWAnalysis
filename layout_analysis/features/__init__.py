"""
Feature extraction for Minecraft map analysis.

Extracts map features that are not captured by the standard layout layers:
- Resource blocks (iron, gold, diamond blocks) at all Y levels
- Chest locations and their inventory contents
"""

from .resource_blocks import ResourceBlockExtractor
from .chests import ChestExtractor

__all__ = [
    "ResourceBlockExtractor",
    "ChestExtractor",
]
