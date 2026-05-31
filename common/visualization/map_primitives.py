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

from .colors import (
    NEUTRAL_COLOR,
    DARK_THEME_BG, MINECRAFT_COLORS, mc_color,
)
from .block_colors import block_color
from common.geometry import blocks_to_unit_squares


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
    exterior_linewidth: float = 0.5
    exterior_alpha: float = 0.9
    hole_linewidth: float = 0.5
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

    # Build team_id → hex from map_context.teams (reliable source for any team naming)
    team_hex = {
        t['id']: mc_color(t.get('color', ''), NEUTRAL_COLOR)
        for t in map_context.get('teams', [])
    }

    # Build island_id → color mapping
    color_map: Dict[int, str] = {0: '#d1d5db'}  # island_id 0 = unassigned/background
    for island in map_context.get('islands', []):
        iid = island['id']
        color_map[iid] = team_hex.get(island.get('team'), NEUTRAL_COLOR)

    # Build 1×1 unit square vertices for each block
    xs = df['world_x'].values
    zs = df['world_z'].values
    squares = blocks_to_unit_squares(xs, zs)  # shape (N, 4, 2)

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
) -> None:
    """Draw island polygon outlines (exterior + holes) colored by team."""
    if style is None:
        style = IslandOutlineStyle()

    team_hex = {
        t['id']: mc_color(t.get('color', ''), NEUTRAL_COLOR)
        for t in map_context.get('teams', [])
    }

    for island in map_context.get('islands', []):
        poly = island.get('simplified_polygon')
        if poly is None:
            continue

        color = team_hex.get(island.get('team'), NEUTRAL_COLOR)

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
        color = mc_color(team_color, mc_color('red'))
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
            c=mc_color(wool.get('wool_color', ''), NEUTRAL_COLOR),
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


def draw_layout_image(
    ax,
    df: pd.DataFrame,
    default_block_id: int = 0,
) -> None:
    """Render a layout parquet DataFrame as block-coloured unit squares.

    Each block at index (world_x, world_z) is drawn as a filled 1×1 polygon
    covering [x, x+1] × [z, z+1] in world space, using PolyCollection for
    geometrically correct rendering at any zoom level or DPI.

    Axis setup follows the project world-space convention: equal aspect ratio
    with z increasing downward (ax.axis('equal') + ax.invert_yaxis()).

    Args:
        ax: Matplotlib axes.
        df: DataFrame with columns world_x, world_z and optionally block_id,
            block_data (as stored in layout_*.parquet files).
        default_block_id: Block ID to use when the DataFrame has no block_id
            column (e.g. 7 for bedrock-only layers).
    """
    if df is None or df.empty:
        return

    xs = df['world_x'].values.astype(int)
    zs = df['world_z'].values.astype(int)
    data_col = (df['block_data'].values.astype(int)
                if 'block_data' in df.columns else np.zeros(len(df), dtype=int))
    ids = (df['block_id'].values.astype(int)
           if 'block_id' in df.columns
           else np.full(len(df), default_block_id, dtype=int))

    squares = blocks_to_unit_squares(xs, zs)  # (N, 4, 2)
    facecolors = np.array(
        [block_color(int(bid), int(dat)) for bid, dat in zip(ids, data_col)],
        dtype=np.float32,
    ) / 255.0

    pc = PolyCollection(squares, facecolors=facecolors, edgecolors='none', linewidths=0,
                        antialiased=False)
    ax.add_collection(pc)
    ax.set_xlim(int(xs.min()), int(xs.max()) + 1)
    ax.set_ylim(int(zs.min()), int(zs.max()) + 1)
    ax.axis('equal')
    ax.invert_yaxis()


def map_base_legend_handles(
    has_build_region: bool = True,
    island_style: Optional[IslandOutlineStyle] = None,
    poi_style: Optional[POIStyle] = None,
    map_context: Optional[dict] = None,
) -> list:
    """Return legend handles for the map base layers.

    When map_context is provided, team island and spawn entries are generated
    from the actual map data. Consumers can extend the returned list with their
    own domain-specific handles.
    """
    if island_style is None:
        island_style = IslandOutlineStyle()
    if poi_style is None:
        poi_style = POIStyle()

    handles = []
    if has_build_region:
        _br = BuildRegionStyle()
        handles.append(
            mpatches.Patch(facecolor=_br.facecolor, alpha=_br.fill_alpha, label='Buildable void')
        )

    if map_context:
        # Island outline entry per team
        for team in map_context.get('teams', []):
            color = mc_color(team.get('color', ''), NEUTRAL_COLOR)
            label = (team.get('name') or team.get('id', 'Unknown')).title()
            handles.append(plt.Line2D(
                [0], [0], color=color,
                linewidth=island_style.exterior_linewidth,
                label=f'{label} island',
            ))
        handles.append(plt.Line2D(
            [0], [0], color=NEUTRAL_COLOR,
            linewidth=island_style.exterior_linewidth, label='Neutral island',
        ))

        # One spawn entry per distinct team_color in the data
        seen: Dict[str, str] = {}  # team_color → team name
        for spawn in map_context.get('poi_assignments', {}).get('spawns', []):
            tc = spawn.get('team_color', '')
            if tc and tc not in seen:
                team_name = (spawn.get('team') or tc).replace('-team', '').replace('_team', '').title()
                seen[tc] = team_name
        for tc, team_name in seen.items():
            handles.append(plt.Line2D(
                [0], [0], marker=poi_style.spawn_marker, color='w',
                markerfacecolor=mc_color(tc), markersize=12,
                label=f'Spawn ({team_name})',
            ))
    else:
        handles += [
            plt.Line2D([0], [0], color=mc_color('blue'),
                       linewidth=island_style.exterior_linewidth, label='Blue island'),
            plt.Line2D([0], [0], color=mc_color('red'),
                       linewidth=island_style.exterior_linewidth, label='Red island'),
            plt.Line2D([0], [0], color=NEUTRAL_COLOR,
                       linewidth=island_style.exterior_linewidth, label='Neutral island'),
        ]

    # Wool objectives — one generic entry; actual markers are colored per wool_color
    handles.append(plt.Line2D(
        [0], [0], marker=poi_style.wool_marker, color='w',
        markerfacecolor=mc_color('yellow'), markeredgecolor='black',
        markersize=8, label='Wool objective',
    ))
    return handles


# ── Dark-theme helpers (used by traffic / graph visualizations) ──────────────


def style_dark_ax(
    ax,
    xmin: Optional[float] = None,
    xmax: Optional[float] = None,
    zmin: Optional[float] = None,
    zmax: Optional[float] = None,
    title: str = "",
    xlabel: str = "",
    ylabel: str = "",
) -> None:
    """Apply shared dark-theme styling to an axis.

    When xmin/xmax/zmin/zmax are provided, sets axis limits with Z inverted
    (north-up convention) and enforces equal aspect ratio.
    """
    ax.set_facecolor(DARK_THEME_BG)
    if xmin is not None:
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(zmax, zmin)
        ax.set_aspect("equal")
    ax.tick_params(colors="#555555", labelsize=6)
    for spine in ax.spines.values():
        spine.set_edgecolor("#333333")
    if title:
        ax.set_title(title, color="#cccccc", fontsize=8, pad=4)
    if xlabel:
        ax.set_xlabel(xlabel, color="#aaaaaa", fontsize=7)
    if ylabel:
        ax.set_ylabel(ylabel, color="#aaaaaa", fontsize=7)


def draw_dark_island_polygons(
    ax,
    map_context: dict,
    alpha: float = 0.12,
    fallback_color: str = "#3a3a5a",
) -> None:
    """Draw island polygon fills using Minecraft team colors on a dark background."""
    import matplotlib.patches as _mpatches

    team_hex: Dict[str, str] = {}
    for team in map_context.get("teams", []):
        tid = team.get("id", "")
        raw = team.get("color", "")
        team_hex[tid] = mc_color(raw, fallback_color)

    for isl in map_context.get("islands", []):
        pts = (isl.get("simplified_polygon") or {}).get("exterior", [])
        if not pts:
            continue
        isl_t = isl.get("team")
        fc = team_hex.get(isl_t, fallback_color)
        a = alpha if isl_t else alpha * 0.5
        patch = _mpatches.Polygon(
            np.array(pts), closed=True,
            facecolor=fc, edgecolor=fc,
            linewidth=0.3, alpha=a, zorder=0,
        )
        ax.add_patch(patch)


def draw_dark_graph_background(
    ax,
    node_info: dict,
    G_full,
    map_context: Optional[dict] = None,
    node_alpha: float = 0.14,
    edge_alpha: float = 0.14,
    xlim: Optional[tuple] = None,
    zlim: Optional[tuple] = None,
) -> None:
    """Draw a traffic graph as a faint background context layer (dark theme).

    Island polygon fills are drawn first if map_context is provided.
    When xlim/zlim are given, only nodes/edges whose source falls within the
    bounding box are rendered — useful for zoomed-in panels.
    """
    if map_context:
        draw_dark_island_polygons(ax, map_context)

    xlo, xhi = xlim if xlim else (None, None)
    zlo, zhi = zlim if zlim else (None, None)

    for u, v in G_full.edges():
        sn = node_info.get(u)
        dn = node_info.get(v)
        if sn is None or dn is None:
            continue
        sc, dc = sn["coords"], dn["coords"]
        if xlo is not None and not (xlo <= sc[0] <= xhi and zlo <= sc[1] <= zhi):
            continue
        ax.plot([sc[0], dc[0]], [sc[1], dc[1]],
                color="#445566", lw=0.5, alpha=edge_alpha, zorder=1)

    if xlo is not None:
        vis_coords = [
            n["coords"] for n in node_info.values()
            if xlo <= n["coords"][0] <= xhi and zlo <= n["coords"][1] <= zhi
        ]
    else:
        vis_coords = [n["coords"] for n in node_info.values()]

    if vis_coords:
        arr = np.array(vis_coords)
        ax.scatter(arr[:, 0], arr[:, 1],
                   s=4, color="#5577aa", alpha=node_alpha,
                   linewidths=0, zorder=2)
