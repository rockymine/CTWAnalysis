"""Index match parquet files into the DuckDB metadata database."""

import duckdb
import pandas as pd
from pathlib import Path
from datetime import datetime
import re

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


def extract_match_id_from_filename(filename: str) -> int:
    """Extract match ID from filename.

    Format: YYYY-MM-DD_HH-MM-SS_ID.parquet
    Example: 2026-01-24_09-26-48_3.parquet -> 3
    """
    match = re.search(r'_(\d+)\.parquet$', filename)
    if match:
        return int(match.group(1))
    return hash(filename) % 1000000


def get_map_name_from_match(match_file: Path) -> str:
    """Determine map name from match file.

    Current implementation: All files in match_logs are for Ingwaz.
    """
    # TODO: Extract from file metadata or filename when available
    return "Ingwaz"


def index_match_files(match_logs_dir: str = 'match_logs'):
    """Index all match files in the database.

    Reads basic metadata from each parquet file and inserts into matches table.
    Skips files already in the database.
    """
    conn = duckdb.connect('match_analysis/metadata.db')
    match_files = sorted(Path(match_logs_dir).glob('*.parquet'))

    print(f"Found {len(match_files)} match files")

    indexed = 0
    skipped = 0

    for match_file in match_files:
        match_id = extract_match_id_from_filename(match_file.name)

        # Check if already indexed
        result = conn.execute(
            "SELECT match_id FROM matches WHERE match_id = ?",
            [match_id],
        ).fetchone()

        if result:
            skipped += 1
            continue

        try:
            df = pd.read_parquet(match_file)

            map_name = get_map_name_from_match(match_file)
            player_count = int(df['player_id'].dropna().nunique())
            position_count = len(df)

            match_start_events = df[df['event_type'] == 0]
            match_end_events = df[df['event_type'] == 1]

            if len(match_start_events) > 0:
                start_ts = int(match_start_events['timestamp'].iloc[0])
                match_start = datetime.fromtimestamp(start_ts) if start_ts > 0 else None
            else:
                match_start = None

            if len(match_end_events) > 0 and len(match_start_events) > 0:
                match_duration = float(
                    match_end_events['timestamp'].iloc[0]
                    - match_start_events['timestamp'].iloc[0]
                )
            else:
                match_duration = float(df['timestamp'].max() - df['timestamp'].min())

            conn.execute(
                """
                INSERT INTO matches (
                    match_id, match_file, map_name, match_start,
                    match_duration, player_count, position_count, processed
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, FALSE)
                """,
                [
                    match_id, str(match_file), map_name, match_start,
                    match_duration, player_count, position_count,
                ],
            )

            indexed += 1
            print(
                f"  Indexed match {match_id}: {map_name}, "
                f"{player_count} players, {match_duration:.0f}s duration"
            )

        except Exception as e:
            print(f"  Error indexing {match_file.name}: {e}")

    conn.close()
    print(f"\nIndexed {indexed} new matches, skipped {skipped} existing")
    return indexed, skipped
