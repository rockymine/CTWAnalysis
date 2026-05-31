"""
XML Analysis Package

Provides tools for parsing Minecraft map XML configurations.
Analyzes teams, spawns, wools, and regions.
"""

from .datatypes import MapData, MapXmlContext, Team, Spawn, Wool, ApplyRule
from .builder import MapXMLParser
from . import builder
from . import exporter

__version__ = "1.0.0"

__all__ = [
    "MapData",
    "MapXmlContext",
    "MapXMLParser",
    "builder",
    "exporter",
]
