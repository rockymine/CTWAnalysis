"""Infer player team membership from spawn positions and map spawn regions.

Loads team spawn centers from preprocessed map_data.json and assigns each
player's SPAWN events to a team by nearest-center Euclidean distance.
Consecutive spawns on the same team are merged into a single time segment.
"""

import json
import math
from pathlib import Path

import pandas as pd


def load_team_spawn_centers(map_data_path: str) -> list[dict]:
    """Load team spawn center coordinates from map_data.json.

    Args:
        map_data_path: Path to the preprocessed map_data.json file.

    Returns:
        List of dicts with keys: team (str), x (float), z (float).
        Empty list if file not found or has no spawns.
    """
    path = Path(map_data_path)
    if not path.exists():
        return []

    with open(path) as f:
        data = json.load(f)

    centers = []
    for spawn in data.get('spawns', []):
        team_raw = spawn.get('team', '')
        if not team_raw:
            continue

        region = spawn.get('region')
        if region is None:
            continue

        bounds = region.get('bounds_2d')
        if bounds is None:
            continue

        mn = bounds.get('min', {})
        mx = bounds.get('max', {})
        x = (mn.get('x', 0) + mx.get('x', 0)) / 2
        z = (mn.get('z', 0) + mx.get('z', 0)) / 2

        # Normalize: "red-team" -> "red"
        team = team_raw.removesuffix('-team')

        centers.append({'team': team, 'x': x, 'z': z})

    return centers


def infer_team(spawn_x: float, spawn_z: float, spawn_centers: list[dict]) -> str:
    """Determine team by nearest spawn center (Euclidean distance in X/Z).

    Returns:
        Team string (e.g. "red", "blue") or "unknown" if no centers available.
    """
    if not spawn_centers:
        return 'unknown'

    best_team = 'unknown'
    best_dist = math.inf

    for center in spawn_centers:
        dx = spawn_x - center['x']
        dz = spawn_z - center['z']
        dist = math.hypot(dx, dz)
        if dist < best_dist:
            best_dist = dist
            best_team = center['team']

    return best_team


def extract_team_segments(
    match_file: str,
    spawn_centers: list[dict],
) -> pd.DataFrame:
    """Build team membership segments for all players in a match.

    For each player, SPAWN events (event_type=2) are read chronologically.
    Each spawn's team is inferred from the nearest spawn center.  Consecutive
    spawns on the same team are merged into a single segment.

    Args:
        match_file: Path to raw match parquet file.
        spawn_centers: Output of load_team_spawn_centers().

    Returns:
        DataFrame with columns: player_id, team, start_timestamp,
        end_timestamp, spawn_x, spawn_z.
        end_timestamp is None for the last segment of each player.
    """
    df = pd.read_parquet(match_file)
    spawns = df[df['event_type'] == 2].copy()

    if len(spawns) == 0:
        return pd.DataFrame(columns=[
            'player_id', 'team', 'start_timestamp',
            'end_timestamp', 'spawn_x', 'spawn_z',
        ])

    segments = []

    for player_id in spawns['player_id'].dropna().unique():
        player_spawns = spawns[spawns['player_id'] == player_id].sort_values('timestamp')

        current_team = None
        seg_start = None
        seg_spawn_x = None
        seg_spawn_z = None

        for row in player_spawns.itertuples():
            team = infer_team(row.x, row.z, spawn_centers)

            if team != current_team:
                # Close previous segment
                if current_team is not None:
                    segments.append({
                        'player_id': int(player_id),
                        'team': current_team,
                        'start_timestamp': int(seg_start),
                        'end_timestamp': int(row.timestamp),
                        'spawn_x': float(seg_spawn_x),
                        'spawn_z': float(seg_spawn_z),
                    })

                # Start new segment
                current_team = team
                seg_start = row.timestamp
                seg_spawn_x = row.x
                seg_spawn_z = row.z

        # Close final segment (end_timestamp = None → until match end)
        if current_team is not None:
            segments.append({
                'player_id': int(player_id),
                'team': current_team,
                'start_timestamp': int(seg_start),
                'end_timestamp': None,
                'spawn_x': float(seg_spawn_x),
                'spawn_z': float(seg_spawn_z),
            })

    return pd.DataFrame(segments)
