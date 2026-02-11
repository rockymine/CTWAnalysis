"""'maps' subcommand — populate the maps table in the analysis DB."""

import argparse
import json
from datetime import datetime
from pathlib import Path

from ctw.common import DEFAULT_OUTPUT_ROOT, ensure_match_db


def register(subparsers):
    p = subparsers.add_parser(
        'maps',
        help='Load map metadata into the analysis database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ctw.py maps --map annealing_iv
  python ctw.py maps                       # all maps with output data
""",
    )
    p.add_argument('--map', help='Map name to load (default: all maps)')
    p.add_argument('--output', help='Output root directory (default: output/)')
    p.set_defaults(func=handler)


def handler(args):
    import duckdb

    ensure_match_db()

    output_root = Path(args.output) if args.output else DEFAULT_OUTPUT_ROOT
    if not output_root.exists():
        print(f"Error: output directory not found: {output_root}")
        return

    # Collect map output directories
    if args.map:
        names = [n.strip() for n in args.map.split(',') if n.strip()]
        map_dirs = []
        for name in names:
            d = output_root / name
            if d.is_dir():
                map_dirs.append(d)
            else:
                print(f"  Warning: output directory not found for '{name}', skipping")
    else:
        map_dirs = sorted(d for d in output_root.iterdir() if d.is_dir())

    if not map_dirs:
        print("No map output directories found.")
        return

    db_path = Path('match_analysis/metadata.db')
    conn = duckdb.connect(str(db_path))

    loaded = 0
    skipped = 0
    for map_dir in map_dirs:
        row = _collect_map_row(map_dir)
        if row is None:
            skipped += 1
            continue
        _upsert_map(conn, row)
        loaded += 1
        print(f"  [OK] {row['map_name']}: {row['island_count']} islands, "
              f"bbox X[{row['min_x']:.0f},{row['max_x']:.0f}] "
              f"Z[{row['min_z']:.0f},{row['max_z']:.0f}]")

    conn.close()
    print(f"\nDone: {loaded} map(s) loaded, {skipped} skipped.")


def _collect_map_row(map_dir: Path) -> dict | None:
    """Read map_data.json and map_context.json, return a row dict or None."""
    map_data_path = map_dir / 'map_data.json'
    map_context_path = map_dir / 'island_analysis' / 'map_context.json'

    if not map_data_path.exists():
        print(f"  Skip {map_dir.name}: map_data.json not found")
        return None
    if not map_context_path.exists():
        print(f"  Skip {map_dir.name}: map_context.json not found")
        return None

    with open(map_data_path, 'r', encoding='utf-8') as f:
        map_data = json.load(f)
    with open(map_context_path, 'r', encoding='utf-8') as f:
        map_context = json.load(f)

    # Validate required fields
    map_name = map_data.get('name')
    if not map_name:
        print(f"  Skip {map_dir.name}: missing 'name' in map_data.json")
        return None

    bbox = map_context.get('bounding_box')
    if not bbox or len(bbox) != 4:
        print(f"  Skip {map_dir.name}: missing/invalid 'bounding_box' in map_context.json")
        return None

    center = map_context.get('map_center')
    if not center or len(center) != 2:
        print(f"  Skip {map_dir.name}: missing/invalid 'map_center' in map_context.json")
        return None

    return {
        'map_slug': map_dir.name,
        'map_name': map_name,
        'max_build_height': map_data.get('max_build_height'),
        'min_x': bbox[0],
        'max_x': bbox[1],
        'min_z': bbox[2],
        'max_z': bbox[3],
        'center_x': center[0],
        'center_z': center[1],
        'island_count': map_context.get('island_count', 0),
        'team_count': len(map_context.get('teams', [])),
        'last_updated': datetime.now(),
    }


def _upsert_map(conn, row: dict):
    """Insert or update a row in the maps table."""
    conn.execute("""
        DELETE FROM maps WHERE map_slug = ?
    """, [row['map_slug']])

    conn.execute("""
        INSERT INTO maps (
            map_slug, map_name, max_build_height,
            min_x, max_x, min_z, max_z,
            center_x, center_z,
            island_count, team_count, last_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        row['map_slug'], row['map_name'], row['max_build_height'],
        row['min_x'], row['max_x'], row['min_z'], row['max_z'],
        row['center_x'], row['center_z'],
        row['island_count'], row['team_count'], row['last_updated'],
    ])
