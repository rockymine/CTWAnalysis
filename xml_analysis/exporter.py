"""JSON exporter for map data.

Converts parsed map data to JSON-serializable format.

Public API:
    to_dict(data, categories)  — serialize MapData to a plain dict
    to_json(data, categories)  — serialize MapData to a JSON string
    save(data, output_path, categories) — write MapData to a JSON file
"""

import json
import logging
import math
from typing import Any, Optional

from common.json_export import save_json as _save_json

logger = logging.getLogger('ctw')

from .datatypes import (
    MapData, Team, Author, Kit, KitItem, KitArmor, Spawn, Wool, ApplyRule,
    WoolSpawner, SpawnerItem, Renewable, BlockDropRule, BlockDropItem,
)
from .regions import (
    Region, RectangleRegion, CuboidRegion, CylinderRegion, CircleRegion,
    SphereRegion, BlockRegion, PointRegion, UnionRegion, NegativeRegion,
    ComplementRegion, IntersectRegion, RegionReference, EverywhereRegion, AboveRegion,
    MirrorRegion, TranslateRegion, HalfRegion,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def to_dict(data: MapData, categories: Optional[dict[str, list[str]]] = None) -> dict[str, Any]:
    """Convert MapData to a JSON-serializable dictionary.

    Args:
        data: MapData object.
        categories: Optional region categories.

    Returns:
        Complete JSON-serializable dictionary.
    """
    result = {
        'name': data.name,
        'version': data.version,
        'gamemode': data.gamemode,
        'objective': data.objective,
        'max_build_height': data.max_build_height,
        'authors': [_encode_author(a) for a in data.authors],
        'kits': [_encode_kit(k) for k in data.kits],
        'teams': [_encode_team(team) for team in data.teams],
        'spawns': [_encode_spawn(spawn) for spawn in data.spawns],
        'observer_spawn': _encode_spawn(data.observer_spawn) if data.observer_spawn else None,
        'wools': [_encode_wool(wool) for wool in data.wools],
        'spawners': [_encode_spawner(s) for s in data.spawners],
        'renewables': [_encode_renewable(r) for r in data.renewables],
        'block_drop_rules': [_encode_block_drop_rule(r) for r in data.block_drop_rules],
        'regions': {
            region_id: _encode_region(region)
            for region_id, region in data.regions.items()
        },
        'apply_rules': [_encode_apply_rule(r) for r in data.apply_rules],
    }

    if categories:
        result['region_categories'] = categories

    return result


def to_json(data: MapData, categories: Optional[dict[str, list[str]]] = None, indent: int = 2) -> str:
    """Convert MapData to a JSON string.

    Args:
        data: MapData object.
        categories: Optional region categories.
        indent: JSON indentation level.

    Returns:
        JSON string.
    """
    return json.dumps(to_dict(data, categories), indent=indent, sort_keys=False)


def save(data: MapData, output_path: str, categories: Optional[dict[str, list[str]]] = None) -> None:
    """Save MapData to a JSON file.

    Args:
        data: MapData object.
        output_path: Path to save JSON file.
        categories: Optional region categories.
    """
    _save_json(to_dict(data, categories), output_path)
    logger.debug(f"  Saved: {output_path}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _coord(v: Any) -> Any:
    """Convert a coordinate value to a JSON-safe representation.

    JSON (RFC 8259) does not permit non-finite floats.  PGM regions use
    ``oo`` / ``-oo`` to express unbounded axes; the XML parser converts these
    to ``float('inf')`` / ``float('-inf')`` for in-memory use.  At serialisation
    time we convert them back to the original string form so the output file is
    valid JSON and round-trips cleanly through the viewer and XML exporter.
    """
    if isinstance(v, float):
        if v == math.inf:
            return "oo"
        if v == -math.inf:
            return "-oo"
    return v


# ---------------------------------------------------------------------------
# Internal encoders
# ---------------------------------------------------------------------------

def _encode_region(region: Region) -> dict[str, Any]:
    """Convert a region to JSON-serializable dictionary."""
    base = {
        'id': region.id,
        'type': region.region_type,
    }

    bounds = region.get_bounds_2d()
    if bounds is not None:
        (min_x, min_z), (max_x, max_z) = bounds
        base['bounds_2d'] = {
            'min': {'x': _coord(min_x), 'z': _coord(min_z)},
            'max': {'x': _coord(max_x), 'z': _coord(max_z)},
        }

    if isinstance(region, RectangleRegion):
        base['min_x'] = _coord(region.min_x)
        base['min_z'] = _coord(region.min_z)
        base['max_x'] = _coord(region.max_x)
        base['max_z'] = _coord(region.max_z)

    elif isinstance(region, CuboidRegion):
        base['min_x'] = _coord(region.min_x)
        base['min_y'] = _coord(region.min_y)
        base['min_z'] = _coord(region.min_z)
        base['max_x'] = _coord(region.max_x)
        base['max_y'] = _coord(region.max_y)
        base['max_z'] = _coord(region.max_z)

    elif isinstance(region, CylinderRegion):
        base['base'] = {'x': _coord(region.base_x), 'y': _coord(region.base_y), 'z': _coord(region.base_z)}
        base['radius'] = _coord(region.radius)
        base['height'] = _coord(region.height)

    elif isinstance(region, CircleRegion):
        base['center'] = {'x': _coord(region.center_x), 'z': _coord(region.center_z)}
        base['radius'] = _coord(region.radius)

    elif isinstance(region, SphereRegion):
        base['origin'] = {'x': _coord(region.origin_x), 'y': _coord(region.origin_y), 'z': _coord(region.origin_z)}
        base['radius'] = _coord(region.radius)

    elif isinstance(region, (BlockRegion, PointRegion)):
        base['position'] = {'x': _coord(region.x), 'y': _coord(region.y), 'z': _coord(region.z)}

    elif isinstance(region, (UnionRegion, NegativeRegion, ComplementRegion, IntersectRegion)):
        base['children'] = [_encode_region(child) for child in region.children]

    elif isinstance(region, HalfRegion):
        base['origin'] = {'x': _coord(region.origin_x), 'y': _coord(region.origin_y), 'z': _coord(region.origin_z)}
        base['normal'] = {'x': _coord(region.normal_x), 'y': _coord(region.normal_y), 'z': _coord(region.normal_z)}

    elif isinstance(region, MirrorRegion):
        if region.source:
            base['source'] = _encode_region(region.source)
        if region.ref_region_id:
            base['ref_region_id'] = region.ref_region_id
        base['origin'] = {'x': _coord(region.origin_x), 'y': _coord(region.origin_y), 'z': _coord(region.origin_z)}
        base['normal'] = {'x': _coord(region.normal_x), 'y': _coord(region.normal_y), 'z': _coord(region.normal_z)}

    elif isinstance(region, TranslateRegion):
        if region.source:
            base['source'] = _encode_region(region.source)
        if region.ref_region_id:
            base['ref_region_id'] = region.ref_region_id
        base['offset'] = {'x': _coord(region.offset_x), 'y': _coord(region.offset_y), 'z': _coord(region.offset_z)}

    elif isinstance(region, RegionReference):
        base['ref_id'] = region.ref_id

    elif isinstance(region, EverywhereRegion):
        pass

    elif isinstance(region, AboveRegion):
        base['y'] = _coord(region.y)

    return base


def _encode_author(author: Author) -> dict[str, Any]:
    """Convert author/contributor to dictionary."""
    result: dict[str, Any] = {'uuid': author.uuid, 'role': author.role}
    if author.contribution:
        result['contribution'] = author.contribution
    return result


def _encode_kit(kit: Kit) -> dict[str, Any]:
    """Convert kit to dictionary."""
    return {
        'id': kit.id,
        'items': [_encode_kit_item(i) for i in kit.items],
        'armor': [_encode_kit_armor(a) for a in kit.armor],
    }


def _encode_kit_item(item: KitItem) -> dict[str, Any]:
    """Convert kit item to dictionary."""
    result: dict[str, Any] = {
        'slot': item.slot,
        'material': item.material,
        'amount': item.amount,
    }
    if item.item_damage:
        result['item_damage'] = item.item_damage
    if item.unbreakable:
        result['unbreakable'] = item.unbreakable
    if item.team_color:
        result['team_color'] = item.team_color
    if item.enchantments:
        result['enchantments'] = item.enchantments
    return result


def _encode_kit_armor(armor: KitArmor) -> dict[str, Any]:
    """Convert kit armor slot to dictionary."""
    result: dict[str, Any] = {
        'slot_name': armor.slot_name,
        'material': armor.material,
    }
    if armor.unbreakable:
        result['unbreakable'] = armor.unbreakable
    if armor.team_color:
        result['team_color'] = armor.team_color
    if armor.enchantments:
        result['enchantments'] = armor.enchantments
    return result


def _encode_team(team: Team) -> dict[str, Any]:
    """Convert team to dictionary."""
    return {
        'id': team.id,
        'name': team.name,
        'color': team.color,
        'dye_color': team.dye_color,
        'max_players': team.max_players,
        'min_players': team.min_players,
    }


def _encode_spawn(spawn: Spawn) -> dict[str, Any]:
    """Convert spawn to dictionary."""
    result = {
        'team': spawn.team,
        'kit': spawn.kit,
        'yaw': spawn.yaw,
    }

    if spawn.region:
        result['region'] = _encode_region(spawn.region)

    return result


def _encode_wool(wool: Wool) -> dict[str, Any]:
    """Convert wool to dictionary."""
    result: dict[str, Any] = {
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
            **({"region_id": wool.monument_region_id} if wool.monument_region_id else {}),
        },
        'wool_room_region': wool.wool_room_region,
    }
    return result


def _encode_spawner(spawner: WoolSpawner) -> dict[str, Any]:
    """Convert a WoolSpawner to dictionary."""
    result: dict[str, Any] = {
        'spawn_region': spawner.spawn_region,
        'player_region': spawner.player_region,
    }
    if spawner.delay:
        result['delay'] = spawner.delay
    if spawner.max_entities is not None:
        result['max_entities'] = spawner.max_entities
    if spawner.items:
        result['items'] = [_encode_spawner_item(item) for item in spawner.items]
    return result


def _encode_spawner_item(item: SpawnerItem) -> dict[str, Any]:
    """Convert a SpawnerItem to dictionary."""
    return {
        'material': item.material,
        'damage': item.damage,
        'amount': item.amount,
    }


def _encode_renewable(renewable: Renewable) -> dict[str, Any]:
    """Convert a Renewable to dictionary."""
    result: dict[str, Any] = {'region_id': renewable.region_id}
    if renewable.rate != 1.0:
        result['rate'] = renewable.rate
    if renewable.renew_filter:
        result['renew_filter'] = renewable.renew_filter
    if renewable.replace_filter:
        result['replace_filter'] = renewable.replace_filter
    if renewable.grow:
        result['grow'] = True
    return result


def _encode_block_drop_rule(rule: BlockDropRule) -> dict[str, Any]:
    """Convert a BlockDropRule to dictionary."""
    result: dict[str, Any] = {}
    if rule.region_id:
        result['region_id'] = rule.region_id
    if rule.filter_id:
        result['filter_id'] = rule.filter_id
    if rule.replacement:
        result['replacement'] = rule.replacement
    if rule.wrong_tool:
        result['wrong_tool'] = True
    if rule.items:
        result['items'] = [
            {k: v for k, v in {
                'material': item.material,
                'damage':   item.damage   if item.damage   != 0   else None,
                'amount':   item.amount   if item.amount   != 1   else None,
                'chance':   item.chance   if item.chance   != 1.0 else None,
            }.items() if v is not None}
            for item in rule.items
        ]
    return result


def _encode_apply_rule(rule: ApplyRule) -> dict[str, Any]:
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
        result['inline_region'] = _encode_region(rule.inline_region)
    if rule.message:
        result['message'] = rule.message
    return result
