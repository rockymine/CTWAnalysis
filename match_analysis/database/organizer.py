"""Organize a flat directory of match parquet files into per-map subfolders."""

import csv
import shutil
from pathlib import Path


def organize_match_files(
    source_dir: Path,
    dest_dir: Path,
    history_csv: Path,
) -> tuple[int, int, int]:
    """Copy flat parquet files from *source_dir* into ``<dest_dir>/<map>/`` subfolders.

    Uses *history_csv* (columns: ``parquet_file``, ``map_name``) to resolve
    the map slug for each file. Only the filename (basename) is looked up —
    the CSV produced by ``matches parse`` stores bare filenames, not paths.

    Files are skipped (not copied) if a file with the same name already exists
    in the destination map subfolder.  This handles the overlap between an
    existing organised ``logs/`` tree and a flat ``logs2/`` download.

    Args:
        source_dir:  Flat directory containing ``.parquet`` files.
        dest_dir:    Root of the per-map folder tree to copy into.
        history_csv: CSV with ``parquet_file,map_name`` columns.

    Returns:
        ``(copied, skipped_duplicate, skipped_unknown)`` counts.
    """
    # Build filename -> map_slug lookup from the CSV
    slug_by_filename: dict[str, str] = {}
    with history_csv.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            # parquet_file may be a bare filename or a relative path — use basename
            filename = Path(row["parquet_file"]).name
            slug_by_filename[filename] = row["map_name"].strip()

    source_files = sorted(source_dir.glob("*.parquet"))
    if not source_files:
        print(f"No .parquet files found in {source_dir}")
        return 0, 0, 0

    copied = 0
    skipped_duplicate = 0
    skipped_unknown = 0

    for source_file in source_files:
        slug = slug_by_filename.get(source_file.name)
        if slug is None:
            print(f"  UNKNOWN map for {source_file.name} — skipping")
            skipped_unknown += 1
            continue

        dest_map_dir = dest_dir / slug
        dest_file = dest_map_dir / source_file.name

        if dest_file.exists():
            skipped_duplicate += 1
            continue

        dest_map_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, dest_file)
        copied += 1

    return copied, skipped_duplicate, skipped_unknown
