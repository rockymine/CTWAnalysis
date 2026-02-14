"""
ctw.core.math — pure math: rotations, D4 symmetry, neighbor offsets.

Dependency tier: NONE (leaf module, no imports from other ctw.core subpackages).
"""

from .rotations import rotate_points, rotate_points_int
from .d4 import (
    D4_ELEMENTS,
    lex_compare,
    compute_canonical_key,
    canonicalize_island,
)
from .offsets import NEIGHBOR_OFFSETS_8, NEIGHBOR_OFFSETS_4

__all__ = [
    "rotate_points",
    "rotate_points_int",
    "D4_ELEMENTS",
    "lex_compare",
    "compute_canonical_key",
    "canonicalize_island",
    "NEIGHBOR_OFFSETS_8",
    "NEIGHBOR_OFFSETS_4",
]
