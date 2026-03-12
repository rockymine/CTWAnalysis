"""Parse structured match log files to extract parquet filenames and map names."""

import re
import csv
from pathlib import Path


HEADER_RE = re.compile(
    r"^#(?P<id>\d+)\s*-\s*(?P<map>.+?)\s*-\s*(?P<dur>.+?)\s*$"
)

PARQUET_RE = re.compile(
    r"(?P<file>\d{4}-\d{2}-\d{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}_\d+\.parquet)\b"
)


def parse_match_log(input_path: Path) -> list[dict]:
    """Parse a structured match log file.

    Extracts (parquet_file, map_name) pairs by matching header lines
    (#ID - MapName - Duration) to the first parquet filename that follows.

    Args:
        input_path: Path to the text log file.

    Returns:
        List of dicts with keys 'parquet_file' and 'map_name'.
    """
    with input_path.open("r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f]

    rows = []
    pending_map: str | None = None

    for line in lines:
        if not line:
            continue

        header_match = HEADER_RE.match(line)
        if header_match:
            pending_map = header_match.group("map").strip().lower()
            continue

        parquet_match = PARQUET_RE.search(line)
        if parquet_match and pending_map:
            rows.append({
                "parquet_file": parquet_match.group("file"),
                "map_name": pending_map,
            })
            pending_map = None

    return rows


def scan_match_folder(folder: Path) -> list[dict]:
    """Scan a folder tree of ``<map_name>/<files>.parquet`` for match entries.

    Expects structure::

        folder/
          MapA/
            2026-01-24_01-20-48_0.parquet
            ...
          MapB/
            ...

    The immediate parent directory name is used as the map name.
    The ``parquet_file`` value is the path relative to *folder*
    (e.g. ``MapA/2026-01-24_01-20-48_0.parquet``), matching what
    ``index_match_files --match-dir folder`` stores in the database.

    Args:
        folder: Root directory containing per-map subdirectories.

    Returns:
        Sorted list of dicts with keys ``parquet_file`` and ``map_name``.
    """
    folder = Path(folder)
    rows = []

    for parquet_path in sorted(folder.rglob('*.parquet')):
        rel = parquet_path.relative_to(folder)
        # Must be inside a map subdirectory (depth >= 2)
        if len(rel.parts) < 2:
            continue
        map_name = rel.parts[0].lower()
        # Store as POSIX relative path (forward slashes)
        rows.append({
            'parquet_file': rel.as_posix(),
            'map_name': map_name,
        })

    return rows


def write_csv(rows: list[dict], output_path: Path) -> None:
    """Write parsed rows to CSV with columns parquet_file,map_name."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["parquet_file", "map_name"])
        writer.writeheader()
        writer.writerows(rows)
