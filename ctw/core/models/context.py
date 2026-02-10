"""
MapContext dataclass for aggregated map information.

Dependency tier: imports from ctw.core.builders (for json_default in save_json).
"""

import json
import os
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional


@dataclass
class MapContext:
    """Comprehensive map information aggregating all analysis results."""

    # Map metadata (from XML)
    map_name: str = ""
    map_version: str = ""
    objective: str = ""
    teams: List[Dict] = field(default_factory=list)

    # Layout info
    bounding_box: Optional[Tuple[float, float, float, float]] = None
    map_center: Optional[Tuple[float, float]] = None
    total_blocks: int = 0

    # Islands summary
    island_count: int = 0
    islands: List[Dict] = field(default_factory=list)

    # Skeleton summary
    total_nodes: int = 0
    total_edges: int = 0
    total_endpoints: int = 0
    total_junctions: int = 0
    unique_canonical_shapes: int = 0

    # POI summary
    poi_assignments: Dict = field(default_factory=dict)

    # Build region
    build_region: Optional[Dict] = None

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return {
            'map_name': self.map_name,
            'map_version': self.map_version,
            'objective': self.objective,
            'teams': self.teams,
            'bounding_box': list(self.bounding_box) if self.bounding_box else None,
            'map_center': list(self.map_center) if self.map_center else None,
            'total_blocks': self.total_blocks,
            'island_count': self.island_count,
            'islands': self.islands,
            'skeleton': {
                'total_nodes': self.total_nodes,
                'total_edges': self.total_edges,
                'total_endpoints': self.total_endpoints,
                'total_junctions': self.total_junctions,
                'unique_canonical_shapes': self.unique_canonical_shapes,
            },
            'poi_assignments': self.poi_assignments,
            'build_region': self.build_region,
        }

    def save_json(self, output_path: str) -> None:
        """Save to JSON file."""
        from ctw.core.builders.serialization import json_default

        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, default=json_default)
        print(f"Map context saved to: {output_path}")
