"""Match analysis visualizations.

Includes player trace maps, kill-death pair maps, and terrain height diagnostics.
"""

import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection
from matplotlib.path import Path as MplPath

from common.visualization import (
    draw_map_base,
    map_base_legend_handles,
    BuildRegionStyle,
    IslandOutlineStyle,
    POIStyle,
    NEUTRAL_COLOR,
    mc_color,
    distance_to_rgba,
)

from match_analysis.database.queries import extract_player_life_segments, get_match_player_ids


# Distinct colors for life segment traces
_SEGMENT_COLORS = [
    '#e6194b', '#3cb44b', '#4363d8', '#f58231', '#911eb4',
    '#42d4f4', '#f032e6', '#bfef45', '#fabed4', '#469990',
    '#dcbeff', '#9A6324', '#fffac8', '#800000', '#aaffc3',
    '#808000', '#ffd8b1', '#000075', '#a9a9a9',
]

# Match trace uses slightly lighter/thinner styles than connectivity viz
_BUILD_STYLE = BuildRegionStyle(fill_alpha=0.10)
_ISLAND_STYLE = IslandOutlineStyle()
_POI_STYLE = POIStyle(wool_marker='D', wool_size=80, zorder=2)

# Location type colors for --color-mode location
_LOCATION_COLORS = {
    'island': '#2ecc71',
    'build_region': '#f39c12',
    'void': '#e74c3c',
}


def _build_zone_color_map(n_nodes: int) -> dict[int, str]:
    """Return a stable dict mapping map_node_id -> hex color, cycling tab20."""
    import matplotlib.cm as cm
    cmap = cm.get_cmap('tab20', 20)
    return {
        node_id: '#{:02x}{:02x}{:02x}'.format(
            int(cmap(node_id % 20)[0] * 255),
            int(cmap(node_id % 20)[1] * 255),
            int(cmap(node_id % 20)[2] * 255),
        )
        for node_id in range(n_nodes)
    }


# Custom marker: tombstone (death)
# Rectangle body with arched top, traced as a single closed outline.
_TOMBSTONE = MplPath(
    [(-0.35, -0.5), (0.35, -0.5), (0.35, 0.15),      # base + right wall
     (0.35, 0.55), (0.0, 0.55),                        # arch right half (quadratic)
     (-0.35, 0.55), (-0.35, 0.15),                     # arch left half (quadratic)
     (-0.35, -0.5)],                                    # close
    [MplPath.MOVETO, MplPath.LINETO, MplPath.LINETO,
     MplPath.CURVE3, MplPath.CURVE3,
     MplPath.CURVE3, MplPath.CURVE3,
     MplPath.CLOSEPOLY],
)

# Custom marker: sword (kill)
# Pointed blade + crossguard + handle + pommel, single closed outline.
_SWORD = MplPath(
    [(0.0, 0.7),                                        # blade tip
     (0.15, 0.6), (0.15, 0.05),                        # right blade edge (wider)
     (0.35, 0.05), (0.35, -0.05),                      # crossguard right
     (0.12, -0.05), (0.12, -0.35),                     # right handle (thicker)
     (0.16, -0.35), (0.16, -0.45),                     # pommel right (wider)
     (-0.16, -0.45), (-0.16, -0.35),                   # pommel left
     (-0.12, -0.35), (-0.12, -0.05),                   # left handle
     (-0.35, -0.05), (-0.35, 0.05),                    # crossguard left
     (-0.15, 0.05), (-0.15, 0.6),                      # left blade edge
     (0.0, 0.7)],                                       # close
    [MplPath.MOVETO] + [MplPath.LINETO] * 16 + [MplPath.CLOSEPOLY],
)


def _resolve_team_color(
    spawn_x: float, spawn_z: float,
    classifier: 'PositionClassifier', map_context: dict,
) -> str:
    """Classify spawn position to determine team, return hex color."""
    team_hex = {t['id']: mc_color(t.get('color', ''), NEUTRAL_COLOR)
                for t in map_context.get('teams', [])}

    result = classifier.classify_position(spawn_x, spawn_z)
    island_id = result['island_id']
    if island_id is None:
        return NEUTRAL_COLOR

    for island in map_context.get('islands', []):
        if island['id'] == island_id:
            return team_hex.get(island.get('team'), NEUTRAL_COLOR)

    return NEUTRAL_COLOR


def plot_player_traces(
    map_context: dict,
    match_id: int,
    player_ids: list[int],
    output_path: Path,
    map_graph: dict | None = None,
    show_deaths: bool = True,
    show_kills: bool = True,
    show_wool: bool = True,
    show_edges: bool = True,
    show_legend: bool = True,
    show_stats: bool = True,
    show_title: bool = True,
    color_mode: str = 'life',
    map_base: str = 'outline',
    map_folder: Path | None = None,
    match_ids: list[int] | None = None,
) -> None:
    """Plot life segments for one or more players on the map base layer.

    Args:
        map_context: Parsed map_context.json dict.
        match_id: Match ID for single-match mode.
        player_ids: List of player IDs to visualize.
        output_path: Where to save the PNG.
        map_graph: Parsed map_graph.json dict (needed for
            color_mode 'team' or 'location').
        show_deaths: Draw death markers.
        show_kills: Draw kill markers.
        show_wool: Draw wool event markers.
        show_edges: Draw connecting lines (False = dots only).
        show_legend: Show the legend.
        show_stats: Show the stats text box.
        show_title: Show the title.
        color_mode: 'life' (per-segment), 'team' (by spawn team),
            or 'location' (by position type).
        map_base: 'outline' for polygon outlines, 'blocks' for individual
            block rendering from layout_bedrock.parquet.
        map_folder: Path to the map folder (required when map_base='blocks').
        match_ids: List of match IDs for overlay mode. When provided,
            all players from all listed matches are rendered on one plot.
    """
    output_path = Path(output_path)
    os.makedirs(output_path.parent, exist_ok=True)

    # Build classifier when needed
    classifier = None
    if color_mode in ('team', 'location') and map_graph is not None:
        from match_analysis.processing.position_classifier import PositionClassifier
        classifier = PositionClassifier(map_context, map_graph)

    # Build zone color map when needed (uses all nodes from map_graph)
    zone_color_map: dict[int, str] = {}
    if color_mode == 'zone' and map_graph is not None:
        n_nodes = len(map_graph.get('map_graph', {}).get('nodes', []))
        zone_color_map = _build_zone_color_map(max(n_nodes, 1))

    # Collect life segments across all requested players (and matches)
    overlay_mode = match_ids is not None and len(match_ids) > 0
    all_segments = []  # (player_id, seg_index, segment)
    all_player_ids = set()

    if overlay_mode:
        for mid in match_ids:
            pids = get_match_player_ids(mid)
            for pid in pids:
                segments = extract_player_life_segments(mid, pid)
                for i, seg in enumerate(segments):
                    all_segments.append((pid, i, seg))
                    all_player_ids.add(pid)
    else:
        for pid in player_ids:
            segments = extract_player_life_segments(match_id, pid)
            for i, seg in enumerate(segments):
                all_segments.append((pid, i, seg))
                all_player_ids.add(pid)

    if not all_segments:
        src = f"{len(match_ids)} matches" if overlay_mode else f"match {match_id}"
        print(f"No life segments found in {src}")
        return

    multi_player = len(all_player_ids) > 1 or overlay_mode

    # --- Figure setup ---
    fig, ax = plt.subplots(figsize=(16, 10))
    map_name = map_context.get('map_name', 'Unknown')

    mode_label = ''
    if color_mode == 'team':
        mode_label = ' [Team View]'
    elif color_mode == 'location':
        mode_label = ' [Location View]'
    elif color_mode == 'zone':
        mode_label = ' [Zone View]'

    if show_title:
        if overlay_mode:
            ax.set_title(
                f"{map_name} — {len(match_ids)} Matches "
                f"({len(all_segments)} lives, {len(all_player_ids)} players)"
                f"{mode_label}",
                fontsize=13, fontweight='bold',
            )
        elif multi_player:
            ax.set_title(
                f"{map_name} — {len(all_player_ids)} Players "
                f"({len(all_segments)} total lives){mode_label}\n"
                f"Match {match_id}",
                fontsize=13, fontweight='bold',
            )
        else:
            ax.set_title(
                f"{map_name} — Player {player_ids[0]} Traces "
                f"({len(all_segments)} lives){mode_label}\n"
                f"Match {match_id}",
                fontsize=13, fontweight='bold',
            )

    draw_map_base(ax, map_context,
                  build_style=_BUILD_STYLE,
                  island_style=_ISLAND_STYLE,
                  poi_style=_POI_STYLE,
                  map_base=map_base,
                  map_folder=map_folder)

    # Visual density adjustments for multi-player / overlay
    if overlay_mode:
        trace_alpha = 0.25
        trace_lw = 0.5
    elif multi_player:
        trace_alpha = 0.4
        trace_lw = 0.8
    else:
        trace_alpha = 0.8
        trace_lw = 1.5

    # --- Draw each life segment ---
    for global_idx, (pid, seg_i, seg) in enumerate(all_segments):
        # Determine segment-level color
        if color_mode == 'life':
            color = _SEGMENT_COLORS[global_idx % len(_SEGMENT_COLORS)]
        elif color_mode == 'team':
            if classifier is not None:
                color = _resolve_team_color(
                    seg['spawn_x'], seg['spawn_z'], classifier, map_context)
            else:
                color = NEUTRAL_COLOR
        else:  # location — segment color used only for markers
            color = _LOCATION_COLORS.get('island', NEUTRAL_COLOR)

        # Classify trace events for location coloring
        trace = seg['trace_events']
        enriched_df = None
        if classifier is not None and len(trace) > 0:
            enriched_df = classifier.classify_dataframe(trace)

        # For zone mode, use per-position nearest_graph_node from DB
        zone_pos_colors: list[str] = []
        if color_mode == 'zone' and zone_color_map:
            positions = seg['positions']
            if 'nearest_graph_node' in positions.columns:
                zone_pos_colors = [
                    zone_color_map.get(int(n), NEUTRAL_COLOR)
                    if n is not None and not (isinstance(n, float) and np.isnan(n))
                    else NEUTRAL_COLOR
                    for n in positions['nearest_graph_node']
                ]
        trace_xs = trace['x'].values
        trace_zs = trace['z'].values

        xs = np.concatenate([[seg['spawn_x']], trace_xs])
        zs = np.concatenate([[seg['spawn_z']], trace_zs])

        # --- Trace drawing ---
        if show_edges:
            if color_mode == 'location' and enriched_df is not None and len(xs) >= 2:
                # Per-segment coloring via LineCollection
                loc_types = ['island'] + enriched_df['location_type'].tolist()
                points = np.column_stack([xs, zs])
                line_segs = [[points[j], points[j + 1]] for j in range(len(points) - 1)]
                seg_colors = [_LOCATION_COLORS.get(loc_types[j + 1], '#95a5a6')
                              for j in range(len(line_segs))]
                lc = LineCollection(line_segs, colors=seg_colors,
                                    linewidths=trace_lw, alpha=trace_alpha, zorder=3)
                ax.add_collection(lc)
            elif color_mode == 'zone' and zone_pos_colors and len(zone_pos_colors) >= 2:
                # Zone mode: dots only (no connecting lines — zones may not be contiguous)
                pos = seg['positions']
                ax.scatter(pos['x'].values, pos['z'].values,
                           c=zone_pos_colors, s=4, alpha=trace_alpha, zorder=3)
            elif len(xs) >= 2:
                label = None
                if not multi_player:
                    label = (f"Life {seg_i + 1} ({seg['outcome']}, "
                             f"{len(seg['positions'])} pos)")
                elif seg_i == 0:
                    label = f"Player {pid}"
                ax.plot(xs, zs, color=color, linewidth=trace_lw,
                        alpha=trace_alpha, zorder=3, label=label)
        else:
            # --no-edges: small dots at each position
            if color_mode == 'location' and enriched_df is not None and len(trace) > 0:
                dot_colors = [_LOCATION_COLORS.get(lt, '#95a5a6')
                              for lt in enriched_df['location_type']]
                ax.scatter(trace_xs, trace_zs, c=dot_colors, s=4,
                           alpha=trace_alpha, zorder=3)
            elif color_mode == 'zone' and zone_pos_colors:
                pos = seg['positions']
                ax.scatter(pos['x'].values, pos['z'].values,
                           c=zone_pos_colors, s=4, alpha=trace_alpha, zorder=3)
            elif len(trace_xs) > 0:
                ax.scatter(trace_xs, trace_zs, c=color, s=4,
                           alpha=trace_alpha, zorder=3)

        # Spawn marker (always shown)
        ax.scatter(seg['spawn_x'], seg['spawn_z'],
                   marker='^', s=80, c=color,
                   edgecolors='black', linewidths=0.6, zorder=5)

        # Death marker (tombstone)
        positions = seg['positions']
        if show_deaths and seg['outcome'] == 'death' and len(positions) > 0:
            last = positions.iloc[-1]
            ax.scatter(last['x'], last['z'],
                       marker=_TOMBSTONE, s=120, c=color,
                       edgecolors='black', linewidths=0.5, zorder=5)

        # Kill markers (sword)
        if show_kills and len(seg['kills']) > 0:
            ax.scatter(seg['kills']['x'].values, seg['kills']['z'].values,
                       marker=_SWORD, s=140, c=color,
                       edgecolors='black', linewidths=0.5, zorder=4)

        # Wool event markers
        if show_wool and len(seg['wool_events']) > 0:
            ax.scatter(seg['wool_events']['x'].values,
                       seg['wool_events']['z'].values,
                       marker='D', s=60, c='gold',
                       edgecolors=color, linewidths=1, zorder=4)

    # --- Legend ---
    if show_legend:
        legend_handles = map_base_legend_handles(
            has_build_region=True,
            island_style=_ISLAND_STYLE,
            poi_style=_POI_STYLE,
            map_context=map_context,
        )
        legend_handles.append(
            plt.Line2D([0], [0], marker='^', color='w', markerfacecolor='gray',
                       markeredgecolor='black', markersize=8, label='Spawn'))
        if show_deaths:
            legend_handles.append(
                plt.Line2D([0], [0], marker=_TOMBSTONE, color='w',
                           markerfacecolor='gray', markeredgecolor='black',
                           markersize=10, label='Death'))
        if show_kills:
            legend_handles.append(
                plt.Line2D([0], [0], marker=_SWORD, color='w',
                           markerfacecolor='gray', markeredgecolor='black',
                           markersize=10, label='Kill'))
        if show_wool:
            legend_handles.append(
                plt.Line2D([0], [0], marker='D', color='w', markerfacecolor='gold',
                           markeredgecolor='gray', markersize=8, label='Wool event'))

        if color_mode == 'team':
            for team in map_context.get('teams', []):
                color = mc_color(team.get('color', ''), NEUTRAL_COLOR)
                name = (team.get('name') or team.get('id', '')).replace('-team', '').capitalize()
                legend_handles.append(
                    plt.Line2D([0], [0], color=color, linewidth=2,
                               label=f'{name} team'))
        elif color_mode == 'location':
            for loc_name, loc_hex in _LOCATION_COLORS.items():
                legend_handles.append(
                    plt.Line2D([0], [0], color=loc_hex, linewidth=2,
                               label=loc_name.replace('_', ' ').capitalize()))
        elif color_mode == 'zone':
            legend_handles.append(
                plt.Line2D([0], [0], color=NEUTRAL_COLOR, linewidth=2,
                           label='Color = nearest skeleton node'))

        ax.legend(handles=legend_handles, loc='upper right',
                  fontsize=8, framealpha=0.9)

    # --- Stats box ---
    if show_stats:
        total_pos = sum(len(s['positions']) for _, _, s in all_segments)
        total_kills = sum(len(s['kills']) for _, _, s in all_segments)
        total_duration = sum(s['end_time'] - s['start_time'] for _, _, s in all_segments)
        if overlay_mode:
            stats_text = (
                f"Matches: {len(match_ids)}  |  "
                f"Players: {len(all_player_ids)}  |  "
                f"Lives: {len(all_segments)}  |  Positions: {total_pos}  |  "
                f"Kills: {total_kills}  |  Total time: {total_duration:.0f}s"
            )
        elif multi_player:
            stats_text = (
                f"Players: {len(all_player_ids)}  |  "
                f"Lives: {len(all_segments)}  |  Positions: {total_pos}  |  "
                f"Kills: {total_kills}  |  Total time: {total_duration:.0f}s"
            )
        else:
            stats_text = (
                f"Lives: {len(all_segments)}  |  Positions: {total_pos}  |  "
                f"Kills: {total_kills}  |  Total time: {total_duration:.0f}s"
            )
        ax.text(
            0.02, 0.02, stats_text,
            transform=ax.transAxes, fontsize=9, fontfamily='monospace',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8),
            zorder=10,
        )

    ax.set_aspect('equal')
    ax.invert_yaxis()
    ax.tick_params(colors='#666666')
    for spine in ax.spines.values():
        spine.set_edgecolor('#cccccc')
    if show_title:
        ax.set_xlabel('X', color='#444444')
        ax.set_ylabel('Z', color='#444444')
    else:
        ax.axis('off')

    fig.savefig(str(output_path), dpi=200, bbox_inches='tight')
    plt.close(fig)
    print(f"Player trace plot saved to: {output_path}")


def _team_to_color(team: str) -> str:
    """Map a team name or ID to a display color via the shared Minecraft color system."""
    key = team.replace('-team', '').replace('team-', '').replace('team_', '')
    return mc_color(key, NEUTRAL_COLOR)


def plot_kill_death_pairs(
    map_context: dict,
    pairs_df: pd.DataFrame,
    output_path: Path,
    match_id: int | None = None,
    match_ids: list[int] | None = None,
    map_graph: dict | None = None,
    show_legend: bool = True,
    show_stats: bool = True,
    color_mode: str = 'team',
    map_base: str = 'outline',
    map_folder: Path | None = None,
) -> None:
    """Plot kill-death pairs as connected marker pairs on the map.

    Args:
        map_context: Parsed map_context.json dict.
        pairs_df: DataFrame from get_kill_death_pairs().
        output_path: Where to save the PNG.
        match_id: Single match ID (for title).
        match_ids: List of match IDs (for overlay title).
        map_graph: Parsed map_graph.json (needed for team color mode).
        show_legend: Show the legend.
        show_stats: Show the stats text box.
        color_mode: 'team' (color by killer team) or 'distance' (green-red gradient).
        map_base: 'outline' or 'blocks'.
        map_folder: Path to map folder (for blocks mode).
    """
    output_path = Path(output_path)
    os.makedirs(output_path.parent, exist_ok=True)

    if len(pairs_df) == 0:
        src = f"match {match_id}" if match_id else f"{len(match_ids)} matches"
        print(f"No kill-death pairs found in {src}")
        return

    n_pairs = len(pairs_df)
    overlay = match_ids is not None and len(match_ids) > 1

    # Compute distances
    dx = pairs_df['kill_x'].values - pairs_df['death_x'].values
    dz = pairs_df['kill_z'].values - pairs_df['death_z'].values
    distances = np.sqrt(dx.astype(float)**2 + dz.astype(float)**2)
    avg_dist = float(np.mean(distances))
    max_dist = float(np.max(distances))

    # Resolve colors per pair — team mode uses separate killer/victim colors
    if color_mode == 'team':
        killer_colors = [
            _team_to_color(t) if pd.notna(t) else NEUTRAL_COLOR
            for t in pairs_df['killer_team']
        ]
        victim_colors = [
            _team_to_color(t) if pd.notna(t) else NEUTRAL_COLOR
            for t in pairs_df['victim_team']
        ]
        line_colors = killer_colors  # lines colored by killer team
    else:  # distance
        dist_colors = [distance_to_rgba(d, max_dist) for d in distances]
        killer_colors = dist_colors
        victim_colors = dist_colors
        line_colors = dist_colors

    # Density-based alpha/linewidth
    if n_pairs > 500:
        line_alpha = 0.15
        line_lw = 0.4
        marker_alpha = 0.3
    elif n_pairs > 100:
        line_alpha = 0.3
        line_lw = 0.6
        marker_alpha = 0.5
    else:
        line_alpha = 0.6
        line_lw = 1.0
        marker_alpha = 0.8

    # --- Figure setup ---
    fig, ax = plt.subplots(figsize=(16, 10))
    map_name = map_context.get('map_name', 'Unknown')

    mode_label = ' [Team]' if color_mode == 'team' else ' [Distance]'
    if overlay:
        ax.set_title(
            f"{map_name} — {n_pairs} Kills across "
            f"{len(match_ids)} Matches{mode_label}",
            fontsize=13, fontweight='bold',
        )
    else:
        ax.set_title(
            f"{map_name} — {n_pairs} Kills (Match {match_id}){mode_label}",
            fontsize=13, fontweight='bold',
        )

    draw_map_base(ax, map_context,
                  build_style=_BUILD_STYLE,
                  island_style=_ISLAND_STYLE,
                  poi_style=_POI_STYLE,
                  map_base=map_base,
                  map_folder=map_folder)

    # --- Draw kill-death pairs ---
    kill_xs = pairs_df['kill_x'].values.astype(float)
    kill_zs = pairs_df['kill_z'].values.astype(float)
    death_xs = pairs_df['death_x'].values.astype(float)
    death_zs = pairs_df['death_z'].values.astype(float)

    # Connecting lines (colored by killer team or distance)
    line_segs = [[(kill_xs[i], kill_zs[i]), (death_xs[i], death_zs[i])]
                 for i in range(n_pairs)]
    lc = LineCollection(line_segs, colors=line_colors,
                        linewidths=line_lw, alpha=line_alpha, zorder=3)
    ax.add_collection(lc)

    # Sword markers at killer positions (killer's team color)
    ax.scatter(kill_xs, kill_zs, marker=_SWORD, s=100, c=killer_colors,
               edgecolors='black', linewidths=0.3, alpha=marker_alpha, zorder=4)

    # Tombstone markers at victim positions (victim's team color)
    ax.scatter(death_xs, death_zs, marker=_TOMBSTONE, s=80, c=victim_colors,
               edgecolors='black', linewidths=0.3, alpha=marker_alpha, zorder=4)

    # --- Legend ---
    if show_legend:
        legend_handles = map_base_legend_handles(
            has_build_region=True,
            island_style=_ISLAND_STYLE,
            poi_style=_POI_STYLE,
            map_context=map_context,
        )
        legend_handles.append(
            plt.Line2D([0], [0], marker=_SWORD, color='w',
                       markerfacecolor='gray', markeredgecolor='black',
                       markersize=10, label='Kill (killer pos)'))
        legend_handles.append(
            plt.Line2D([0], [0], marker=_TOMBSTONE, color='w',
                       markerfacecolor='gray', markeredgecolor='black',
                       markersize=10, label='Death (victim pos)'))
        legend_handles.append(
            plt.Line2D([0], [0], color='gray', linewidth=1,
                       alpha=0.5, label='Kill→Death line'))

        if color_mode == 'team':
            for team in map_context.get('teams', []):
                color = mc_color(team.get('color', ''), NEUTRAL_COLOR)
                name = (team.get('name') or team.get('id', '')).replace('-team', '').capitalize()
                legend_handles.append(
                    plt.Line2D([0], [0], color=color, linewidth=2,
                               label=f'{name} team'))
        else:  # distance
            legend_handles.append(
                plt.Line2D([0], [0], color='green', linewidth=2, label='Short range'))
            legend_handles.append(
                plt.Line2D([0], [0], color='red', linewidth=2, label='Long range'))

        ax.legend(handles=legend_handles, loc='upper right',
                  fontsize=8, framealpha=0.9)

    # --- Stats box ---
    if show_stats:
        n_matches = len(match_ids) if overlay else 1
        stats_parts = []
        if overlay:
            stats_parts.append(f"Matches: {n_matches}")
        stats_parts.extend([
            f"Kill pairs: {n_pairs}",
            f"Avg dist: {avg_dist:.1f}",
            f"Max dist: {max_dist:.1f}",
        ])
        stats_text = '  |  '.join(stats_parts)
        ax.text(
            0.02, 0.02, stats_text,
            transform=ax.transAxes, fontsize=9, fontfamily='monospace',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8),
            zorder=10,
        )

    ax.set_aspect('equal')
    ax.invert_yaxis()
    ax.tick_params(colors='#666666')
    for spine in ax.spines.values():
        spine.set_edgecolor('#cccccc')
    ax.set_xlabel('X', color='#444444')
    ax.set_ylabel('Z', color='#444444')

    fig.savefig(str(output_path), dpi=200, bbox_inches='tight')
    plt.close(fig)
    print(f"Kill-death pairs plot saved to: {output_path}")


# Re-export from terrain_height_plot so the package's visualization module
# is the canonical entry point for all match analysis visualizations.
from match_analysis.terrain_height_plot import plot_terrain_height
