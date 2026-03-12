"""
Resource block extractor for Minecraft Anvil region files.

Scans all Y levels for full resource blocks (iron, gold, diamond blocks).
These deposits are used as crafting supply points on CTW maps.

Minecraft 1.8.9 block IDs for resource blocks:
    41  — gold_block
    42  — iron_block
    57  — diamond_block
"""

import logging
from typing import Optional
import pandas as pd

from ..region_reader import RegionReader
from ..utils import decode_block_id, get_block_index

logger = logging.getLogger('ctw')

# Default resource blocks to scan for: {block_id: resource_type label}
DEFAULT_RESOURCE_BLOCKS: dict[int, str] = {
    41: 'gold_block',
    42: 'iron_block',
    57: 'diamond_block',
}


def _nbt_int(tag) -> int:
    """Extract a Python int from an NBT tag or plain int."""
    return tag.value if hasattr(tag, 'value') else int(tag)


def _nbt_bytes(tag) -> Optional[bytes]:
    """Extract bytes from an NBT byte-array tag, or None."""
    if tag is None:
        return None
    return bytes(tag.value) if hasattr(tag, 'value') else bytes(tag)


class ResourceBlockExtractor:
    """
    Scans all Y levels of a Minecraft world for resource blocks.

    Uses direct section-array scanning (reading the raw Blocks byte array
    rather than calling chunk.get_block() per position) so it completes in
    a single pass through each 16³ section.

    Output DataFrame columns:
        world_x    — block X index
        world_z    — block Z index
        y          — block Y level
        resource_type — label string, e.g. 'iron_block'
    """

    def __init__(
        self,
        region_reader: RegionReader,
        target_blocks: Optional[dict[int, str]] = None,
    ):
        """
        Args:
            region_reader: RegionReader instance for the world.
            target_blocks: Mapping of block_id → label to search for.
                           Defaults to iron_block, gold_block, diamond_block.
        """
        self.reader = region_reader
        self.target_blocks = target_blocks if target_blocks is not None else DEFAULT_RESOURCE_BLOCKS

    def extract(self) -> pd.DataFrame:
        """
        Scan all chunks and sections for resource blocks.

        Returns:
            DataFrame with columns: world_x, world_z, y, resource_type
        """
        rows: list[dict] = []
        chunk_count = 0
        target_ids = set(self.target_blocks)

        logger.debug(
            f"Scanning for resource blocks: {list(self.target_blocks.values())}"
        )

        for chunk, chunk_x, chunk_z in self.reader.iter_chunks():
            chunk_count += 1
            if chunk_count % 100 == 0:
                logger.debug(
                    f"  Processed {chunk_count} chunks, found {len(rows)} resource blocks..."
                )

            try:
                sections = chunk.data.get('Sections', [])
            except Exception:
                continue

            for section in sections:
                blocks_tag = section.get('Blocks')
                if blocks_tag is None:
                    continue

                blocks = _nbt_bytes(blocks_tag)
                add = _nbt_bytes(section.get('Add'))

                sy_tag = section.get('Y')
                if sy_tag is None:
                    continue
                section_y = _nbt_int(sy_tag)

                # Single pass through the 4096-element Blocks array
                for index in range(4096):
                    block_id = decode_block_id(blocks, add, index)
                    if block_id not in target_ids:
                        continue

                    # Decode local coords from index: (y*16 + z)*16 + x
                    x_local = index % 16
                    z_local = (index // 16) % 16
                    y_local = index // 256

                    rows.append({
                        'world_x': chunk_x * 16 + x_local,
                        'world_z': chunk_z * 16 + z_local,
                        'y': section_y * 16 + y_local,
                        'resource_type': self.target_blocks[block_id],
                    })

        logger.debug(
            f"Completed resource block scan: {chunk_count} chunks, "
            f"{len(rows)} blocks found"
        )

        df = pd.DataFrame(rows)
        if df.empty:
            return pd.DataFrame(columns=['world_x', 'world_z', 'y', 'resource_type'])
        return df
