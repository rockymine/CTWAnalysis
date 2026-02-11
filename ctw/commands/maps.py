"""'maps' subcommand — map metadata and spawn data commands."""

import argparse
import json
from datetime import datetime
from pathlib import Path

from ctw.common import DEFAULT_OUTPUT_ROOT, ensure_match_db


def register(subparsers):
    maps_parser = subparsers.add_parser(
        'maps',
        help='Map metadata commands',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Actions:
  load         Load map metadata into the maps table
  spawns       Load spawn data into the map_spawns table

Examples:
  python ctw.py maps load --map annealing_iv
  python ctw.py maps load                       # all maps with output data
  python ctw.py maps spawns --map annealing_iv
  python ctw.py maps spawns                      # all maps
""",
    )
    maps_sub = maps_parser.add_subparsers(
        dest='maps_action', metavar='<action>',
    )

    # maps load
    p = maps_sub.add_parser('load', help='Load map metadata into the maps table')
    p.add_argument('--map', help='Map name to load (default: all maps)')
    p.add_argument('--output', help='Output root directory (default: output/)')
    p.set_defaults(func=handle_load)

    # maps spawns
    p = maps_sub.add_parser('spawns', help='Load spawn data into the map_spawns table')
    p.add_argument('--map', help='Map name to load (default: all maps)')
    p.add_argument('--output', help='Output root directory (default: output/)')
    p.set_defaults(func=handle_spawns)


def _resolve_map_dirs(args):
    """Resolve map output directories from args. Returns list of Path or None."""
    output_root = Path(args.output) if args.output else DEFAULT_OUTPUT_ROOT
    if not output_root.exists():
        print(f"Error: output directory not found: {output_root}")
        return None

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
        return None
    return map_dirs


def handle_load(args):
    import duckdb

    ensure_match_db()

    map_dirs = _resolve_map_dirs(args)
    if map_dirs is None:
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


def handle_spawns(args):
    import duckdb

    ensure_match_db()

    map_dirs = _resolve_map_dirs(args)
    if map_dirs is None:
        return

    db_path = Path('match_analysis/metadata.db')
    conn = duckdb.connect(str(db_path))

    loaded = 0
    skipped = 0
    for map_dir in map_dirs:
        map_slug = map_dir.name
        map_context_path = map_dir / 'island_analysis' / 'map_context.json'

        if not map_context_path.exists():
            print(f"  Skip {map_slug}: map_context.json not found")
            skipped += 1
            continue

        # Look up map_id
        result = conn.execute(
            "SELECT map_id FROM maps WHERE map_slug = ?", [map_slug]
        ).fetchone()
        if result is None:
            print(f"  Skip {map_slug}: not in maps table (run 'maps load' first)")
            skipped += 1
            continue
        map_id = result[0]

        with open(map_context_path, 'r', encoding='utf-8') as f:
            map_context = json.load(f)

        spawns = map_context.get('poi_assignments', {}).get('spawns', [])
        if not spawns:
            print(f"  Skip {map_slug}: no spawns in map_context.json")
            skipped += 1
            continue

        # Delete existing spawns for this map, then insert new ones
        conn.execute("DELETE FROM map_spawns WHERE map_id = ?", [map_id])

        for spawn in spawns:
            bounds = spawn.get('bounds_2d', {})
            bounds_min = bounds.get('min', {})
            bounds_max = bounds.get('max', {})
            conn.execute("""
                INSERT INTO map_spawns (map_id, x, z, min_x, min_z, max_x, max_z, team, team_color)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                map_id,
                spawn['x'], spawn['z'],
                bounds_min['x'], bounds_min['z'],
                bounds_max['x'], bounds_max['z'],
                spawn['team'], spawn['team_color'],
            ])

        loaded += 1
        print(f"  [OK] {map_slug}: {len(spawns)} spawn(s) loaded")

    conn.close()
    print(f"\nDone: {loaded} map(s) processed, {skipped} skipped.")


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
    # Delete dependent map_spawns first (foreign key constraint)
    conn.execute("""
        DELETE FROM map_spawns WHERE map_id IN (
            SELECT map_id FROM maps WHERE map_slug = ?
        )
    """, [row['map_slug']])
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
