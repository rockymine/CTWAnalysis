"""Position classification and skeleton path snapping for match analysis.

Classifies player position events against map geometry (islands, build regions, void)
and optionally snaps positions to nearest skeleton edge pixels.
"""

from typing import Optional

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
        self._island_polygons: list[tuple[int, Polygon]] = []
        self._build_polygons: list[Polygon] = []
        self._node_list: list[dict] = []
        self._node_coords: Optional[np.ndarray] = None
        self._edge_pixels_by_island: dict[int, np.ndarray] = {}

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

    def classify_bulk(
        self, xs: np.ndarray, zs: np.ndarray,
    ) -> dict[str, np.ndarray]:
        """Classify many positions at once (vectorized).

        Args:
            xs: 1-D array of x coordinates.
            zs: 1-D array of z coordinates.

        Returns:
            Dict of arrays, each length N:
                location_type (object), island_id (object),
                nearest_node_1/2 (object), nearest_island_1/2 (object).
            None values are used for missing data.
        """
        from shapely.prepared import prep

        n = len(xs)
        location_type = np.full(n, 'void', dtype=object)
        island_id = np.full(n, None, dtype=object)

        # Polygon containment — prepared geometries for speed
        remaining = np.ones(n, dtype=bool)
        for iid, polygon in self._island_polygons:
            if not remaining.any():
                break
            prepped = prep(polygon)
            for i in np.where(remaining)[0]:
                if prepped.contains(Point(xs[i], zs[i])):
                    location_type[i] = 'island'
                    island_id[i] = iid
                    remaining[i] = False

        # Build region check on remaining void positions
        for polygon in self._build_polygons:
            if not remaining.any():
                break
            prepped = prep(polygon)
            for i in np.where(remaining)[0]:
                if prepped.contains(Point(xs[i], zs[i])):
                    location_type[i] = 'build_region'
                    remaining[i] = False

        # Nearest nodes — fully vectorized
        nearest_node_1 = np.full(n, None, dtype=object)
        nearest_node_2 = np.full(n, None, dtype=object)
        nearest_island_1 = np.full(n, None, dtype=object)
        nearest_island_2 = np.full(n, None, dtype=object)

        if len(self._node_list) >= 2:
            # shape (n_nodes, n_points)
            dx = self._node_coords[:, 0, np.newaxis] - xs[np.newaxis, :]
            dz = self._node_coords[:, 1, np.newaxis] - zs[np.newaxis, :]
            dists = np.hypot(dx, dz)
            # top-2 per column (kth must be < n_nodes)
            n_nodes = len(self._node_list)
            if n_nodes == 2:
                idx = np.array([np.zeros(n, dtype=int), np.ones(n, dtype=int)])
            else:
                idx = np.argpartition(dists, 2, axis=0)[:2]
            for j in range(n):
                i0, i1 = idx[0, j], idx[1, j]
                # ensure i0 is actually closer
                if dists[i0, j] > dists[i1, j]:
                    i0, i1 = i1, i0
                nearest_node_1[j] = self._node_list[i0]['map_node_id']
                nearest_island_1[j] = self._node_list[i0]['island_id']
                nearest_node_2[j] = self._node_list[i1]['map_node_id']
                nearest_island_2[j] = self._node_list[i1]['island_id']
        elif len(self._node_list) == 1:
            nearest_node_1[:] = self._node_list[0]['map_node_id']
            nearest_island_1[:] = self._node_list[0]['island_id']

        return {
            'location_type': location_type,
            'island_id': island_id,
            'nearest_node_1': nearest_node_1,
            'nearest_node_2': nearest_node_2,
            'nearest_island_1': nearest_island_1,
            'nearest_island_2': nearest_island_2,
        }

    def classify_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Classify all positions in a DataFrame, adding new columns.

        Expects columns: x, z (world coords).
        Adds columns: location_type, island_id, nearest_node_1, nearest_node_2,
            nearest_island_1, nearest_island_2.
        """
        out = df.copy()
        if len(df) == 0:
            for col in ['location_type', 'island_id',
                         'nearest_node_1', 'nearest_node_2',
                         'nearest_island_1', 'nearest_island_2']:
                out[col] = pd.Series(dtype=object)
            return out

        bulk = self.classify_bulk(
            df['x'].values.astype(float),
            df['z'].values.astype(float),
        )
        for col, arr in bulk.items():
            out[col] = arr
        return out
