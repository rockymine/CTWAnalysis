"""
CTW Life Segment Classification Analysis

Analyzes and classifies player life segments based on positioning and behavior.
"""

import json
import os
from collections import Counter, defaultdict
import pandas as pd

from match_analysis_DEPRECATED import (
    load_map_data,
    load_match_data,
    detect_life_segments,
    assign_teams,
    analyze_map_characteristics,
    classify_all_segments,
    calculate_player_stats
)
from match_analysis_DEPRECATED.pdf_report import generate_classification_pdf, generate_match_summary_pdf


def load_config(config_path: str = 'config.json') -> dict:
    """Load configuration from JSON file."""
    with open(config_path, 'r') as f:
        config = json.load(f)
    return config


def generate_classification_report(
    life_segments,
    classifications,
    map_chars,
    output_dir: str = 'output'
) -> None:
    """
    Generate comprehensive classification report.

    Args:
        life_segments: List of LifeSegment objects
        classifications: List of SegmentClassification objects
        map_chars: MapCharacteristics object
        output_dir: Output directory
    """
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, 'classification_report.txt')

    with open(report_path, 'w') as f:
        f.write("="*80 + "\n")
        f.write("CTW LIFE SEGMENT CLASSIFICATION REPORT\n")
        f.write("="*80 + "\n\n")

        # Map characteristics
        f.write("MAP CHARACTERISTICS\n")
        f.write("-"*80 + "\n")
        f.write(f"Midpoint axis: {map_chars.midpoint_axis.upper()}\n")
        f.write(f"Midpoint coordinate: {map_chars.midpoint_coord:.1f}\n")
        f.write(f"Red team side: {'positive' if map_chars.red_side_positive else 'negative'}\n")
        f.write(f"Skybridge height: Y={map_chars.skybridge_height:.1f}\n")
        f.write(f"Ground level: Y={map_chars.ground_level:.1f}\n")
        f.write(f"Tunnel threshold: Y={map_chars.tunnel_threshold:.1f}\n\n")

        # Role distribution
        f.write("="*80 + "\n")
        f.write("ROLE DISTRIBUTION\n")
        f.write("="*80 + "\n\n")

        role_counts = Counter(c.primary_role for c in classifications)
        total_segments = len(classifications)

        f.write(f"Total classified segments: {total_segments}\n\n")

        for role, count in role_counts.most_common():
            percentage = (count / total_segments) * 100
            f.write(f"{role:25s}: {count:4d} segments ({percentage:5.1f}%)\n")

        # Role descriptions
        f.write("\n" + "="*80 + "\n")
        f.write("ROLE DEFINITIONS\n")
        f.write("="*80 + "\n\n")

        role_definitions = {
            'WOOL_RUNNER': 'Carries wool from enemy base to own base',
            'SKYBRIDGE_CONTROLLER': 'Stays on skybridge (high altitude), controls lanes with kills',
            'ATTACKER_STEALTH': 'Uses tunnels to infiltrate enemy territory',
            'RUSHER': 'Fast movement to enemy side immediately after spawn',
            'ATTACKER_AGGRESSIVE': 'Pushes enemy side with high kill count',
            'ATTACKER_PASSIVE': 'Moves to enemy side without many kills',
            'CAMPER': 'Minimal movement, waits for enemies and gets kills',
            'MID_CONTROLLER': 'Controls the middle area between territories',
            'BASE_DEFENDER': 'Guards own spawn area',
            'DEFENDER': 'Stays primarily on own side',
            'FLANKER': 'Moves around map edges with high mobility',
            'ROAMER': 'General roaming without clear pattern'
        }

        for role, count in role_counts.most_common():
            if role in role_definitions:
                f.write(f"{role}:\n")
                f.write(f"  {role_definitions[role]}\n\n")

        # Team-specific statistics
        f.write("="*80 + "\n")
        f.write("TEAM-SPECIFIC ROLE DISTRIBUTION\n")
        f.write("="*80 + "\n\n")

        for team in ['red', 'blue']:
            team_segments = [seg for seg in life_segments if seg.team == team]
            team_classifications = [classifications[i] for i, seg in enumerate(life_segments) if seg.team == team]

            if not team_classifications:
                continue

            f.write(f"{team.upper()} TEAM:\n")
            f.write("-"*80 + "\n")

            team_role_counts = Counter(c.primary_role for c in team_classifications)
            team_total = len(team_classifications)

            for role, count in team_role_counts.most_common(10):
                percentage = (count / team_total) * 100
                f.write(f"  {role:23s}: {count:4d} ({percentage:5.1f}%)\n")

            f.write("\n")

        # Top players by role
        f.write("="*80 + "\n")
        f.write("TOP PLAYERS BY ROLE\n")
        f.write("="*80 + "\n\n")

        # Group by player and role
        player_roles = defaultdict(lambda: defaultdict(int))
        player_kills = defaultdict(int)
        player_team = {}

        for i, seg in enumerate(life_segments):
            classification = classifications[i]
            player_roles[seg.player_id][classification.primary_role] += 1
            player_kills[seg.player_id] += classification.kills
            player_team[seg.player_id] = seg.team

        # Find specialists for each major role
        major_roles = [role for role, count in role_counts.most_common(8) if count > 10]

        for role in major_roles:
            f.write(f"{role}:\n")

            # Find players who used this role most
            role_specialists = []
            for player_id, roles in player_roles.items():
                role_count = roles[role]
                total_segments = sum(roles.values())
                if role_count > 0:
                    ratio = role_count / total_segments
                    role_specialists.append((player_id, role_count, total_segments, ratio, player_team[player_id]))

            role_specialists.sort(key=lambda x: x[1], reverse=True)

            for player_id, role_count, total, ratio, team in role_specialists[:5]:
                f.write(f"  Player {player_id:5.0f} ({team:4s}): {role_count:2d}/{total:2d} segments ({ratio*100:5.1f}%) - {player_kills[player_id]} total kills\n")

            f.write("\n")

        # Detailed segment examples
        f.write("="*80 + "\n")
        f.write("DETAILED SEGMENT EXAMPLES\n")
        f.write("="*80 + "\n\n")

        # Show examples for each major role
        shown_roles = Counter()
        examples_per_role = 2

        for i, seg in enumerate(life_segments):
            classification = classifications[i]
            role = classification.primary_role

            if role not in major_roles or shown_roles[role] >= examples_per_role:
                continue

            shown_roles[role] += 1

            f.write(f"Example {role} segment:\n")
            f.write("-"*80 + "\n")
            f.write(f"  Player: {seg.player_id} ({seg.team} team)\n")
            f.write(f"  Duration: {seg.end_time - seg.spawn_time:.1f}s\n")
            f.write(f"  Primary role: {classification.primary_role}\n")
            if classification.secondary_roles:
                f.write(f"  Secondary roles: {', '.join(classification.secondary_roles)}\n")
            f.write(f"  Description: {classification.description}\n")
            f.write(f"\n  Metrics:\n")
            f.write(f"    Time on own side: {classification.time_on_own_side:.1f}s ({classification.time_on_own_side/(seg.end_time - seg.spawn_time)*100:.0f}%)\n")
            f.write(f"    Time on enemy side: {classification.time_on_enemy_side:.1f}s ({classification.time_on_enemy_side/(seg.end_time - seg.spawn_time)*100:.0f}%)\n")
            f.write(f"    Time at skybridge: {classification.time_at_skybridge:.1f}s\n")
            f.write(f"    Time tunneling: {classification.time_tunneling:.1f}s\n")
            f.write(f"    Total distance: {classification.total_distance:.1f} blocks\n")
            f.write(f"    Average speed: {classification.avg_speed:.2f} blocks/s\n")
            f.write(f"    Max penetration: {classification.max_penetration_depth:.1f} blocks\n")
            f.write(f"    Kills: {classification.kills}\n")
            f.write(f"    Deaths: {classification.deaths}\n")
            f.write(f"    Wool interactions: {classification.wool_touches} touches, {classification.wool_captures} captures\n")
            f.write(f"  End reason: {seg.end_reason}\n")
            f.write("\n")

        f.write("="*80 + "\n")
        f.write("Report generated by CTW Analysis Toolkit\n")
        f.write("="*80 + "\n")

    print(f"\nClassification report saved to: {report_path}")


def export_classifications_csv(
    life_segments,
    classifications,
    output_dir: str = 'output'
) -> None:
    """
    Export classifications to CSV for further analysis.

    Args:
        life_segments: List of LifeSegment objects
        classifications: List of SegmentClassification objects
        output_dir: Output directory
    """
    os.makedirs(output_dir, exist_ok=True)
    csv_path = os.path.join(output_dir, 'segment_classifications.csv')

    rows = []
    for i, seg in enumerate(life_segments):
        classification = classifications[i]

        row = {
            'segment_id': i,
            'player_id': seg.player_id,
            'team': seg.team,
            'spawn_time': seg.spawn_time,
            'duration': seg.end_time - seg.spawn_time,
            'end_reason': seg.end_reason,
            **classification.to_dict()
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    df.to_csv(csv_path, index=False)
    print(f"Classifications exported to: {csv_path}")


def print_classification_summary(classifications) -> None:
    """Print a quick summary of classifications."""
    role_counts = Counter(c.primary_role for c in classifications)

    print("\n" + "="*70)
    print("CLASSIFICATION SUMMARY")
    print("="*70)
    print(f"\nTotal segments classified: {len(classifications)}\n")

    print("Role distribution:")
    for role, count in role_counts.most_common(15):
        percentage = (count / len(classifications)) * 100
        bar_length = int(percentage / 2)
        bar = '#' * bar_length
        print(f"  {role:25s}: {count:4d} ({percentage:5.1f}%) {bar}")

    print("="*70 + "\n")


def main():
    """Main classification pipeline."""
    print("="*70)
    print("CTW LIFE SEGMENT CLASSIFICATION")
    print("="*70)

    # Load configuration
    print("\n1. Loading configuration...")
    config = load_config()

    # Load data
    print("\n2. Loading data...")
    map_data = load_map_data(config['data_files']['map_name'])
    match_data = load_match_data(config['data_files']['match_file'])

    # Process match data
    print("\n3. Detecting life segments...")
    life_segments = detect_life_segments(match_data)
    life_segments = assign_teams(life_segments)

    # Analyze map characteristics
    print("\n4. Analyzing map characteristics...")
    map_chars = analyze_map_characteristics(life_segments, match_data)

    print(f"   Midpoint: {map_chars.midpoint_axis}={map_chars.midpoint_coord:.1f}")
    print(f"   Skybridge: Y={map_chars.skybridge_height:.1f}")
    print(f"   Tunnel threshold: Y={map_chars.tunnel_threshold:.1f}")

    # Classify segments
    print("\n5. Classifying life segments...")
    classifications = classify_all_segments(life_segments, map_chars)
    print(f"   Classified {len(classifications)} segments")

    # Print summary
    print_classification_summary(classifications)

    # Generate detailed report
    print("\n6. Generating reports...")
    output_dir = config['output']['folder']
    generate_classification_report(life_segments, classifications, map_chars, output_dir)
    export_classifications_csv(life_segments, classifications, output_dir)

    # Generate PDF reports (if enabled)
    if config.get('output', {}).get('generate_pdf', True):
        print("\n7. Generating PDF reports...")
        player_stats = calculate_player_stats(life_segments)

        classification_pdf = os.path.join(output_dir, 'classification_report.pdf')
        generate_classification_pdf(life_segments, classifications, map_chars, config, classification_pdf)

        match_summary_pdf = os.path.join(output_dir, 'match_summary.pdf')
        generate_match_summary_pdf(life_segments, player_stats, config, match_summary_pdf)

    print("\n" + "="*70)
    print("Classification complete!")
    print(f"  Text reports: {output_dir}/")
    print(f"  PDF reports: {output_dir}/")
    print("="*70 + "\n")


if __name__ == '__main__':
    main()
