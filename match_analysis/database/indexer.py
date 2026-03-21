"""Index match parquet files into the DuckDB metadata database."""

import csv
import duckdb
import pandas as pd
import re
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


def get_map_slug_from_match(match_file: Path, logs_dir: Path = None,
                             history: dict[str, str] | None = None) -> str | None:
    """Determine map slug from match file.

    Resolution order:
    1. History CSV lookup (relative path from logs_dir, then basename).
    2. Parent directory name (assumes ``<map>/<file>.parquet`` layout).

    Returns the map slug (lowercase) or ``None`` if it cannot be determined.
    """
    # 1. History CSV lookup
    if history is not None:
        if logs_dir is not None:
            try:
                rel = match_file.resolve().relative_to(logs_dir.resolve())
                slug = history.get(rel.as_posix())
                if slug is not None:
                    return slug
            except ValueError:
                pass
        # Fallback: basename only
        slug = history.get(match_file.name)
        if slug is not None:
            return slug

    # 2. Parent directory name
    parent = match_file.parent.name
    if parent:
        return parent.lower()

    return None


def _resolve_map_id(conn, map_slug: str) -> int | None:
    """Look up map_id from maps table by slug. Returns None if not found."""
    result = conn.execute(
        "SELECT map_id FROM maps WHERE map_slug = ?", [map_slug]
    ).fetchone()
    return result[0] if result else None


def _create_stub_map(conn, map_slug: str) -> int:
    """Insert a stub row into maps for a slug that has no processed map data.

    Uses map_slug as a placeholder map_name and zeroes for all spatial fields.
    Sets stub=TRUE so the row can be identified and enriched later via
    'ctw maps load', which will UPDATE in-place preserving the map_id.

    Returns the newly assigned map_id.
    """
    conn.execute(
        """
        INSERT INTO maps (
            map_slug, map_name,
            min_x, max_x, min_z, max_z,
            center_x, center_z, island_count,
            stub, last_updated
        )
        VALUES (?, ?, 0, 0, 0, 0, 0, 0, 0, TRUE, CURRENT_TIMESTAMP)
        """,
        [map_slug, map_slug],
    )
    result = conn.execute(
        "SELECT map_id FROM maps WHERE map_slug = ?", [map_slug]
    ).fetchone()
    return result[0]


def _load_history(history_csv: str) -> dict[str, str]:
    """Load a history CSV into a ``{parquet_file: map_slug}`` dict."""
    with open(history_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        return {row['parquet_file']: row['map_name'].lower() for row in reader}


def index_match_files(match_logs_dir: str = 'match_logs', history_csv: str | None = None) -> tuple[int, int]:
    """Index all match files in the database.

    Reads basic metadata from each parquet file and inserts into matches table.
    Assigns sequential match_id (max existing + 1).
    Skips files whose match_file path is already in the database.

    Map resolution order per file:
    1. History CSV lookup (if ``--history`` provided).
    2. Parent directory name (``<map>/<file>.parquet`` layout).
    3. If the resolved map is not in the ``maps`` table the file is skipped.

    Args:
        match_logs_dir: Directory containing match parquet files.
        history_csv: Optional path to a CSV with parquet_file,map_name columns.
    """
    conn = duckdb.connect('match_analysis/metadata.db')
    logs_path = Path(match_logs_dir)
    # Recursive glob to support nested <map>/<files>.parquet layout
    match_files = sorted(logs_path.rglob('*.parquet'))

    print(f"Found {len(match_files)} match files")

    history = _load_history(history_csv) if history_csv else None

    # Determine next sequential match_id
    result = conn.execute(
        "SELECT COALESCE(MAX(match_id), 0) FROM matches"
    ).fetchone()
    next_id = (result[0] if result else 0) + 1

    indexed = 0
    skipped = 0
    stub_created: set[str] = set()  # slugs for which we created a stub this run

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
            map_slug = get_map_slug_from_match(
                match_file, logs_dir=logs_path, history=history,
            )
            if map_slug is None:
                print(f"  Skip {match_file.name}: could not determine map name")
                skipped += 1
                continue

            map_id = _resolve_map_id(conn, map_slug)
            if map_id is None:
                map_id = _create_stub_map(conn, map_slug)
                stub_created.add(map_slug)
                print(f"  Stub created for map '{map_slug}' (map_id={map_id})")

            df = pd.read_parquet(match_file)

            player_count = int(df['player_id'].dropna().nunique())
            position_count = len(df)

            match_start_events = df[df['event_type'] == 0]
            match_end_events = df[df['event_type'] == 1]

            filename_match = re.search(r'(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})', match_file.name)
            match_start = datetime.strptime(filename_match.group(1), '%Y-%m-%d_%H-%M-%S') if filename_match else None

            if len(match_end_events) > 0 and len(match_start_events) > 0:
                match_duration = float(
                    match_end_events['timestamp'].iloc[0]
                    - match_start_events['timestamp'].iloc[0]
                )
            else:
                match_duration = float(df['timestamp'].max() - df['timestamp'].min())

            match_id_val = next_id

            conn.execute(
                """
                INSERT INTO matches (
                    match_id, match_file, map_id, match_start,
                    match_duration, player_count, position_count, processed
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, FALSE)
                """,
                [
                    match_id_val, match_file_posix, map_id, match_start,
                    match_duration, player_count, position_count,
                ],
            )

            next_id += 1
            indexed += 1
            print(
                f"  Indexed match {match_id_val}: {map_slug}, "
                f"{player_count} players, {match_duration:.0f}s duration"
            )

        except Exception as e:
            print(f"  Error indexing {match_file.name}: {e}")

    conn.close()

    # Summary
    if stub_created:
        print(f"\nNote: {len(stub_created)} stub map(s) created for unregistered slugs:")
        for slug in sorted(stub_created):
            print(f"  {slug}")
        print("Run 'ctw run --map <name>' then 'ctw maps load' to enrich these stubs.")

    print(f"\nIndexed {indexed} new matches, skipped {skipped} existing/unresolvable")
    return indexed, skipped
