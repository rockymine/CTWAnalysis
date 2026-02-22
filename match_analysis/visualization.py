"""Player trace visualization on map base layer.

Renders life segments (position traces) for one or more players on top
of a simplified map showing build region, island outlines, and POI markers.
"""

import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection
from matplotlib.path import Path as MplPath

from visualization import (
    draw_map_base,
    map_base_legend_handles,
    BuildRegionStyle,
    IslandOutlineStyle,
    POIStyle,
)

from match_analysis.match_queries import extract_player_life_segments, get_match_player_ids


# Distinct colors for life segment traces
_SEGMENT_COLORS = [
    '#e6194b', '#3cb44b', '#4363d8', '#f58231', '#911eb4',
    '#42d4f4', '#f032e6', '#bfef45', '#fabed4', '#469990',
    '#dcbeff', '#9A6324', '#fffac8', '#800000', '#aaffc3',
    '#808000', '#ffd8b1', '#000075', '#a9a9a9',
]

# Match trace uses slightly lighter/thinner styles than connectivity viz
_BUILD_STYLE = BuildRegionStyle(fill_alpha=0.10)
_ISLAND_STYLE = IslandOutlineStyle(
    exterior_linewidth=1.5, exterior_alpha=0.7,
    hole_linewidth=1.0, hole_alpha=0.5,
)
_POI_STYLE = POIStyle(wool_marker='D', wool_size=80, zorder=2)

# Team color mapping for --color-mode team
_TEAM_TRACE_COLORS = {
    'red': '#e74c3c',
    'blue': '#3498db',
    'green': '#2ecc71',
    'yellow': '#f39c12',
    'purple': '#9b59b6',
    'gray': '#95a5a6',
}

# Location type colors for --color-mode location
_LOCATION_COLORS = {
    'island': '#2ecc71',
    'build_region': '#f39c12',
    'void': '#e74c3c',
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
    classifier, map_context: dict,
) -> str:
    """Classify spawn position to determine team, return hex color."""
    result = classifier.classify_position(spawn_x, spawn_z)
    island_id = result['island_id']
    if island_id is None:
        return _TEAM_TRACE_COLORS['gray']

    for island in map_context.get('islands', []):
        if island['id'] == island_id:
            team_str = island.get('team') or ''
            team_key = team_str.replace('-team', '') if team_str else ''
            return _TEAM_TRACE_COLORS.get(team_key, _TEAM_TRACE_COLORS['gray'])

    return _TEAM_TRACE_COLORS['gray']


def plot_player_traces(
    map_context: dict,
    match_id: int,
    player_ids: list[int],
    output_path: Path,
    map_graph: dict = None,
    show_deaths: bool = True,
    show_kills: bool = True,
    show_wool: bool = True,
    show_edges: bool = True,
    show_legend: bool = True,
    show_stats: bool = True,
    show_title: bool = True,
    color_mode: str = 'life',
    map_base: str = 'outline',
    map_folder: Path = None,
    match_ids: list[int] = None,
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
        from match_analysis.position_classifier import PositionClassifier
        classifier = PositionClassifier(map_context, map_graph)

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
                color = _TEAM_TRACE_COLORS['gray']
        else:  # location — segment color used only for markers
            color = _LOCATION_COLORS.get('island', '#95a5a6')

        # Classify trace events for location coloring
        trace = seg['trace_events']
        enriched_df = None
        if classifier is not None and len(trace) > 0:
            enriched_df = classifier.classify_dataframe(trace)
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
            for team_name, team_hex in _TEAM_TRACE_COLORS.items():
                if team_name != 'gray':
                    legend_handles.append(
                        plt.Line2D([0], [0], color=team_hex, linewidth=2,
                                   label=f'{team_name.capitalize()} team'))
        elif color_mode == 'location':
            for loc_name, loc_hex in _LOCATION_COLORS.items():
                legend_handles.append(
                    plt.Line2D([0], [0], color=loc_hex, linewidth=2,
                               label=loc_name.replace('_', ' ').capitalize()))

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
    if show_title:
        ax.set_xlabel('X (blocks)')
        ax.set_ylabel('Z (blocks)')
        ax.grid(True, alpha=0.2)
    else:
        ax.axis('off')

    fig.savefig(str(output_path), dpi=200, bbox_inches='tight')
    plt.close(fig)
    print(f"Player trace plot saved to: {output_path}")


def _team_to_color(team: str) -> str:
    """Map a team name to a display color."""
    # Normalize: strip common prefixes
    key = team.replace('-team', '').replace('team-', '').replace('team_', '')
    return _TEAM_TRACE_COLORS.get(key, _TEAM_TRACE_COLORS['gray'])


def _distance_to_color(dist: float, max_dist: float) -> tuple:
    """Map distance to a green→yellow→red gradient."""
    if max_dist <= 0:
        return (0.2, 0.8, 0.2, 1.0)
    t = min(dist / max_dist, 1.0)
    # Green (0) → Yellow (0.5) → Red (1)
    if t < 0.5:
        r = t * 2
        g = 1.0
    else:
        r = 1.0
        g = 1.0 - (t - 0.5) * 2
    return (r, g, 0.15, 1.0)


def plot_kill_death_pairs(
    map_context: dict,
    pairs_df,
    output_path: Path,
    match_id: int | None = None,
    match_ids: list[int] | None = None,
    map_graph: dict = None,
    show_legend: bool = True,
    show_stats: bool = True,
    color_mode: str = 'team',
    map_base: str = 'outline',
    map_folder: Path = None,
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
            _team_to_color(t) if pd.notna(t) else _TEAM_TRACE_COLORS['gray']
            for t in pairs_df['killer_team']
        ]
        victim_colors = [
            _team_to_color(t) if pd.notna(t) else _TEAM_TRACE_COLORS['gray']
            for t in pairs_df['victim_team']
        ]
        line_colors = killer_colors  # lines colored by killer team
    else:  # distance
        dist_colors = [_distance_to_color(d, max_dist) for d in distances]
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
            for team_name, team_hex in _TEAM_TRACE_COLORS.items():
                if team_name != 'gray':
                    legend_handles.append(
                        plt.Line2D([0], [0], color=team_hex, linewidth=2,
                                   label=f'{team_name.capitalize()} team'))
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
    ax.set_xlabel('X (blocks)')
    ax.set_ylabel('Z (blocks)')
    ax.grid(True, alpha=0.2)

    fig.savefig(str(output_path), dpi=200, bbox_inches='tight')
    plt.close(fig)
    print(f"Kill-death pairs plot saved to: {output_path}")
