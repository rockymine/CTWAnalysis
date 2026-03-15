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
import numpy as np
import pandas as pd

from ..region_reader import RegionReader
from ..extractors import _iter_chunk_sections

logger = logging.getLogger('ctw')

# Default resource blocks to scan for: {block_id: resource_type label}
DEFAULT_RESOURCE_BLOCKS: dict[int, str] = {
    41: 'gold_block',
    42: 'iron_block',
    57: 'diamond_block',
}


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
        all_wx: list[np.ndarray] = []
        all_wz: list[np.ndarray] = []
        all_y:  list[np.ndarray] = []
        all_rt: list[np.ndarray] = []
        chunk_count = 0

        logger.debug(
            f"Scanning for resource blocks: {list(self.target_blocks.values())}"
        )

        for chunk, chunk_x, chunk_z in self.reader.iter_chunks():
            chunk_count += 1
            if chunk_count % 100 == 0:
                n = sum(len(a) for a in all_wx)
                logger.debug(
                    f"  Processed {chunk_count} chunks, found {n} resource blocks..."
                )

            for section_y, blocks_3d, _ in _iter_chunk_sections(chunk):
                for block_id, label in self.target_blocks.items():
                    yy, zz, xx = np.where(blocks_3d == block_id)
                    if len(yy) == 0:
                        continue
                    all_wx.append((chunk_x * 16 + xx).astype(np.int32))
                    all_wz.append((chunk_z * 16 + zz).astype(np.int32))
                    all_y.append((section_y * 16 + yy).astype(np.int32))
                    all_rt.append(np.full(len(yy), label, dtype=object))

        total = sum(len(a) for a in all_wx)
        logger.debug(
            f"Completed resource block scan: {chunk_count} chunks, "
            f"{total} blocks found"
        )

        if not all_wx:
            return pd.DataFrame(columns=['world_x', 'world_z', 'y', 'resource_type'])
        return pd.DataFrame({
            'world_x': np.concatenate(all_wx),
            'world_z': np.concatenate(all_wz),
            'y': np.concatenate(all_y),
            'resource_type': np.concatenate(all_rt),
        })
