"""
Tile entity extractor for Minecraft Anvil region files.

Reads the ``TileEntities`` NBT list from each chunk — the per-block compound
tags that store configuration beyond what a block-ID + data nibble can hold.
Currently focused on mob spawners (in-game block ID 52, NBT id 'MobSpawner'),
but the extractor is generic and can be extended to other tile entity types
(chests, signs, command blocks, …) by passing a custom ``target_entity_ids``
set.

Mob spawner fields extracted
-----------------------------
``entity_id``             — entity type string (e.g. ``'Zombie'``, ``'Bat'``, ``'Item'``)
``spawn_count``           — SpawnCount: how many entities spawn per activation
``spawn_range``           — SpawnRange: horizontal activation radius (blocks)
``min_spawn_delay``       — MinSpawnDelay (ticks)
``max_spawn_delay``       — MaxSpawnDelay (ticks)
``required_player_range`` — RequiredPlayerRange: distance to activate (blocks)
``max_nearby_entities``   — MaxNearbyEntities: cap before spawning pauses
``spawns_wool``           — True when SpawnData.Item.id == 'minecraft:wool'
``spawn_item_id``         — item id string from SpawnData.Item (None if not an Item spawner)
``spawn_item_damage``     — item damage/variant from SpawnData.Item (None if absent)

The ``spawns_wool`` flag is the primary filter for the wool-room respawn detector:
only spawners where this is True count as a wool respawn mechanism.

Output
------
``layout_tile_entities.parquet`` — one row per tile entity, columns:

    world_x, world_z, y, tile_type, entity_id, spawns_wool,
    spawn_item_id, spawn_item_damage,
    spawn_count, spawn_range, min_spawn_delay, max_spawn_delay,
    required_player_range, max_nearby_entities

Note on position: TileEntity NBT already stores absolute world coordinates
(``x``, ``y``, ``z`` fields), so no chunk-offset arithmetic is needed here.
"""

import logging
from typing import Optional
import pandas as pd

from ..region_reader import RegionReader

logger = logging.getLogger('ctw')

# Default tile entity types to extract
DEFAULT_TILE_ENTITY_IDS: set[str] = {'MobSpawner'}


def _read_compound_tags(compound) -> dict:
    """Flatten a TAG_Compound into a plain ``{name: scalar_value}`` dict.

    TAG_Compound children are stored in a ``.tags`` list where each entry
    has a ``.name`` attribute and a ``.value`` attribute (or is itself a
    nested compound).  Only scalar values are extracted; nested compounds
    are skipped.
    """
    result: dict = {}
    try:
        for tag in compound.tags:
            raw = tag.value if hasattr(tag, 'value') else None
            if raw is not None:
                result[tag.name] = raw
    except Exception:
        pass
    return result

# Output parquet column order (used for the empty-DataFrame fallback)
_COLUMNS: list[str] = [
    'world_x', 'world_z', 'y', 'tile_type', 'entity_id',
    'spawns_wool', 'spawn_item_id', 'spawn_item_damage',
    'spawn_count', 'spawn_range', 'min_spawn_delay', 'max_spawn_delay',
    'required_player_range', 'max_nearby_entities',
]


class TileEntityExtractor:
    """
    Extracts tile entity data from Minecraft Anvil chunk NBT.

    Unlike block-array scanning (which reads ``Sections[].Blocks``/``Data``),
    this reads ``chunk.data['TileEntities']`` — the list of compound tags
    carrying extended per-block state.

    Args:
        region_reader:     RegionReader instance for the world.
        target_entity_ids: Set of NBT ``id`` strings to capture.
                           Defaults to ``{'MobSpawner'}``.
    """

    def __init__(
        self,
        region_reader: RegionReader,
        target_entity_ids: Optional[set[str]] = None,
    ) -> None:
        self.reader = region_reader
        self.target_ids: set[str] = (
            target_entity_ids if target_entity_ids is not None
            else DEFAULT_TILE_ENTITY_IDS
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self) -> pd.DataFrame:
        """Scan all chunks and return a DataFrame of tile entity records.

        Returns:
            DataFrame with columns defined by ``_COLUMNS``.  Numeric fields
            for spawner configuration are ``Int64`` (nullable integer) so
            that missing values are represented as ``pd.NA`` rather than
            ``NaN``-promoted floats.
        """
        rows: list[dict] = []
        chunk_count = 0

        logger.debug(f"Scanning for tile entities: {sorted(self.target_ids)}")

        for chunk, _chunk_x, _chunk_z in self.reader.iter_chunks():
            chunk_count += 1
            if chunk_count % 100 == 0:
                logger.debug(
                    f"  Processed {chunk_count} chunks, "
                    f"found {len(rows)} tile entities..."
                )

            try:
                tile_entities = chunk.data.get('TileEntities', [])
                if not tile_entities:
                    continue
            except Exception:
                continue

            for te in tile_entities:
                row = self._parse_tile_entity(te)
                if row is not None:
                    rows.append(row)

        logger.debug(
            f"Completed tile entity scan: {chunk_count} chunks, "
            f"{len(rows)} entities found"
        )

        if not rows:
            df = pd.DataFrame(columns=_COLUMNS)
        else:
            df = pd.DataFrame(rows)

        # Use nullable integer types for optional numeric fields
        nullable_int_cols = [
            'spawn_item_damage',
            'spawn_count', 'spawn_range', 'min_spawn_delay', 'max_spawn_delay',
            'required_player_range', 'max_nearby_entities',
        ]
        for col in nullable_int_cols:
            if col in df.columns:
                df[col] = df[col].astype('Int64')

        return df

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_tile_entity(self, te) -> Optional[dict]:
        """Parse a single TileEntity NBT compound.

        Returns a dict row if the entity type is in ``target_ids``,
        otherwise returns None.  Position is read from the tile entity's
        own ``x``/``y``/``z`` fields (absolute world coordinates).
        """
        try:
            te_id_raw = te.get('id')
            if te_id_raw is None:
                return None
            tile_type: str = (
                te_id_raw.value if hasattr(te_id_raw, 'value') else str(te_id_raw)
            )
            if tile_type not in self.target_ids:
                return None

            x_raw = te.get('x')
            y_raw = te.get('y')
            z_raw = te.get('z')
            if x_raw is None or y_raw is None or z_raw is None:
                return None

            world_x = int(x_raw.value if hasattr(x_raw, 'value') else x_raw)
            world_y = int(y_raw.value if hasattr(y_raw, 'value') else y_raw)
            world_z = int(z_raw.value if hasattr(z_raw, 'value') else z_raw)

            row: dict = {
                'world_x':               world_x,
                'world_z':               world_z,
                'y':                     world_y,
                'tile_type':             tile_type,
                'entity_id':             None,
                'spawns_wool':           False,
                'spawn_item_id':         None,
                'spawn_item_damage':     None,
                'spawn_count':           None,
                'spawn_range':           None,
                'min_spawn_delay':       None,
                'max_spawn_delay':       None,
                'required_player_range': None,
                'max_nearby_entities':   None,
            }

            if tile_type == 'MobSpawner':
                row.update(self._parse_mob_spawner_fields(te))

            return row

        except Exception:
            return None

    def _parse_mob_spawner_fields(self, te) -> dict:
        """Extract MobSpawner-specific NBT fields into a partial row dict.

        Reads scalar fields directly from the top-level spawner compound, then
        digs into ``SpawnData.Item`` (if present) to identify Item-entity spawners
        that drop specific items.  The ``spawns_wool`` flag is True only when
        ``SpawnData.Item.id == 'minecraft:wool'``.
        """

        def _int_field(tag) -> Optional[int]:
            if tag is None:
                return None
            raw = tag.value if hasattr(tag, 'value') else tag
            try:
                return int(raw)
            except (TypeError, ValueError):
                return None

        def _str_field(tag) -> Optional[str]:
            if tag is None:
                return None
            raw = tag.value if hasattr(tag, 'value') else tag
            return str(raw) if raw is not None else None

        fields: dict = {
            'entity_id':              _str_field(te.get('EntityId')),
            'spawns_wool':            False,
            'spawn_item_id':          None,
            'spawn_item_damage':      None,
            'spawn_count':            _int_field(te.get('SpawnCount')),
            'spawn_range':            _int_field(te.get('SpawnRange')),
            'min_spawn_delay':        _int_field(te.get('MinSpawnDelay')),
            'max_spawn_delay':        _int_field(te.get('MaxSpawnDelay')),
            'required_player_range':  _int_field(te.get('RequiredPlayerRange')),
            'max_nearby_entities':    _int_field(te.get('MaxNearbyEntities')),
        }

        # ── SpawnData.Item — only present for entity_id == 'Item' spawners ──
        spawn_data = te.get('SpawnData')
        if spawn_data is not None:
            item_compound = spawn_data.get('Item')
            if item_compound is not None:
                item_fields = _read_compound_tags(item_compound)
                item_id  = item_fields.get('id')
                item_dmg = item_fields.get('Damage')
                if item_id is not None:
                    fields['spawn_item_id']     = str(item_id)
                    fields['spawn_item_damage']  = (
                        int(item_dmg) if item_dmg is not None else None
                    )
                    fields['spawns_wool'] = (
                        str(item_id).lower() in ('minecraft:wool', 'wool', '35')
                    )

        return fields
