"""Match data service — life segment extraction and DB queries."""

import duckdb
import pandas as pd
from pathlib import Path


DB_PATH = 'match_analysis/metadata.db'


def get_match_file(match_id: int) -> tuple[str, str]:
    """Look up match file path and map name from the database.

    Returns:
        (match_file, map_name) tuple.  The match_file path is normalized
        to the current platform's separator convention.

    Raises:
        ValueError: If match_id not found in database.
    """
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        result = conn.execute(
            "SELECT match_file, map_name FROM matches WHERE match_id = ?",
            [match_id],
        ).fetchone()
    finally:
        conn.close()

    if not result:
        raise ValueError(f"Match {match_id} not found in database")

    # Normalize stored path to current platform (handles legacy backslash paths)
    match_file = str(Path(result[0].replace('\\', '/')))
    return match_file, result[1]


def extract_player_life_segments(
    match_file: str,
    player_id: int,
) -> list[dict]:
    """Extract life segments for a single player from a match parquet file.

    Each life segment spans from a SPAWN event (type 2) to the next DEATH
    event (type 4) or end of match.  For each segment the trace events
    (kills, positions, wool touches/captures) are collected.

    Args:
        match_file: Path to raw match parquet file.
        player_id: Player ID to extract segments for.

    Returns:
        List of segment dicts, each containing:
            trace_events, positions, kills, wool_events (DataFrames),
            spawn_x, spawn_z, outcome, start_time, end_time.
    """
    df = pd.read_parquet(match_file)
    player_df = df[df['player_id'] == player_id].sort_values('timestamp')

    if len(player_df) == 0:
        return []

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

    return segments


def get_match_player_ids(match_file: str) -> list[int]:
    """Return sorted list of unique player IDs in a match parquet file."""
    df = pd.read_parquet(match_file, columns=['player_id'])
    return sorted(int(pid) for pid in df['player_id'].dropna().unique())
