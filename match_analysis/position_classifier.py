"""Position classification and skeleton path snapping for match analysis.

Classifies player position events against map geometry (islands, build regions, void)
and optionally snaps positions to nearest skeleton edge pixels.
"""

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from shapely.geometry import Point, Polygon


class PositionClassifier:
    """Classifies positions against map geometry. Load once, classify many.

    Args:
        map_context: Parsed map_context.json dict.
        map_graph: Parsed map_graph.json dict.
    """

    def __init__(self, map_context: dict, map_graph: dict):
        self._island_polygons: List[Tuple[int, Polygon]] = []
        self._build_polygons: List[Polygon] = []
        self._node_list: List[dict] = []
        self._node_coords: Optional[np.ndarray] = None
        self._edge_pixels_by_island: Dict[int, np.ndarray] = {}

        self._build_island_polygons(map_context)
        self._build_region_polygons(map_context)
        self._build_node_index(map_graph)
        self._build_edge_pixel_index(map_graph)

    def _build_island_polygons(self, map_context: dict) -> None:
        """Build Shapely Polygons from island simplified_polygon data."""
        for island in map_context.get('islands', []):
            poly_data = island.get('simplified_polygon')
            if poly_data is None:
                continue
            exterior = poly_data.get('exterior', [])
            if len(exterior) < 3:
                continue
            holes = [h for h in poly_data.get('holes', []) if len(h) >= 3]
            try:
                polygon = Polygon(exterior, holes)
                if polygon.is_valid:
                    self._island_polygons.append((island['id'], polygon))
            except Exception:
                pass

    def _build_region_polygons(self, map_context: dict) -> None:
        """Build Shapely Polygons from buildable_void data."""
        build_region = map_context.get('build_region')
        if not build_region:
            return
        for poly_data in build_region.get('buildable_void', []):
            exterior = poly_data.get('exterior', [])
            if len(exterior) < 3:
                continue
            holes = [h for h in poly_data.get('holes', []) if len(h) >= 3]
            try:
                polygon = Polygon(exterior, holes)
                if polygon.is_valid:
                    self._build_polygons.append(polygon)
            except Exception:
                pass

    def _build_node_index(self, map_graph: dict) -> None:
        """Extract map graph nodes into a list + numpy coords array."""
        graph_section = map_graph.get('map_graph', {})
        self._node_list = graph_section.get('nodes', [])
        if self._node_list:
            self._node_coords = np.array(
                [n['coords'] for n in self._node_list], dtype=np.float64,
            )
        else:
            self._node_coords = np.empty((0, 2), dtype=np.float64)

    def _build_edge_pixel_index(self, map_graph: dict) -> None:
        """Build per-island flat numpy arrays of all edge pixel coords."""
        for island_data in map_graph.get('islands', []):
            island_id = island_data['island_id']
            skeleton = island_data.get('skeleton')
            if skeleton is None:
                continue
            edge_pixels = skeleton.get('edge_pixels', {})
            all_pixels = []
            for ep_data in edge_pixels.values():
                pixels = ep_data.get('pixels', [])
                if pixels:
                    all_pixels.extend(pixels)
            if all_pixels:
                self._edge_pixels_by_island[island_id] = np.array(
                    all_pixels, dtype=np.float64,
                )

    def classify_position(self, x: float, z: float) -> dict:
        """Classify a single (x, z) position.

        Returns dict with: location_type, island_id,
            nearest_node_1, nearest_node_2,
            nearest_island_1, nearest_island_2
        """
        point = Point(x, z)

        # Check islands
        location_type = 'void'
        island_id = None
        for iid, polygon in self._island_polygons:
            if point.within(polygon):
                location_type = 'island'
                island_id = iid
                break

        # Check build region if not on island
        if location_type == 'void':
            for polygon in self._build_polygons:
                if point.within(polygon):
                    location_type = 'build_region'
                    break

        # Find two nearest map graph nodes
        nearest_node_1 = None
        nearest_node_2 = None
        nearest_island_1 = None
        nearest_island_2 = None

        if len(self._node_list) >= 2:
            dists = np.hypot(
                self._node_coords[:, 0] - x,
                self._node_coords[:, 1] - z,
            )
            idx = np.argsort(dists)[:2]
            nearest_node_1 = self._node_list[idx[0]]['map_node_id']
            nearest_island_1 = self._node_list[idx[0]]['island_id']
            nearest_node_2 = self._node_list[idx[1]]['map_node_id']
            nearest_island_2 = self._node_list[idx[1]]['island_id']
        elif len(self._node_list) == 1:
            nearest_node_1 = self._node_list[0]['map_node_id']
            nearest_island_1 = self._node_list[0]['island_id']

        return {
            'location_type': location_type,
            'island_id': island_id,
            'nearest_node_1': nearest_node_1,
            'nearest_node_2': nearest_node_2,
            'nearest_island_1': nearest_island_1,
            'nearest_island_2': nearest_island_2,
        }

    def snap_to_skeleton(
        self, x: float, z: float, island_id: int,
    ) -> Tuple[float, float]:
        """Snap an on-island position to the nearest skeleton edge pixel.

        Returns (snap_x, snap_z). Falls back to (x, z) if no pixels available.
        """
        pixels = self._edge_pixels_by_island.get(island_id)
        if pixels is None or len(pixels) == 0:
            return (x, z)

        dists = np.hypot(pixels[:, 0] - x, pixels[:, 1] - z)
        nearest_idx = np.argmin(dists)
        return (float(pixels[nearest_idx, 0]), float(pixels[nearest_idx, 1]))

    def classify_dataframe(
        self, df: pd.DataFrame, snap_skeleton: bool = False,
    ) -> pd.DataFrame:
        """Classify all positions in a DataFrame, adding new columns.

        Expects columns: x, z (world coords).
        Adds columns: location_type, island_id, nearest_node_1, nearest_node_2,
            nearest_island_1, nearest_island_2.
        If snap_skeleton=True, also adds: snap_x, snap_z.
        """
        results = []
        for row in df.itertuples():
            cls = self.classify_position(row.x, row.z)
            if snap_skeleton and cls['island_id'] is not None:
                sx, sz = self.snap_to_skeleton(row.x, row.z, cls['island_id'])
                cls['snap_x'] = sx
                cls['snap_z'] = sz
            else:
                cls['snap_x'] = row.x
                cls['snap_z'] = row.z
            results.append(cls)

        result_df = pd.DataFrame(results, index=df.index)
        out = df.copy()
        for col in result_df.columns:
            out[col] = result_df[col]
        return out
