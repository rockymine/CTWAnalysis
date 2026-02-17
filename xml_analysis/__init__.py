"""
XML Analysis Package

Provides tools for parsing and visualizing Minecraft map XML configurations.
Analyzes teams, spawns, wools, and regions.
"""

from .datatypes import MapData, Team, Spawn, Wool, ApplyRule
from .parser import MapXMLParser
from .visualization import MapVisualizer
from . import exporter

__version__ = "1.0.0"

__all__ = [
    "MapData",
    "MapXMLParser",
    "MapVisualizer",
    "exporter",
]
