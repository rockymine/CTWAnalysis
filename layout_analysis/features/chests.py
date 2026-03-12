"""
Chest extractor for Minecraft Anvil region files.

Reads tile entities from chunk NBT data to find chests (and trapped chests)
and extract their full inventory contents.

Chest types recognised:
    'Chest'         — standard chest (block ID 54)
    'TrappedChest'  — trapped chest (block ID 146)
"""

import logging
import pandas as pd

from ..region_reader import RegionReader

logger = logging.getLogger('ctw')

# Tile-entity id strings for chest variants
_CHEST_IDS = frozenset({'Chest', 'TrappedChest'})


def _nbt_val(tag):
    """Return the Python value of an NBT tag, or the tag itself if plain."""
    return tag.value if hasattr(tag, 'value') else tag


class ChestExtractor:
    """
    Finds chests in a Minecraft world and extracts their inventory contents.

    Uses tile-entity (block-entity) NBT data stored in each chunk, so no
    block-array scanning is required — only chunks that actually contain
    chests produce any output.

    Output DataFrame columns:
        world_x    — chest block X index
        world_z    — chest block Z index
        y          — chest block Y level
        chest_type — 'chest' or 'trapped_chest'
        slot       — inventory slot number (0–26)
        item_id    — Minecraft item/block string ID (e.g. 'minecraft:iron_ingot')
        item_damage — damage / metadata value
        count      — stack size
    """

    def __init__(self, region_reader: RegionReader):
        """
        Args:
            region_reader: RegionReader instance for the world.
        """
        self.reader = region_reader

    def extract(self) -> pd.DataFrame:
        """
        Scan all chunks for chest tile entities and collect inventory data.

        Returns:
            DataFrame with columns:
                world_x, world_z, y, chest_type, slot, item_id, item_damage, count
        """
        rows: list[dict] = []
        chunk_count = 0
        chest_count = 0

        logger.debug("Scanning for chests...")

        for chunk, chunk_x, chunk_z in self.reader.iter_chunks():
            chunk_count += 1
            if chunk_count % 100 == 0:
                logger.debug(
                    f"  Processed {chunk_count} chunks, found {chest_count} chests..."
                )

            try:
                tile_entities = chunk.data.get('TileEntities', [])
            except Exception:
                continue

            for te in tile_entities:
                try:
                    id_tag = te.get('id')
                    if id_tag is None:
                        continue
                    te_id = _nbt_val(id_tag)
                    if te_id not in _CHEST_IDS:
                        continue

                    chest_type = 'trapped_chest' if te_id == 'TrappedChest' else 'chest'
                    wx = _nbt_val(te.get('x'))
                    wy = _nbt_val(te.get('y'))
                    wz = _nbt_val(te.get('z'))
                    chest_count += 1

                    items = te.get('Items', [])
                    for item in items:
                        rows.append({
                            'world_x': int(wx),
                            'world_z': int(wz),
                            'y': int(wy),
                            'chest_type': chest_type,
                            'slot': int(_nbt_val(item.get('Slot'))),
                            'item_id': str(_nbt_val(item.get('id', ''))),
                            'item_damage': int(_nbt_val(item.get('Damage', 0))),
                            'count': int(_nbt_val(item.get('Count', 1))),
                        })

                except Exception as e:
                    logger.debug(f"  Skipping malformed tile entity: {e}")
                    continue

        logger.debug(
            f"Completed chest scan: {chunk_count} chunks, "
            f"{chest_count} chests, {len(rows)} item slots"
        )

        if not rows:
            return pd.DataFrame(
                columns=[
                    'world_x', 'world_z', 'y', 'chest_type',
                    'slot', 'item_id', 'item_damage', 'count',
                ]
            )
        return pd.DataFrame(rows)
