"""
CTW Preprocessing

Functions for detecting life segments and assigning teams.
"""

from typing import List, Dict, Tuple
import pandas as pd
import numpy as np
from sklearn.cluster import DBSCAN
from collections import Counter

from .constants import EVENT_IDS, SPAWN_CLUSTER_RADIUS, MIN_CLUSTER_SIZE


class LifeSegment:
    """
    Represents a single life segment for a player.

    A life segment begins with a spawn and ends with death, match end,
    or a new spawn (team switch).
    """

    def __init__(self, player_id: float, segment_id: int):
        self.player_id = player_id
        self.segment_id = segment_id
        self.spawn_time: int = None
        self.end_time: int = None
        self.spawn_coords: Tuple[float, float, float] = None
        self.end_reason: str = None  # 'death', 'match_end', 'team_switch', 'incomplete'
        self.team: str = 'unknown'
        self.events: pd.DataFrame = pd.DataFrame()

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            'player_id': self.player_id,
            'segment_id': self.segment_id,
            'spawn_time': self.spawn_time,
            'end_time': self.end_time,
            'spawn_coords': self.spawn_coords,
            'end_reason': self.end_reason,
            'team': self.team,
            'num_events': len(self.events),
            'kills': len(self.events[self.events['event_type'] == EVENT_IDS['KILL']]),
            'deaths': len(self.events[self.events['event_type'] == EVENT_IDS['DEATH']]),
            'wool_touches': len(self.events[self.events['event_type'] == EVENT_IDS['WOOL_TOUCH']]),
            'wool_captures': len(self.events[self.events['event_type'] == EVENT_IDS['WOOL_CAPTURE']])
        }

    def __repr__(self):
        return (f"LifeSegment(player={self.player_id}, segment={self.segment_id}, "
                f"team={self.team}, duration={self.end_time - self.spawn_time if self.end_time else 'ongoing'})")


def detect_life_segments(match_data: pd.DataFrame) -> List[LifeSegment]:
    """
    Split player match history into individual life segments.

    A life segment begins with a SPAWN event and ends with:
    - DEATH event
    - Next SPAWN event (team switch)
    - MATCH_END event
    - Last POSITION event (player left)

    Args:
        match_data: Match event log DataFrame

    Returns:
        List of LifeSegment objects

    """
    print("Detecting life segments...")

    # Filter out NaN player IDs (match start/end events)
    player_data = match_data[match_data['player_id'].notna()].copy()

    # Sort by player and timestamp
    player_data = player_data.sort_values(['player_id', 'timestamp'])

    # Get unique players
    players = player_data['player_id'].unique()

    life_segments = []

    for player_id in players:
        player_events = player_data[player_data['player_id'] == player_id].copy()

        # Find all spawn events for this player
        spawn_events = player_events[player_events['event_type'] == EVENT_IDS['SPAWN']]

        if spawn_events.empty:
            # Player has no spawn events (spectator or incomplete data)
            continue

        segment_id = 0

        for idx, (spawn_idx, spawn_row) in enumerate(spawn_events.iterrows()):
            segment = LifeSegment(player_id, segment_id)
            segment.spawn_time = spawn_row['timestamp']
            segment.spawn_coords = (spawn_row['x'], spawn_row['y'], spawn_row['z'])

            # Find the end of this segment
            # Next spawn (team switch)
            next_spawns = spawn_events[spawn_events['timestamp'] > spawn_row['timestamp']]
            next_spawn_time = next_spawns['timestamp'].min() if not next_spawns.empty else None

            # Death events after this spawn
            death_events = player_events[
                (player_events['event_type'] == EVENT_IDS['DEATH']) &
                (player_events['timestamp'] > spawn_row['timestamp'])
            ]

            if next_spawn_time is not None:
                death_events = death_events[death_events['timestamp'] < next_spawn_time]

            # Determine end time and reason
            if not death_events.empty:
                # Ended by death
                segment.end_time = death_events['timestamp'].min()
                segment.end_reason = 'death'
            elif next_spawn_time is not None:
                # Ended by team switch (new spawn)
                segment.end_time = next_spawn_time
                segment.end_reason = 'team_switch'
            else:
                # No death or next spawn - check for match end or last position
                match_end_events = match_data[match_data['event_type'] == EVENT_IDS['MATCH_END']]
                if not match_end_events.empty:
                    segment.end_time = match_end_events['timestamp'].max()
                    segment.end_reason = 'match_end'
                else:
                    # Use last position event
                    last_position = player_events[
                        (player_events['event_type'] == EVENT_IDS['POSITION']) &
                        (player_events['timestamp'] > spawn_row['timestamp'])
                    ]
                    if not last_position.empty:
                        segment.end_time = last_position['timestamp'].max()
                        segment.end_reason = 'incomplete'
                    else:
                        # No events after spawn - skip this segment
                        continue

            # Collect all events in this segment
            segment.events = player_events[
                (player_events['timestamp'] >= segment.spawn_time) &
                (player_events['timestamp'] <= segment.end_time)
            ].copy()

            life_segments.append(segment)
            segment_id += 1

    print(f"Detected {len(life_segments)} life segments from {len(players)} players")
    return life_segments


def cluster_spawn_points(life_segments: List[LifeSegment]) -> Dict:
    """
    Cluster spawn coordinates to identify team regions.

    Uses DBSCAN clustering to group spawns into team regions (typically 2: red and blue).

    Args:
        life_segments: List of LifeSegment objects

    Returns:
        Dictionary with cluster information:
        {
            'cluster_labels': array of cluster labels for each segment,
            'cluster_centers': dict mapping cluster_id -> (x, z) center,
            'team_mapping': dict mapping cluster_id -> 'red'/'blue'/'unknown'
        }
    """
    print("Clustering spawn points to identify teams...")

    # Extract spawn coordinates (x, z only for 2D clustering)
    spawn_coords = np.array([seg.spawn_coords[:1] + seg.spawn_coords[2:] for seg in life_segments])

    # Apply DBSCAN clustering
    clustering = DBSCAN(eps=SPAWN_CLUSTER_RADIUS, min_samples=MIN_CLUSTER_SIZE)
    cluster_labels = clustering.fit_predict(spawn_coords)

    # Calculate cluster centers
    unique_labels = set(cluster_labels)
    cluster_centers = {}

    for label in unique_labels:
        if label == -1:  # Noise/outliers
            continue

        mask = cluster_labels == label
        cluster_points = spawn_coords[mask]
        center = cluster_points.mean(axis=0)
        cluster_centers[label] = tuple(center)

    # Identify the two main clusters (teams)
    cluster_sizes = Counter(cluster_labels)
    # Ignore noise (-1)
    valid_clusters = [(label, size) for label, size in cluster_sizes.items() if label != -1]
    valid_clusters.sort(key=lambda x: x[1], reverse=True)

    team_mapping = {}

    if len(valid_clusters) >= 2:
        # Assign red/blue based on X coordinate (or Z if X is similar)
        cluster_1, cluster_2 = valid_clusters[0][0], valid_clusters[1][0]
        center_1 = cluster_centers[cluster_1]
        center_2 = cluster_centers[cluster_2]

        # Red team typically spawns at lower X coordinate
        if center_1[0] < center_2[0]:
            team_mapping[cluster_1] = 'red'
            team_mapping[cluster_2] = 'blue'
        else:
            team_mapping[cluster_1] = 'blue'
            team_mapping[cluster_2] = 'red'

        # Additional clusters are marked as unknown
        for label, _ in valid_clusters[2:]:
            team_mapping[label] = 'unknown'

        print(f"Found {len(valid_clusters)} spawn clusters")
        print(f"  Red team center: {cluster_centers[cluster_1 if team_mapping[cluster_1] == 'red' else cluster_2]}")
        print(f"  Blue team center: {cluster_centers[cluster_2 if team_mapping[cluster_2] == 'blue' else cluster_1]}")

    elif len(valid_clusters) == 1:
        # Only one cluster found - assign as unknown
        team_mapping[valid_clusters[0][0]] = 'unknown'
        print(f"Warning: Only 1 spawn cluster found - cannot identify teams")

    else:
        print(f"Warning: No valid spawn clusters found")

    # Outliers (-1) are marked as unknown
    team_mapping[-1] = 'unknown'

    return {
        'cluster_labels': cluster_labels,
        'cluster_centers': cluster_centers,
        'team_mapping': team_mapping
    }


def assign_teams(life_segments: List[LifeSegment]) -> List[LifeSegment]:
    """
    Assign team labels to life segments based on spawn location clustering.

    Each life segment is assigned independently, allowing for team switches
    (different spawns for the same player).

    Args:
        life_segments: List of LifeSegment objects

    Returns:
        Updated list of LifeSegment objects with team assignments
    """
    if not life_segments:
        print("No life segments to assign teams")
        return life_segments

    # Cluster spawn points
    cluster_info = cluster_spawn_points(life_segments)

    # Assign teams to segments
    for segment, cluster_label in zip(life_segments, cluster_info['cluster_labels']):
        segment.team = cluster_info['team_mapping'].get(cluster_label, 'unknown')

    # Print team distribution
    team_counts = Counter(seg.team for seg in life_segments)
    print(f"Team distribution: {dict(team_counts)}")

    return life_segments
