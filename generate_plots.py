"""
CTW Plot Generation Script

Generates static plots based on config.json settings.
"""

import json
import os
from pathlib import Path
from typing import List, Dict, Optional
import pandas as pd
import matplotlib.pyplot as plt

from match_analysis_DEPRECATED import (
    load_map_data,
    load_match_data,
    detect_life_segments,
    assign_teams,
    render_map_tiles,
    setup_map_axes,
    calculate_player_stats,
    print_match_summary,
    analyze_map_characteristics,
    classify_all_segments,
    EVENT_IDS,
    TEAM_COLORS,
    EVENT_MARKERS
)
from match_analysis_DEPRECATED.preprocessing import LifeSegment
from match_analysis_DEPRECATED.pdf_report import generate_match_summary_pdf


def load_config(config_path: str = 'config.json') -> dict:
    """Load configuration from JSON file."""
    with open(config_path, 'r') as f:
        config = json.load(f)
    return config


def plot_match(
    ax: plt.Axes,
    map_data: pd.DataFrame,
    life_segments: List[LifeSegment],
    team_filter: Optional[str] = None,
    segment_indices: Optional[List[int]] = None,
    show_map: bool = True,
    show_positions: bool = True,
    show_kills: bool = False,
    show_deaths: bool = True,
    show_wool_touches: bool = True,
    show_wool_captures: bool = True
) -> None:
    """
    Plot match data with specified settings.

    Args:
        ax: Matplotlib axes
        map_data: Map bedrock data
        life_segments: List of LifeSegment objects
        team_filter: 'red', 'blue', or None (all teams)
        segment_indices: Optional list of segment indices to plot (for role filtering)
        show_map: Display map tiles
        show_positions: Display position traces
        show_kills: Display kill events
        show_deaths: Display death events
        show_wool_touches: Display wool touch events
        show_wool_captures: Display wool capture events
    """
    # Render map if enabled
    if show_map:
        render_map_tiles(ax, map_data)

    # Filter segments by indices first (role filtering)
    if segment_indices is not None:
        segments_to_plot = [life_segments[i] for i in segment_indices]
    else:
        segments_to_plot = life_segments

    # Then filter by team if specified
    if team_filter:
        segments_to_plot = [seg for seg in segments_to_plot if seg.team == team_filter]

    # Track which labels we've added to legend
    labels_added = set()

    # Plot each life segment
    for segment in segments_to_plot:
        events = segment.events
        if events.empty:
            continue

        # Get segment color based on team
        color = TEAM_COLORS.get(segment.team, TEAM_COLORS['unknown'])

        # Plot position trace
        if show_positions:
            position_events = events[events['event_type'] == EVENT_IDS['POSITION']]
            if not position_events.empty:
                ax.plot(
                    position_events['x'],
                    position_events['z'],
                    color=color,
                    alpha=0.6,
                    linewidth=2,
                    zorder=1
                )

        # Plot spawn (always shown)
        spawn_x, spawn_y, spawn_z = segment.spawn_coords
        spawn_marker = EVENT_MARKERS['spawn']
        ax.scatter(
            [spawn_x], [spawn_z],
            marker=spawn_marker['marker'],
            s=spawn_marker['size'],
            c=spawn_marker['color'],
            edgecolors=spawn_marker['edgecolor'],
            linewidths=spawn_marker['linewidth'],
            zorder=3,
            label='Spawn' if 'Spawn' not in labels_added else ''
        )
        labels_added.add('Spawn')

        # Plot deaths
        if show_deaths:
            death_events = events[events['event_type'] == EVENT_IDS['DEATH']]
            if not death_events.empty:
                death_marker = EVENT_MARKERS['death']
                ax.scatter(
                    death_events['x'],
                    death_events['z'],
                    marker=death_marker['marker'],
                    s=death_marker['size'],
                    c=death_marker['color'],
                    linewidths=death_marker['linewidth'],
                    zorder=3,
                    label='Death' if 'Death' not in labels_added else ''
                )
                labels_added.add('Death')

        # Plot kills
        if show_kills:
            kill_events = events[events['event_type'] == EVENT_IDS['KILL']]
            if not kill_events.empty:
                kill_marker = EVENT_MARKERS['kill']
                ax.scatter(
                    kill_events['x'],
                    kill_events['z'],
                    marker=kill_marker['marker'],
                    s=kill_marker['size'],
                    c=kill_marker['color'],
                    linewidths=kill_marker['linewidth'],
                    zorder=3,
                    label='Kill' if 'Kill' not in labels_added else ''
                )
                labels_added.add('Kill')

        # Plot wool touches
        if show_wool_touches:
            wool_touch_events = events[events['event_type'] == EVENT_IDS['WOOL_TOUCH']]
            if not wool_touch_events.empty:
                touch_marker = EVENT_MARKERS['wool_touch']
                ax.scatter(
                    wool_touch_events['x'],
                    wool_touch_events['z'],
                    marker=touch_marker['marker'],
                    s=touch_marker['size'],
                    c=touch_marker['color'],
                    edgecolors=touch_marker['edgecolor'],
                    linewidths=touch_marker['linewidth'],
                    zorder=3,
                    label='Wool Touch' if 'Wool Touch' not in labels_added else ''
                )
                labels_added.add('Wool Touch')

        # Plot wool captures
        if show_wool_captures:
            wool_capture_events = events[events['event_type'] == EVENT_IDS['WOOL_CAPTURE']]
            if not wool_capture_events.empty:
                capture_marker = EVENT_MARKERS['wool_capture']
                ax.scatter(
                    wool_capture_events['x'],
                    wool_capture_events['z'],
                    marker=capture_marker['marker'],
                    s=capture_marker['size'],
                    c=capture_marker['color'],
                    edgecolors=capture_marker['edgecolor'],
                    linewidths=capture_marker['linewidth'],
                    zorder=4,
                    label='Wool Capture' if 'Wool Capture' not in labels_added else ''
                )
                labels_added.add('Wool Capture')

    # Add team color patches to legend
    from matplotlib.patches import Patch
    team_patches = []
    if team_filter is None or team_filter == 'red':
        team_patches.append(Patch(color=TEAM_COLORS['red'], label='Red Team'))
    if team_filter is None or team_filter == 'blue':
        team_patches.append(Patch(color=TEAM_COLORS['blue'], label='Blue Team'))

    # Combine all legend items
    handles, labels = ax.get_legend_handles_labels()
    handles.extend(team_patches)
    labels.extend([p.get_label() for p in team_patches])

    # Add legend
    ax.legend(handles, labels, loc='upper right', fontsize=9, framealpha=0.9)


def generate_summary_report(
    config: dict,
    life_segments: List[LifeSegment],
    player_stats: pd.DataFrame,
    output_dir: str
) -> None:
    """
    Generate a text summary report of the match.

    Args:
        config: Configuration dictionary
        life_segments: List of LifeSegment objects
        player_stats: DataFrame with player statistics
        output_dir: Output directory path
    """
    from collections import Counter

    summary_path = os.path.join(output_dir, 'match_summary.txt')

    with open(summary_path, 'w') as f:
        f.write("="*70 + "\n")
        f.write("CTW MATCH ANALYSIS SUMMARY\n")
        f.write("="*70 + "\n\n")

        # Match information
        f.write("MATCH INFORMATION\n")
        f.write("-"*70 + "\n")
        f.write(f"Map: {config['data_files']['map_name']}\n")
        f.write(f"Match File: {config['data_files']['match_file']}\n\n")

        # Overall statistics
        f.write("OVERALL STATISTICS\n")
        f.write("-"*70 + "\n")
        f.write(f"Total Players: {len(set(seg.player_id for seg in life_segments))}\n")
        f.write(f"Total Life Segments: {len(life_segments)}\n\n")

        # Team distribution
        team_counts = Counter(seg.team for seg in life_segments)
        f.write("Team Distribution:\n")
        for team, count in team_counts.items():
            f.write(f"  {team.capitalize()}: {count} segments\n")
        f.write("\n")

        # End reasons
        end_reasons = Counter(seg.end_reason for seg in life_segments)
        f.write("Life Segment End Reasons:\n")
        for reason, count in end_reasons.items():
            f.write(f"  {reason}: {count}\n")
        f.write("\n")

        # Event totals
        total_kills = sum(seg.to_dict()['kills'] for seg in life_segments)
        total_deaths = sum(seg.to_dict()['deaths'] for seg in life_segments)
        total_wool_touches = sum(seg.to_dict()['wool_touches'] for seg in life_segments)
        total_wool_captures = sum(seg.to_dict()['wool_captures'] for seg in life_segments)

        f.write("Total Events:\n")
        f.write(f"  Kills: {total_kills}\n")
        f.write(f"  Deaths: {total_deaths}\n")
        f.write(f"  Wool Touches: {total_wool_touches}\n")
        f.write(f"  Wool Captures: {total_wool_captures}\n\n")

        # Top players
        f.write("="*70 + "\n")
        f.write("TOP 20 PLAYERS BY KILLS\n")
        f.write("="*70 + "\n\n")
        f.write(player_stats.head(20).to_string(index=False))
        f.write("\n\n")

        # Team statistics
        f.write("="*70 + "\n")
        f.write("TEAM STATISTICS\n")
        f.write("="*70 + "\n\n")

        for team in ['red', 'blue']:
            team_segments = [seg for seg in life_segments if seg.team == team]
            if not team_segments:
                continue

            team_kills = sum(seg.to_dict()['kills'] for seg in team_segments)
            team_deaths = sum(seg.to_dict()['deaths'] for seg in team_segments)
            team_wool_touches = sum(seg.to_dict()['wool_touches'] for seg in team_segments)
            team_wool_captures = sum(seg.to_dict()['wool_captures'] for seg in team_segments)
            team_players = len(set(seg.player_id for seg in team_segments))

            f.write(f"{team.upper()} TEAM:\n")
            f.write(f"  Players: {team_players}\n")
            f.write(f"  Life Segments: {len(team_segments)}\n")
            f.write(f"  Total Kills: {team_kills}\n")
            f.write(f"  Total Deaths: {team_deaths}\n")
            f.write(f"  Wool Touches: {team_wool_touches}\n")
            f.write(f"  Wool Captures: {team_wool_captures}\n")
            f.write(f"  K/D Ratio: {team_kills/team_deaths:.2f}\n\n")

        f.write("="*70 + "\n")
        f.write("Report generated by CTW Analysis Toolkit\n")
        f.write("="*70 + "\n")

    print(f"Summary report saved to: {summary_path}")


def main():
    """Main plot generation pipeline."""
    print("="*70)
    print("CTW PLOT GENERATION")
    print("="*70)

    # Load configuration
    print("\n1. Loading configuration...")
    config = load_config()
    print(f"   Map: {config['data_files']['map_name']}")
    print(f"   Match: {config['data_files']['match_file']}")
    print(f"   Output folder: {config['output']['folder']}")

    # Create output directory
    output_dir = config['output']['folder']
    os.makedirs(output_dir, exist_ok=True)

    # Load data
    print("\n2. Loading data...")
    map_data = load_map_data(config['data_files']['map_name'])
    match_data = load_match_data(config['data_files']['match_file'])

    # Process match data
    print("\n3. Processing match data...")
    life_segments = detect_life_segments(match_data)
    life_segments = assign_teams(life_segments)

    # Classify segments if role plotting is enabled
    classifications = None
    if config.get('role_settings'):
        print("\n4. Classifying life segments for role-based plots...")
        map_chars = analyze_map_characteristics(life_segments, match_data)
        classifications = classify_all_segments(life_segments, map_chars)
        print(f"   Classified {len(classifications)} segments")

    # Calculate statistics
    step = 5 if classifications else 4
    print(f"\n{step}. Calculating player statistics...")
    player_stats = calculate_player_stats(life_segments)

    # Generate summary report
    step += 1
    print(f"\n{step}. Generating summary report...")
    generate_summary_report(config, life_segments, player_stats, output_dir)

    # Generate PDF summary (if enabled)
    if config.get('output', {}).get('generate_pdf', True):
        step += 1
        print(f"\n{step}. Generating PDF summary...")
        match_summary_pdf = os.path.join(output_dir, 'match_summary.pdf')
        generate_match_summary_pdf(life_segments, player_stats, config, match_summary_pdf)

    # Generate plots
    step += 1
    print(f"\n{step}. Generating plots...")
    dpi = config['output']['dpi']
    show_map = config['map_settings']['show_map']

    # Data settings
    show_kills = config['data_settings']['kills']
    show_deaths = config['data_settings']['deaths']
    show_wool_touches = config['data_settings']['wool_touches']
    show_wool_captures = config['data_settings']['wool_captures']
    show_positions = config['data_settings']['positions']

    # Team-based plots
    team_configs = []
    if config['team_settings']['all_teams']:
        team_configs.append(('all_teams', None, 'All Teams'))
    if config['team_settings']['red_team']:
        team_configs.append(('red_team', 'red', 'Red Team'))
    if config['team_settings']['blue_team']:
        team_configs.append(('blue_team', 'blue', 'Blue Team'))

    plot_count = 0
    for team_key, team_filter, team_title in team_configs:
        print(f"\n   Generating {team_title} plot...")

        fig, ax = plt.subplots(figsize=(14, 10))

        # Plot match
        plot_match(
            ax=ax,
            map_data=map_data,
            life_segments=life_segments,
            team_filter=team_filter,
            show_map=show_map,
            show_positions=show_positions,
            show_kills=show_kills,
            show_deaths=show_deaths,
            show_wool_touches=show_wool_touches,
            show_wool_captures=show_wool_captures
        )

        # Setup axes
        setup_map_axes(
            ax,
            map_data,
            title=f"CTW Match - {config['data_files']['map_name']} - {team_title}"
        )

        # Save plot
        output_path = os.path.join(output_dir, f"{team_key}.png")
        fig.savefig(output_path, dpi=dpi, bbox_inches='tight')
        plt.close(fig)

        print(f"   Saved: {output_path}")
        plot_count += 1

    # Role-based plots (if classifications exist and roles are enabled)
    if classifications and config.get('role_settings'):
        print(f"\n{step + 1}. Generating role-based plots...")

        # Map config role names to classification role names
        role_name_map = {
            'wool_runner': 'WOOL_RUNNER',
            'skybridge_controller': 'SKYBRIDGE_CONTROLLER',
            'attacker_stealth': 'ATTACKER_STEALTH',
            'rusher': 'RUSHER',
            'attacker_aggressive': 'ATTACKER_AGGRESSIVE',
            'attacker_passive': 'ATTACKER_PASSIVE',
            'camper': 'CAMPER',
            'mid_controller': 'MID_CONTROLLER',
            'base_defender': 'BASE_DEFENDER',
            'defender': 'DEFENDER',
            'flanker': 'FLANKER',
            'roamer': 'ROAMER'
        }

        for role_key, enabled in config['role_settings'].items():
            if not enabled:
                continue

            role_name = role_name_map.get(role_key)
            if not role_name:
                continue

            # Find all segments with this role
            role_indices = [i for i, c in enumerate(classifications) if c.primary_role == role_name]

            if not role_indices:
                print(f"   Skipping {role_key} - no segments found")
                continue

            print(f"\n   Generating {role_key} plot ({len(role_indices)} segments)...")

            fig, ax = plt.subplots(figsize=(14, 10))

            # Plot role segments
            plot_match(
                ax=ax,
                map_data=map_data,
                life_segments=life_segments,
                segment_indices=role_indices,
                show_map=show_map,
                show_positions=show_positions,
                show_kills=show_kills,
                show_deaths=show_deaths,
                show_wool_touches=show_wool_touches,
                show_wool_captures=show_wool_captures
            )

            # Setup axes
            role_title = role_name.replace('_', ' ').title()
            setup_map_axes(
                ax,
                map_data,
                title=f"CTW Match - {config['data_files']['map_name']} - {role_title} Role"
            )

            # Save plot
            output_path = os.path.join(output_dir, f"{role_key}.png")
            fig.savefig(output_path, dpi=dpi, bbox_inches='tight')
            plt.close(fig)

            print(f"   Saved: {output_path}")
            plot_count += 1

    print(f"\n{'='*70}")
    print(f"Plot generation complete!")
    print(f"  Generated {plot_count} plots")
    print(f"  Output directory: {output_dir}")
    print(f"{'='*70}\n")


if __name__ == '__main__':
    main()
