"""Map-level drawing primitives for CTW visualizations.

Shared functions for rendering build regions, island polygon outlines,
and POI markers from map_context.json data onto matplotlib Axes.

Style parameters have defaults matching the connectivity visualization;
callers can override individual values via style dataclasses.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import PolyCollection

from .colors import TEAM_COLORS, NEUTRAL_COLOR, WOOL_COLOR, SPAWN_COLORS


# ── Style dataclasses ────────────────────────────────────────────────


@dataclass(frozen=True)
class BuildRegionStyle:
    """Style parameters for build region (buildable_void) polygons."""
    facecolor: str = '#22c55e'
    fill_alpha: float = 0.12
    edgecolor: str = '#16a34a'
    linewidth: float = 0.5
    zorder: int = 0


@dataclass(frozen=True)
class IslandOutlineStyle:
    """Style parameters for island polygon outlines."""
    exterior_linewidth: float = 2.0
    exterior_alpha: float = 0.9
    hole_linewidth: float = 1.5
    hole_alpha: float = 0.7
    zorder: int = 1


@dataclass(frozen=True)
class POIStyle:
    """Style parameters for POI markers (spawns and wools)."""
    spawn_marker: str = '*'
    spawn_size: float = 200
    spawn_edge_color: str = 'black'
    spawn_edge_width: float = 0.6
    wool_marker: str = '*'
    wool_size: float = 150
    wool_color: str = WOOL_COLOR
    wool_edge_color: str = 'black'
    wool_edge_width: float = 0.6
    zorder: int = 8


@dataclass(frozen=True)
class BlockBaseStyle:
    """Style parameters for block-level base layer rendering."""
    fill_alpha: float = 0.15
    edge_alpha: float = 0.3
    edgecolor: str = '#9ca3af'
    linewidth: float = 0.3
    zorder: int = 0


# Island-id → color mapping for block base layer.
# Matches the team colors used elsewhere; neutral islands get gray tones.
_ISLAND_BLOCK_COLORS = {
    0: '#d1d5db',    # unassigned / background
}


# ── Drawing functions ────────────────────────────────────────────────


def draw_build_region(
    ax,
    map_context: dict,
    style: Optional[BuildRegionStyle] = None,
) -> bool:
    """Draw buildable void polygons (green overlay with holes cut out).

    Returns True if a build region was drawn, False otherwise.
    """
    if style is None:
        style = BuildRegionStyle()

    build_region = map_context.get('build_region')
    if not build_region:
        return False

    for poly_coords in build_region.get('buildable_void', []):
        exterior = np.array(poly_coords['exterior'])
        if len(exterior) >= 3:
            ax.fill(
                exterior[:, 0], exterior[:, 1],
                facecolor=style.facecolor,
                alpha=style.fill_alpha,
                edgecolor=style.edgecolor,
                linewidth=style.linewidth,
                zorder=style.zorder,
            )
            for hole in poly_coords.get('holes', []):
                h = np.array(hole)
                if len(h) >= 3:
                    ax.fill(
                        h[:, 0], h[:, 1],
                        facecolor='white', alpha=1.0,
                        zorder=style.zorder,
                    )
    return True


def draw_block_base(
    ax,
    map_folder: Path,
    map_context: dict,
    style: Optional[BlockBaseStyle] = None,
) -> None:
    """Draw individual blocks from layout_bedrock.parquet, colored by island.

    Blocks are colored using their island's team color (from map_context).
    Unassigned blocks (island_id 0) are drawn in light gray.

    Args:
        ax: Matplotlib axes.
        map_folder: Path to the map folder containing layout_bedrock.parquet.
        map_context: Parsed map_context.json (used for island→team mapping).
        style: Visual style overrides.
    """
    if style is None:
        style = BlockBaseStyle()

    parquet_path = Path(map_folder) / 'layout_bedrock.parquet'
    if not parquet_path.exists():
        return

    df = pd.read_parquet(parquet_path, columns=['world_x', 'world_z', 'island_id'])

    # Build island_id → color mapping from map_context team data
    color_map = dict(_ISLAND_BLOCK_COLORS)
    for island in map_context.get('islands', []):
        iid = island['id']
        team = island.get('team')
        color_map[iid] = TEAM_COLORS.get(team, NEUTRAL_COLOR)

    # Build 1×1 unit square vertices for each block
    xs = df['world_x'].values
    zs = df['world_z'].values
    squares = np.stack([
        np.column_stack([xs,       zs]),
        np.column_stack([xs + 1,   zs]),
        np.column_stack([xs + 1,   zs + 1]),
        np.column_stack([xs,       zs + 1]),
    ], axis=1)  # shape (N, 4, 2)

    facecolors = [color_map.get(iid, NEUTRAL_COLOR) for iid in df['island_id']]

    pc = PolyCollection(
        squares,
        facecolors=facecolors,
        edgecolors=style.edgecolor,
        alpha=style.fill_alpha,
        linewidths=style.linewidth,
        zorder=style.zorder,
    )
    ax.add_collection(pc)


def draw_island_outlines(
    ax,
    map_context: dict,
    style: Optional[IslandOutlineStyle] = None,
    team_colors: Optional[Dict[str, str]] = None,
    neutral_color: Optional[str] = None,
) -> None:
    """Draw island polygon outlines (exterior + holes) with team colors."""
    if style is None:
        style = IslandOutlineStyle()
    if team_colors is None:
        team_colors = TEAM_COLORS
    if neutral_color is None:
        neutral_color = NEUTRAL_COLOR

    for island in map_context.get('islands', []):
        poly = island.get('simplified_polygon')
        if poly is None:
            continue

        team = island.get('team')
        color = team_colors.get(team, neutral_color)

        exterior = np.array(poly['exterior'])
        if len(exterior) < 3:
            continue

        ax.plot(
            exterior[:, 0], exterior[:, 1],
            color=color,
            linewidth=style.exterior_linewidth,
            alpha=style.exterior_alpha,
            zorder=style.zorder,
        )
        for hole_coords in poly.get('holes', []):
            hole = np.array(hole_coords)
            if len(hole) >= 3:
                ax.plot(
                    hole[:, 0], hole[:, 1],
                    color=color,
                    linewidth=style.hole_linewidth,
                    alpha=style.hole_alpha,
                    zorder=style.zorder,
                )


def draw_pois(
    ax,
    map_context: dict,
    style: Optional[POIStyle] = None,
) -> None:
    """Draw POI markers (team spawns and wool objectives)."""
    if style is None:
        style = POIStyle()

    poi_assignments = map_context.get('poi_assignments', {})

    for spawn in poi_assignments.get('spawns', []):
        team_color = spawn.get('team_color', '')
        color = SPAWN_COLORS.get(team_color, SPAWN_COLORS.get('red'))
        ax.scatter(
            spawn['x'], spawn['z'],
            marker=style.spawn_marker,
            s=style.spawn_size,
            c=color,
            edgecolors=style.spawn_edge_color,
            linewidths=style.spawn_edge_width,
            zorder=style.zorder,
        )

    for wool in poi_assignments.get('wools', []):
        ax.scatter(
            wool['x'], wool['z'],
            marker=style.wool_marker,
            s=style.wool_size,
            c=style.wool_color,
            edgecolors=style.wool_edge_color,
            linewidths=style.wool_edge_width,
            zorder=style.zorder,
        )


def draw_map_base(
    ax,
    map_context: dict,
    build_style: Optional[BuildRegionStyle] = None,
    island_style: Optional[IslandOutlineStyle] = None,
    poi_style: Optional[POIStyle] = None,
    map_base: str = 'outline',
    map_folder: Optional[Path] = None,
    block_style: Optional[BlockBaseStyle] = None,
) -> bool:
    """Convenience wrapper: draw all map base layers.

    Args:
        map_base: 'outline' for polygon outlines (default), or 'blocks'
            for individual block rendering from layout_bedrock.parquet.
        map_folder: Required when map_base='blocks'. Path to the map folder.
        block_style: Style overrides for block rendering.

    Returns True if a build region was drawn (useful for legend construction).
    """
    has_build = draw_build_region(ax, map_context, style=build_style)

    if map_base == 'blocks' and map_folder is not None:
        draw_block_base(ax, map_folder, map_context, style=block_style)
    else:
        draw_island_outlines(ax, map_context, style=island_style)

    draw_pois(ax, map_context, style=poi_style)
    return has_build


def map_base_legend_handles(
    has_build_region: bool = True,
    island_style: Optional[IslandOutlineStyle] = None,
    poi_style: Optional[POIStyle] = None,
) -> list:
    """Return standard legend handles for the map base layers.

    Consumers can extend this list with their own domain-specific handles.
    """
    if island_style is None:
        island_style = IslandOutlineStyle()
    if poi_style is None:
        poi_style = POIStyle()

    handles = []
    if has_build_region:
        handles.append(
            mpatches.Patch(facecolor='#22c55e', alpha=0.15, label='Buildable void')
        )
    handles += [
        plt.Line2D([0], [0], color=TEAM_COLORS['blue'],
                   linewidth=island_style.exterior_linewidth, label='Blue team island'),
        plt.Line2D([0], [0], color=TEAM_COLORS['red'],
                   linewidth=island_style.exterior_linewidth, label='Red team island'),
        plt.Line2D([0], [0], color=NEUTRAL_COLOR,
                   linewidth=island_style.exterior_linewidth, label='Neutral island'),
        plt.Line2D([0], [0], marker=poi_style.spawn_marker, color='w',
                   markerfacecolor=SPAWN_COLORS['blue'],
                   markersize=12, label='Spawn (blue)'),
        plt.Line2D([0], [0], marker=poi_style.spawn_marker, color='w',
                   markerfacecolor=SPAWN_COLORS['red'],
                   markersize=12, label='Spawn (red)'),
        plt.Line2D([0], [0], marker=poi_style.wool_marker, color='w',
                   markerfacecolor=WOOL_COLOR,
                   markeredgecolor='black',
                   markersize=8, label='Wool'),
    ]
    return handles
