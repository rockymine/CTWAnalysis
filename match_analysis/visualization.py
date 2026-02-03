"""Player trace visualization on map base layer.

Renders life segments (position traces) for a specific player on top
of a simplified map showing build region, island outlines, and POI markers.
"""

import json
import os
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd


# Team colors for island boundaries (same as connectivity viz)
_TEAM_COLORS = {
    'blue': '#3b82f6',
    'red': '#ef4444',
}
_NEUTRAL_COLOR = '#6b7280'

# Distinct colors for life segment traces
_SEGMENT_COLORS = [
    '#e6194b', '#3cb44b', '#4363d8', '#f58231', '#911eb4',
    '#42d4f4', '#f032e6', '#bfef45', '#fabed4', '#469990',
    '#dcbeff', '#9A6324', '#fffac8', '#800000', '#aaffc3',
    '#808000', '#ffd8b1', '#000075', '#a9a9a9',
]


def _draw_map_base(ax, map_context):
    """Draw the simplified map base: build region, island outlines, POIs."""

    # Build region (buildable void)
    build_region = map_context.get('build_region')
    if build_region:
        for poly_coords in build_region.get('buildable_void', []):
            exterior = np.array(poly_coords['exterior'])
            if len(exterior) >= 3:
                ax.fill(
                    exterior[:, 0], exterior[:, 1],
                    facecolor='#22c55e', alpha=0.10,
                    edgecolor='#16a34a', linewidth=0.5,
                    zorder=0,
                )
                for hole in poly_coords.get('holes', []):
                    h = np.array(hole)
                    if len(h) >= 3:
                        ax.fill(h[:, 0], h[:, 1],
                                facecolor='white', alpha=1.0, zorder=0)

    # Island polygon outlines
    for island in map_context.get('islands', []):
        poly = island.get('simplified_polygon')
        if poly is None:
            continue
        team = island.get('team')
        color = _TEAM_COLORS.get(team, _NEUTRAL_COLOR)

        exterior = np.array(poly['exterior'])
        if len(exterior) < 3:
            continue
        ax.plot(exterior[:, 0], exterior[:, 1],
                color=color, linewidth=1.5, alpha=0.7, zorder=1)

        for hole_coords in poly.get('holes', []):
            hole = np.array(hole_coords)
            if len(hole) >= 3:
                ax.plot(hole[:, 0], hole[:, 1],
                        color=color, linewidth=1.0, alpha=0.5, zorder=1)

    # POI markers
    poi_assignments = map_context.get('poi_assignments', {})
    for spawn in poi_assignments.get('spawns', []):
        team_color = spawn.get('team_color', '')
        color = '#3b82f6' if team_color == 'blue' else '#ef4444'
        ax.scatter(spawn['x'], spawn['z'],
                   marker='*', s=200, c=color,
                   edgecolors='black', linewidths=0.6, zorder=2)

    for wool in poi_assignments.get('wools', []):
        ax.scatter(wool['x'], wool['z'],
                   marker='D', s=80, c='#f1c40f',
                   edgecolors='black', linewidths=0.6, zorder=2)


def plot_player_traces(
    map_context: dict,
    match_file: str,
    player_id: int,
    output_path: Path,
) -> None:
    """Plot all life segments of a player on the map base layer.

    Args:
        map_context: Parsed map_context.json dict.
        match_file: Path to the raw match parquet file.
        player_id: Player ID to visualize.
        output_path: Where to save the PNG.
    """
    output_path = Path(output_path)
    os.makedirs(output_path.parent, exist_ok=True)

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

        positions = player_df[
            (player_df['timestamp'] >= start_time)
            & (player_df['timestamp'] <= end_time)
            & (player_df['event_type'] == 5)
        ]
        kills = player_df[
            (player_df['timestamp'] >= start_time)
            & (player_df['timestamp'] <= end_time)
            & (player_df['event_type'] == 3)
        ]
        wool_events = player_df[
            (player_df['timestamp'] >= start_time)
            & (player_df['timestamp'] <= end_time)
            & (player_df['event_type'].isin([6, 7]))
        ]

        segments.append({
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

    _draw_map_base(ax, map_context)

    # Draw each life segment
    for i, seg in enumerate(segments):
        color = _SEGMENT_COLORS[i % len(_SEGMENT_COLORS)]
        positions = seg['positions']

        # Build trace: spawn point + all position events
        xs = np.concatenate([[seg['spawn_x']], positions['x'].values])
        zs = np.concatenate([[seg['spawn_z']], positions['z'].values])

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
    legend_handles = [
        mpatches.Patch(facecolor='#22c55e', alpha=0.15, label='Buildable void'),
        plt.Line2D([0], [0], color=_TEAM_COLORS['blue'], linewidth=1.5, label='Blue island'),
        plt.Line2D([0], [0], color=_TEAM_COLORS['red'], linewidth=1.5, label='Red island'),
        plt.Line2D([0], [0], color=_NEUTRAL_COLOR, linewidth=1.5, label='Neutral island'),
        plt.Line2D([0], [0], marker='*', color='w', markerfacecolor='#3b82f6',
                   markersize=12, label='Spawn POI'),
        plt.Line2D([0], [0], marker='D', color='w', markerfacecolor='#f1c40f',
                   markeredgecolor='black', markersize=6, label='Wool POI'),
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
