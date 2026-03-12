"""Extract structured events from raw match parquet DataFrames.

Provides functions to extract life segments, combat events, position events,
wool events, and a segment lookup helper. All functions accept a pre-read
DataFrame rather than a file path.
"""

from typing import Callable

import pandas as pd


EVENT_TYPES = {
    0: "MATCH_START",
    1: "MATCH_END",
    2: "SPAWN",
    3: "KILL",
    4: "DEATH",
    5: "POSITION",
    6: "WOOL_TOUCH",
    7: "WOOL_CAPTURE",
}


def extract_life_segments(df: pd.DataFrame) -> pd.DataFrame:
    """Extract life segments from raw match DataFrame.

    Life segment = spawn -> death (or match end).
    Uses event_type codes:
    - 2: SPAWN (start of life)
    - 4: DEATH (end of life)
    - 1: MATCH_END (alternative end if no death)

    Args:
        df: Raw match DataFrame (from pd.read_parquet).

    Returns DataFrame with one row per life segment containing:
    - player_id, segment_idx
    - start_timestamp, end_timestamp, duration
    - outcome ('death' or 'match_end')
    - Event counts (kills, wool_touches, wool_captures, position_count)
    """
    sorted_df = df.sort_values(['player_id', 'timestamp'])

    # Build spawn/death tables with per-player ordinal index
    spawns = sorted_df[sorted_df['event_type'] == 2].copy()
    deaths = sorted_df[sorted_df['event_type'] == 4].copy()

    if len(spawns) == 0:
        return pd.DataFrame(columns=[
            'player_id', 'segment_idx', 'start_timestamp', 'end_timestamp',
            'duration', 'outcome', 'spawn_x', 'spawn_z',
            'position_count', 'kill_count', 'wool_touches', 'wool_captures',
        ])

    spawns['segment_idx'] = spawns.groupby('player_id').cumcount()
    deaths['segment_idx'] = deaths.groupby('player_id').cumcount()

    # Pair nth spawn with nth death per player
    segments = spawns[['player_id', 'segment_idx', 'timestamp', 'x', 'z']].rename(
        columns={'timestamp': 'start_timestamp', 'x': 'spawn_x', 'z': 'spawn_z'},
    )
    death_times = deaths[['player_id', 'segment_idx', 'timestamp']].rename(
        columns={'timestamp': 'end_timestamp'},
    )
    segments = segments.merge(death_times, on=['player_id', 'segment_idx'], how='left')

    # Segments without a death end at the player's last event
    last_ts = sorted_df.groupby('player_id')['timestamp'].last()
    no_death = segments['end_timestamp'].isna()
    segments.loc[no_death, 'end_timestamp'] = (
        segments.loc[no_death, 'player_id'].map(last_ts)
    )
    segments['outcome'] = no_death.map({True: 'match_end', False: 'death'})
    segments['duration'] = (
        segments['end_timestamp'] - segments['start_timestamp']
    ).astype(float)

    # Assign segment_idx to all events via merge_asof (backward = last spawn ≤ ts)
    events = sorted_df[sorted_df['event_type'].isin([3, 5, 6, 7])].copy()
    if len(events) > 0:
        spawn_keys = spawns[['player_id', 'timestamp', 'segment_idx']].sort_values(
            'timestamp',
        )
        events = events.sort_values('timestamp')
        events = pd.merge_asof(
            events, spawn_keys,
            on='timestamp', by='player_id', direction='backward',
            suffixes=('', '_seg'),
        )
        # Aggregate event counts per segment
        counts = events.groupby(['player_id', 'segment_idx'])['event_type'].agg(
            kill_count=lambda x: (x == 3).sum(),
            position_count=lambda x: (x == 5).sum(),
            wool_touches=lambda x: (x == 6).sum(),
            wool_captures=lambda x: (x == 7).sum(),
        ).reset_index()
        segments = segments.merge(counts, on=['player_id', 'segment_idx'], how='left')
    else:
        for col in ['kill_count', 'position_count', 'wool_touches', 'wool_captures']:
            segments[col] = 0

    # Fill NaN counts (segments with no matching events)
    for col in ['kill_count', 'position_count', 'wool_touches', 'wool_captures']:
        segments[col] = segments[col].fillna(0).astype(int)

    # Cast to final types
    segments['player_id'] = segments['player_id'].astype(int)
    segments['start_timestamp'] = segments['start_timestamp'].astype(int)
    segments['end_timestamp'] = segments['end_timestamp'].astype(int)

    return segments[['player_id', 'segment_idx', 'start_timestamp', 'end_timestamp',
                     'duration', 'outcome', 'spawn_x', 'spawn_z',
                     'position_count', 'kill_count', 'wool_touches', 'wool_captures']]


def build_segment_lookup(
    life_segments_df: pd.DataFrame,
) -> Callable[[int, int], int | None]:
    """Build a lookup function that maps (player_id, timestamp) to segment_idx.

    Returns a callable: find_segment_idx(player_id, timestamp) -> int | None
    """
    seg_lookup: dict[int, list[tuple[int, int, int]]] = {}
    for row in life_segments_df.itertuples():
        seg_lookup.setdefault(row.player_id, []).append(
            (row.start_timestamp, row.end_timestamp, row.segment_idx)
        )

    def find_segment_idx(player_id: int, ts: int) -> int | None:
        for start, end, idx in seg_lookup.get(player_id, []):
            if start <= ts <= end:
                return idx
        return None

    return find_segment_idx


def extract_combat_events(
    df: pd.DataFrame, find_segment_idx: Callable[[int, int], int | None],
) -> pd.DataFrame:
    """Extract kill and death events, each assigned to a life segment.

    Args:
        df: Raw match DataFrame (from pd.read_parquet).
        find_segment_idx: Callable from build_segment_lookup().

    Returns:
        DataFrame with columns: player_id, timestamp, event_type,
        victim_id, x, y, z, segment_idx.
    """
    combat = df[df['event_type'].isin([3, 4])].copy()

    if len(combat) == 0:
        return pd.DataFrame(columns=[
            'player_id', 'timestamp', 'event_type',
            'victim_id', 'x', 'y', 'z', 'held_item', 'segment_idx',
        ])

    combat['segment_idx'] = combat.apply(
        lambda r: find_segment_idx(int(r['player_id']), r['timestamp']), axis=1
    )
    # Ensure victim_id column exists (some parquet schemas omit it)
    if 'victim_id' not in combat.columns:
        combat['victim_id'] = None
    # held_item is only present on kill events (type 3); death events (type 4) have no held_item
    if 'held_item' not in combat.columns:
        combat['held_item'] = None

    return combat[['player_id', 'timestamp', 'event_type',
                    'victim_id', 'x', 'y', 'z', 'held_item', 'segment_idx']]


def extract_position_events(
    df: pd.DataFrame, find_segment_idx: Callable[[int, int], int | None],
) -> pd.DataFrame:
    """Extract position events (type 5), each assigned to a life segment.

    Args:
        df: Raw match DataFrame (from pd.read_parquet).
        find_segment_idx: Callable from build_segment_lookup().

    Returns:
        DataFrame with columns: player_id, timestamp, x, y, z, segment_idx.
    """
    positions = df[df['event_type'] == 5].copy()

    if len(positions) == 0:
        return pd.DataFrame(columns=[
            'player_id', 'timestamp', 'x', 'y', 'z', 'segment_idx',
        ])

    positions['segment_idx'] = positions.apply(
        lambda r: find_segment_idx(int(r['player_id']), r['timestamp']), axis=1
    )

    return positions[['player_id', 'timestamp', 'x', 'y', 'z', 'segment_idx']]


def extract_wool_events(
    df: pd.DataFrame, find_segment_idx: Callable[[int, int], int | None],
) -> pd.DataFrame:
    """Extract wool touch/capture events (types 6/7), each assigned to a life segment.

    Args:
        df: Raw match DataFrame (from pd.read_parquet).
        find_segment_idx: Callable from build_segment_lookup().

    Returns:
        DataFrame with columns: player_id, timestamp, event_type,
        wool_id, x, y, z, segment_idx.
    """
    wool = df[df['event_type'].isin([6, 7])].copy()

    if len(wool) == 0:
        return pd.DataFrame(columns=[
            'player_id', 'timestamp', 'event_type',
            'wool_id', 'x', 'y', 'z', 'segment_idx',
        ])

    wool['segment_idx'] = wool.apply(
        lambda r: find_segment_idx(int(r['player_id']), r['timestamp']), axis=1
    )
    if 'wool_id' not in wool.columns:
        wool['wool_id'] = None

    return wool[['player_id', 'timestamp', 'event_type',
                 'wool_id', 'x', 'y', 'z', 'segment_idx']]
