"""
Kit parser for Minecraft map XML configuration.

Reads the <kits> section and returns two DataFrames:
  - kit_items_df  — one row per inventory item slot
  - kit_armor_df  — one row per armor slot (helmet/chestplate/leggings/boots)

Enchantments are stored as a comma-separated string of "name:level" pairs,
e.g. "infinity:1" or "efficiency:2,protection:1".  Level is omitted-as-1 when
not specified.  Both XML forms are handled:
  - Nested element:  <enchantment level="2">dig speed</enchantment>
  - Attribute:       enchantment="dig speed:2"  or  enchantment="arrow infinite"
"""

import logging
import xml.etree.ElementTree as ET

import pandas as pd

from .datatypes import Spawn

logger = logging.getLogger('ctw')

_ARMOR_SLOTS = ('helmet', 'chestplate', 'leggings', 'boots')

_KIT_ITEMS_COLUMNS = [
    'kit_id', 'team', 'slot', 'material',
    'amount', 'item_damage', 'unbreakable', 'team_color', 'enchantments',
]
_KIT_ARMOR_COLUMNS = [
    'kit_id', 'team', 'slot_name', 'material',
    'unbreakable', 'team_color', 'enchantments',
]


def _parse_enchantment_attr(value: str) -> str:
    """Parse enchantment attribute value into normalised "name:level" string.

    Handles forms:
      "infinity"          → "infinity:1"
      "arrow infinite"    → "arrow_infinite:1"
      "dig speed:2"       → "dig_speed:2"
      "protection projectile:2" → "protection_projectile:2"
    """
    value = value.strip()
    if ':' in value:
        parts = value.rsplit(':', 1)
        name = parts[0].strip().replace(' ', '_')
        try:
            level = int(parts[1].strip())
        except ValueError:
            level = 1
    else:
        name = value.replace(' ', '_')
        level = 1
    return f"{name}:{level}"


def _parse_enchantment_elem(elem: ET.Element) -> str:
    """Parse a nested <enchantment> element into "name:level" string."""
    name = (elem.text or '').strip().replace(' ', '_')
    try:
        level = int(elem.get('level', '1'))
    except ValueError:
        level = 1
    return f"{name}:{level}"


def _collect_enchantments(elem: ET.Element) -> str:
    """Collect all enchantments from an item/armor element.

    Checks for:
      - enchantment= attribute on the element itself
      - <enchantment> child elements
    Returns comma-joined string, or '' if none.
    """
    parts: list[str] = []

    attr = elem.get('enchantment', '').strip()
    if attr:
        parts.append(_parse_enchantment_attr(attr))

    for child in elem:
        if child.tag == 'enchantment':
            parts.append(_parse_enchantment_elem(child))

    return ','.join(parts)


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.lower() in ('true', '1', 'yes')


def _kit_teams(kit_id: str, spawns: list[Spawn]) -> list[str]:
    """Return the list of team IDs that reference this kit via <spawn>.

    If no spawn references this kit, returns [''] (empty string = all/unassigned).
    """
    teams = [s.team for s in spawns if s.kit == kit_id]
    return teams if teams else ['']


def parse_kits(
    root: ET.Element,
    spawns: list[Spawn],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parse the <kits> section from the XML root element.

    Args:
        root: Root XML element of the parsed map.xml.
        spawns: Spawn list from the same XML (used to resolve team associations).

    Returns:
        (kit_items_df, kit_armor_df) — DataFrames ready to write to parquet.
        Both are empty DataFrames with correct columns if no kits are found.
    """
    kits_elem = root.find('kits')
    if kits_elem is None:
        logger.debug("  No <kits> element found")
        return (
            pd.DataFrame(columns=_KIT_ITEMS_COLUMNS),
            pd.DataFrame(columns=_KIT_ARMOR_COLUMNS),
        )

    item_rows: list[dict] = []
    armor_rows: list[dict] = []

    kit_count = 0
    for kit_elem in kits_elem.findall('kit'):
        kit_id = kit_elem.get('id', '')
        if not kit_id:
            continue

        teams = _kit_teams(kit_id, spawns)

        # Collect items
        items_in_kit: list[dict] = []
        for item_elem in kit_elem.findall('item'):
            slot_str = item_elem.get('slot', '')
            material = item_elem.get('material', '').strip()
            if not material:
                continue
            try:
                slot = int(slot_str)
            except ValueError:
                logger.debug(f"    Kit '{kit_id}': skipping item with invalid slot '{slot_str}'")
                continue

            items_in_kit.append({
                'kit_id': kit_id,
                'slot': slot,
                'material': material,
                'amount': int(item_elem.get('amount', '1')),
                'item_damage': int(item_elem.get('damage', '0')),
                'unbreakable': _parse_bool(item_elem.get('unbreakable')),
                'team_color': _parse_bool(item_elem.get('team-color')),
                'enchantments': _collect_enchantments(item_elem) or None,
            })

        # Collect armor
        armor_in_kit: list[dict] = []
        for slot_name in _ARMOR_SLOTS:
            armor_elem = kit_elem.find(slot_name)
            if armor_elem is None:
                continue
            material = armor_elem.get('material', '').strip()
            if not material:
                continue
            armor_in_kit.append({
                'kit_id': kit_id,
                'slot_name': slot_name,
                'material': material,
                'unbreakable': _parse_bool(armor_elem.get('unbreakable')),
                'team_color': _parse_bool(armor_elem.get('team-color')),
                'enchantments': _collect_enchantments(armor_elem) or None,
            })

        if not items_in_kit and not armor_in_kit:
            logger.debug(f"    Kit '{kit_id}': no items or armor, skipping")
            continue

        kit_count += 1

        # Expand per team
        for team in teams:
            for base in items_in_kit:
                item_rows.append({**base, 'team': team})
            for base in armor_in_kit:
                armor_rows.append({**base, 'team': team})

    logger.debug(
        f"  Parsed {kit_count} kit(s): "
        f"{len(item_rows)} item rows, {len(armor_rows)} armor rows"
    )

    items_df = (
        pd.DataFrame(item_rows, columns=_KIT_ITEMS_COLUMNS)
        if item_rows
        else pd.DataFrame(columns=_KIT_ITEMS_COLUMNS)
    )
    armor_df = (
        pd.DataFrame(armor_rows, columns=_KIT_ARMOR_COLUMNS)
        if armor_rows
        else pd.DataFrame(columns=_KIT_ARMOR_COLUMNS)
    )
    return items_df, armor_df
