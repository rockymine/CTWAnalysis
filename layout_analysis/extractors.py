"""
Extraction modes for analyzing Minecraft world layouts.

Provides five extractors:
1. Y0LayerExtractor          - Extracts non-air blocks at world y=0
2. TopSurfaceExtractor       - Finds highest non-excluded non-air block in each column
3. VerticalDensityExtractor  - Filters columns by density metrics
4. LowestBedrockExtractor    - Finds lowest bedrock (block 7) in each column
5. LowestSolidLayerExtractor - Finds lowest non-excluded non-air block in each column

All extractors read Minecraft Anvil section data as NumPy arrays (one section read per
section_y rather than one get_block call per block), giving a large speedup for
full-column scans.
"""

import logging
from typing import Iterator, Literal
import numpy as np
import pandas as pd
from .region_reader import RegionReader

logger = logging.getLogger('ctw')


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _iter_chunk_sections(chunk) -> Iterator[tuple[int, np.ndarray, np.ndarray]]:
    """
    Yield ``(section_y, blocks_3d, data_3d)`` for every section in *chunk*.

    ``blocks_3d`` — ``(16, 16, 16)`` uint16 array, axis order **[y, z, x]**,
    containing block IDs (base Blocks byte + optional Add nibbles).

    ``data_3d``   — ``(16, 16, 16)`` uint8  array, same axis order,
    containing block damage/variant nibbles.

    Sections are yielded in ascending Y order.  Malformed or empty sections
    are silently skipped.
    """
    try:
        sections_nbt = chunk.data.get('Sections', [])
    except Exception:
        return

    parsed: list[tuple[int, np.ndarray, np.ndarray]] = []
    for sec in sections_nbt:
        try:
            y_raw = sec.get('Y')
            blocks_raw = sec.get('Blocks')
            data_raw = sec.get('Data')
            if y_raw is None or blocks_raw is None or data_raw is None:
                continue

            # NBT numeric tags expose their int value via .value
            y_val: int = y_raw.value if hasattr(y_raw, 'value') else int(y_raw)

            # Convert NBT byte arrays to plain bytes
            blocks_bytes = bytes(blocks_raw.value) if hasattr(blocks_raw, 'value') else bytes(blocks_raw)
            data_bytes = bytes(data_raw.value) if hasattr(data_raw, 'value') else bytes(data_raw)
            if len(blocks_bytes) != 4096 or len(data_bytes) != 2048:
                continue

            # Block IDs (base, one byte per block)
            blocks = np.frombuffer(blocks_bytes, dtype=np.uint8).astype(np.uint16)

            # Optional Add nibble array — extends block IDs beyond 255
            add_raw = sec.get('Add')
            if add_raw is not None:
                add_bytes = bytes(add_raw.value) if hasattr(add_raw, 'value') else bytes(add_raw)
                if len(add_bytes) == 2048:
                    add_packed = np.frombuffer(add_bytes, dtype=np.uint8)
                    add_nibbles = np.empty(4096, dtype=np.uint16)
                    add_nibbles[0::2] = add_packed & 0x0F
                    add_nibbles[1::2] = (add_packed >> 4) & 0x0F
                    blocks |= (add_nibbles << 8)

            # Data values: two nibbles per byte
            data_packed = np.frombuffer(data_bytes, dtype=np.uint8)
            data_nibbles = np.empty(4096, dtype=np.uint8)
            data_nibbles[0::2] = data_packed & 0x0F
            data_nibbles[1::2] = (data_packed >> 4) & 0x0F

            # Layout in memory: YZX order (index = y*256 + z*16 + x)
            blocks_3d = blocks.reshape(16, 16, 16)        # [y, z, x]
            data_3d = data_nibbles.reshape(16, 16, 16)    # [y, z, x]
            parsed.append((y_val, blocks_3d, data_3d))
        except Exception:
            continue

    for item in sorted(parsed, key=lambda t: t[0]):
        yield item


def _col_max_run(col: np.ndarray) -> int:
    """Maximum consecutive True run length in a 1-D boolean array."""
    if not np.any(col):
        return 0
    extended = np.concatenate([[False], col, [False]])
    diff = np.diff(extended.astype(np.int8))
    starts = np.where(diff == 1)[0]
    ends = np.where(diff == -1)[0]
    return int((ends - starts).max())


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------

class Y0LayerExtractor:
    """
    Extracts all non-air blocks at world y=0.

    Criterion: block_id != 0 at y=0
    """

    def __init__(self, region_reader: RegionReader) -> None:
        self.reader = region_reader

    def extract(self) -> pd.DataFrame:
        """
        Extract all non-air blocks at y=0.

        Returns:
            DataFrame with columns: world_x, world_z, block_id, block_data
        """
        all_wx: list[np.ndarray] = []
        all_wz: list[np.ndarray] = []
        all_id: list[np.ndarray] = []
        all_dt: list[np.ndarray] = []
        chunk_count = 0

        logger.debug("Extracting Y0 layer...")

        for chunk, chunk_x, chunk_z in self.reader.iter_chunks():
            chunk_count += 1
            if chunk_count % 100 == 0:
                n = sum(len(a) for a in all_wx)
                logger.debug(f"  Processed {chunk_count} chunks, found {n} points...")

            for section_y, blocks_3d, data_3d in _iter_chunk_sections(chunk):
                if section_y != 0:
                    continue  # y=0 is always in section 0
                # Local y=0 slice: shape (16, 16) [z, x]
                y0_blocks = blocks_3d[0]
                y0_data = data_3d[0]
                zz, xx = np.where(y0_blocks != 0)
                if len(zz):
                    all_wx.append((chunk_x * 16 + xx).astype(np.int32))
                    all_wz.append((chunk_z * 16 + zz).astype(np.int32))
                    all_id.append(y0_blocks[zz, xx].astype(np.uint16))
                    all_dt.append(y0_data[zz, xx])
                break  # Only need section 0

        total = sum(len(a) for a in all_wx)
        logger.debug(f"Completed Y0 extraction: {chunk_count} chunks, {total} matching points")

        if not all_wx:
            return pd.DataFrame(columns=['world_x', 'world_z', 'block_id', 'block_data'])
        return pd.DataFrame({
            'world_x': np.concatenate(all_wx),
            'world_z': np.concatenate(all_wz),
            'block_id': np.concatenate(all_id),
            'block_data': np.concatenate(all_dt),
        })


# ---------------------------------------------------------------------------
# Non-solid decorative block IDs excluded by TopSurfaceExtractor when
# skip_non_solid=True.  Water (8, 9) is intentionally omitted because water
# forms walkable surfaces (moats, traps) in CTW.
# ---------------------------------------------------------------------------
NON_SOLID_BLOCK_IDS: frozenset[int] = frozenset({
    6,    # sapling
    31,   # tall_grass (dead_bush variant=0, tall_grass variant=1, fern variant=2)
    32,   # dead_bush
    37,   # yellow_flower
    38,   # red_flower
    39,   # brown mushroom
    40,   # red mushroom
    50,   # torch
    55,   # redstone_wire
    59,   # crops
    63,   # sign_post
    65,   # ladder
    66,   # rails
    69,   # wall_sign
    69,   # lever
    70,   # STONE_PLATE
    71,   # IRON_DOOR_BLOCK
    72,   # WOOD_PLATE
    75,   # REDSTONE_TORCH_OFF
    76,   # REDSTONE_TORCH_ON
    77,   # stone_button
    78,   # SNOW
    83,   # SUGAR_CANE_BLOCK
    104,  # PUMPKIN_STEM
    105,  # MELON_STEM
    106,  # VINE
    115,  # NETHER_WARTS
    141,  # CARROT
    142,  # POTATO
    147,  # GOLD_PLATE
    148,  # IRON_PLATE
    143,  # wooden_button
    166,  # BARRIER
})


class TopSurfaceExtractor:
    """
    Finds the highest non-excluded non-air block in each column, optionally
    capped at a map's build height limit.

    Scans each column from y=255 downward and returns the first block whose
    ID is not air (0) and not in exclude_ids. When exclude_ids is non-empty
    this produces a "structural" surface that skips decoration blocks
    (e.g. leaves, tall grass, build-region markers).

    When skip_non_solid=True the extractor also skips the blocks listed in
    NON_SOLID_BLOCK_IDS (buttons, redstone wire, dead bushes, tall grass,
    flowers). Water (IDs 8 and 9) is never skipped — it is walkable in CTW.

    When max_build_height is set, blocks at y >= max_build_height are ignored
    entirely. This excludes decorative structures built above the playable
    ceiling (birds, tall trees, floating markers, observer islands) whose
    surface_y would otherwise eclipse the genuine navigable terrain below.

    Criterion: column contains at least one qualifying block below the height cap
    """

    def __init__(
        self,
        region_reader: RegionReader,
        exclude_ids: set[int] | None = None,
        skip_non_solid: bool = False,
        max_build_height: int | None = None,
    ) -> None:
        """
        Args:
            region_reader: RegionReader instance for the world
            exclude_ids: Block IDs to skip when searching top-down.
                         Air (0) is always excluded regardless of this set.
                         Pass an empty set or None for the raw top surface.
            skip_non_solid: When True, also exclude NON_SOLID_BLOCK_IDS
                            (buttons, redstone wire, dead bushes, tall grass,
                            flowers). Produces a cleaner surface_y for
                            height_above_terrain computation.
            max_build_height: When set, blocks at y >= this value are ignored.
                              Read from <maxBuildHeight> in map.xml.
        """
        self.reader = region_reader
        self._exclude_ids: set[int] = set(exclude_ids) if exclude_ids else set()
        if skip_non_solid:
            self._exclude_ids |= NON_SOLID_BLOCK_IDS
        self._max_build_height: int | None = max_build_height

    def extract(self) -> pd.DataFrame:
        """
        Extract the highest qualifying block in each column.

        Returns:
            DataFrame with columns: world_x, world_z, y, block_id, block_data
        """
        all_wx: list[np.ndarray] = []
        all_wz: list[np.ndarray] = []
        all_y:  list[np.ndarray] = []
        all_id: list[np.ndarray] = []
        all_dt: list[np.ndarray] = []
        chunk_count = 0

        logger.debug("Extracting top surface...")

        for chunk, chunk_x, chunk_z in self.reader.iter_chunks():
            chunk_count += 1
            if chunk_count % 100 == 0:
                n = sum(len(a) for a in all_wx)
                logger.debug(f"  Processed {chunk_count} chunks, found {n} points...")

            # found_y[z, x] — highest qualifying y found; -1 = not found yet
            found_y = np.full((16, 16), -1, dtype=np.int16)
            found_id = np.zeros((16, 16), dtype=np.uint16)
            found_dt = np.zeros((16, 16), dtype=np.uint8)

            # Collect sections sorted descending (top → bottom)
            sections = list(_iter_chunk_sections(chunk))
            sections.sort(key=lambda t: t[0], reverse=True)

            for section_y, blocks_3d, data_3d in sections:
                if np.all(found_y >= 0):
                    break  # All columns resolved

                # Skip sections entirely above the build height limit.
                # Blocks at y == max_build_height are included; only y > max_build_height
                # are excluded (players can stand on the top surface at max_build_height).
                if self._max_build_height is not None:
                    world_y_base = section_y * 16
                    if world_y_base > self._max_build_height:
                        continue

                # Solid mask: non-air and not excluded
                solid = blocks_3d != 0
                for exc in self._exclude_ids:
                    solid &= blocks_3d != exc

                # For sections that straddle the build height, zero out rows
                # above the limit. limit_local_y is the first local index to exclude
                # (local_y = max_build_height - section_y*16 + 1).
                if self._max_build_height is not None:
                    world_y_base = section_y * 16
                    limit_local_y = self._max_build_height - world_y_base + 1
                    if 0 < limit_local_y < 16:
                        solid[limit_local_y:] = False

                # Columns still unfound that have any qualifying block in this section
                not_found = found_y < 0                  # (16, 16)
                has_any = solid.any(axis=0)              # (16, 16)
                to_process = not_found & has_any

                if not np.any(to_process):
                    continue

                # Find the highest (largest local_y) qualifying block per column
                # solid[::-1] reverses so argmax finds the highest first
                solid_rev = solid[::-1]                          # [y_desc, z, x]
                argmax_rev = np.argmax(solid_rev, axis=0)        # (16, 16)
                highest_local_y = (15 - argmax_rev).astype(np.int16)

                zz, xx = np.where(to_process)
                local_ys = highest_local_y[zz, xx]
                world_ys = (section_y * 16 + local_ys).astype(np.int16)

                found_y[zz, xx] = world_ys
                found_id[zz, xx] = blocks_3d[local_ys, zz, xx]
                found_dt[zz, xx] = data_3d[local_ys, zz, xx]

            # Collect results for this chunk
            zz, xx = np.where(found_y >= 0)
            if len(zz):
                all_wx.append((chunk_x * 16 + xx).astype(np.int32))
                all_wz.append((chunk_z * 16 + zz).astype(np.int32))
                all_y.append(found_y[zz, xx])
                all_id.append(found_id[zz, xx])
                all_dt.append(found_dt[zz, xx])

        total = sum(len(a) for a in all_wx)
        logger.debug(f"Completed top surface extraction: {chunk_count} chunks, {total} matching points")

        if not all_wx:
            return pd.DataFrame(columns=['world_x', 'world_z', 'y', 'block_id', 'block_data'])
        return pd.DataFrame({
            'world_x': np.concatenate(all_wx),
            'world_z': np.concatenate(all_wz),
            'y': np.concatenate(all_y),
            'block_id': np.concatenate(all_id),
            'block_data': np.concatenate(all_dt),
        })


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
        mode: Literal['run', 'count'] = 'run',
    ) -> None:
        self.reader = region_reader
        self.threshold = threshold
        self.mode = mode

    def extract(self) -> pd.DataFrame:
        """
        Extract columns meeting the density threshold.

        Returns:
            DataFrame with columns: world_x, world_z, metric
        """
        all_wx: list[np.ndarray] = []
        all_wz: list[np.ndarray] = []
        all_m:  list[np.ndarray] = []
        chunk_count = 0

        logger.debug(f"Extracting vertical density (mode={self.mode}, threshold={self.threshold})...")

        for chunk, chunk_x, chunk_z in self.reader.iter_chunks():
            chunk_count += 1
            if chunk_count % 100 == 0:
                n = sum(len(a) for a in all_wx)
                logger.debug(f"  Processed {chunk_count} chunks, found {n} points...")

            # Build full (256, 16, 16) block array from all sections
            full_blocks = np.zeros((256, 16, 16), dtype=np.uint16)
            for section_y, blocks_3d, _ in _iter_chunk_sections(chunk):
                y_start = section_y * 16
                if 0 <= y_start < 256:
                    full_blocks[y_start:y_start + 16] = blocks_3d

            non_air = full_blocks != 0  # (256, 16, 16)

            if self.mode == 'count':
                metrics = np.sum(non_air, axis=0).astype(np.int32)   # (16, 16)
            else:  # 'run'
                # Compute max consecutive run per column (256 columns, 256 y-steps)
                flat = non_air.reshape(256, 256)  # [y, col]
                metrics = np.zeros(256, dtype=np.int32)
                for col_i in range(256):
                    metrics[col_i] = _col_max_run(flat[:, col_i])
                metrics = metrics.reshape(16, 16)

            # Filter by threshold
            mask = metrics >= self.threshold
            zz, xx = np.where(mask)
            if len(zz):
                all_wx.append((chunk_x * 16 + xx).astype(np.int32))
                all_wz.append((chunk_z * 16 + zz).astype(np.int32))
                all_m.append(metrics[zz, xx])

        total = sum(len(a) for a in all_wx)
        logger.debug(f"Completed density extraction: {chunk_count} chunks, {total} matching points")

        if not all_wx:
            return pd.DataFrame(columns=['world_x', 'world_z', 'metric'])
        return pd.DataFrame({
            'world_x': np.concatenate(all_wx),
            'world_z': np.concatenate(all_wz),
            'metric': np.concatenate(all_m),
        })


class LowestBedrockExtractor:
    """
    Finds the lowest bedrock block (block_id=7) in each column and the height
    of the consecutive stacked bedrock run from that lowest block upward.

    Criterion: column contains at least one bedrock block.
    Output columns: world_x, world_z, y (lowest bedrock), block_data, height (stacked count).
    """

    def __init__(self, region_reader: RegionReader) -> None:
        self.reader = region_reader

    def extract(self) -> pd.DataFrame:
        """
        Extract the lowest bedrock block in each column and the height of the
        consecutive stacked bedrock run starting from that lowest block.

        Returns:
            DataFrame with columns: world_x, world_z, y, block_data, height
            - y: world-y of the lowest bedrock block in the column
            - height: number of consecutive bedrock blocks stacked from y upward
              (e.g. height=5 means bedrock at y, y+1, y+2, y+3, y+4)
        """
        all_wx: list[np.ndarray] = []
        all_wz: list[np.ndarray] = []
        all_y:  list[np.ndarray] = []
        all_dt: list[np.ndarray] = []
        all_ht: list[np.ndarray] = []
        chunk_count = 0

        logger.debug("Extracting lowest bedrock blocks...")

        y_indices = np.arange(16, dtype=np.int16)  # (16,) reused each section

        for chunk, chunk_x, chunk_z in self.reader.iter_chunks():
            chunk_count += 1
            if chunk_count % 100 == 0:
                n = sum(len(a) for a in all_wx)
                logger.debug(f"  Processed {chunk_count} chunks, found {n} points...")

            found_y = np.full((16, 16), -1, dtype=np.int16)
            found_dt = np.zeros((16, 16), dtype=np.uint8)
            found_height = np.zeros((16, 16), dtype=np.int16)
            height_complete = np.zeros((16, 16), dtype=bool)

            for section_y, blocks_3d, data_3d in _iter_chunk_sections(chunk):
                bedrock_mask = blocks_3d == 7          # (16, 16, 16)
                not_found = found_y < 0                # (16, 16)
                has_any = bedrock_mask.any(axis=0)     # (16, 16)

                # --- Newly found columns: record lowest y and start height ---
                to_process = not_found & has_any
                if np.any(to_process):
                    first_y_local = np.argmax(bedrock_mask, axis=0)  # (16, 16)
                    zz, xx = np.where(to_process)
                    local_ys = first_y_local[zz, xx]

                    found_y[zz, xx] = (section_y * 16 + local_ys).astype(np.int16)
                    found_dt[zz, xx] = data_3d[local_ys, zz, xx]

                    # Vectorized height within this section: find first non-bedrock
                    # block at or above first_y_local for each newly-found column.
                    # y_above[y, z, x] = True if y >= first_y_local[z, x]
                    y_above = (y_indices[:, np.newaxis, np.newaxis]
                               >= first_y_local[np.newaxis, :, :])  # (16, 16, 16)
                    non_bedrock_above = ~bedrock_mask & y_above       # (16, 16, 16)
                    has_non_bedrock = non_bedrock_above.any(axis=0)   # (16, 16)
                    first_non_bedrock = np.argmax(non_bedrock_above, axis=0)  # (16, 16)

                    # height = gap to first non-bedrock; if none, run hits section top
                    section_height = np.where(
                        has_non_bedrock,
                        first_non_bedrock - first_y_local,
                        np.int16(16) - first_y_local,
                    )
                    found_height = np.where(to_process, section_height, found_height)
                    height_complete = height_complete | (to_process & has_non_bedrock)

                # --- Ongoing columns: bedrock run may continue from previous section ---
                ongoing = (found_y >= 0) & ~height_complete
                if np.any(ongoing):
                    starts_with_bedrock = bedrock_mask[0, :, :]      # (16, 16)
                    still_running = ongoing & starts_with_bedrock

                    if np.any(still_running):
                        # Find first non-bedrock from y=0 in this section
                        non_bedrock_from_zero = ~bedrock_mask         # (16, 16, 16)
                        has_non_bedrock_zero = non_bedrock_from_zero.any(axis=0)
                        first_non_bedrock_zero = np.argmax(non_bedrock_from_zero, axis=0)

                        height_ext = np.where(
                            has_non_bedrock_zero,
                            first_non_bedrock_zero,
                            np.int16(16),
                        )
                        found_height = np.where(
                            still_running,
                            found_height + height_ext,
                            found_height,
                        )
                        height_complete = (height_complete
                                           | (still_running & has_non_bedrock_zero))

                    # Columns whose run ended (bedrock stopped before this section)
                    height_complete = height_complete | (ongoing & ~starts_with_bedrock)

                # Break once all found columns have complete height info
                if np.all(found_y >= 0) and np.all(height_complete | (found_y < 0)):
                    break

            zz, xx = np.where(found_y >= 0)
            if len(zz):
                all_wx.append((chunk_x * 16 + xx).astype(np.int32))
                all_wz.append((chunk_z * 16 + zz).astype(np.int32))
                all_y.append(found_y[zz, xx])
                all_dt.append(found_dt[zz, xx])
                all_ht.append(found_height[zz, xx])

        total = sum(len(a) for a in all_wx)
        logger.debug(f"Completed lowest bedrock extraction: {chunk_count} chunks, {total} matching points")

        if not all_wx:
            return pd.DataFrame(columns=['world_x', 'world_z', 'y', 'block_data', 'height'])
        return pd.DataFrame({
            'world_x':   np.concatenate(all_wx),
            'world_z':   np.concatenate(all_wz),
            'y':         np.concatenate(all_y),
            'block_data': np.concatenate(all_dt),
            'height':    np.concatenate(all_ht),
        })


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
    ) -> None:
        """
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
        all_wx: list[np.ndarray] = []
        all_wz: list[np.ndarray] = []
        all_y:  list[np.ndarray] = []
        all_id: list[np.ndarray] = []
        all_dt: list[np.ndarray] = []
        chunk_count = 0

        logger.debug("Extracting lowest solid layer...")

        for chunk, chunk_x, chunk_z in self.reader.iter_chunks():
            chunk_count += 1
            if chunk_count % 100 == 0:
                n = sum(len(a) for a in all_wx)
                logger.debug(f"  Processed {chunk_count} chunks, found {n} points...")

            found_y = np.full((16, 16), -1, dtype=np.int16)
            found_id = np.zeros((16, 16), dtype=np.uint16)
            found_dt = np.zeros((16, 16), dtype=np.uint8)

            for section_y, blocks_3d, data_3d in _iter_chunk_sections(chunk):
                if np.all(found_y >= 0):
                    break

                # Solid mask: non-air and not in exclude set
                solid = blocks_3d != 0
                for exc in self._exclude_ids:
                    solid &= blocks_3d != exc

                not_found = found_y < 0               # (16, 16)
                has_any = solid.any(axis=0)            # (16, 16)
                to_process = not_found & has_any

                if not np.any(to_process):
                    continue

                # Lowest solid: first True along y axis (argmax on bool = first True)
                first_y = np.argmax(solid, axis=0)    # (16, 16)
                zz, xx = np.where(to_process)
                local_ys = first_y[zz, xx]

                found_y[zz, xx] = (section_y * 16 + local_ys).astype(np.int16)
                found_id[zz, xx] = blocks_3d[local_ys, zz, xx]
                found_dt[zz, xx] = data_3d[local_ys, zz, xx]

            zz, xx = np.where(found_y >= 0)
            if len(zz):
                all_wx.append((chunk_x * 16 + xx).astype(np.int32))
                all_wz.append((chunk_z * 16 + zz).astype(np.int32))
                all_y.append(found_y[zz, xx])
                all_id.append(found_id[zz, xx])
                all_dt.append(found_dt[zz, xx])

        total = sum(len(a) for a in all_wx)
        logger.debug(f"Completed lowest solid extraction: {chunk_count} chunks, {total} matching points")

        if not all_wx:
            return pd.DataFrame(columns=['world_x', 'world_z', 'y', 'block_id', 'block_data'])
        return pd.DataFrame({
            'world_x': np.concatenate(all_wx),
            'world_z': np.concatenate(all_wz),
            'y': np.concatenate(all_y),
            'block_id': np.concatenate(all_id),
            'block_data': np.concatenate(all_dt),
        })
