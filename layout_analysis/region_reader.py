"""
Region file reader for Minecraft Anvil format.

Provides streaming access to chunks and sections without loading entire world into memory.
"""

import logging
import os
from pathlib import Path
from typing import Iterator, Optional
import anvil

logger = logging.getLogger('ctw')


class RegionReader:
    """
    Reads Minecraft region files and provides streaming access to chunks and sections.
    """

    def __init__(self, region_dir: str):
        """
        Initialize the region reader.

        Args:
            region_dir: Path to the world's region directory
        """
        self.region_dir = Path(region_dir)
        if not self.region_dir.exists():
            raise ValueError(f"Region directory does not exist: {region_dir}")

    def get_region_files(self) -> list:
        """
        Get all region files in the directory.

        Returns:
            List of region file paths
        """
        return sorted(self.region_dir.glob("r.*.*.mca"))

    def iter_chunks(self) -> Iterator[tuple[anvil.Chunk, int, int]]:
        """
        Iterate over all chunks in all region files.

        Yields:
            Tuple of (chunk, chunk_x, chunk_z)
        """
        region_files = self.get_region_files()

        for region_file in region_files:
            # Parse region coordinates from filename: r.<rx>.<rz>.mca
            filename = region_file.stem
            parts = filename.split('.')
            if len(parts) != 3:
                continue

            try:
                region_x = int(parts[1])
                region_z = int(parts[2])
            except ValueError:
                continue

            # Open the region
            try:
                region = anvil.Region.from_file(str(region_file))
            except Exception as e:
                logger.warning(f"Failed to read region {region_file}: {e}")
                continue

            # Iterate over chunks in the region (32x32 grid)
            for local_x in range(32):
                for local_z in range(32):
                    try:
                        chunk = region.get_chunk(local_x, local_z)
                        if chunk is not None:
                            # Calculate world chunk coordinates
                            chunk_x = region_x * 32 + local_x
                            chunk_z = region_z * 32 + local_z
                            yield chunk, chunk_x, chunk_z
                    except Exception:
                        # Chunk doesn't exist or is corrupted, skip silently
                        continue

    def get_section(self, chunk: anvil.Chunk, section_y: int) -> Optional[dict]:
        """
        Get a specific section from a chunk.

        Args:
            chunk: The chunk object
            section_y: Section Y coordinate (0-15 for y=0-255)

        Returns:
            Dictionary with 'Blocks', 'Data', 'Add' (optional), 'Y' keys, or None if section doesn't exist
        """
        # Access the chunk's NBT data
        try:
            # anvil-parser already unwraps the Level tag, so sections are directly accessible
            sections = chunk.data.get('Sections', [])

            for section in sections:
                if section.get('Y') == section_y:
                    # Extract the arrays we need
                    blocks = section.get('Blocks')
                    data = section.get('Data')
                    add = section.get('Add')

                    if blocks is None or data is None:
                        return None

                    # Convert to bytes/bytearray if needed
                    if hasattr(blocks, 'value'):
                        blocks = bytes(blocks.value)
                    else:
                        blocks = bytes(blocks)

                    if hasattr(data, 'value'):
                        data = bytes(data.value)
                    else:
                        data = bytes(data)

                    result = {
                        'Y': section_y,
                        'Blocks': blocks,
                        'Data': data,
                    }

                    if add is not None:
                        if hasattr(add, 'value'):
                            add = bytes(add.value)
                        else:
                            add = bytes(add)
                        result['Add'] = add

                    return result

        except Exception as e:
            # Section doesn't exist or error accessing it
            return None

        return None
