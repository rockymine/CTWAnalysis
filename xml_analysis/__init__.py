"""
XML Analysis Package

Provides tools for parsing and visualizing Minecraft map XML configurations.
Analyzes teams, spawns, wools, and regions.
"""

from .parser import MapXMLParser
from .visualizer import MapVisualizer
from .exporter import MapDataEncoder

__version__ = "1.0.0"

__all__ = [
    "MapXMLParser",
    "MapVisualizer",
    "MapDataEncoder",
]
