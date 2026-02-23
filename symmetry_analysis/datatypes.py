"""Data classes for symmetry analysis."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


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
    center: Dict[str, Any]           # center_x, center_z, type, description, blocks
    pair_analysis: Dict[str, Any]    # total_pairs, transform_counts, pairs
    global_symmetry: List[Dict[str, Any]]  # per-candidate symmetry entries

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
    def primary(self) -> Optional[Dict[str, Any]]:
        """Highest-confidence detected global symmetry entry, or None."""
        detected = [s for s in self.global_symmetry if s['detected']]
        return max(detected, key=lambda s: s['confidence']) if detected else None

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return the plain dict used by symmetry_exporter.save()."""
        return {
            'map_name': self.map_name,
            'center': self.center,
            'pair_analysis': self.pair_analysis,
            'global_symmetry': self.global_symmetry,
        }
