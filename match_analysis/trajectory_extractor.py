"""Extract life segments from raw match parquet files."""

import pandas as pd
import duckdb
from pathlib import Path
import time


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


def extract_life_segments_from_match(match_file: str) -> pd.DataFrame:
    """Extract life segments from raw match parquet.

    Life segment = spawn -> death (or match end).
    Uses event_type codes:
    - 2: SPAWN (start of life)
    - 4: DEATH (end of life)
    - 1: MATCH_END (alternative end if no death)

    Returns DataFrame with one row per life segment containing:
    - player_id, segment_idx
    - start_timestamp, end_timestamp, duration
    - outcome ('death' or 'match_end')
    - Event counts (kills, wool_touches, wool_captures)
    - All position records for this segment
    """
    df = pd.read_parquet(match_file)

    life_segments = []

    for player_id in df['player_id'].dropna().unique():
        player_df = df[df['player_id'] == player_id].sort_values('timestamp')

        spawn_events = player_df[player_df['event_type'] == 2]
        death_events = player_df[player_df['event_type'] == 4]

        for segment_idx, spawn_row in enumerate(spawn_events.itertuples()):
            start_time = spawn_row.timestamp

            # Find next death after this spawn
            next_deaths = death_events[death_events['timestamp'] > start_time]

            if len(next_deaths) > 0:
                end_time = next_deaths.iloc[0]['timestamp']
                outcome = 'death'
            else:
                end_time = player_df['timestamp'].iloc[-1]
                outcome = 'match_end'

            segment_events = player_df[
                (player_df['timestamp'] >= start_time)
                & (player_df['timestamp'] <= end_time)
            ]

            if len(segment_events) == 0:
                continue

            kill_count = len(segment_events[segment_events['event_type'] == 3])
            wool_touches = len(segment_events[segment_events['event_type'] == 6])
            wool_captures = len(segment_events[segment_events['event_type'] == 7])

            positions = segment_events[segment_events['event_type'] == 5]

            life_segments.append({
                'player_id': int(player_id),
                'segment_idx': segment_idx,
                'start_timestamp': int(start_time),
                'end_timestamp': int(end_time),
                'duration': float(end_time - start_time),
                'outcome': outcome,
                'spawn_x': float(spawn_row.x),
                'spawn_z': float(spawn_row.z),
                'position_count': len(positions),
                'kill_count': kill_count,
                'wool_touches': wool_touches,
                'wool_captures': wool_captures,
                'positions': positions.to_dict('records'),
            })

    return pd.DataFrame(life_segments)


def extract_combat_events(match_file: str, life_segments_df: pd.DataFrame) -> pd.DataFrame:
    """Extract kill and death events, each assigned to a life segment.

    Args:
        match_file: Path to raw match parquet file.
        life_segments_df: DataFrame from extract_life_segments_from_match().

    Returns:
        DataFrame with columns: player_id, timestamp, event_type,
        victim_id, x, y, z, segment_idx.
    """
    df = pd.read_parquet(match_file)
    combat = df[df['event_type'].isin([3, 4])].copy()

    if len(combat) == 0:
        return pd.DataFrame(columns=[
            'player_id', 'timestamp', 'event_type',
            'victim_id', 'x', 'y', 'z', 'segment_idx',
        ])

    # Build segment lookup: for each player, list of (start, end, idx)
    seg_lookup = {}
    for row in life_segments_df.itertuples():
        seg_lookup.setdefault(row.player_id, []).append(
            (row.start_timestamp, row.end_timestamp, row.segment_idx)
        )

    def find_segment_idx(player_id, ts):
        for start, end, idx in seg_lookup.get(player_id, []):
            if start <= ts <= end:
                return idx
        return None

    combat['segment_idx'] = combat.apply(
        lambda r: find_segment_idx(int(r['player_id']), r['timestamp']), axis=1
    )
    # Convert victim_id: replace NaN with None for clean DB insertion
    combat['victim_id'] = combat['victim_id'].where(combat['victim_id'].notna(), other=None)

    return combat[['player_id', 'timestamp', 'event_type',
                    'victim_id', 'x', 'y', 'z', 'segment_idx']]


def process_match(match_id: int):
    """Process a single match: extract life segments and save to parquet.

    This is Phase 1 - basic extraction only.
    Later phases will add position classification, phase segmentation,
    and role detection.
    """
    start_time = time.time()
    conn = duckdb.connect('match_analysis/metadata.db')

    try:
        result = conn.execute(
            "SELECT match_file, map_name FROM matches WHERE match_id = ?",
            [match_id],
        ).fetchone()

        if not result:
            print(f"Match {match_id} not found in database")
            return

        match_file_raw, map_name = result
        # Normalize stored path to current platform (handles legacy backslash paths)
        match_file = str(Path(match_file_raw.replace('\\', '/')))
        print(f"\nProcessing match {match_id} ({map_name})")
        print(f"File: {match_file}")

        print("Extracting life segments...")
        life_segments_df = extract_life_segments_from_match(match_file)

        print(f"Found {len(life_segments_df)} life segments")
        print(f"  Players: {life_segments_df['player_id'].nunique()}")
        print(f"  Total positions: {life_segments_df['position_count'].sum()}")
        print(f"  Total kills: {life_segments_df['kill_count'].sum()}")
        print(f"  Total wool captures: {life_segments_df['wool_captures'].sum()}")

        output_file = Path(f'match_analysis/trajectories/{match_id}.parquet')
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Save metadata only (positions column dropped - will be used in later phases)
        metadata_df = life_segments_df.drop(columns=['positions'])
        metadata_df.to_parquet(output_file, index=False)

        print(f"Saved life segment metadata to {output_file}")

        # Clear any previous segments for this match (supports reprocessing)
        conn.execute(
            "DELETE FROM life_segments WHERE match_id = ?", [match_id]
        )

        # Insert life segments into DuckDB
        for row in life_segments_df.itertuples():
            conn.execute(
                """
                INSERT INTO life_segments
                    (match_id, player_id, segment_idx,
                     start_timestamp, end_timestamp, duration, outcome,
                     spawn_x, spawn_z,
                     position_count, kill_count, wool_touches, wool_captures)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [match_id, row.player_id, row.segment_idx,
                 row.start_timestamp, row.end_timestamp, row.duration, row.outcome,
                 row.spawn_x, row.spawn_z,
                 row.position_count, row.kill_count, row.wool_touches, row.wool_captures],
            )

        print(f"Inserted {len(life_segments_df)} life segments into database")

        # Extract and insert combat events
        combat_df = extract_combat_events(match_file, life_segments_df)
        conn.execute(
            "DELETE FROM combat_events WHERE match_id = ?", [match_id]
        )
        for row in combat_df.itertuples():
            victim = int(row.victim_id) if pd.notna(row.victim_id) else None
            seg_idx = int(row.segment_idx) if pd.notna(row.segment_idx) else None
            conn.execute(
                """
                INSERT INTO combat_events
                    (match_id, timestamp, event_type, player_id,
                     victim_id, x, y, z, segment_idx)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [match_id, int(row.timestamp), int(row.event_type),
                 int(row.player_id), victim,
                 int(row.x), int(row.y), int(row.z), seg_idx],
            )
        print(f"Inserted {len(combat_df)} combat events into database")

        processing_time = time.time() - start_time

        conn.execute(
            """
            UPDATE matches
            SET processed = TRUE,
                processed_at = CURRENT_TIMESTAMP,
                processing_time = ?
            WHERE match_id = ?
            """,
            [processing_time, match_id],
        )

        conn.execute(
            """
            INSERT INTO processing_log (match_id, step, status, duration)
            VALUES (?, 'trajectory_extraction', 'success', ?)
            """,
            [match_id, processing_time],
        )

        print(f"\nSuccessfully processed in {processing_time:.2f}s")

    except Exception as e:
        print(f"\nError processing match {match_id}: {e}")
        import traceback
        traceback.print_exc()

        conn.execute(
            """
            INSERT INTO processing_log (match_id, step, status, error_message)
            VALUES (?, 'trajectory_extraction', 'failed', ?)
            """,
            [match_id, str(e)],
        )

    finally:
        conn.close()
