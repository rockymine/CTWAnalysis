"""
Extraction modes for analyzing Minecraft world layouts.

Provides three extractors:
1. Y0LayerExtractor - Extracts non-air blocks at world y=0
2. TopSurfaceExtractor - Finds highest non-air block in each column
3. VerticalDensityExtractor - Filters columns by density metrics
"""

import logging
from typing import List, Tuple, Literal
import pandas as pd
from .region_reader import RegionReader

logger = logging.getLogger('ctw')


class Y0LayerExtractor:
    """
    Extracts all non-air blocks at world y=0.

    Criterion: block_id != 0 at y=0
    """

    def __init__(self, region_reader: RegionReader):
        """
        Initialize the extractor.

        Args:
            region_reader: RegionReader instance for the world
        """
        self.reader = region_reader

    def extract(self) -> pd.DataFrame:
        """
        Extract all non-air blocks at y=0.

        Returns:
            DataFrame with columns: world_x, world_z, block_id, block_data
        """
        points = []
        chunk_count = 0

        logger.debug("Extracting Y0 layer...")

        for chunk, chunk_x, chunk_z in self.reader.iter_chunks():
            chunk_count += 1
            if chunk_count % 100 == 0:
                logger.debug(f"  Processed {chunk_count} chunks, found {len(points)} points...")

            # Iterate over all x,z positions in the chunk at y=0
            for local_x in range(16):
                for local_z in range(16):
                    try:
                        block = chunk.get_block(local_x, 0, local_z)

                        # Check if non-air
                        if block.id != 0:
                            world_x = chunk_x * 16 + local_x
                            world_z = chunk_z * 16 + local_z

                            points.append({
                                'world_x': world_x,
                                'world_z': world_z,
                                'block_id': block.id,
                                'block_data': block.data,
                            })
                    except Exception:
                        # Block doesn't exist or error, skip
                        continue

        logger.debug(f"Completed Y0 extraction: {chunk_count} chunks, {len(points)} matching points")

        return pd.DataFrame(points)


class TopSurfaceExtractor:
    """
    Finds the highest non-air block in each column.

    Criterion: column has at least one non-air block
    """

    def __init__(self, region_reader: RegionReader):
        """
        Initialize the extractor.

        Args:
            region_reader: RegionReader instance for the world
        """
        self.reader = region_reader

    def extract(self) -> pd.DataFrame:
        """
        Extract the highest non-air block in each column.

        Returns:
            DataFrame with columns: world_x, world_z, y, block_id, block_data
        """
        points = []
        chunk_count = 0

        logger.debug("Extracting top surface...")

        for chunk, chunk_x, chunk_z in self.reader.iter_chunks():
            chunk_count += 1
            if chunk_count % 100 == 0:
                logger.debug(f"  Processed {chunk_count} chunks, found {len(points)} points...")

            # For each x,z column in the chunk, find the highest non-air block
            for local_x in range(16):
                for local_z in range(16):
                    highest_y = None
                    highest_id = None
                    highest_data = None

                    # Scan from top to bottom (y=255 down to y=0)
                    for y in range(255, -1, -1):
                        try:
                            block = chunk.get_block(local_x, y, local_z)

                            if block.id != 0:
                                # Found the highest non-air block
                                highest_y = y
                                highest_id = block.id
                                highest_data = block.data
                                break
                        except Exception:
                            # Block doesn't exist or error, continue
                            continue

                    # Add to results if we found a non-air block
                    if highest_y is not None:
                        world_x = chunk_x * 16 + local_x
                        world_z = chunk_z * 16 + local_z

                        points.append({
                            'world_x': world_x,
                            'world_z': world_z,
                            'y': highest_y,
                            'block_id': highest_id,
                            'block_data': highest_data,
                        })

        logger.debug(f"Completed top surface extraction: {chunk_count} chunks, {len(points)} matching points")

        return pd.DataFrame(points)


class VerticalDensityExtractor:
    """
    Filters columns by vertical density metrics.

    Supports two modes:
    - 'run': Maximum consecutive run length of non-air blocks
    - 'count': Total number of non-air blocks

    Criterion: metric >= threshold
    """

    def __init__(
        self,
        region_reader: RegionReader,
        threshold: int = 10,
        mode: Literal['run', 'count'] = 'run'
    ):
        """
        Initialize the extractor.

        Args:
            region_reader: RegionReader instance for the world
            threshold: Minimum metric value to include the column
            mode: Density calculation mode ('run' or 'count')
        """
        self.reader = region_reader
        self.threshold = threshold
        self.mode = mode

    def extract(self) -> pd.DataFrame:
        """
        Extract columns meeting the density threshold.

        Returns:
            DataFrame with columns: world_x, world_z, metric
        """
        points = []
        chunk_count = 0

        logger.debug(f"Extracting vertical density (mode={self.mode}, threshold={self.threshold})...")

        for chunk, chunk_x, chunk_z in self.reader.iter_chunks():
            chunk_count += 1
            if chunk_count % 100 == 0:
                logger.debug(f"  Processed {chunk_count} chunks, found {len(points)} points...")

            # For each x,z column in the chunk, calculate the metric
            for local_x in range(16):
                for local_z in range(16):
                    # Collect all block IDs in the column from bottom to top
                    column_blocks = []

                    for y in range(256):  # y=0 to y=255
                        try:
                            block = chunk.get_block(local_x, y, local_z)
                            column_blocks.append(block.id)
                        except Exception:
                            # Block doesn't exist, treat as air
                            column_blocks.append(0)

                    # Calculate metric based on mode
                    if self.mode == 'run':
                        metric = self._calculate_max_run(column_blocks)
                    elif self.mode == 'count':
                        metric = self._calculate_count(column_blocks)
                    else:
                        raise ValueError(f"Invalid mode: {self.mode}")

                    # Check if meets threshold
                    if metric >= self.threshold:
                        world_x = chunk_x * 16 + local_x
                        world_z = chunk_z * 16 + local_z

                        points.append({
                            'world_x': world_x,
                            'world_z': world_z,
                            'metric': metric,
                        })

        logger.debug(f"Completed density extraction: {chunk_count} chunks, {len(points)} matching points")

        return pd.DataFrame(points)

    def _calculate_max_run(self, column_blocks: List[int]) -> int:
        """
        Calculate the maximum consecutive run length of non-air blocks.

        Args:
            column_blocks: List of block IDs from bottom to top

        Returns:
            Maximum consecutive run length
        """
        max_run = 0
        current_run = 0

        for block_id in column_blocks:
            if block_id != 0:
                current_run += 1
                max_run = max(max_run, current_run)
            else:
                current_run = 0

        return max_run

    def _calculate_count(self, column_blocks: List[int]) -> int:
        """
        Calculate the total count of non-air blocks.

        Args:
            column_blocks: List of block IDs from bottom to top

        Returns:
            Count of non-air blocks
        """
        return sum(1 for block_id in column_blocks if block_id != 0)


class LowestBedrockExtractor:
    """
    Finds the lowest bedrock block (block_id=7) in each column.

    Criterion: column contains at least one bedrock block
    """

    def __init__(self, region_reader: RegionReader):
        """
        Initialize the extractor.

        Args:
            region_reader: RegionReader instance for the world
        """
        self.reader = region_reader

    def extract(self) -> pd.DataFrame:
        """
        Extract the lowest bedrock block in each column.

        Returns:
            DataFrame with columns: world_x, world_z, y, block_data
        """
        points = []
        chunk_count = 0

        logger.debug("Extracting lowest bedrock blocks...")

        for chunk, chunk_x, chunk_z in self.reader.iter_chunks():
            chunk_count += 1
            if chunk_count % 100 == 0:
                logger.debug(f"  Processed {chunk_count} chunks, found {len(points)} points...")

            # For each x,z column in the chunk, find the lowest bedrock block
            for local_x in range(16):
                for local_z in range(16):
                    lowest_y = None
                    lowest_data = None

                    # Scan from bottom to top (y=0 to y=255)
                    for y in range(256):
                        try:
                            block = chunk.get_block(local_x, y, local_z)

                            if block.id == 7:  # Bedrock
                                # Found the lowest bedrock block
                                lowest_y = y
                                lowest_data = block.data
                                break
                        except Exception:
                            # Block doesn't exist or error, continue
                            continue

                    # Add to results if we found a bedrock block
                    if lowest_y is not None:
                        world_x = chunk_x * 16 + local_x
                        world_z = chunk_z * 16 + local_z

                        points.append({
                            'world_x': world_x,
                            'world_z': world_z,
                            'y': lowest_y,
                            'block_data': lowest_data,
                        })

        logger.debug(f"Completed lowest bedrock extraction: {chunk_count} chunks, {len(points)} matching points")

        return pd.DataFrame(points)
