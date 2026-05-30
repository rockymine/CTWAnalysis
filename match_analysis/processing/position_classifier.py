"""Position classification for match analysis.

Classifies player position events against map geometry (islands, build regions,
void).  Outputs location_type and island_id only — skeleton node columns have
been removed.

Uses Shapely 2.x STRtree for bulk polygon containment, which is significantly
faster than the previous per-point loop.
"""

from typing import Optional

import numpy as np
import pandas as pd
from shapely import STRtree
from shapely import points as shp_points
from shapely.geometry import Point, Polygon


class PositionClassifier:
    """Classifies positions against map geometry. Load once, classify many.

    Args:
        map_context: Parsed map_context.json dict.
    """

    def __init__(self, map_context: dict):
        self._island_polygons: list[tuple[int, Polygon]] = []
        self._island_ids_arr: list[int] = []
        self._build_polygons: list[Polygon] = []

        self._island_tree: Optional[STRtree] = None
        self._build_tree: Optional[STRtree] = None

        self._build_island_polygons(map_context)
        self._build_region_polygons(map_context)
        self._build_trees()

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

    def _build_trees(self) -> None:
        """Build STRtree indices for fast bulk containment queries."""
        if self._island_polygons:
            self._island_tree = STRtree([poly for _, poly in self._island_polygons])
            self._island_ids_arr = [iid for iid, _ in self._island_polygons]
        if self._build_polygons:
            self._build_tree = STRtree(self._build_polygons)

    def classify_position(self, x: float, z: float) -> dict:
        """Classify a single (x, z) position.

        x and z are expected to be integer block indices (as stored in the DB).
        The test point is shifted to the block centre (+0.5) to avoid the
        polygon-boundary false-negative from Shapely's strict `within`.

        Returns dict with: location_type (str), island_id (int or None).
        """
        point = Point(x + 0.5, z + 0.5)

        for iid, polygon in self._island_polygons:
            if point.within(polygon):
                return {'location_type': 'island', 'island_id': iid}

        for polygon in self._build_polygons:
            if point.within(polygon):
                return {'location_type': 'build_region', 'island_id': None}

        return {'location_type': 'void', 'island_id': None}

    def classify_bulk(
        self, xs: np.ndarray, zs: np.ndarray,
    ) -> dict[str, np.ndarray]:
        """Classify many positions at once (vectorized via STRtree).

        Args:
            xs: 1-D array of x coordinates.
            zs: 1-D array of z coordinates.

        Returns:
            Dict with two arrays each of length N:
                'location_type' (object dtype): 'island', 'build_region', or 'void'.
                'island_id' (object dtype): integer island ID or None.
        """
        n = len(xs)
        location_type = np.full(n, 'void', dtype=object)
        island_id = np.full(n, None, dtype=object)

        # Shift to block centres before testing containment.
        #
        # Position events store integer block indices (plugin casts with (int),
        # i.e. floor).  Island and build-region polygon edges run along integer
        # grid lines, so testing Point(x_int, z_int) lands exactly on the
        # boundary where Shapely's strict `within` predicate returns False.
        # Adding 0.5 moves the test point to the centre of the block the player
        # occupies, placing it firmly inside any polygon that contains that block.
        pts = shp_points(xs + 0.5, zs + 0.5)

        # Island containment via STRtree
        if self._island_tree is not None:
            result = self._island_tree.query(pts, predicate='within')
            # result shape: (2, k) — result[0]=point indices, result[1]=poly indices
            if result.shape[1] > 0:
                for pi, gi in zip(result[0], result[1]):
                    if location_type[pi] == 'void':
                        location_type[pi] = 'island'
                        island_id[pi] = self._island_ids_arr[gi]

        # Build region containment on remaining void positions via STRtree
        if self._build_tree is not None:
            void_mask = location_type == 'void'
            if void_mask.any():
                void_idx = np.where(void_mask)[0]
                void_pts = shp_points(xs[void_idx] + 0.5, zs[void_idx] + 0.5)
                result2 = self._build_tree.query(void_pts, predicate='within')
                if result2.shape[1] > 0:
                    # result2[0] = indices into void_idx array
                    for pi in set(result2[0]):
                        location_type[void_idx[pi]] = 'build_region'

        return {
            'location_type': location_type,
            'island_id': island_id,
        }

    def classify_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Classify all positions in a DataFrame, adding location_type and island_id.

        Expects columns: x, z (world coords).
        """
        out = df.copy()
        if len(df) == 0:
            out['location_type'] = pd.Series(dtype=object)
            out['island_id'] = pd.Series(dtype=object)
            return out

        bulk = self.classify_bulk(
            df['x'].values.astype(float),
            df['z'].values.astype(float),
        )
        out['location_type'] = bulk['location_type']
        out['island_id'] = bulk['island_id']
        return out
