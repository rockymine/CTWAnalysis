"""
JSON exporter for map data.

Converts parsed map data to JSON-serializable format.
"""

import json
from typing import Dict, Any, List

from .parser import MapData, Team, Spawn, Wool, ApplyRule
from .regions import (
    Region, RectangleRegion, CuboidRegion, CylinderRegion, CircleRegion,
    SphereRegion, BlockRegion, PointRegion, UnionRegion, NegativeRegion,
    ComplementRegion, IntersectRegion, RegionReference, EverywhereRegion, AboveRegion,
)


class MapDataEncoder:
    """Encoder for map data to JSON-serializable format."""

    @staticmethod
    def encode_region(region: Region) -> Dict[str, Any]:
        """
        Convert a region to JSON-serializable dictionary.

        Args:
            region: Region object

        Returns:
            Dictionary representation
        """
        base = {
            'id': region.id,
            'type': region.region_type,
        }

        # Add bounds if available
        bounds = region.get_bounds_2d()
        if bounds is not None:
            (min_x, min_z), (max_x, max_z) = bounds
            base['bounds_2d'] = {
                'min': {'x': min_x, 'z': min_z},
                'max': {'x': max_x, 'z': max_z}
            }

        # Add type-specific attributes
        if isinstance(region, RectangleRegion):
            base['min_x'] = region.min_x
            base['min_z'] = region.min_z
            base['max_x'] = region.max_x
            base['max_z'] = region.max_z

        elif isinstance(region, CuboidRegion):
            base['min_x'] = region.min_x
            base['min_y'] = region.min_y
            base['min_z'] = region.min_z
            base['max_x'] = region.max_x
            base['max_y'] = region.max_y
            base['max_z'] = region.max_z

        elif isinstance(region, CylinderRegion):
            base['base'] = {'x': region.base_x, 'y': region.base_y, 'z': region.base_z}
            base['radius'] = region.radius
            base['height'] = region.height

        elif isinstance(region, CircleRegion):
            base['center'] = {'x': region.center_x, 'z': region.center_z}
            base['radius'] = region.radius

        elif isinstance(region, SphereRegion):
            base['origin'] = {'x': region.origin_x, 'y': region.origin_y, 'z': region.origin_z}
            base['radius'] = region.radius

        elif isinstance(region, (BlockRegion, PointRegion)):
            base['position'] = {'x': region.x, 'y': region.y, 'z': region.z}

        elif isinstance(region, (UnionRegion, NegativeRegion, ComplementRegion, IntersectRegion)):
            base['children'] = [MapDataEncoder.encode_region(child) for child in region.children]

        elif isinstance(region, RegionReference):
            base['ref_id'] = region.ref_id

        elif isinstance(region, EverywhereRegion):
            pass  # type field is sufficient

        elif isinstance(region, AboveRegion):
            base['y'] = region.y

        return base

    @staticmethod
    def encode_team(team: Team) -> Dict[str, Any]:
        """Convert team to dictionary."""
        return {
            'id': team.id,
            'name': team.name,
            'color': team.color,
            'dye_color': team.dye_color,
            'max_players': team.max_players,
        }

    @staticmethod
    def encode_spawn(spawn: Spawn) -> Dict[str, Any]:
        """Convert spawn to dictionary."""
        result = {
            'team': spawn.team,
            'kit': spawn.kit,
            'yaw': spawn.yaw,
        }

        if spawn.region:
            result['region'] = MapDataEncoder.encode_region(spawn.region)

        return result

    @staticmethod
    def encode_wool(wool: Wool) -> Dict[str, Any]:
        """Convert wool to dictionary."""
        return {
            'team': wool.team,
            'color': wool.color,
            'location': {
                'x': wool.location[0],
                'y': wool.location[1],
                'z': wool.location[2],
            },
            'monument': {
                'x': wool.monument[0],
                'y': wool.monument[1],
                'z': wool.monument[2],
            },
        }

    @staticmethod
    def encode_map_data(data: MapData, categories: Dict[str, List[str]] = None) -> Dict[str, Any]:
        """
        Convert complete map data to dictionary.

        Args:
            data: MapData object
            categories: Optional region categories

        Returns:
            Complete JSON-serializable dictionary
        """
        result = {
            'name': data.name,
            'version': data.version,
            'objective': data.objective,
            'max_build_height': data.max_build_height,
            'teams': [MapDataEncoder.encode_team(team) for team in data.teams],
            'spawns': [MapDataEncoder.encode_spawn(spawn) for spawn in data.spawns],
            'wools': [MapDataEncoder.encode_wool(wool) for wool in data.wools],
            'regions': {
                region_id: MapDataEncoder.encode_region(region)
                for region_id, region in data.regions.items()
            },
            'apply_rules': [MapDataEncoder.encode_apply_rule(r) for r in data.apply_rules],
        }

        if categories:
            result['region_categories'] = categories

        return result

    @staticmethod
    def encode_apply_rule(rule: ApplyRule) -> Dict[str, Any]:
        """Convert an apply rule to dictionary."""
        result = {}
        if rule.block_filter:
            result['block'] = rule.block_filter
        if rule.block_place_filter:
            result['block_place'] = rule.block_place_filter
        if rule.block_break_filter:
            result['block_break'] = rule.block_break_filter
        if rule.use_filter:
            result['use'] = rule.use_filter
        if rule.region_id:
            result['region'] = rule.region_id
        if rule.inline_region:
            result['inline_region'] = MapDataEncoder.encode_region(rule.inline_region)
        if rule.message:
            result['message'] = rule.message
        return result

    @staticmethod
    def to_json(data: MapData, categories: Dict[str, List[str]] = None, indent: int = 2) -> str:
        """
        Convert map data to JSON string.

        Args:
            data: MapData object
            categories: Optional region categories
            indent: JSON indentation level

        Returns:
            JSON string
        """
        encoded = MapDataEncoder.encode_map_data(data, categories)
        return json.dumps(encoded, indent=indent, sort_keys=False)

    @staticmethod
    def save_json(data: MapData, output_path: str, categories: Dict[str, List[str]] = None):
        """
        Save map data to JSON file.

        Args:
            data: MapData object
            output_path: Path to save JSON file
            categories: Optional region categories
        """
        json_str = MapDataEncoder.to_json(data, categories)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(json_str)
        print(f"  Saved JSON: {output_path}")
