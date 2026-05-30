"""Data classes for symmetry analysis."""

from dataclasses import dataclass
from typing import Any, Optional

# Symmetry-group order for tie-breaking in primary selection.
# rot_90 (order 4) > rot_180 (order 2) > mirrors (order 1).
_SYMMETRY_ORDER: dict[str, int] = {
    'rot_90': 4,
    'rot_180': 2,
    'mirror_x': 1,
    'mirror_z': 1,
}


@dataclass
class SymmetryResult:
    """Result of geometric symmetry analysis (detect_symmetry()).

    Carries the in-memory payload produced by detect_symmetry() so the
    pipeline can pass it directly to assemble_map() without a round-trip
    through symmetry.json.  The symmetry.json artifact is still written
    for human inspection and for backwards-compatible fallback.

    Fields mirror the top-level keys of the JSON output exactly.
    """
    map_name: str
    center: dict[str, Any]           # center_x, center_z, type, description, blocks
    pair_analysis: dict[str, Any]    # total_pairs, transform_counts, pairs
    global_symmetry: list[dict[str, Any]]  # per-candidate symmetry entries

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def center_x(self) -> float:
        return self.center['center_x']

    @property
    def center_z(self) -> float:
        return self.center['center_z']

    @property
    def primary(self) -> Optional[dict[str, Any]]:
        """Highest-confidence detected global symmetry entry, or None.

        Ties in confidence are broken by symmetry order (rot_90 > rot_180 > mirror)
        so that the strongest applicable symmetry type is always reported.
        """
        detected = [s for s in self.global_symmetry if s['detected']]
        return (
            max(detected, key=lambda s: (s['confidence'], _SYMMETRY_ORDER.get(s['type'], 0)))
            if detected else None
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return the plain dict used by symmetry_exporter.save()."""
        return {
            'map_name': self.map_name,
            'center': self.center,
            'pair_analysis': self.pair_analysis,
            'global_symmetry': self.global_symmetry,
        }
