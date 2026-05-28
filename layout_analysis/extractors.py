"""
Extraction modes for analyzing Minecraft world layouts.

Provides five extractors:
1. Y0LayerExtractor          - Extracts non-air blocks at world y=0
2. TopSurfaceExtractor       - Finds highest non-excluded non-air block in each column
3. LowestSolidExtractor      - Finds lowest non-excluded non-air block in each column
4. LowestBedrockExtractor    - Finds lowest bedrock (block 7) in each column
5. VerticalSegmentsExtractor - Finds all contiguous Y-ranges of solid blocks per column

All extractors read Minecraft Anvil section data as NumPy arrays (one section read per
section_y rather than one get_block call per block), giving a large speedup for
full-column scans.
"""

import logging
from typing import Iterator
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


def _build_full_blocks(chunk) -> np.ndarray:
    """Return a (256, 16, 16) uint16 block array populated from all sections in chunk."""
    full = np.zeros((256, 16, 16), dtype=np.uint16)
    for section_y, blocks_3d, _ in _iter_chunk_sections(chunk):
        y_start = section_y * 16
        if 0 <= y_start < 256:
            full[y_start:y_start + 16] = blocks_3d
    return full


def _build_exclude_lut(exclude: frozenset[int]) -> np.ndarray:
    """Return a 65536-element bool LUT where True means the block ID is excluded (air or in exclude)."""
    lut = np.zeros(65536, dtype=bool)
    lut[0] = True
    for i in exclude:
        lut[i] = True
    return lut


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

# Block IDs excluded by VerticalSegmentsExtractor (beyond NON_SOLID_BLOCK_IDS) when
# skip_non_solid=True. Block 36 (PISTON_MOVING_PIECE) is used by many CTW maps as an
# invisible build-region boundary marker and has no visible geometry.
_SEGMENTS_EXTRA_EXCLUDE: frozenset[int] = frozenset({36})


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
        self._max_build_height: int | None = max_build_height
        exclude: frozenset[int] = frozenset(exclude_ids) if exclude_ids else frozenset()
        if skip_non_solid:
            exclude = exclude | NON_SOLID_BLOCK_IDS
        self._exclude_lut = _build_exclude_lut(exclude)

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
                solid = ~self._exclude_lut[blocks_3d]

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


# Default block IDs excluded by LowestSolidExtractor.
# Block 36 (PISTON_MOVING_PIECE) is used by many maps as a build-region
# boundary marker and should never be treated as part of an island.
_DEFAULT_SOLID_EXCLUDE: frozenset[int] = frozenset({36})


class LowestSolidExtractor:
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
        exclude = frozenset(exclude_ids) if exclude_ids is not None else _DEFAULT_SOLID_EXCLUDE
        self._exclude_lut = _build_exclude_lut(exclude)

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
                solid = ~self._exclude_lut[blocks_3d]

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


class LowestBedrockExtractor:
    """
    Finds the lowest bedrock block (block_id=7) in each column.

    Implemented as a filtered view over LowestSolidExtractor: finds the lowest
    non-air block per column, then retains only columns where that block is bedrock.

    Criterion: column contains at least one bedrock block
    """

    def __init__(self, region_reader: RegionReader) -> None:
        self._inner = LowestSolidExtractor(region_reader, exclude_ids=set())

    def extract(self) -> pd.DataFrame:
        """
        Extract the lowest bedrock block in each column.

        Returns:
            DataFrame with columns: world_x, world_z, y, block_id, block_data
        """
        df = self._inner.extract()
        return df[df.block_id == 7].reset_index(drop=True)


class VerticalSegmentsExtractor:
    """
    Finds all contiguous Y-ranges of solid blocks in each column.

    For every (x, z) column, scans the full height (y=0..255) and records every
    unbroken run of non-excluded, non-air blocks as an interval [y_start, y_end]
    (both inclusive).  Returns one row per run, so a column with a bedrock floor
    and an elevated platform yields two rows.

    This is the building block for side-profile / cross-section rendering: a
    renderer can draw a filled rectangle from y_start to y_end for each row
    without needing to know what is in the air gaps between runs.

    Uses _build_full_blocks internally, extracting interval boundaries per column.

    Criterion: at least one qualifying block exists anywhere in the column
    """

    def __init__(
        self,
        region_reader: RegionReader,
        exclude_ids: set[int] | None = None,
        skip_non_solid: bool = True,
        min_run_length: int = 1,
    ) -> None:
        """
        Args:
            region_reader: RegionReader instance for the world.
            exclude_ids: Additional block IDs to treat as air on top of whatever
                         skip_non_solid applies.  Air (0) is always excluded.
            skip_non_solid: When True (default), also excludes NON_SOLID_BLOCK_IDS
                            (buttons, pressure plates, redstone wire, tall grass,
                            signs, rails, torches, vines, flowers, etc.) plus block 36
                            (PISTON_MOVING_PIECE — invisible build-region marker).
                            Pass False for a raw, unfiltered column profile.
            min_run_length: Skip solid runs shorter than this many blocks.
                            Default 1 includes every single-block layer.
        """
        self.reader = region_reader
        exclude: frozenset[int] = frozenset(exclude_ids) if exclude_ids else frozenset()
        if skip_non_solid:
            exclude = exclude | NON_SOLID_BLOCK_IDS | _SEGMENTS_EXTRA_EXCLUDE
        self._exclude_lut = _build_exclude_lut(exclude)
        self.min_run_length = min_run_length

    def extract(self) -> pd.DataFrame:
        """
        Extract all contiguous solid Y-ranges in each column.

        Returns:
            DataFrame with columns: world_x, world_z, y_start, y_end
            y_start and y_end are both inclusive world Y coordinates.
            Sorted by (world_x, world_z, y_start).
        """
        all_wx:  list[np.ndarray] = []
        all_wz:  list[np.ndarray] = []
        all_ys:  list[np.ndarray] = []
        all_ye:  list[np.ndarray] = []
        chunk_count = 0

        logger.debug("Extracting vertical segments...")

        for chunk, chunk_x, chunk_z in self.reader.iter_chunks():
            chunk_count += 1
            if chunk_count % 100 == 0:
                n = sum(len(a) for a in all_wx)
                logger.debug(f"  Processed {chunk_count} chunks, found {n} runs...")

            full_blocks = _build_full_blocks(chunk)          # (256, 16, 16) uint16

            solid = ~self._exclude_lut[full_blocks]          # (256, 16, 16) bool

            # Flatten to (256, 256): axis-1 col index = z*16 + x (C-order)
            flat = solid.reshape(256, 256)

            # Pad False rows at both ends so np.diff captures edge transitions
            padded = np.zeros((258, 256), dtype=bool)
            padded[1:257] = flat
            d = np.diff(padded.view(np.int8), axis=0)  # (257, 256)

            starts = np.argwhere(d == 1)   # [y_idx, col_idx] — y_idx = y_start
            ends   = np.argwhere(d == -1)  # [y_idx, col_idx] — y_idx = exclusive y_end

            if len(starts) == 0:
                continue

            # Sort by (col, y) so that starts[i] and ends[i] correspond to the same run
            order_s = np.lexsort((starts[:, 0], starts[:, 1]))
            order_e = np.lexsort((ends[:, 0],   ends[:, 1]))
            starts = starts[order_s]
            ends   = ends[order_e]

            y_start = starts[:, 0].astype(np.int16)
            y_end   = (ends[:, 0] - 1).astype(np.int16)  # make inclusive
            col_idx = starts[:, 1]

            if self.min_run_length > 1:
                keep = (y_end - y_start + 1) >= self.min_run_length
                y_start = y_start[keep]
                y_end   = y_end[keep]
                col_idx = col_idx[keep]

            if len(y_start) == 0:
                continue

            x_local = (col_idx % 16).astype(np.int32)
            z_local = (col_idx // 16).astype(np.int32)
            all_wx.append((chunk_x * 16 + x_local).astype(np.int32))
            all_wz.append((chunk_z * 16 + z_local).astype(np.int32))
            all_ys.append(y_start)
            all_ye.append(y_end)

        total = sum(len(a) for a in all_wx)
        logger.debug(f"Completed vertical segments extraction: {chunk_count} chunks, {total} runs")

        if not all_wx:
            return pd.DataFrame(columns=['world_x', 'world_z', 'y_start', 'y_end'])
        return pd.DataFrame({
            'world_x': np.concatenate(all_wx),
            'world_z': np.concatenate(all_wz),
            'y_start': np.concatenate(all_ys),
            'y_end':   np.concatenate(all_ye),
        })
