"""
Minecraft map center computation and classification.

Understands Minecraft block semantics: a block at integer (x, z)
occupies [x, x+1) x [z, z+1).

Dependency tier: standalone (only uses numpy).
"""

import numpy as np
from typing import Dict, Tuple


def compute_map_center(layout_df) -> Tuple[float, float]:
    """Compute the geometric center of all blocks in the layout.

    Args:
        layout_df: DataFrame with world_x and world_z columns.

    Returns:
        (center_x, center_z) tuple.
    """
    x_col = 'world_x' if 'world_x' in layout_df.columns else 'x'
    z_col = 'world_z' if 'world_z' in layout_df.columns else 'z'

    min_x = layout_df[x_col].min()
    max_x = layout_df[x_col].max()
    min_z = layout_df[z_col].min()
    max_z = layout_df[z_col].max()

    return ((min_x + max_x + 1) / 2.0, (min_z + max_z + 1) / 2.0)


def classify_center(bbox: Tuple[float, float, float, float]) -> Dict:
    """Classify the geometric map center based on bounding box dimensions.

    The center type depends on whether each dimension spans an odd or even
    number of blocks:
        - odd x odd   -> single block center
        - even x odd  -> 2x1 center line (horizontal)
        - odd x even  -> 1x2 center line (vertical)
        - even x even -> 2x2 center area

    Returns dict with keys: center_x, center_z, type, description, blocks
    """
    min_x, max_x, min_z, max_z = bbox
    width_x = max_x - min_x
    width_z = max_z - min_z

    center_x = (min_x + max_x) / 2.0
    center_z = (min_z + max_z) / 2.0

    odd_x = (int(width_x) % 2 == 1)
    odd_z = (int(width_z) % 2 == 1)

    if odd_x and odd_z:
        center_type = "single_block"
        description = "Single block center"
        bx = int(center_x - 0.5)
        bz = int(center_z - 0.5)
        blocks = [(bx, bz)]
    elif not odd_x and odd_z:
        center_type = "2x1_line"
        description = "2x1 center line (along X axis)"
        bx1 = int(center_x - 1)
        bx2 = int(center_x)
        bz = int(center_z - 0.5)
        blocks = [(bx1, bz), (bx2, bz)]
    elif odd_x and not odd_z:
        center_type = "1x2_line"
        description = "1x2 center line (along Z axis)"
        bx = int(center_x - 0.5)
        bz1 = int(center_z - 1)
        bz2 = int(center_z)
        blocks = [(bx, bz1), (bx, bz2)]
    else:
        center_type = "2x2_area"
        description = "2x2 center area"
        bx1 = int(center_x - 1)
        bx2 = int(center_x)
        bz1 = int(center_z - 1)
        bz2 = int(center_z)
        blocks = [(bx1, bz1), (bx2, bz1), (bx1, bz2), (bx2, bz2)]

    return {
        "center_x": center_x,
        "center_z": center_z,
        "type": center_type,
        "description": description,
        "blocks": blocks,
        "map_width_x": int(width_x),
        "map_width_z": int(width_z),
    }


def classify_island_center(
    islands: list,
    map_center: Tuple[float, float],
) -> None:
    """Set has_center and distance_to_center on each island.

    An island only gets has_center=True if the geometric map center
    actually lies on the island -- i.e. at least one of the center
    block(s) is present in the island's block set.
    """
    if not islands:
        return

    cx, cz = map_center
    cx_is_half = (cx % 1 != 0)
    cz_is_half = (cz % 1 != 0)

    center_blocks = set()
    if cx_is_half and cz_is_half:
        center_blocks.add((int(cx - 0.5), int(cz - 0.5)))
    elif not cx_is_half and cz_is_half:
        bz = int(cz - 0.5)
        center_blocks.add((int(cx) - 1, bz))
        center_blocks.add((int(cx), bz))
    elif cx_is_half and not cz_is_half:
        bx = int(cx - 0.5)
        center_blocks.add((bx, int(cz) - 1))
        center_blocks.add((bx, int(cz)))
    else:
        for dx in (-1, 0):
            for dz in (-1, 0):
                center_blocks.add((int(cx) + dx, int(cz) + dz))

    for island in islands:
        cx_i, cz_i = island.center
        dist = np.sqrt((cx_i - map_center[0]) ** 2 + (cz_i - map_center[1]) ** 2)
        island.distance_to_center = float(dist)

        block_set = set(map(tuple, island.blocks))
        if center_blocks & block_set:
            island.has_center = True
