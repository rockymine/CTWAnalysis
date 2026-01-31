"""
CTW Data Loader

Functions for loading map and match data from parquet files.
"""

import os
from pathlib import Path
from typing import List
import pandas as pd

# Base directories
MAP_DATA_DIR = Path("map_data")
MATCH_LOGS_DIR = Path("match_logs")


def load_map_data(map_name: str) -> pd.DataFrame:
    """
    Load map bedrock data from parquet file.

    Args:
        map_name: Name of the map (without .parquet extension)

    Returns:
        DataFrame with columns: X, Y, Z

    Raises:
        FileNotFoundError: If map file doesn't exist
        ValueError: If map data is invalid or empty
    """
    # Add .parquet extension if not present
    if not map_name.endswith('.parquet'):
        map_name = f"{map_name}.parquet"

    map_path = MAP_DATA_DIR / map_name

    if not map_path.exists():
        raise FileNotFoundError(
            f"Map file not found: {map_path}\n"
            f"Available maps: {', '.join(list_available_maps())}"
        )

    try:
        map_data = pd.read_parquet(map_path)
    except Exception as e:
        raise ValueError(f"Failed to load map data from {map_path}: {e}")

    # Validate structure
    required_columns = ['X', 'Z']
    missing_columns = set(required_columns) - set(map_data.columns)
    if missing_columns:
        raise ValueError(f"Map data missing required columns: {missing_columns}")

    if map_data.empty:
        raise ValueError(f"Map data is empty: {map_path}")

    print(f"Loaded map '{map_name}': {len(map_data)} blocks")
    return map_data


def load_match_data(match_file: str) -> pd.DataFrame:
    """
    Load match event log from parquet file.

    Args:
        match_file: Filename of the match (with or without .parquet extension)

    Returns:
        DataFrame with columns: timestamp, event_type, player_id, x, y, z,
                               held_item, inventory_count, wool_id

    Raises:
        FileNotFoundError: If match file doesn't exist
        ValueError: If match data is invalid or empty
    """
    # Add .parquet extension if not present
    if not match_file.endswith('.parquet'):
        match_file = f"{match_file}.parquet"

    match_path = MATCH_LOGS_DIR / match_file

    if not match_path.exists():
        raise FileNotFoundError(
            f"Match file not found: {match_path}\n"
            f"Available matches: {', '.join(list_available_matches()[:5])} ..."
        )

    try:
        match_data = pd.read_parquet(match_path)
    except Exception as e:
        raise ValueError(f"Failed to load match data from {match_path}: {e}")

    # Validate structure
    required_columns = ['timestamp', 'event_type', 'player_id', 'x', 'y', 'z']
    missing_columns = set(required_columns) - set(match_data.columns)
    if missing_columns:
        raise ValueError(f"Match data missing required columns: {missing_columns}")

    if match_data.empty:
        raise ValueError(f"Match data is empty: {match_path}")

    print(f"Loaded match '{match_file}': {len(match_data)} events, "
          f"{match_data['player_id'].nunique()} unique players")
    return match_data


def list_available_maps() -> List[str]:
    """
    List all available map names.

    Returns:
        List of map names (without .parquet extension)
    """
    if not MAP_DATA_DIR.exists():
        return []

    maps = [
        f.stem for f in MAP_DATA_DIR.glob("*.parquet")
    ]
    return sorted(maps)


def list_available_matches() -> List[str]:
    """
    List all available match files.

    Returns:
        List of match filenames (without .parquet extension)
    """
    if not MATCH_LOGS_DIR.exists():
        return []

    matches = [
        f.stem for f in MATCH_LOGS_DIR.glob("*.parquet")
    ]
    return sorted(matches, reverse=True)  # Most recent first


def get_match_info(match_file: str) -> dict:
    """
    Get basic information about a match without loading full data.

    Args:
        match_file: Match filename (with or without .parquet)

    Returns:
        Dictionary with match metadata
    """
    if not match_file.endswith('.parquet'):
        match_file = f"{match_file}.parquet"

    match_path = MATCH_LOGS_DIR / match_file

    if not match_path.exists():
        raise FileNotFoundError(f"Match file not found: {match_path}")

    # Load with minimal columns for speed
    match_data = pd.read_parquet(match_path, columns=['event_type', 'player_id', 'timestamp'])

    from .constants import EVENT_TYPES

    return {
        'filename': match_file,
        'total_events': len(match_data),
        'unique_players': match_data['player_id'].nunique(),
        'start_time': match_data['timestamp'].min(),
        'end_time': match_data['timestamp'].max(),
        'duration_seconds': match_data['timestamp'].max() - match_data['timestamp'].min(),
        'event_counts': match_data['event_type'].value_counts().to_dict()
    }
