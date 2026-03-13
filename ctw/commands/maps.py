"""'maps' subcommand — map metadata and spawn data commands."""

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from ctw.common import DEFAULT_OUTPUT_ROOT, ensure_match_db

# Size tier thresholds (max_players_per_team, lower bound inclusive)
_SIZE_TIERS = [
    (80, 'giga'),
    (64, 'mega'),
    (48, 'hecto'),
    (32, 'centi'),
    (22, 'milli'),
    (14, 'micro'),
    (6,  'nano'),
    (1,  'pico'),
]


def _size_tier(max_players_per_team: Optional[int]) -> Optional[str]:
    """Return the size tier label for a given per-team player count."""
    if max_players_per_team is None:
        return None
    for threshold, label in _SIZE_TIERS:
        if max_players_per_team >= threshold:
            return label
    return None


def _count_surface_blocks(map_dir: Path) -> Optional[int]:
    """Count non-void surface blocks from layout_top_surface.parquet.

    Block ID 36 is excluded — it is used as a void/region marker and must
    not be counted as playable terrain.
    Returns None if the parquet file is absent.
    """
    surface_path = map_dir / 'layout_top_surface.parquet'
    if not surface_path.exists():
        return None
    df = pd.read_parquet(surface_path, columns=['block_id'])
    return int((df['block_id'] != 36).sum())


def _read_symmetry(map_dir: Path) -> tuple[Optional[str], Optional[bool]]:
    """Return (primary_symmetry_type, has_intra_team_symmetry) from symmetry.json.

    primary_symmetry_type is the highest-confidence detected global symmetry,
    or None if symmetry.json is absent or no symmetry is detected.
    has_intra_team_symmetry is True if any team has intra-team symmetry detected.
    """
    sym_path = map_dir / 'symmetry.json'
    if not sym_path.exists():
        return None, None

    with open(sym_path, 'r', encoding='utf-8') as f:
        sym = json.load(f)

    detected = [s for s in sym.get('global_symmetry', []) if s.get('detected')]
    if detected:
        primary = max(detected, key=lambda s: s.get('confidence', 0.0))
        symmetry_type = primary['type']
    else:
        symmetry_type = 'none'

    intra = sym.get('intra_team_symmetry', [])
    has_intra = any(t.get('symmetry_detected') for t in intra) if intra else False

    return symmetry_type, has_intra


def register(subparsers):
    maps_parser = subparsers.add_parser(
        'maps',
        help='Map metadata commands',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Actions:
  load         Load map metadata into the maps table
  spawns       Load spawn data into the map_spawns table
  resources    Classify resource blocks and chests by zone, store in DB
  kits         Load kit items and armor into the DB

Examples:
  python ctw.py maps load --map annealing_iv
  python ctw.py maps load                       # all maps with output data
  python ctw.py maps spawns --map annealing_iv
  python ctw.py maps resources --map arabia
  python ctw.py maps resources                  # all maps
  python ctw.py maps kits --map arabia
  python ctw.py maps kits                       # all maps
  python ctw.py maps kits --map-dir /path/to/CommunityMaps  # external map dir
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

    # maps resources
    p = maps_sub.add_parser(
        'resources',
        help='Classify resource blocks and chests by zone, store in DB',
    )
    p.add_argument('--map', help='Map name (default: all maps)')
    p.add_argument('--output', help='Output root directory (default: output/)')
    p.add_argument('--defense-buffer', type=float, default=10.0,
                   help='Blocks outside wool room counted as defense (default: 10)')
    p.add_argument('--near-spawn-buffer', type=float, default=15.0,
                   help='Blocks outside spawn counted as near_spawn (default: 15)')
    p.set_defaults(func=handle_resources)

    # maps kits
    p = maps_sub.add_parser(
        'kits',
        help='Load kit items and armor into the DB',
    )
    p.add_argument('--map', help='Map name (default: all maps)')
    p.add_argument('--output', help='Output root directory (default: output/)')
    p.add_argument('--map-dir',
                   help='Directory containing map folders for XML lookup '
                        '(default: map_folders/). Use when maps live outside '
                        'the project, e.g. CommunityMaps.')
    p.set_defaults(func=handle_kits)


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
              f"{row['team_count']}t/{row['wools_per_team']}w/{row['max_players_per_team']}p, "
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
        map_context_path = map_dir / 'map_context.json'

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
    map_context_path = map_dir / 'map_context.json'

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

    teams = map_data.get('teams', [])
    team_count = len(teams)
    wools = map_data.get('wools', [])
    wools_per_team = round(len(wools) / team_count) if team_count > 0 else None
    player_counts = [t.get('max_players') for t in teams if t.get('max_players')]
    max_players_per_team = round(sum(player_counts) / len(player_counts)) if player_counts else None

    symmetry_type, has_intra_team_symmetry = _read_symmetry(map_dir)
    total_blocks = _count_surface_blocks(map_dir)

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
        'team_count': team_count,
        'wools_per_team': wools_per_team,
        'max_players_per_team': max_players_per_team,
        'total_blocks': total_blocks,
        'size_tier': _size_tier(max_players_per_team),
        'symmetry_type': symmetry_type,
        'has_intra_team_symmetry': has_intra_team_symmetry,
        'last_updated': datetime.now(),
    }


def _upsert_map(conn, row: dict):
    """Insert or update a row in the maps table.

    If the map already exists (by map_slug), updates it in place so the
    map_id PK is preserved and FK references in matches remain valid.
    If it does not exist, inserts a new row.
    Clears map_spawns in both cases since they may be stale after an update.
    """
    existing = conn.execute(
        "SELECT map_id FROM maps WHERE map_slug = ?", [row['map_slug']]
    ).fetchone()

    if existing:
        conn.execute(
            "DELETE FROM map_spawns WHERE map_id = ?", [existing[0]]
        )
        conn.execute("""
            UPDATE maps SET
                map_name = ?,
                max_build_height = ?,
                min_x = ?, max_x = ?,
                min_z = ?, max_z = ?,
                center_x = ?, center_z = ?,
                island_count = ?,
                team_count = ?,
                wools_per_team = ?,
                max_players_per_team = ?,
                total_blocks = ?,
                size_tier = ?,
                symmetry_type = ?,
                has_intra_team_symmetry = ?,
                last_updated = ?
            WHERE map_slug = ?
        """, [
            row['map_name'], row['max_build_height'],
            row['min_x'], row['max_x'],
            row['min_z'], row['max_z'],
            row['center_x'], row['center_z'],
            row['island_count'], row['team_count'],
            row['wools_per_team'], row['max_players_per_team'],
            row['total_blocks'], row['size_tier'],
            row['symmetry_type'], row['has_intra_team_symmetry'],
            row['last_updated'],
            row['map_slug'],
        ])
    else:
        conn.execute("""
            INSERT INTO maps (
                map_slug, map_name, max_build_height,
                min_x, max_x, min_z, max_z,
                center_x, center_z,
                island_count, team_count,
                wools_per_team, max_players_per_team, total_blocks,
                size_tier, symmetry_type, has_intra_team_symmetry,
                last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            row['map_slug'], row['map_name'], row['max_build_height'],
            row['min_x'], row['max_x'], row['min_z'], row['max_z'],
            row['center_x'], row['center_z'],
            row['island_count'], row['team_count'],
            row['wools_per_team'], row['max_players_per_team'],
            row['total_blocks'], row['size_tier'],
            row['symmetry_type'], row['has_intra_team_symmetry'],
            row['last_updated'],
        ])


def handle_resources(args) -> None:
    """Classify resource blocks and chests by zone and store results in the DB."""
    import duckdb
    from layout_analysis.features import ZoneClassifier, detect_double_chests
    from match_analysis.database.schema import migrate_resource_tables

    ensure_match_db()

    map_dirs = _resolve_map_dirs(args)
    if map_dirs is None:
        return

    db_path = Path('match_analysis/metadata.db')
    conn = duckdb.connect(str(db_path))
    migrate_resource_tables(str(db_path))

    loaded = 0
    skipped = 0

    for map_dir in map_dirs:
        map_slug = map_dir.name
        map_data_path = map_dir / 'map_data.json'
        rb_path = map_dir / 'layout_resource_blocks.parquet'
        cc_path = map_dir / 'layout_chest_contents.parquet'

        if not map_data_path.exists():
            print(f"  Skip {map_slug}: map_data.json not found")
            skipped += 1
            continue
        if not rb_path.exists() and not cc_path.exists():
            print(f"  Skip {map_slug}: layout parquets not found (run 'layout' first)")
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

        with open(map_data_path, 'r', encoding='utf-8') as f:
            map_data = json.load(f)

        clf = ZoneClassifier(
            map_data,
            defense_buffer=args.defense_buffer,
            near_spawn_buffer=args.near_spawn_buffer,
        )

        # --- Resource blocks ---
        rb_rows = 0
        if rb_path.exists():
            rb_df = pd.read_parquet(str(rb_path))
            if not rb_df.empty:
                rb_classified = clf.classify_dataframe(rb_df)
                conn.execute(
                    "DELETE FROM map_resource_blocks WHERE map_id = ?", [map_id]
                )
                for _, row in rb_classified.iterrows():
                    conn.execute("""
                        INSERT INTO map_resource_blocks
                            (map_id, world_x, world_z, y, resource_type, zone, team)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, [
                        map_id,
                        int(row['world_x']), int(row['world_z']), int(row['y']),
                        str(row['resource_type']), str(row['zone']),
                        row['team'] if row['team'] is not None else None,
                    ])
                rb_rows = len(rb_classified)

        # --- Chests ---
        chest_rows = 0
        content_rows = 0
        if cc_path.exists():
            cc_df = pd.read_parquet(str(cc_path))
            if not cc_df.empty:
                cc_dbl = detect_double_chests(cc_df)
                # Unique chest locations
                chest_loc_cols = ['world_x', 'world_z', 'y', 'chest_type', 'is_double', 'chest_group_id']
                chests_df = cc_dbl[chest_loc_cols].drop_duplicates(
                    subset=['world_x', 'world_z', 'y']
                )
                chests_classified = clf.classify_dataframe(chests_df)

                conn.execute("DELETE FROM map_chests WHERE map_id = ?", [map_id])
                conn.execute("DELETE FROM map_chest_contents WHERE map_id = ?", [map_id])

                for _, row in chests_classified.iterrows():
                    conn.execute("""
                        INSERT INTO map_chests
                            (map_id, world_x, world_z, y, chest_type, zone, team,
                             is_double, chest_group_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, [
                        map_id,
                        int(row['world_x']), int(row['world_z']), int(row['y']),
                        str(row['chest_type']), str(row['zone']),
                        row['team'] if row['team'] is not None else None,
                        bool(row['is_double']),
                        int(row['chest_group_id']) if row['chest_group_id'] is not None else None,
                    ])
                chest_rows = len(chests_classified)

                # Insert chest contents (items)
                for _, row in cc_dbl.iterrows():
                    conn.execute("""
                        INSERT INTO map_chest_contents
                            (map_id, world_x, world_z, y, slot, item_id, item_damage, count)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, [
                        map_id,
                        int(row['world_x']), int(row['world_z']), int(row['y']),
                        int(row['slot']), str(row['item_id']),
                        int(row['item_damage']), int(row['count']),
                    ])
                content_rows = len(cc_dbl)

        # Print summary
        _print_resources_summary(
            map_slug,
            rb_classified if rb_rows > 0 else None,
            chests_classified if chest_rows > 0 else None,
        )
        loaded += 1

    conn.close()
    print(f"\nDone: {loaded} map(s) processed, {skipped} skipped.")


def handle_kits(args) -> None:
    """Parse kit items and armor from map.xml and store in the DB."""
    import duckdb
    from xml_analysis.builder import MapXMLParser
    from xml_analysis.kit_parser import parse_kits
    from match_analysis.database.schema import migrate_kit_tables

    ensure_match_db()

    map_dirs = _resolve_map_dirs(args)
    if map_dirs is None:
        return

    db_path = Path('match_analysis/metadata.db')
    migrate_kit_tables(str(db_path))
    conn = duckdb.connect(str(db_path))

    loaded = 0
    skipped = 0

    for map_dir in map_dirs:
        map_slug = map_dir.name

        # Locate map.xml — use --map-dir if given, else default map_folders/
        from ctw.common import PROJECT_ROOT
        xml_root = Path(args.map_dir) if getattr(args, 'map_dir', None) else PROJECT_ROOT / 'map_folders'
        xml_path = xml_root / map_slug / 'map.xml'
        if not xml_path.exists():
            print(f"  Skip {map_slug}: map.xml not found at {xml_path}")
            skipped += 1
            continue

        result = conn.execute(
            "SELECT map_id FROM maps WHERE map_slug = ?", [map_slug]
        ).fetchone()
        if result is None:
            print(f"  Skip {map_slug}: not in maps table (run 'maps load' first)")
            skipped += 1
            continue
        map_id = result[0]

        try:
            parser = MapXMLParser(str(xml_path))
            map_data = parser.parse()
            items_df, armor_df = parse_kits(parser.root, map_data.spawns)
        except Exception as e:
            print(f"  Skip {map_slug}: failed to parse XML — {e}")
            skipped += 1
            continue

        conn.execute("DELETE FROM map_kit_items WHERE map_id = ?", [map_id])
        conn.execute("DELETE FROM map_kit_armor WHERE map_id = ?", [map_id])

        for _, row in items_df.iterrows():
            enc = row['enchantments']
            conn.execute("""
                INSERT INTO map_kit_items
                    (map_id, kit_id, team, slot, material, amount,
                     item_damage, unbreakable, team_color, enchantments)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                map_id,
                str(row['kit_id']), str(row['team']),
                int(row['slot']), str(row['material']),
                int(row['amount']), int(row['item_damage']),
                bool(row['unbreakable']), bool(row['team_color']),
                str(enc) if enc is not None and enc == enc else None,
            ])

        for _, row in armor_df.iterrows():
            enc = row['enchantments']
            conn.execute("""
                INSERT INTO map_kit_armor
                    (map_id, kit_id, team, slot_name, material,
                     unbreakable, team_color, enchantments)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                map_id,
                str(row['kit_id']), str(row['team']),
                str(row['slot_name']), str(row['material']),
                bool(row['unbreakable']), bool(row['team_color']),
                str(enc) if enc is not None and enc == enc else None,
            ])

        print(f"  [OK] {map_slug}: {len(items_df)} item rows, {len(armor_df)} armor rows")
        loaded += 1

    conn.close()
    print(f"\nDone: {loaded} map(s) loaded, {skipped} skipped.")


def _print_resources_summary(
    map_slug: str,
    rb_classified: Optional[pd.DataFrame],
    chests_classified: Optional[pd.DataFrame],
) -> None:
    """Print a per-map resource summary to stdout."""
    print(f"\n  {map_slug}")

    if rb_classified is not None and not rb_classified.empty:
        rb_summary = (
            rb_classified
            .fillna({'team': '?'})
            .groupby(['resource_type', 'zone', 'team'], observed=True)
            .size()
            .reset_index(name='n')
        )
        print("    Resource blocks:")
        for _, r in rb_summary.iterrows():
            print(f"      {r.resource_type:18s}  zone={r.zone:12s}  team={str(r.team):14s}  n={r.n}")
    else:
        print("    (no resource blocks)")

    if chests_classified is not None and not chests_classified.empty:
        print("    Chests:")
        c = chests_classified.fillna({'team': '?'})
        for (zone, team), grp in c.groupby(['zone', 'team'], observed=True):
            dbl = int(grp['is_double'].sum())
            singles = len(grp) - dbl
            print(f"      zone={zone:12s}  team={str(team):14s}  "
                  f"n={len(grp)}  (double={dbl//2} pairs, single={singles})")
    else:
        print("    (no chests)")
