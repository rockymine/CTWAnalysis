"""Player trace visualization on map base layer.

Renders life segments (position traces) for a specific player on top
of a simplified map showing build region, island outlines, and POI markers.
"""

import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from visualization import (
    draw_map_base,
    map_base_legend_handles,
    BuildRegionStyle,
    IslandOutlineStyle,
    POIStyle,
)


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


def plot_player_traces(
    map_context: dict,
    match_file: str,
    player_id: int,
    output_path: Path,
    map_graph: dict = None,
    snap_skeleton: bool = False,
) -> None:
    """Plot all life segments of a player on the map base layer.

    Args:
        map_context: Parsed map_context.json dict.
        match_file: Path to the raw match parquet file.
        player_id: Player ID to visualize.
        output_path: Where to save the PNG.
        map_graph: Parsed map_graph.json dict (required if snap_skeleton=True).
        snap_skeleton: Snap on-island positions to skeleton paths.
    """
    output_path = Path(output_path)
    os.makedirs(output_path.parent, exist_ok=True)

    classifier = None
    if snap_skeleton and map_graph is not None:
        from match_analysis.position_classifier import PositionClassifier
        classifier = PositionClassifier(map_context, map_graph)

    # Load match data
    df = pd.read_parquet(match_file)
    player_df = df[df['player_id'] == player_id].sort_values('timestamp')

    if len(player_df) == 0:
        print(f"No events found for player {player_id} in {match_file}")
        return

    # Extract life segments: spawn -> death/match_end
    spawns = player_df[player_df['event_type'] == 2]
    deaths = player_df[player_df['event_type'] == 4]

    segments = []
    for spawn_row in spawns.itertuples():
        start_time = spawn_row.timestamp
        next_deaths = deaths[deaths['timestamp'] > start_time]
        if len(next_deaths) > 0:
            end_time = next_deaths.iloc[0]['timestamp']
            outcome = 'death'
        else:
            end_time = player_df['timestamp'].iloc[-1]
            outcome = 'match_end'

        # All events with coordinates in this life segment (for the trace line)
        trace_events = player_df[
            (player_df['timestamp'] >= start_time)
            & (player_df['timestamp'] <= end_time)
            & (player_df['event_type'].isin([3, 5, 6, 7]))
        ]
        kills = trace_events[trace_events['event_type'] == 3]
        wool_events = trace_events[trace_events['event_type'].isin([6, 7])]
        positions = trace_events[trace_events['event_type'] == 5]

        segments.append({
            'trace_events': trace_events,
            'positions': positions,
            'kills': kills,
            'wool_events': wool_events,
            'spawn_x': spawn_row.x,
            'spawn_z': spawn_row.z,
            'outcome': outcome,
            'start_time': start_time,
            'end_time': end_time,
        })

    if not segments:
        print(f"No life segments found for player {player_id}")
        return

    # Plot
    fig, ax = plt.subplots(figsize=(16, 10))
    map_name = map_context.get('map_name', 'Unknown')
    match_name = Path(match_file).stem
    ax.set_title(
        f"{map_name} — Player {player_id} Traces ({len(segments)} lives)\n"
        f"Match: {match_name}",
        fontsize=13, fontweight='bold',
    )

    draw_map_base(ax, map_context,
                  build_style=_BUILD_STYLE,
                  island_style=_ISLAND_STYLE,
                  poi_style=_POI_STYLE)

    # Draw each life segment
    for i, seg in enumerate(segments):
        color = _SEGMENT_COLORS[i % len(_SEGMENT_COLORS)]
        positions = seg['positions']

        # Build trace: spawn point + all events with coordinates (sorted by timestamp)
        trace = seg['trace_events']

        if classifier is not None:
            enriched = classifier.classify_dataframe(trace, snap_skeleton=True)
            trace_xs = enriched['snap_x'].values
            trace_zs = enriched['snap_z'].values
        else:
            trace_xs = trace['x'].values
            trace_zs = trace['z'].values

        xs = np.concatenate([[seg['spawn_x']], trace_xs])
        zs = np.concatenate([[seg['spawn_z']], trace_zs])

        if len(xs) >= 2:
            ax.plot(xs, zs, color=color, linewidth=1.5, alpha=0.8, zorder=3,
                    label=f"Life {i + 1} ({seg['outcome']}, {len(positions)} pos)")

        # Spawn marker (triangle)
        ax.scatter(seg['spawn_x'], seg['spawn_z'],
                   marker='^', s=80, c=color,
                   edgecolors='black', linewidths=0.6, zorder=5)

        # Death marker (x) if died
        if seg['outcome'] == 'death' and len(positions) > 0:
            last = positions.iloc[-1]
            ax.scatter(last['x'], last['z'],
                       marker='x', s=80, c=color,
                       linewidths=2, zorder=5)

        # Kill markers (+)
        if len(seg['kills']) > 0:
            ax.scatter(seg['kills']['x'].values, seg['kills']['z'].values,
                       marker='+', s=100, c=color,
                       linewidths=2, zorder=4)

        # Wool event markers (diamond)
        if len(seg['wool_events']) > 0:
            ax.scatter(seg['wool_events']['x'].values,
                       seg['wool_events']['z'].values,
                       marker='D', s=60, c='gold',
                       edgecolors=color, linewidths=1, zorder=4)

    # Legend
    legend_handles = map_base_legend_handles(
        has_build_region=True,
        island_style=_ISLAND_STYLE,
        poi_style=_POI_STYLE,
    )
    legend_handles += [
        plt.Line2D([0], [0], marker='^', color='w', markerfacecolor='gray',
                   markeredgecolor='black', markersize=8, label='Spawn (player)'),
        plt.Line2D([0], [0], marker='x', color='black',
                   markersize=8, label='Death'),
        plt.Line2D([0], [0], marker='+', color='black',
                   markersize=8, label='Kill'),
    ]
    ax.legend(handles=legend_handles, loc='upper right', fontsize=8, framealpha=0.9)

    # Stats box
    total_pos = sum(len(s['positions']) for s in segments)
    total_kills = sum(len(s['kills']) for s in segments)
    total_duration = sum(s['end_time'] - s['start_time'] for s in segments)
    stats_text = (
        f"Lives: {len(segments)}  |  Positions: {total_pos}  |  "
        f"Kills: {total_kills}  |  Total time: {total_duration:.0f}s"
    )
    ax.text(
        0.02, 0.02, stats_text,
        transform=ax.transAxes, fontsize=9, fontfamily='monospace',
        bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8),
        zorder=10,
    )

    ax.set_xlabel('X (blocks)')
    ax.set_ylabel('Z (blocks)')
    ax.set_aspect('equal')
    ax.grid(True, alpha=0.2)

    fig.savefig(str(output_path), dpi=200, bbox_inches='tight')
    plt.close(fig)
    print(f"Player trace plot saved to: {output_path}")
