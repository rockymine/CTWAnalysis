"""Index match parquet files into the DuckDB metadata database."""

import csv
import duckdb
import pandas as pd
from pathlib import Path, PurePosixPath
from datetime import datetime

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


def get_map_name_from_match(match_file: Path) -> str:
    """Determine map name from match file.

    Current implementation: All files in match_logs are for Ingwaz.
    """
    # TODO: Extract from file metadata or filename when available
    return "ingwaz"


def _apply_history_mapping(conn, history_csv: str, match_logs_dir: str = None):
    """Update map_name for indexed matches using a history CSV.

    The CSV must have columns: parquet_file, map_name.
    The parquet_file value can be a basename (``file.parquet``) or a
    relative path (``MapName/file.parquet``).  Matching is tried against
    the relative path from *match_logs_dir* first, then the basename.
    """
    with open(history_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        history = {row['parquet_file']: row['map_name'].lower() for row in reader}

    rows = conn.execute("SELECT match_id, match_file FROM matches").fetchall()

    matched = 0
    unmatched = 0
    # Use Path (not PurePosixPath) so relative_to is case-insensitive on Windows
    logs_dir_resolved = (
        Path(match_logs_dir).resolve() if match_logs_dir else None
    )

    for match_id, match_file in rows:
        # Try relative path from match_logs_dir first
        map_name = None
        if logs_dir_resolved is not None:
            try:
                rel = Path(match_file).relative_to(logs_dir_resolved)
                map_name = history.get(rel.as_posix())
            except ValueError:
                pass

        # Fallback: basename
        if map_name is None:
            map_name = history.get(PurePosixPath(match_file).name)

        if map_name is not None:
            conn.execute(
                "UPDATE matches SET map_name = ? WHERE match_id = ?",
                [map_name, match_id],
            )
            matched += 1
        else:
            unmatched += 1

    print(f"\nHistory mapping: {matched} matched, {unmatched} unmatched")


def index_match_files(match_logs_dir: str = 'match_logs', history_csv: str = None):
    """Index all match files in the database.

    Reads basic metadata from each parquet file and inserts into matches table.
    Assigns sequential match_id (max existing + 1).
    Skips files whose match_file path is already in the database.

    Args:
        match_logs_dir: Directory containing match parquet files.
        history_csv: Optional path to a CSV with parquet_file,map_name columns.
            If provided, map_name is updated for matching rows after indexing.
    """
    conn = duckdb.connect('match_analysis/metadata.db')
    logs_path = Path(match_logs_dir)
    # Recursive glob to support nested <map>/<files>.parquet layout
    match_files = sorted(logs_path.rglob('*.parquet'))

    print(f"Found {len(match_files)} match files")

    # Determine next sequential match_id
    result = conn.execute(
        "SELECT COALESCE(MAX(match_id), 0) FROM matches"
    ).fetchone()
    next_id = (result[0] if result else 0) + 1

    indexed = 0
    skipped = 0

    for match_file in match_files:
        # Store as POSIX path (forward slashes) for cross-platform compat
        match_file_posix = PurePosixPath(match_file).as_posix()

        # Check if already indexed by file path (UNIQUE constraint)
        existing = conn.execute(
            "SELECT match_id FROM matches WHERE match_file = ?",
            [match_file_posix],
        ).fetchone()

        if existing:
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

            match_id = next_id

            conn.execute(
                """
                INSERT INTO matches (
                    match_id, match_file, map_name, match_start,
                    match_duration, player_count, position_count, processed
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, FALSE)
                """,
                [
                    match_id, match_file_posix, map_name, match_start,
                    match_duration, player_count, position_count,
                ],
            )

            next_id += 1
            indexed += 1
            print(
                f"  Indexed match {match_id}: {map_name}, "
                f"{player_count} players, {match_duration:.0f}s duration"
            )

        except Exception as e:
            print(f"  Error indexing {match_file.name}: {e}")

    # Apply history mapping if provided
    if history_csv:
        _apply_history_mapping(conn, history_csv, match_logs_dir)

    conn.close()
    print(f"\nIndexed {indexed} new matches, skipped {skipped} existing")
    return indexed, skipped
