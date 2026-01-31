"""
POI-aware skeleton graph annotation.

Classifies skeleton nodes as spawn, wool, or none by matching XML map data
(spawn regions, wool locations) to the nearest skeleton endpoint on the
appropriate island. Also sets island-level flags (has_spawn, has_wool,
has_center, distance_to_center, team).
"""

import re
import numpy as np
from typing import List, Dict, Tuple, Optional

from .datatypes import IslandResult
from ..islands.datatypes import Island
from xml_analysis.regions import (
    CylinderRegion, PointRegion, BlockRegion, UnionRegion,
    CuboidRegion, RectangleRegion,
)


def extract_spawn_locations(map_data) -> List[Dict]:
    """
    Extract spawn (x, z) locations from map data.

    Two strategies tried in order:
    1. Inline regions on Spawn objects (e.g. cuboid with coordinates)
    2. Named regions matching player spawn patterns (e.g. "blue-spawn-point")

    Excludes observer spawns, wool spawners, and composite union containers.

    Returns:
        List of dicts with keys: x, z, team, team_color
    """
    team_colors = {t.id: t.color for t in map_data.teams}
    spawns = []

    # Strategy 1: Use inline regions from Spawn objects
    for spawn_obj in map_data.spawns:
        if not spawn_obj.team:
            continue
        if spawn_obj.region is not None:
            x, z = _get_region_center_xz(spawn_obj.region)
            if x is not None:
                team_color = team_colors.get(spawn_obj.team, '')
                spawns.append({
                    'x': x, 'z': z,
                    'team': spawn_obj.team,
                    'team_color': team_color,
                    'region_id': f'{spawn_obj.team}-spawn (inline)',
                })

    # If inline regions yielded results, use those
    if spawns:
        return spawns

    # Strategy 2: Fall back to named regions
    spawn_pattern = re.compile(r'spawn', re.IGNORECASE)
    exclude_pattern = re.compile(r'wool|not-|obs', re.IGNORECASE)

    for region_id, region in map_data.regions.items():
        if not spawn_pattern.search(region_id):
            continue
        if exclude_pattern.search(region_id):
            continue
        # Skip union/composite regions — they are containers, not spawn points
        if isinstance(region, UnionRegion):
            continue

        x, z = _get_region_center_xz(region)
        if x is None:
            continue

        team = _extract_team_from_id(region_id, map_data.teams)
        team_color = team_colors.get(team, '')

        spawns.append({
            'x': x, 'z': z,
            'team': team,
            'team_color': team_color,
            'region_id': region_id,
        })

    return spawns


def extract_wool_locations(map_data) -> List[Dict]:
    """
    Extract wool (x, z) locations from map_data.wools.

    Returns:
        List of dicts with keys: x, z, team, wool_color
    """
    wools = []
    for wool in map_data.wools:
        wools.append({
            'x': wool.location[0],
            'z': wool.location[2],
            'team': wool.team,
            'wool_color': wool.color,
        })
    return wools


def find_containing_island(
    point_xz: Tuple[float, float],
    islands: List[Island],
    tolerance: float = 5.0,
) -> Optional[Island]:
    """
    Find the island whose bounding box contains the given (x, z) point.

    Args:
        point_xz: (x, z) world coordinate
        islands: List of islands
        tolerance: Extra padding around bounding box

    Returns:
        The matching Island, or None
    """
    x, z = point_xz
    for island in islands:
        min_x, max_x, min_z, max_z = island.bounding_box
        if (min_x - tolerance <= x <= max_x + tolerance and
                min_z - tolerance <= z <= max_z + tolerance):
            return island
    return None


def find_nearest_node(
    point_xz: Tuple[float, float],
    island_result: IslandResult,
    node_type: Optional[str] = None,
) -> Optional[int]:
    """
    Find the skeleton node nearest to a world (x, z) point.

    Converts each node from mask (r,c) -> canonical (x,z) -> world (x,z)
    and finds the closest one.

    Args:
        point_xz: Target world coordinate
        island_result: IslandResult containing graph and transform info
        node_type: If set, only consider nodes of this type ('endpoint'/'junction')

    Returns:
        node_id of the nearest node, or None if no nodes
    """
    raster = island_result.raster
    transform = island_result.canonical.transform
    target = np.array(point_xz, dtype=float)

    best_id = None
    best_dist = float('inf')

    for node in island_result.graph.nodes:
        if node_type and node.node_type != node_type:
            continue

        cx, cz = raster.rc_to_canonical(node.rc[0], node.rc[1])
        world_pt = transform.to_original(np.array([[cx, cz]], dtype=float))[0]
        dist = np.linalg.norm(world_pt - target)

        if dist < best_dist:
            best_dist = dist
            best_id = node.node_id

    return best_id


def compute_map_center(layout_df) -> Tuple[float, float]:
    """
    Compute the geometric center of all blocks in the layout.

    Args:
        layout_df: DataFrame with world_x and world_z columns

    Returns:
        (center_x, center_z) tuple
    """
    x_col = 'world_x' if 'world_x' in layout_df.columns else 'x'
    z_col = 'world_z' if 'world_z' in layout_df.columns else 'z'

    min_x = layout_df[x_col].min()
    max_x = layout_df[x_col].max()
    min_z = layout_df[z_col].min()
    max_z = layout_df[z_col].max()

    return ((min_x + max_x) / 2.0, (min_z + max_z) / 2.0)


def classify_island_center(
    islands: List[Island],
    map_center: Tuple[float, float],
) -> None:
    """
    Set has_center and distance_to_center on each island.

    The island closest to map_center gets has_center=True.
    """
    if not islands:
        return

    best_island = None
    best_dist = float('inf')

    for island in islands:
        cx, cz = island.center
        dist = np.sqrt((cx - map_center[0]) ** 2 + (cz - map_center[1]) ** 2)
        island.distance_to_center = float(dist)

        if dist < best_dist:
            best_dist = dist
            best_island = island

    if best_island is not None:
        best_island.has_center = True


def annotate_skeleton_pois(
    islands: List[Island],
    skeleton_results: List[IslandResult],
    map_data,
) -> Dict[str, list]:
    """
    Main annotation function. Sets node.poi_type/poi_color and
    island.has_spawn/has_wool/team based on XML map data.

    Args:
        islands: List of Island objects
        skeleton_results: List of IslandResult objects
        map_data: Parsed MapData from XML

    Returns:
        Dict with 'spawns' and 'wools' lists of assignment info
    """
    result_by_id = {r.island_id: r for r in skeleton_results}
    assignments = {'spawns': [], 'wools': []}

    # Extract POI locations from XML
    spawn_locs = extract_spawn_locations(map_data)
    wool_locs = extract_wool_locations(map_data)

    # Annotate spawns
    for spawn in spawn_locs:
        island = find_containing_island((spawn['x'], spawn['z']), islands)
        if island is None:
            assignments['spawns'].append({
                **spawn, 'island_id': None, 'node_id': None,
            })
            continue

        ir = result_by_id.get(island.id)
        node_id = None
        if ir is not None:
            node_id = find_nearest_node((spawn['x'], spawn['z']), ir)

            if node_id is not None:
                for node in ir.graph.nodes:
                    if node.node_id == node_id:
                        node.poi_type = 'spawn'
                        node.poi_color = spawn['team_color']
                        break

        island.has_spawn = True
        island.team = spawn['team']

        assignments['spawns'].append({
            **spawn, 'island_id': island.id, 'node_id': node_id,
        })

    # Annotate wools
    for wool in wool_locs:
        island = find_containing_island((wool['x'], wool['z']), islands)
        if island is None:
            assignments['wools'].append({
                **wool, 'island_id': None, 'node_id': None,
            })
            continue

        ir = result_by_id.get(island.id)
        node_id = None
        if ir is not None:
            node_id = find_nearest_node((wool['x'], wool['z']), ir)

            if node_id is not None:
                for node in ir.graph.nodes:
                    if node.node_id == node_id:
                        node.poi_type = 'wool'
                        node.poi_color = wool['wool_color']
                        break

        island.has_wool = True

        assignments['wools'].append({
            **wool, 'island_id': island.id, 'node_id': node_id,
        })

    return assignments


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_region_center_xz(region) -> Tuple[Optional[float], Optional[float]]:
    """Extract (x, z) center from a region object."""
    if isinstance(region, CylinderRegion):
        return region.base_x, region.base_z
    elif isinstance(region, (PointRegion, BlockRegion)):
        return region.x, region.z
    # Try get_bounds_2d fallback
    bounds = region.get_bounds_2d()
    if bounds is not None:
        (min_x, min_z), (max_x, max_z) = bounds
        if all(abs(v) < 1e6 for v in [min_x, min_z, max_x, max_z]):
            return (min_x + max_x) / 2, (min_z + max_z) / 2
    return None, None


def _extract_team_from_id(region_id: str, teams) -> str:
    """Extract team id from a region id like 'blue-spawn-point'.

    Tries matching by full team id first, then by team color or name.
    """
    region_lower = region_id.lower()
    # Try full team id (e.g. "blue-team")
    for team in teams:
        if team.id.lower() in region_lower:
            return team.id
    # Try team color (e.g. "blue") or name (e.g. "Blue")
    for team in teams:
        if team.color.lower() in region_lower:
            return team.id
        if team.name and team.name.lower() in region_lower:
            return team.id
    return ''
