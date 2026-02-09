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

from ctw.core.models import IslandResult, Island
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
                entry = {
                    'x': x, 'z': z,
                    'team': spawn_obj.team,
                    'team_color': team_color,
                    'region_id': f'{spawn_obj.team}-spawn (inline)',
                }
                bounds = spawn_obj.region.get_bounds_2d()
                if bounds is not None:
                    (min_x, min_z), (max_x, max_z) = bounds
                    entry['bounds_2d'] = {
                        'min': {'x': min_x, 'z': min_z},
                        'max': {'x': max_x, 'z': max_z},
                    }
                spawns.append(entry)

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

        entry = {
            'x': x, 'z': z,
            'team': team,
            'team_color': team_color,
            'region_id': region_id,
        }
        bounds = region.get_bounds_2d()
        if bounds is not None:
            (min_x, min_z), (max_x, max_z) = bounds
            entry['bounds_2d'] = {
                'min': {'x': min_x, 'z': min_z},
                'max': {'x': max_x, 'z': max_z},
            }
        spawns.append(entry)

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


# Re-export from ctw.core.geometry for backward compatibility
from ctw.core.geometry import compute_map_center, classify_island_center


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
        wool_x, wool_z = wool['x'], wool['z']
        fallback = None

        island = find_containing_island((wool_x, wool_z), islands)

        if island is None:
            # Wool location outside all islands — try wool-room region fallback
            room = _find_wool_room_center(wool['wool_color'], map_data, islands)
            if room is not None:
                fallback = {
                    'original_x': wool_x,
                    'original_z': wool_z,
                    'room_region': room['region_id'],
                }
                wool_x, wool_z = room['x'], room['z']
                island = find_containing_island((wool_x, wool_z), islands)

        if island is None:
            entry = {**wool, 'x': wool_x, 'z': wool_z,
                     'island_id': None, 'node_id': None}
            if fallback:
                entry['fallback'] = fallback
            assignments['wools'].append(entry)
            continue

        ir = result_by_id.get(island.id)
        node_id = None
        if ir is not None:
            node_id = find_nearest_node((wool_x, wool_z), ir)

            if node_id is not None:
                for node in ir.graph.nodes:
                    if node.node_id == node_id:
                        node.poi_type = 'wool'
                        node.poi_color = wool['wool_color']
                        break

        island.has_wool = True

        entry = {**wool, 'x': wool_x, 'z': wool_z,
                 'island_id': island.id, 'node_id': node_id}
        if fallback:
            entry['fallback'] = fallback
        assignments['wools'].append(entry)

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


def _find_wool_room_center(
    wool_color: str,
    map_data,
    islands: List[Island],
) -> Optional[Dict]:
    """Find a wool-room region matching the wool color and return its centroid.

    Used as a fallback when the wool's declared location is outside the map.
    Matches regions whose ID contains both "wool-room" and the wool color
    (with spaces replaced by hyphens, e.g. "light blue" → "light-blue").

    Returns dict with 'x', 'z', 'region_id' keys, or None.
    """
    color_key = wool_color.strip().lower().replace(' ', '-')

    matched_region = None
    matched_id = None
    for region_id, region in map_data.regions.items():
        rid_lower = region_id.lower()
        if 'wool-room' in rid_lower and color_key in rid_lower:
            matched_region = region
            matched_id = region_id
            break

    if matched_region is None:
        return None

    # Try shapely centroid (handles mirrors/unions correctly)
    try:
        registry = map_data.regions
        dummy_bounds = (-10000, -10000, 10000, 10000)
        geom = matched_region.to_shapely_2d(dummy_bounds, registry=registry)
        if geom is not None and not geom.is_empty:
            centroid = geom.centroid
            return {'x': centroid.x, 'z': centroid.y, 'region_id': matched_id}
    except Exception:
        pass

    # Fallback to bounds center
    bounds = matched_region.get_bounds_2d()
    if bounds is not None:
        (min_x, min_z), (max_x, max_z) = bounds
        return {
            'x': (min_x + max_x) / 2,
            'z': (min_z + max_z) / 2,
            'region_id': matched_id,
        }

    return None


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
