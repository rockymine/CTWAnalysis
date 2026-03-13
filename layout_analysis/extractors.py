"""
Extraction modes for analyzing Minecraft world layouts.

Provides four extractors:
1. Y0LayerExtractor          - Extracts non-air blocks at world y=0
2. TopSurfaceExtractor       - Finds highest non-excluded non-air block in each column
3. VerticalDensityExtractor  - Filters columns by density metrics
4. LowestBedrockExtractor    - Finds lowest bedrock (block 7) in each column
5. LowestSolidLayerExtractor - Finds lowest non-excluded non-air block in each column
"""

import logging
from typing import Literal
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
    Finds the highest non-excluded non-air block in each column.

    Scans each column from y=255 downward and returns the first block whose
    ID is not air (0) and not in exclude_ids. When exclude_ids is non-empty
    this produces a "structural" surface that skips decoration blocks
    (e.g. leaves, tall grass, build-region markers).

    Criterion: column contains at least one qualifying block
    """

    def __init__(
        self,
        region_reader: RegionReader,
        exclude_ids: set[int] | None = None,
    ):
        """
        Initialize the extractor.

        Args:
            region_reader: RegionReader instance for the world
            exclude_ids: Block IDs to skip when searching top-down.
                         Air (0) is always excluded regardless of this set.
                         Pass an empty set or None for the raw top surface.
        """
        self.reader = region_reader
        self._exclude_ids: set[int] = set(exclude_ids) if exclude_ids else set()

    def extract(self) -> pd.DataFrame:
        """
        Extract the highest qualifying block in each column.

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

            for local_x in range(16):
                for local_z in range(16):
                    highest_y = None
                    highest_id = None
                    highest_data = None

                    # Scan from top to bottom (y=255 down to y=0)
                    for y in range(255, -1, -1):
                        try:
                            block = chunk.get_block(local_x, y, local_z)
                            if block.id != 0 and block.id not in self._exclude_ids:
                                highest_y = y
                                highest_id = block.id
                                highest_data = block.data
                                break
                        except Exception:
                            continue

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

    def _calculate_max_run(self, column_blocks: list[int]) -> int:
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

    def _calculate_count(self, column_blocks: list[int]) -> int:
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


# Default block IDs excluded by LowestSolidLayerExtractor.
# Block 36 (PISTON_MOVING_PIECE) is used by many maps as a build-region
# boundary marker and should never be treated as part of an island.
_DEFAULT_SOLID_EXCLUDE: frozenset[int] = frozenset({36})


class LowestSolidLayerExtractor:
    """
    Finds the lowest non-excluded non-air block in each column.

    Scans each column from y=0 upward and returns the first block whose
    ID is not air (0) and not in exclude_ids.  This gives a "view from
    below" that is robust across map styles:

    - Standard bedrock maps: returns the bedrock block (same footprint as
      LowestBedrockExtractor, but also captures the block_id).
    - Maps with raised or non-bedrock floors: returns whatever the actual
      floor material is.
    - Floating-island maps: returns the underside of each island (columns
      above void simply yield no result).

    Unlike LowestBedrockExtractor this extractor also returns the block_id,
    making it useful for both island detection and material analysis.

    Criterion: column contains at least one qualifying block
    """

    def __init__(
        self,
        region_reader: RegionReader,
        exclude_ids: set[int] | None = None,
    ):
        """
        Initialize the extractor.

        Args:
            region_reader: RegionReader instance for the world
            exclude_ids: Block IDs to skip when searching bottom-up.
                         Air (0) is always excluded.  Defaults to {36}
                         (build-region marker).  Pass an explicit set to
                         override (an empty set means only air is excluded).
        """
        self.reader = region_reader
        self._exclude_ids: frozenset[int] = (
            frozenset(exclude_ids) if exclude_ids is not None
            else _DEFAULT_SOLID_EXCLUDE
        )

    def extract(self) -> pd.DataFrame:
        """
        Extract the lowest qualifying block in each column.

        Returns:
            DataFrame with columns: world_x, world_z, y, block_id, block_data
        """
        points = []
        chunk_count = 0

        logger.debug("Extracting lowest solid layer...")

        for chunk, chunk_x, chunk_z in self.reader.iter_chunks():
            chunk_count += 1
            if chunk_count % 100 == 0:
                logger.debug(f"  Processed {chunk_count} chunks, found {len(points)} points...")

            for local_x in range(16):
                for local_z in range(16):
                    lowest_y = None
                    lowest_id = None
                    lowest_data = None

                    # Scan from bottom to top (y=0 to y=255), early termination
                    for y in range(256):
                        try:
                            block = chunk.get_block(local_x, y, local_z)
                            if block.id != 0 and block.id not in self._exclude_ids:
                                lowest_y = y
                                lowest_id = block.id
                                lowest_data = block.data
                                break
                        except Exception:
                            continue

                    if lowest_y is not None:
                        world_x = chunk_x * 16 + local_x
                        world_z = chunk_z * 16 + local_z
                        points.append({
                            'world_x': world_x,
                            'world_z': world_z,
                            'y': lowest_y,
                            'block_id': lowest_id,
                            'block_data': lowest_data,
                        })

        logger.debug(f"Completed lowest solid extraction: {chunk_count} chunks, {len(points)} matching points")

        return pd.DataFrame(points)
