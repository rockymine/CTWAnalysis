"""
CTW Utility Functions

Helper functions for analysis and data export.
"""

from typing import List, Tuple
import pandas as pd
import csv

from .preprocessing import LifeSegment
from .constants import EVENT_TYPES


def get_map_bounds(map_data: pd.DataFrame) -> Tuple[float, float, float, float]:
    """
    Get map boundary coordinates.

    Args:
        map_data: DataFrame with X, Z columns

    Returns:
        Tuple of (x_min, x_max, z_min, z_max)
    """
    return (
        map_data['X'].min(),
        map_data['X'].max(),
        map_data['Z'].min(),
        map_data['Z'].max()
    )


def calculate_player_stats(life_segments: List[LifeSegment]) -> pd.DataFrame:
    """
    Aggregate statistics per player across all life segments.

    Args:
        life_segments: List of LifeSegment objects

    Returns:
        DataFrame with columns: player_id, total_segments, total_kills, total_deaths,
                               total_wool_touches, total_wool_captures, primary_team
    """
    from collections import defaultdict, Counter

    stats = defaultdict(lambda: {
        'total_segments': 0,
        'total_kills': 0,
        'total_deaths': 0,
        'total_wool_touches': 0,
        'total_wool_captures': 0,
        'teams': []
    })

    for segment in life_segments:
        player_id = segment.player_id
        stats[player_id]['total_segments'] += 1
        stats[player_id]['total_kills'] += segment.to_dict()['kills']
        stats[player_id]['total_deaths'] += segment.to_dict()['deaths']
        stats[player_id]['total_wool_touches'] += segment.to_dict()['wool_touches']
        stats[player_id]['total_wool_captures'] += segment.to_dict()['wool_captures']
        stats[player_id]['teams'].append(segment.team)

    # Convert to DataFrame
    rows = []
    for player_id, data in stats.items():
        # Determine primary team (most common)
        team_counts = Counter(data['teams'])
        primary_team = team_counts.most_common(1)[0][0] if team_counts else 'unknown'

        rows.append({
            'player_id': player_id,
            'total_segments': data['total_segments'],
            'total_kills': data['total_kills'],
            'total_deaths': data['total_deaths'],
            'total_wool_touches': data['total_wool_touches'],
            'total_wool_captures': data['total_wool_captures'],
            'primary_team': primary_team
        })

    return pd.DataFrame(rows).sort_values('total_kills', ascending=False)


def export_segments_to_csv(life_segments: List[LifeSegment], output_path: str) -> None:
    """
    Export life segments to CSV for external analysis.

    Args:
        life_segments: List of LifeSegment objects
        output_path: Path to output CSV file
    """
    with open(output_path, 'w', newline='') as csvfile:
        fieldnames = [
            'player_id', 'segment_id', 'team',
            'spawn_time', 'end_time', 'duration',
            'spawn_x', 'spawn_y', 'spawn_z',
            'end_reason', 'num_events',
            'kills', 'deaths', 'wool_touches', 'wool_captures'
        ]

        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for segment in life_segments:
            seg_dict = segment.to_dict()
            row = {
                'player_id': segment.player_id,
                'segment_id': segment.segment_id,
                'team': segment.team,
                'spawn_time': segment.spawn_time,
                'end_time': segment.end_time,
                'duration': segment.end_time - segment.spawn_time if segment.end_time else None,
                'spawn_x': segment.spawn_coords[0] if segment.spawn_coords else None,
                'spawn_y': segment.spawn_coords[1] if segment.spawn_coords else None,
                'spawn_z': segment.spawn_coords[2] if segment.spawn_coords else None,
                'end_reason': segment.end_reason,
                'num_events': seg_dict['num_events'],
                'kills': seg_dict['kills'],
                'deaths': seg_dict['deaths'],
                'wool_touches': seg_dict['wool_touches'],
                'wool_captures': seg_dict['wool_captures']
            }
            writer.writerow(row)

    print(f"Exported {len(life_segments)} life segments to {output_path}")


def print_match_summary(life_segments: List[LifeSegment]) -> None:
    """
    Print a summary of the match statistics.

    Args:
        life_segments: List of LifeSegment objects
    """
    from collections import Counter

    print("\n" + "="*60)
    print("MATCH SUMMARY")
    print("="*60)

    # Player stats
    unique_players = len(set(seg.player_id for seg in life_segments))
    print(f"Total Players: {unique_players}")
    print(f"Total Life Segments: {len(life_segments)}")

    # Team distribution
    team_counts = Counter(seg.team for seg in life_segments)
    print(f"\nTeam Distribution:")
    for team, count in team_counts.items():
        print(f"  {team.capitalize()}: {count} segments")

    # End reasons
    end_reasons = Counter(seg.end_reason for seg in life_segments)
    print(f"\nLife Segment End Reasons:")
    for reason, count in end_reasons.items():
        print(f"  {reason}: {count}")

    # Aggregate stats
    total_kills = sum(seg.to_dict()['kills'] for seg in life_segments)
    total_deaths = sum(seg.to_dict()['deaths'] for seg in life_segments)
    total_wool_touches = sum(seg.to_dict()['wool_touches'] for seg in life_segments)
    total_wool_captures = sum(seg.to_dict()['wool_captures'] for seg in life_segments)

    print(f"\nTotal Events:")
    print(f"  Kills: {total_kills}")
    print(f"  Deaths: {total_deaths}")
    print(f"  Wool Touches: {total_wool_touches}")
    print(f"  Wool Captures: {total_wool_captures}")

    print("="*60 + "\n")
