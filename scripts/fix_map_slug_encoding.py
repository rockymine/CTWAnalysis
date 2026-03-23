"""One-time migration: fix map slugs that were incorrectly derived from
special characters by the PGM plugin's normalization.

Renames (target slug does not yet exist):
  la_bataille_de_lpe  -> la_bataille_de_lepee
  rntgen              -> rontgen

Merges (target slug already exists as a separate stub):
  mxico               -> mexico

For renames: insert a corrected stub, redirect child rows, delete old stub,
rename physical folder.  Avoids DuckDB FK re-check on parent UPDATE.

For merges: redirect child rows to the existing target map_id, update
match_file paths, delete old stub, move physical folder contents into the
existing target folder.
"""

import shutil
import duckdb
from pathlib import Path

# (old_slug, new_slug) — target does NOT yet exist in maps table
RENAMES: list[tuple[str, str]] = [
    ("la_bataille_de_lpe", "la_bataille_de_lepee"),
    ("rntgen",             "rontgen"),
]

# (old_slug, new_slug) — target ALREADY EXISTS as a separate stub
MERGES: list[tuple[str, str]] = [
    ("mxico", "mexico"),
]

LOGS_DIR = Path(r"C:\Users\Michael\source\repos\PGMLoggerResults\logs")
DB_PATH  = Path(r"C:\Users\Michael\source\repos\CTWAnalysisWithClaudeCode\match_analysis\metadata.db")


def _redirect_matches(conn, old_map_id: int, new_map_id: int,
                      old_slug: str, new_slug: str) -> int:
    """Redirect matches from old_map_id to new_map_id and fix file paths.

    If the target match_file already exists (e.g. the file was re-indexed
    under the correct slug after organize+index), delete the old duplicate
    row first to avoid violating the UNIQUE(match_file) constraint.
    """
    old_segment = f"/{old_slug}/"
    new_segment = f"/{new_slug}/"

    # Find old rows whose corrected path is already indexed under new slug
    duplicate_ids = [
        row[0] for row in conn.execute(
            """
            SELECT old_m.match_id
            FROM matches old_m
            JOIN matches new_m
              ON new_m.match_file = REPLACE(old_m.match_file, ?, ?)
             AND new_m.map_id = ?
            WHERE old_m.map_id = ?
            """,
            [old_segment, new_segment, new_map_id, old_map_id],
        ).fetchall()
    ]
    if duplicate_ids:
        conn.execute(
            f"DELETE FROM matches WHERE match_id IN ({','.join('?' * len(duplicate_ids))})",
            duplicate_ids,
        )
        print(f"  matches: {len(duplicate_ids)} duplicate(s) deleted (already indexed under '{new_slug}')")

    # Redirect remaining rows
    conn.execute(
        """
        UPDATE matches
        SET map_id     = ?,
            match_file = REPLACE(match_file, ?, ?)
        WHERE map_id = ?
        """,
        [new_map_id, old_segment, new_segment, old_map_id],
    )
    return conn.execute(
        "SELECT COUNT(*) FROM matches WHERE map_id = ?", [new_map_id]
    ).fetchone()[0]


def _move_folder_contents(old_dir: Path, new_dir: Path) -> tuple[int, int]:
    """Move files from old_dir into new_dir, skipping files already present."""
    moved = 0
    skipped = 0
    for source_file in old_dir.glob("*.parquet"):
        dest_file = new_dir / source_file.name
        if dest_file.exists():
            skipped += 1
        else:
            shutil.move(str(source_file), dest_file)
            moved += 1
    return moved, skipped


def handle_rename(conn, old_slug: str, new_slug: str) -> None:
    old_row = conn.execute(
        "SELECT map_id, map_name, stub FROM maps WHERE map_slug = ?", [old_slug]
    ).fetchone()
    if old_row is None:
        print(f"  SKIP: '{old_slug}' not found in maps table")
        return
    old_map_id, old_map_name, _ = old_row

    if conn.execute("SELECT 1 FROM maps WHERE map_slug = ?", [new_slug]).fetchone():
        print(f"  ERROR: '{new_slug}' already exists — use MERGES list instead")
        return

    new_map_name = new_slug if old_map_name == old_slug else old_map_name
    conn.execute(
        """
        INSERT INTO maps (
            map_slug, map_name,
            min_x, max_x, min_z, max_z,
            center_x, center_z, island_count,
            stub, last_updated
        )
        SELECT ?, ?,
               min_x, max_x, min_z, max_z,
               center_x, center_z, island_count,
               stub, CURRENT_TIMESTAMP
        FROM maps WHERE map_id = ?
        """,
        [new_slug, new_map_name, old_map_id],
    )
    new_map_id = conn.execute(
        "SELECT map_id FROM maps WHERE map_slug = ?", [new_slug]
    ).fetchone()[0]
    print(f"  maps: inserted new stub map_id={new_map_id} ('{new_slug}')")

    count = _redirect_matches(conn, old_map_id, new_map_id, old_slug, new_slug)
    print(f"  matches: {count} total rows now under new map_id")

    conn.execute("DELETE FROM maps WHERE map_id = ?", [old_map_id])
    print(f"  maps: old stub map_id={old_map_id} ('{old_slug}') deleted")

    old_dir = LOGS_DIR / old_slug
    new_dir = LOGS_DIR / new_slug
    if old_dir.exists():
        if new_dir.exists():
            print(f"  ERROR: target folder already exists: {new_dir}. Resolve manually.")
        else:
            old_dir.rename(new_dir)
            print(f"  folder: '{old_slug}'  ->  '{new_slug}'")
    else:
        print(f"  folder: '{old_dir}' not found on disk — skipping")


def handle_merge(conn, old_slug: str, new_slug: str) -> None:
    old_row = conn.execute(
        "SELECT map_id FROM maps WHERE map_slug = ?", [old_slug]
    ).fetchone()
    if old_row is None:
        print(f"  SKIP: '{old_slug}' not found in maps table")
        return
    old_map_id = old_row[0]

    new_row = conn.execute(
        "SELECT map_id FROM maps WHERE map_slug = ?", [new_slug]
    ).fetchone()
    if new_row is None:
        print(f"  ERROR: target '{new_slug}' not found — use RENAMES list instead")
        return
    new_map_id = new_row[0]

    count = _redirect_matches(conn, old_map_id, new_map_id, old_slug, new_slug)
    print(f"  matches: {count} total rows now under map_id={new_map_id} ('{new_slug}')")

    conn.execute("DELETE FROM maps WHERE map_id = ?", [old_map_id])
    print(f"  maps: old stub map_id={old_map_id} ('{old_slug}') deleted")

    old_dir = LOGS_DIR / old_slug
    new_dir = LOGS_DIR / new_slug
    if old_dir.exists():
        if new_dir.exists():
            moved, skipped = _move_folder_contents(old_dir, new_dir)
            print(f"  folder: moved {moved} files into '{new_slug}/', skipped {skipped} duplicates")
            if not any(old_dir.iterdir()):
                old_dir.rmdir()
                print(f"  folder: '{old_slug}/' removed (empty)")
            else:
                print(f"  folder: '{old_slug}/' not empty after move — check manually")
        else:
            old_dir.rename(new_dir)
            print(f"  folder: '{old_slug}'  ->  '{new_slug}' (simple rename, target was absent)")
    else:
        print(f"  folder: '{old_dir}' not found on disk — skipping")


def main() -> None:
    conn = duckdb.connect(str(DB_PATH))

    for old_slug, new_slug in RENAMES:
        print(f"\n{'='*60}")
        print(f"  RENAME  {old_slug}  ->  {new_slug}")
        print(f"{'='*60}")
        handle_rename(conn, old_slug, new_slug)

    for old_slug, new_slug in MERGES:
        print(f"\n{'='*60}")
        print(f"  MERGE   {old_slug}  ->  {new_slug}")
        print(f"{'='*60}")
        handle_merge(conn, old_slug, new_slug)

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
