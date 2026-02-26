"""Backward-compatibility shim.

canonicalize_island() and CanonicalIsland have moved to island_analysis.
This module re-exports them so that existing imports from skeleton_analysis
continue to work.
"""

from island_analysis.canonicalize import canonicalize_island  # noqa: F401
from island_analysis.datatypes import CanonicalIsland  # noqa: F401
