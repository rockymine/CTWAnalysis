"""
D4 symmetry canonicalization for islands.

Re-exports canonicalize_island from ctw.core.geometry for backward
compatibility. All D4 math now lives in ctw.core.geometry.
"""

from ctw.core.geometry import (
    canonicalize_island,
    rotate_points_int as _rotate_int,
    D4_ELEMENTS as _D4_ELEMENTS,
    lex_compare as _lex_compare,
    compute_canonical_key as _compute_canonical_key,
)

__all__ = ["canonicalize_island"]
