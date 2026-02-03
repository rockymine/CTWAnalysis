"""
CTW Life Segment Classifier

Classifies player life segments based on positioning, movement patterns, and actions.
"""

from typing import List, Tuple, Dict, Optional
import numpy as np
import pandas as pd
from collections import Counter

from .preprocessing import LifeSegment
from .constants import EVENT_IDS


class MapCharacteristics:
    """Store map-specific characteristics for classification."""

    def __init__(
        self,
        midpoint_coord: float,
        midpoint_axis: str,  # 'x' or 'z'
        red_side_positive: bool,  # True if red team is on positive side of midpoint
        skybridge_height: float,
        ground_level: float,
        tunnel_threshold: float
    ):
        self.midpoint_coord = midpoint_coord
        self.midpoint_axis = midpoint_axis
        self.red_side_positive = red_side_positive
        self.skybridge_height = skybridge_height
        self.ground_level = ground_level
        self.tunnel_threshold = tunnel_threshold

    def is_on_own_side(self, team: str, coord_value: float) -> bool:
        """Check if a coordinate is on the team's own side."""
        if team == 'red':
            if self.red_side_positive:
                return coord_value > self.midpoint_coord
            else:
                return coord_value < self.midpoint_coord
        elif team == 'blue':
            if self.red_side_positive:
                return coord_value < self.midpoint_coord
            else:
                return coord_value > self.midpoint_coord
        return False

    def distance_from_midpoint(self, coord_value: float) -> float:
        """Calculate distance from map midpoint."""
        return abs(coord_value - self.midpoint_coord)


def analyze_map_characteristics(life_segments: List[LifeSegment], match_data: pd.DataFrame) -> MapCharacteristics:
    """
    Analyze map characteristics from life segments.

    Args:
        life_segments: List of LifeSegment objects
        match_data: Full match data DataFrame

    Returns:
        MapCharacteristics object
    """
    # Get team spawn centers
    red_segments = [seg for seg in life_segments if seg.team == 'red']
    blue_segments = [seg for seg in life_segments if seg.team == 'blue']

    if not red_segments or not blue_segments:
        raise ValueError("Need both red and blue team segments")

    red_spawns = np.array([seg.spawn_coords for seg in red_segments])
    blue_spawns = np.array([seg.spawn_coords for seg in blue_segments])

    red_center = red_spawns.mean(axis=0)
    blue_center = blue_spawns.mean(axis=0)

    # Determine map split axis
    x_diff = abs(red_center[0] - blue_center[0])
    z_diff = abs(red_center[2] - blue_center[2])

    if z_diff > x_diff:
        midpoint_axis = 'z'
        midpoint_coord = (red_center[2] + blue_center[2]) / 2
        red_side_positive = red_center[2] > blue_center[2]
    else:
        midpoint_axis = 'x'
        midpoint_coord = (red_center[0] + blue_center[0]) / 2
        red_side_positive = red_center[0] > blue_center[0]

    # Analyze Y coordinates
    position_events = match_data[match_data['event_type'] == EVENT_IDS['POSITION']]

    # Build height: mode of top 5% Y values
    high_y_threshold = position_events['y'].quantile(0.95)
    high_y_events = position_events[position_events['y'] >= high_y_threshold]
    skybridge_height = high_y_events['y'].mode()[0] if len(high_y_events) > 0 else high_y_threshold

    # Ground level: 25th percentile
    ground_level = position_events['y'].quantile(0.25)

    # Tunnel threshold: 5th percentile
    tunnel_threshold = position_events['y'].quantile(0.05)

    return MapCharacteristics(
        midpoint_coord=midpoint_coord,
        midpoint_axis=midpoint_axis,
        red_side_positive=red_side_positive,
        skybridge_height=skybridge_height,
        ground_level=ground_level,
        tunnel_threshold=tunnel_threshold
    )


class SegmentClassification:
    """Classification result for a life segment."""

    def __init__(self):
        # Primary role
        self.primary_role: str = 'unknown'
        self.secondary_roles: List[str] = []

        # Metrics
        self.time_on_own_side: float = 0.0
        self.time_on_enemy_side: float = 0.0
        self.time_at_skybridge: float = 0.0
        self.time_tunneling: float = 0.0
        self.time_stationary: float = 0.0

        # Movement
        self.total_distance: float = 0.0
        self.avg_speed: float = 0.0
        self.max_penetration_depth: float = 0.0

        # Combat
        self.kills: int = 0
        self.deaths: int = 0
        self.kill_efficiency: float = 0.0

        # Wool
        self.wool_touches: int = 0
        self.wool_captures: int = 0

        # Description
        self.description: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'primary_role': self.primary_role,
            'secondary_roles': ','.join(self.secondary_roles),
            'time_on_own_side': self.time_on_own_side,
            'time_on_enemy_side': self.time_on_enemy_side,
            'time_at_skybridge': self.time_at_skybridge,
            'time_tunneling': self.time_tunneling,
            'time_stationary': self.time_stationary,
            'total_distance': self.total_distance,
            'avg_speed': self.avg_speed,
            'max_penetration_depth': self.max_penetration_depth,
            'kills': self.kills,
            'deaths': self.deaths,
            'wool_touches': self.wool_touches,
            'wool_captures': self.wool_captures,
            'description': self.description
        }


def classify_segment(segment: LifeSegment, map_chars: MapCharacteristics) -> SegmentClassification:
    """
    Classify a life segment based on positioning and actions.

    Classification Categories:
    - DEFENDER: Stays primarily on own side, reactive positioning
    - ATTACKER_AGGRESSIVE: Pushes enemy side with kills
    - ATTACKER_STEALTH: Tunnels or sneaks to enemy side
    - RUSHER: Fast movement to enemy side immediately after spawn
    - SKYBRIDGE_CONTROLLER: Stays on skybridge, controls lanes
    - CAMPER: Minimal movement, waits for enemies
    - WOOL_RUNNER: Carries wool back to base
    - ESCORT: Supports wool carriers
    - FLANKER: Moves around map edges
    - BASE_DEFENDER: Guards spawn area
    - MID_CONTROLLER: Controls middle area

    Args:
        segment: LifeSegment object
        map_chars: MapCharacteristics object

    Returns:
        SegmentClassification object
    """
    classification = SegmentClassification()

    # Get position events
    position_events = segment.events[segment.events['event_type'] == EVENT_IDS['POSITION']].copy()

    if len(position_events) < 2:
        classification.primary_role = 'insufficient_data'
        classification.description = "Too few position events to classify"
        return classification

    # Extract segment statistics
    seg_dict = segment.to_dict()
    classification.kills = seg_dict['kills']
    classification.deaths = seg_dict['deaths']
    classification.wool_touches = seg_dict['wool_touches']
    classification.wool_captures = seg_dict['wool_captures']

    duration = segment.end_time - segment.spawn_time

    # Calculate movement metrics
    distances = []
    timestamps = []
    for i in range(1, len(position_events)):
        prev = position_events.iloc[i-1]
        curr = position_events.iloc[i]
        dist = np.sqrt(
            (curr['x'] - prev['x'])**2 +
            (curr['y'] - prev['y'])**2 +
            (curr['z'] - prev['z'])**2
        )
        distances.append(dist)
        timestamps.append(curr['timestamp'] - prev['timestamp'])

    classification.total_distance = sum(distances) if distances else 0.0
    classification.avg_speed = classification.total_distance / duration if duration > 0 else 0.0

    # Analyze positioning over time
    coord_axis = map_chars.midpoint_axis
    position_events['main_coord'] = position_events['z'] if coord_axis == 'z' else position_events['x']

    time_on_own_side = 0.0
    time_on_enemy_side = 0.0
    time_at_skybridge = 0.0
    time_tunneling = 0.0
    max_penetration = 0.0

    for i in range(len(position_events)):
        row = position_events.iloc[i]

        # Time step (assume ~1 second between position updates or use actual)
        if i < len(position_events) - 1:
            time_delta = position_events.iloc[i+1]['timestamp'] - row['timestamp']
        else:
            time_delta = 1.0

        # Check territory
        on_own_side = map_chars.is_on_own_side(segment.team, row['main_coord'])
        penetration = map_chars.distance_from_midpoint(row['main_coord'])

        if on_own_side:
            time_on_own_side += time_delta
        else:
            time_on_enemy_side += time_delta
            max_penetration = max(max_penetration, penetration)

        # Check Y level
        if row['y'] >= map_chars.skybridge_height - 1:  # Within 1 block of skybridge
            time_at_skybridge += time_delta
        elif row['y'] <= map_chars.tunnel_threshold:
            time_tunneling += time_delta

    classification.time_on_own_side = time_on_own_side
    classification.time_on_enemy_side = time_on_enemy_side
    classification.time_at_skybridge = time_at_skybridge
    classification.time_tunneling = time_tunneling
    classification.max_penetration_depth = max_penetration

    # Calculate stationarity (low movement speed)
    stationary_threshold = 0.5  # blocks/second
    if classification.avg_speed < stationary_threshold:
        classification.time_stationary = duration

    # CLASSIFICATION LOGIC
    territory_ratio = time_on_enemy_side / duration if duration > 0 else 0
    skybridge_ratio = time_at_skybridge / duration if duration > 0 else 0
    tunnel_ratio = time_tunneling / duration if duration > 0 else 0
    own_side_ratio = time_on_own_side / duration if duration > 0 else 0

    kill_rate = classification.kills / (duration / 60) if duration > 0 else 0  # kills per minute

    # Primary role classification
    roles = []

    # Wool carrier
    if classification.wool_touches > 0 or classification.wool_captures > 0:
        roles.append(('WOOL_RUNNER', 100))
        if classification.wool_captures > 0:
            classification.description = f"Wool carrier with {classification.wool_captures} capture(s)"
        else:
            classification.description = f"Wool carrier with {classification.wool_touches} touch(es)"

    # Skybridge controller
    elif skybridge_ratio > 0.7 and classification.kills >= 2:
        roles.append(('SKYBRIDGE_CONTROLLER', 90))
        classification.description = f"Controls skybridge with {classification.kills} kills"

    # Tunnel attacker
    elif tunnel_ratio > 0.5 and territory_ratio > 0.6:
        roles.append(('ATTACKER_STEALTH', 85))
        classification.description = f"Tunnels to enemy side ({tunnel_ratio*100:.0f}% underground)"

    # Rusher (fast movement to enemy side early)
    elif classification.avg_speed > 3.0 and territory_ratio > 0.7 and duration < 120:
        roles.append(('RUSHER', 90))
        classification.description = f"Fast rush ({classification.avg_speed:.1f} blocks/s)"

    # Aggressive attacker
    elif territory_ratio > 0.6 and classification.kills >= 2:
        roles.append(('ATTACKER_AGGRESSIVE', 85))
        classification.description = f"Aggressive attack with {classification.kills} kills"

    # Passive attacker
    elif territory_ratio > 0.6:
        roles.append(('ATTACKER_PASSIVE', 75))
        classification.description = f"Pushes enemy side ({territory_ratio*100:.0f}% enemy territory)"

    # Camper
    elif classification.avg_speed < 0.5 and classification.kills >= 2:
        roles.append(('CAMPER', 80))
        classification.description = f"Camps with {classification.kills} kills"

    # Mid controller
    elif abs(territory_ratio - 0.5) < 0.2 and classification.kills >= 1:
        roles.append(('MID_CONTROLLER', 75))
        classification.description = "Controls middle area"

    # Base defender
    elif own_side_ratio > 0.8 and max_penetration < 30:
        roles.append(('BASE_DEFENDER', 80))
        classification.description = "Guards base area"

    # General defender
    elif own_side_ratio > 0.6:
        roles.append(('DEFENDER', 70))
        classification.description = f"Defends own side ({own_side_ratio*100:.0f}%)"

    # Flanker (high movement, crosses sides)
    elif classification.total_distance > 200 and 0.3 < territory_ratio < 0.7:
        roles.append(('FLANKER', 65))
        classification.description = f"Flanks ({classification.total_distance:.0f} blocks traveled)"

    # Default
    else:
        roles.append(('ROAMER', 50))
        classification.description = "General roaming"

    # Add secondary roles
    if skybridge_ratio > 0.3 and 'SKYBRIDGE_CONTROLLER' not in [r[0] for r in roles]:
        classification.secondary_roles.append('skybridge_user')

    if tunnel_ratio > 0.2 and 'ATTACKER_STEALTH' not in [r[0] for r in roles]:
        classification.secondary_roles.append('tunneler')

    if classification.kills >= 3 and kill_rate > 1.0:
        classification.secondary_roles.append('high_kills')

    if classification.avg_speed > 2.5:
        classification.secondary_roles.append('mobile')

    # Select primary role (highest confidence)
    if roles:
        roles.sort(key=lambda x: x[1], reverse=True)
        classification.primary_role = roles[0][0]

    return classification


def classify_all_segments(
    life_segments: List[LifeSegment],
    map_chars: MapCharacteristics
) -> List[SegmentClassification]:
    """
    Classify all life segments.

    Args:
        life_segments: List of LifeSegment objects
        map_chars: MapCharacteristics object

    Returns:
        List of SegmentClassification objects
    """
    classifications = []
    for segment in life_segments:
        classification = classify_segment(segment, map_chars)
        classifications.append(classification)

    return classifications
