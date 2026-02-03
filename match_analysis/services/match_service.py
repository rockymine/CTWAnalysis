"""Match analysis orchestration."""

import json
from pathlib import Path
from collections import Counter


def parse_match_history(match_history_file: Path, map_name: str):
    """
    Parse match history file to find all matches for a given map.

    Args:
        match_history_file: Path to match_history.txt
        map_name: Name of the map to filter for

    Returns:
        list: List of match file names for this map
    """
    if not match_history_file.exists():
        return []

    matches = []
    with open(match_history_file, 'r') as f:
        lines = [line.strip() for line in f.readlines()]

    # Parse alternating lines (map name, match file, map name, match file, ...)
    for i in range(0, len(lines) - 1, 2):
        file_map_name = lines[i]
        match_file = lines[i + 1]

        # Match by map name (case-insensitive, flexible matching)
        if file_map_name.lower().replace(' ', '') == map_name.lower().replace(' ', ''):
            matches.append(match_file)

    return matches


def analyze_single_match(map_name: str, match_file: str, bedrock_parquet: Path, output_dir: Path):
    """
    Analyze a single match and generate plots/reports.

    Args:
        map_name: Name of the map
        match_file: Match parquet filename
        bedrock_parquet: Path to bedrock layout parquet file
        output_dir: Directory to save results

    Returns:
        bool: True if successful, False otherwise
    """
    import matplotlib.pyplot as plt
    import pandas as pd
    from matplotlib.patches import Patch
    from match_analysis_DEPRECATED import (
        load_match_data,
        detect_life_segments,
        assign_teams,
        render_map_tiles,
        setup_map_axes,
        calculate_player_stats,
        analyze_map_characteristics,
        classify_all_segments,
        EVENT_IDS,
        TEAM_COLORS,
        EVENT_MARKERS,
    )
    from match_analysis_DEPRECATED.pdf_report import (
        generate_match_summary_pdf,
        generate_classification_pdf,
    )
    from classify_segments import generate_classification_report
    from match_analysis_DEPRECATED.path_network_viz import (
        plot_combined_network,
        plot_team_networks,
    )

    try:
        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)

        # Load map data directly from bedrock parquet
        map_data = pd.read_parquet(bedrock_parquet)

        # Rename columns to match expected format (world_x -> X, world_z -> Z)
        if 'world_x' in map_data.columns:
            map_data = map_data.rename(columns={'world_x': 'X', 'world_z': 'Z', 'y': 'Y'})
        elif 'x' in map_data.columns:
            map_data = map_data.rename(columns={'x': 'X', 'z': 'Z', 'y': 'Y'})

        print(f"      Loaded map bedrock: {len(map_data)} blocks")

        # Load match data
        match_data = load_match_data(match_file)

        # Process match data
        life_segments = detect_life_segments(match_data)
        life_segments = assign_teams(life_segments)

        if not life_segments:
            print(f"      [X] No life segments found in match")
            return False

        # Classify segments
        map_chars = analyze_map_characteristics(life_segments, match_data)
        classifications = classify_all_segments(life_segments, map_chars)

        # Calculate statistics
        player_stats = calculate_player_stats(life_segments)

        # Generate team plots
        plot_configs = [
            ('all_teams', None, 'All Teams'),
            ('red_team', 'red', 'Red Team'),
            ('blue_team', 'blue', 'Blue Team')
        ]

        for team_key, team_filter, team_title in plot_configs:
            fig, ax = plt.subplots(figsize=(14, 10))

            # Filter segments
            if team_filter:
                segments_to_plot = [seg for seg in life_segments if seg.team == team_filter]
            else:
                segments_to_plot = life_segments

            # Render map
            render_map_tiles(ax, map_data)

            # Plot segments
            labels_added = set()
            for segment in segments_to_plot:
                events = segment.events
                if events.empty:
                    continue

                color = TEAM_COLORS.get(segment.team, TEAM_COLORS['unknown'])

                # Position trace
                position_events = events[events['event_type'] == EVENT_IDS['POSITION']]
                if not position_events.empty:
                    ax.plot(position_events['x'], position_events['z'],
                           color=color, alpha=0.6, linewidth=2, zorder=1)

                # Spawn
                spawn_x, spawn_y, spawn_z = segment.spawn_coords
                spawn_marker = EVENT_MARKERS['spawn']
                ax.scatter([spawn_x], [spawn_z],
                          marker=spawn_marker['marker'], s=spawn_marker['size'],
                          c=spawn_marker['color'], edgecolors=spawn_marker['edgecolor'],
                          linewidths=spawn_marker['linewidth'], zorder=3,
                          label='Spawn' if 'Spawn' not in labels_added else '')
                labels_added.add('Spawn')

                # Deaths
                death_events = events[events['event_type'] == EVENT_IDS['DEATH']]
                if not death_events.empty:
                    death_marker = EVENT_MARKERS['death']
                    ax.scatter(death_events['x'], death_events['z'],
                              marker=death_marker['marker'], s=death_marker['size'],
                              c=death_marker['color'], linewidths=death_marker['linewidth'],
                              zorder=3, label='Death' if 'Death' not in labels_added else '')
                    labels_added.add('Death')

                # Wool captures
                wool_capture_events = events[events['event_type'] == EVENT_IDS['WOOL_CAPTURE']]
                if not wool_capture_events.empty:
                    capture_marker = EVENT_MARKERS['wool_capture']
                    ax.scatter(wool_capture_events['x'], wool_capture_events['z'],
                              marker=capture_marker['marker'], s=capture_marker['size'],
                              c=capture_marker['color'], edgecolors=capture_marker['edgecolor'],
                              linewidths=capture_marker['linewidth'], zorder=4,
                              label='Wool Capture' if 'Wool Capture' not in labels_added else '')
                    labels_added.add('Wool Capture')

            # Setup axes and legend
            setup_map_axes(ax, map_data, title=f"CTW Match - {map_name} - {team_title}")

            # Add team patches to legend
            handles, labels_list = ax.get_legend_handles_labels()
            if team_filter is None or team_filter == 'red':
                handles.append(Patch(color=TEAM_COLORS['red'], label='Red Team'))
                labels_list.append('Red Team')
            if team_filter is None or team_filter == 'blue':
                handles.append(Patch(color=TEAM_COLORS['blue'], label='Blue Team'))
                labels_list.append('Blue Team')
            ax.legend(handles, labels_list, loc='upper right', fontsize=9, framealpha=0.9)

            # Save
            plot_path = output_dir / f'{team_key}.png'
            fig.savefig(plot_path, dpi=150, bbox_inches='tight')
            plt.close(fig)

        # Generate PDF summary
        pdf_path = output_dir / 'match_summary.pdf'
        config = {'data_files': {'map_name': map_name, 'match_file': match_file}}
        generate_match_summary_pdf(life_segments, player_stats, config, str(pdf_path))

        # Generate classification reports
        generate_classification_report(
            life_segments=life_segments,
            classifications=classifications,
            map_chars=map_chars,
            output_dir=str(output_dir)
        )

        classification_pdf_path = output_dir / 'classification_report.pdf'
        generate_classification_pdf(
            life_segments=life_segments,
            classifications=classifications,
            map_chars=map_chars,
            config=config,
            output_path=str(classification_pdf_path)
        )

        # Generate path network visualizations
        path_network_combined = output_dir / 'path_network_combined.png'
        plot_combined_network(
            life_segments=life_segments,
            map_data=map_data,
            output_path=str(path_network_combined),
            resolution=1.0,
            cluster_radius=5.0
        )

        # Generate team-specific path networks
        plot_team_networks(
            life_segments=life_segments,
            map_data=map_data,
            output_dir=str(output_dir),
            resolution=1.0
        )

        # Generate text summary
        summary_path = output_dir / 'match_summary.txt'
        with open(summary_path, 'w') as f:
            f.write("=" * 70 + "\n")
            f.write("CTW MATCH ANALYSIS SUMMARY\n")
            f.write("=" * 70 + "\n\n")
            f.write(f"Map: {map_name}\n")
            f.write(f"Match: {match_file}\n\n")
            f.write(f"Total Players: {len(set(seg.player_id for seg in life_segments))}\n")
            f.write(f"Total Life Segments: {len(life_segments)}\n\n")

            team_counts = Counter(seg.team for seg in life_segments)
            f.write("Team Distribution:\n")
            for team, count in team_counts.items():
                f.write(f"  {team.capitalize()}: {count} segments\n")

        return True

    except Exception as e:
        print(f"      [X] Error analyzing match: {e}")
        return False


def analyze_matches(map_folder: Path, match_history_file: Path):
    """
    Step 4: Analyze matches for this map.

    Args:
        map_folder: Path to map folder (e.g., map_folders/tumbleweed)
        match_history_file: Path to match history file

    Returns:
        list: Paths to generated match analysis folders
    """
    print(f"\n[4/4] Match Analysis: {map_folder.name}")
    print("=" * 70)

    # Check prerequisites
    json_file = map_folder / 'map_data.json'
    if not json_file.exists():
        print("  [X] Map data JSON not found. Run XML analysis first.")
        return []

    # Check for bedrock layout file (required for match analysis)
    bedrock_file = map_folder / 'layout_bedrock.parquet'
    if not bedrock_file.exists():
        print("  [X] Bedrock layout file not found. Run layout analysis first.")
        return []

    print(f"  Prerequisites satisfied:")
    print(f"    [OK] Map data: {json_file.name}")
    print(f"    [OK] Bedrock layout: {bedrock_file.name}")

    # Parse match history to find matches for this map
    with open(json_file, 'r') as f:
        map_data_json = json.load(f)
    map_name = map_data_json['name']

    matches = parse_match_history(match_history_file, map_name)

    if not matches:
        print(f"  No matches found for {map_name} in match history")
        return []

    print(f"  Found {len(matches)} match(es) for {map_name}")

    # Create matches directory
    matches_dir = map_folder / 'matches'
    matches_dir.mkdir(exist_ok=True)

    # Analyze each match
    results = []
    for i, match_file in enumerate(matches, 1):
        # Extract match ID from filename (remove .parquet extension)
        match_id = match_file.replace('.parquet', '')

        print(f"\n  [{i}/{len(matches)}] Analyzing match: {match_id}")

        # Create output directory for this match
        match_output_dir = matches_dir / match_id
        if match_output_dir.exists():
            print(f"      Match analysis already exists. Skipping.")
            results.append(match_output_dir)
            continue

        # Analyze match
        success = analyze_single_match(map_name, match_file, bedrock_file, match_output_dir)

        if success:
            print(f"      [OK] Saved to: {match_output_dir.relative_to(map_folder)}")
            results.append(match_output_dir)
        else:
            # Remove failed directory
            if match_output_dir.exists():
                import shutil
                shutil.rmtree(match_output_dir)

    print(f"\n  Successfully analyzed {len(results)}/{len(matches)} matches")

    return results
