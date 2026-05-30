from __future__ import annotations

from typing import Optional


_WOOL_COLOR_DAMAGE: dict[str, int] = {
    'white': 0, 'orange': 1, 'magenta': 2, 'light_blue': 3,
    'yellow': 4, 'lime': 5, 'pink': 6, 'gray': 7,
    'light_gray': 8, 'cyan': 9, 'purple': 10, 'blue': 11,
    'brown': 12, 'green': 13, 'red': 14, 'black': 15,
}


def wool_color_to_damage(color: str) -> Optional[int]:
    """Return the Minecraft damage value for a wool color name, or None."""
    # Handle names with spaces or underscores (e.g. 'light blue' → 'light_blue')
    normalized = color.lower().replace(' ', '_')
    return _WOOL_COLOR_DAMAGE.get(normalized)


def find_pgm_spawner(
    data: dict,
    wool_room_region: str | None,
    wool_color_damage: Optional[int],
) -> dict | None:
    """Return the first PGM spawner entry that matches this wool, or None."""
    for spawner in data.get("spawners", []):
        if wool_room_region and spawner.get("player_region") == wool_room_region:
            return spawner
        for item in spawner.get("items", []):
            if (item.get("material", "").lower() == "wool"
                    and item.get("damage") == wool_color_damage):
                return spawner
    return None


def determine_respawn_type(
    matched_spawner: dict | None,
    mob_spawner_count: int,
    block_wool_count: int,
    chest_wool_count: int,
) -> str:
    """Return the highest-priority respawn mechanism label."""
    if matched_spawner:
        return "pgm_spawner"
    if mob_spawner_count > 0:
        return "mob_spawner"
    if block_wool_count > 0:
        return "renewable"
    if chest_wool_count > 0:
        return "chest"
    return "unknown"


def collect_mob_entity_types(mob_spawners: list[dict]) -> list[str]:
    """Return sorted unique entity/item labels from a list of mob spawner dicts."""
    labels: set[str] = set()
    for spawner in mob_spawners:
        item_id = spawner.get("spawn_item_id")
        entity_id = spawner.get("entity_id")
        if item_id:
            labels.add(item_id.replace("minecraft:", ""))
        elif entity_id:
            labels.add(entity_id)
    return sorted(labels)


def find_relevant_renewables(
    data: dict,
    wool_room_region: str | None,
    layout_result: dict,
) -> list[dict]:
    """Return renewable rules whose region matches the wool room or spatially contains a block_wool."""
    regions_dict: dict = data.get("regions", {})
    relevant: list[dict] = []
    seen: set[str] = set()
    for ren in data.get("renewables", []):
        rid = ren.get("region_id", "")
        if rid in seen:
            continue
        matched = rid == wool_room_region
        if not matched:
            region_bounds = regions_dict.get(rid, {}).get("bounds_2d")
            if region_bounds:
                mn = region_bounds["min"]
                mx = region_bounds["max"]
                for bw in layout_result.get("block_wool", []):
                    if mn["x"] <= bw["x"] <= mx["x"] and mn["z"] <= bw["z"] <= mx["z"]:
                        matched = True
                        break
        if matched:
            relevant.append(ren)
            seen.add(rid)
    return relevant
