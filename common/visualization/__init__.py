"""Shared visualization primitives for CTW map analysis."""

from .colors import TEAM_COLORS, NEUTRAL_COLOR, WOOL_COLOR, SPAWN_COLORS
from .block_colors import block_color
from .map_primitives import (
    BlockBaseStyle,
    BuildRegionStyle,
    IslandOutlineStyle,
    POIStyle,
    draw_block_base,
    draw_build_region,
    draw_island_outlines,
    draw_layout_image,
    draw_pois,
    draw_map_base,
    map_base_legend_handles,
)
