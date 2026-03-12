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


def detect_double_chests(chest_df: 'pd.DataFrame') -> 'pd.DataFrame':
    """
    Detect double chests among a set of chest positions.

    Two chest blocks form a double chest when they share the same Y level and
    are exactly 1 block apart in either the X or Z direction. In vanilla
    Minecraft, adjacent chests always merge into a double chest — no two
    independent single chests can be horizontally adjacent.

    Args:
        chest_df: DataFrame with at least columns ``world_x``, ``world_z``, ``y``.
                  Typically the output of :class:`ChestExtractor`.

    Returns:
        Copy of ``chest_df`` with two extra columns added:

        ``is_double``      — True if this chest block is part of a double chest.
        ``chest_group_id`` — Integer ID shared by both halves of a double chest;
                             single chests get their own unique ID.
    """
    import pandas as pd

    if chest_df.empty:
        result = chest_df.copy()
        result['is_double'] = pd.Series(dtype=bool)
        result['chest_group_id'] = pd.Series(dtype='Int64')
        return result

    # Build a lookup from position → row index (use first occurrence per position)
    pos_cols = ['world_x', 'world_z', 'y']
    positions = chest_df[pos_cols].drop_duplicates()
    pos_set: set[tuple[int, int, int]] = set(
        (int(r.world_x), int(r.world_z), int(r.y))
        for r in positions.itertuples()
    )

    group_id: dict[tuple[int, int, int], int] = {}
    is_double: dict[tuple[int, int, int], bool] = {}
    next_id = 0

    for pos in sorted(pos_set):
        x, z, y = pos
        if pos in group_id:
            continue  # already assigned as part of a pair

        # Check adjacent positions (same Y, ±1 in X or Z)
        partner = None
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            candidate = (x + dx, z + dz, y)
            if candidate in pos_set:
                partner = candidate
                break

        if partner is not None and partner not in group_id:
            group_id[pos] = next_id
            group_id[partner] = next_id
            is_double[pos] = True
            is_double[partner] = True
        else:
            group_id[pos] = next_id
            is_double[pos] = False

        next_id += 1

    result = chest_df.copy()
    result['is_double'] = result.apply(
        lambda r: is_double.get((int(r.world_x), int(r.world_z), int(r.y)), False),
        axis=1,
    )
    result['chest_group_id'] = result.apply(
        lambda r: group_id.get((int(r.world_x), int(r.world_z), int(r.y)), -1),
        axis=1,
    ).astype('Int64')
    return result


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
