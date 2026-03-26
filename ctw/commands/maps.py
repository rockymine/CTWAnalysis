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


def _read_symmetry(map_dir: Path) -> tuple[Optional[str], Optional[float], Optional[bool]]:
    """Return (primary_symmetry_type, symmetry_confidence, has_intra_team_symmetry) from symmetry.json.

    primary_symmetry_type is the type string of the highest-confidence detected
    global symmetry, or 'none' if no symmetry is detected.
    symmetry_confidence is the confidence of the primary symmetry (0.0–1.0), or
    None if symmetry.json is absent.
    has_intra_team_symmetry is True if any team has intra-team symmetry detected.
    """
    sym_path = map_dir / 'symmetry.json'
    if not sym_path.exists():
        return None, None, None

    with open(sym_path, 'r', encoding='utf-8') as f:
        sym = json.load(f)

    detected = [s for s in sym.get('global_symmetry', []) if s.get('detected')]
    if detected:
        primary = max(detected, key=lambda s: s.get('confidence', 0.0))
        symmetry_type = primary['type']
        symmetry_confidence = primary.get('confidence')
    else:
        symmetry_type = 'none'
        symmetry_confidence = 0.0

    intra = sym.get('intra_team_symmetry', [])
    has_intra = any(t.get('symmetry_detected') for t in intra) if intra else False

    return symmetry_type, symmetry_confidence, has_intra


def register(subparsers):
    maps_parser = subparsers.add_parser(
        'maps',
        help='Map metadata commands',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Actions:
  load              Load map metadata into the maps table
  spawns            Load spawn data into the map_spawns table
  resources         Classify resource blocks and chests by zone, store in DB
  kits              Load kit items and armor into the DB
  spatial-relations Compute vector-based POI spatial relations and store in DB
  terrain-height    Load terrain height data into the map_terrain_height table
  authors           Parse map.xml authors/contributors and look up Minecraft names
  geometry-graph    Build geometry-derived adjacency graph from map polygons

Examples:
  python ctw.py maps load --map annealing_iv
  python ctw.py maps load                       # all maps with output data
  python ctw.py maps spawns --map annealing_iv
  python ctw.py maps resources --map arabia
  python ctw.py maps resources                  # all maps
  python ctw.py maps kits --map arabia
  python ctw.py maps kits                       # all maps
  python ctw.py maps kits --map-dir /path/to/CommunityMaps  # external map dir
  python ctw.py maps spatial-relations --map kanto
  python ctw.py maps spatial-relations          # all maps
  python ctw.py maps terrain-height --map arabia
  python ctw.py maps terrain-height             # all maps
  python ctw.py maps chest-classify             # all maps
  python ctw.py maps chest-classify --map arabia
  python ctw.py maps geometry-graph --map tumbleweed
  python ctw.py maps geometry-graph             # all maps with output data
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
    p.add_argument('--skip-existing', action='store_true', dest='skip_existing',
                   help='Skip maps that already have resource or chest rows in the DB')
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
    p.add_argument('--skip-existing', action='store_true', dest='skip_existing',
                   help='Skip maps that already have kit rows in the DB')
    p.set_defaults(func=handle_kits)

    # maps spatial-relations
    p = maps_sub.add_parser(
        'spatial-relations',
        help='Compute vector-based POI spatial relations and store in DB',
    )
    p.add_argument('--map', help='Map slug to process (default: all maps in DB)')
    p.set_defaults(func=handle_spatial_relations)

    # maps terrain-height
    p = maps_sub.add_parser(
        'terrain-height',
        help='Load terrain height data (surface_y, lowest_y) into map_terrain_height',
    )
    p.add_argument('--map', help='Map name to process (default: all maps with output data)')
    p.add_argument('--output', help='Output root directory (default: output/)')
    p.set_defaults(func=handle_terrain_height)

    # maps chest-classify
    p = maps_sub.add_parser(
        'chest-classify',
        help='Classify each chest by its contents and store in map_chests.content_category',
    )
    p.add_argument('--map', default=None,
                   help='Map slug(s), comma-separated (default: all maps in DB)')
    p.set_defaults(func=handle_chest_classify)

    # maps authors
    p = maps_sub.add_parser(
        'authors',
        help='Parse map.xml authors/contributors and look up Minecraft names via Mojang API',
    )
    p.add_argument('--map', default=None,
                   help='Map slug(s), comma-separated (default: all maps in DB)')
    p.add_argument('--map-dir', default=None,
                   help='Directory containing map folders for XML lookup '
                        '(default: map_folders/). Use for CommunityMaps / PublicMaps.')
    p.add_argument('--no-fetch', action='store_true', dest='no_fetch',
                   help='Skip Mojang API lookups; insert UUIDs with NULL names')
    p.set_defaults(func=handle_authors)

    # maps geometry-graph
    p = maps_sub.add_parser(
        'geometry-graph',
        help='Build geometry-derived adjacency graph from map polygons',
    )
    p.add_argument('--map', default=None,
                   help='Map slug(s), comma-separated (default: all maps with output data)')
    p.add_argument('--output', default=None,
                   help='Output root directory (default: output/)')
    p.add_argument('--grid-size', type=int, default=None, dest='grid_size',
                   help='Grid cell size in blocks (default: adaptive from map size)')
    p.add_argument('--use-db-wools', action='store_true', dest='use_db_wools',
                   help='Use DB-confirmed wool locations instead of map_context positions')
    p.add_argument('--no-plot', action='store_true', dest='no_plot',
                   help='Skip generating the geometry_graph.png visualization')
    p.add_argument('--force', action='store_true',
                   help='Overwrite existing geometry_graph.json and geometry_graph.png')
    p.set_defaults(func=handle_geometry_graph)


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
                spawn['team'].removesuffix('-team'), spawn['team_color'],
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

    symmetry_type, symmetry_confidence, has_intra_team_symmetry = _read_symmetry(map_dir)
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
        'symmetry_confidence': symmetry_confidence,
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
                symmetry_confidence = ?,
                has_intra_team_symmetry = ?,
                stub = FALSE,
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
            row['symmetry_type'], row['symmetry_confidence'],
            row['has_intra_team_symmetry'],
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
                size_tier, symmetry_type, symmetry_confidence,
                has_intra_team_symmetry, stub, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, FALSE, ?)
        """, [
            row['map_slug'], row['map_name'], row['max_build_height'],
            row['min_x'], row['max_x'], row['min_z'], row['max_z'],
            row['center_x'], row['center_z'],
            row['island_count'], row['team_count'],
            row['wools_per_team'], row['max_players_per_team'],
            row['total_blocks'], row['size_tier'],
            row['symmetry_type'], row['symmetry_confidence'],
            row['has_intra_team_symmetry'],
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

        if getattr(args, 'skip_existing', False):
            has_data = conn.execute(
                "SELECT COUNT(*) FROM map_resource_blocks WHERE map_id = ?", [map_id]
            ).fetchone()[0]
            if has_data == 0:
                has_data = conn.execute(
                    "SELECT COUNT(*) FROM map_chests WHERE map_id = ?", [map_id]
                ).fetchone()[0]
            if has_data > 0:
                skipped += 1
                continue

        with open(map_data_path, 'r', encoding='utf-8') as f:
            map_data = json.load(f)

        # Prefer DB wool positions (from map_wool_locations) over XML-declared
        # positions, which may point to monument blocks rather than wool rooms.
        # Fall back to XML positions when no DB data exists for this map.
        db_wool_rows = conn.execute(
            "SELECT x, z FROM map_wool_locations WHERE map_id = ?", [map_id]
        ).fetchall()
        wool_positions = [(float(r[0]), float(r[1])) for r in db_wool_rows] or None

        clf = ZoneClassifier(
            map_data,
            defense_buffer=args.defense_buffer,
            near_spawn_buffer=args.near_spawn_buffer,
            wool_positions=wool_positions,
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
                chests_classified = clf.classify_dataframe(chests_df, include_near_spawn=False)

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


def handle_chest_classify(args) -> None:
    """Classify each chest by its contents and write to map_chests.content_category."""
    import duckdb
    from match_analysis.database.schema import migrate_chest_category_column
    from ctw.common import PROJECT_ROOT

    db_path = str(PROJECT_ROOT / 'match_analysis' / 'metadata.db')
    migrate_chest_category_column(db_path)

    conn = duckdb.connect(db_path)

    # Resolve target map_ids
    if getattr(args, 'map', None):
        slugs = [s.strip() for s in args.map.split(',') if s.strip()]
        placeholders = ', '.join('?' * len(slugs))
        rows = conn.execute(
            f"SELECT map_id, map_slug FROM maps WHERE map_slug IN ({placeholders})",
            slugs,
        ).fetchall()
        found_slugs = {r[1] for r in rows}
        for slug in slugs:
            if slug not in found_slugs:
                print(f"  Warning: map slug not found in DB: {slug}")
        map_ids = [r[0] for r in rows]
    else:
        map_ids = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT map_id FROM map_chests"
            ).fetchall()
        ]

    if not map_ids:
        print("No maps to classify.")
        conn.close()
        return

    id_placeholders = ', '.join('?' * len(map_ids))

    # Compute content_category per chest using a priority-based CASE expression.
    # Priority: wool > combat (armor) > kit > weapon > supply (gapple/potion) > defense
    #
    # kit catches legacy full-kit spawn chests (pre-XML kit module) found on maps
    # like blocks_ctw and the race_for_victory series.  These chests contain a
    # weapon, a mining tool (pickaxe/axe/shovel), and food all together — a
    # combination that never appears in true weapon chests.  Classifying them as
    # 'kit' prevents their food and tool items from polluting weapon-chest stats.
    #
    # has_wool uses map_wool_locations to validate the wool damage value (color).
    # If a map has entries there, only wool whose item_damage matches a known
    # objective wool_id is counted — this prevents building-material wool of a
    # non-objective color (e.g. pink on Fairy Tales 2) from being misclassified.
    # Maps without entries fall back to accepting any wool item.
    conn.execute(f"""
        UPDATE map_chests
        SET content_category = classified.content_category
        FROM (
            WITH objective_damage AS (
                SELECT map_id, LIST(DISTINCT wool_id) AS valid_damages
                FROM map_wool_locations
                GROUP BY map_id
            ),
            chest_flags AS (
                SELECT
                    mcc.map_id, mcc.world_x, mcc.world_z, mcc.y,
                    MAX(CASE
                        WHEN mcc.item_id IN ('minecraft:wool', '35')
                             AND (od.valid_damages IS NULL
                                  OR mcc.item_damage = ANY(od.valid_damages))
                        THEN 1 ELSE 0 END)
                        AS has_wool,
                    MAX(CASE WHEN mcc.item_id LIKE '%chestplate%' OR mcc.item_id LIKE '%helmet%'
                                  OR mcc.item_id LIKE '%leggings%' OR mcc.item_id LIKE '%boots%'
                             THEN 1 ELSE 0 END) AS has_armor,
                    MAX(CASE WHEN mcc.item_id LIKE '%sword%'
                                  OR mcc.item_id IN ('minecraft:bow', '261', 'minecraft:arrow', '262')
                             THEN 1 ELSE 0 END) AS has_weapon,
                    MAX(CASE WHEN mcc.item_id IN (
                                  'minecraft:cooked_fish',     '350',
                                  'minecraft:cooked_beef',     '364',
                                  'minecraft:bread',           '297',
                                  'minecraft:cooked_chicken',  '366',
                                  'minecraft:cooked_porkchop', '320'
                             ) THEN 1 ELSE 0 END) AS has_food,
                    MAX(CASE WHEN mcc.item_id LIKE '%axe%'
                                  OR mcc.item_id LIKE '%shovel%'
                             THEN 1 ELSE 0 END) AS has_tool,
                    MAX(CASE WHEN mcc.item_id IN ('minecraft:golden_apple', '322') THEN 1 ELSE 0 END)
                        AS has_gapple,
                    MAX(CASE WHEN mcc.item_id IN ('minecraft:potion', '373') THEN 1 ELSE 0 END)
                        AS has_potion
                FROM map_chest_contents mcc
                LEFT JOIN objective_damage od ON od.map_id = mcc.map_id
                WHERE mcc.map_id IN ({id_placeholders})
                GROUP BY mcc.map_id, mcc.world_x, mcc.world_z, mcc.y
            )
            SELECT
                map_id, world_x, world_z, y,
                CASE
                    WHEN has_wool   = 1                              THEN 'wool'
                    WHEN has_armor  = 1                              THEN 'combat'
                    WHEN has_weapon = 1 AND has_food = 1
                                        AND has_tool = 1            THEN 'kit'
                    WHEN has_weapon = 1                              THEN 'weapon'
                    WHEN has_gapple = 1 OR has_potion = 1           THEN 'supply'
                    ELSE 'defense'
                END AS content_category
            FROM chest_flags
        ) AS classified
        WHERE map_chests.map_id     = classified.map_id
          AND map_chests.world_x    = classified.world_x
          AND map_chests.world_z    = classified.world_z
          AND map_chests.y          = classified.y
          AND map_chests.map_id IN ({id_placeholders})
    """, map_ids + map_ids)

    # Chests with no contents get 'empty'
    conn.execute(f"""
        UPDATE map_chests
        SET content_category = 'empty'
        WHERE content_category IS NULL
          AND map_id IN ({id_placeholders})
    """, map_ids)

    counts = conn.execute(f"""
        SELECT content_category, COUNT(*) AS n
        FROM map_chests
        WHERE map_id IN ({id_placeholders})
        GROUP BY content_category
        ORDER BY n DESC
    """, map_ids).fetchall()

    conn.close()

    total = sum(r[1] for r in counts)
    print(f"\nClassified {total} chests across {len(map_ids)} map(s):")
    for category, n in counts:
        print(f"  {category:<10} {n:>5}  ({100*n/total:.1f}%)")


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

        if getattr(args, 'skip_existing', False):
            has_data = conn.execute(
                "SELECT COUNT(*) FROM map_kit_items WHERE map_id = ?", [map_id]
            ).fetchone()[0]
            if has_data > 0:
                skipped += 1
                continue

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


def handle_spatial_relations(args) -> None:
    """Compute vector-based POI spatial relations and store them in the DB."""
    import duckdb
    from match_analysis.traffic.spatial_relations import compute_and_upsert
    from match_analysis.database.schema import migrate_spatial_relations_tables

    ensure_match_db()
    migrate_spatial_relations_tables()

    db_path = Path('match_analysis/metadata.db')

    conn_ro = duckdb.connect(str(db_path), read_only=True)
    if args.map:
        slugs = [s.strip() for s in args.map.split(',') if s.strip()]
    else:
        slugs = [r[0] for r in conn_ro.execute(
            "SELECT map_slug FROM maps ORDER BY map_slug"
        ).fetchall()]
    conn_ro.close()

    if not slugs:
        print("No maps found in the maps table.")
        return

    print(f"Computing spatial relations for {len(slugs)} map(s)...")
    loaded = 0
    skipped = 0
    for slug in slugs:
        conn = duckdb.connect(str(db_path))
        try:
            # Quick pre-check: does this map have spawn data?
            has_spawns = conn.execute(
                "SELECT COUNT(*) FROM map_spawns ms "
                "JOIN maps m ON m.map_id = ms.map_id "
                "WHERE m.map_slug = ?",
                [slug],
            ).fetchone()[0]
            if has_spawns == 0:
                print(f"  Skip {slug}: no spawn data (run 'maps spawns' first)")
                skipped += 1
                continue
            has_wools = conn.execute(
                "SELECT COUNT(*) FROM map_wool_locations mwl "
                "JOIN maps m ON m.map_id = mwl.map_id "
                "WHERE m.map_slug = ?",
                [slug],
            ).fetchone()[0]
            if has_wools == 0:
                print(f"  Skip {slug}: no wool locations (run 'matches update-wool-locations' first)")
                skipped += 1
                continue

            compute_and_upsert(conn, conn, slug)
            # Report summary counts
            map_id = conn.execute(
                "SELECT map_id FROM maps WHERE map_slug = ?", [slug]
            ).fetchone()[0]
            n_wool = conn.execute(
                "SELECT COUNT(*) FROM map_wool_attack_relations WHERE map_id = ?",
                [map_id],
            ).fetchone()[0]
            n_team = conn.execute(
                "SELECT COUNT(*) FROM map_team_spatial WHERE map_id = ?",
                [map_id],
            ).fetchone()[0]
            print(f"  [OK] {slug}: {n_wool} wool relation(s), {n_team} team pair(s)")
            loaded += 1
        except Exception as e:
            print(f"  {slug}: ERROR — {e}")
            skipped += 1
        finally:
            conn.close()

    print(f"\nDone: {loaded} map(s) processed, {skipped} skipped.")


def handle_terrain_height(args) -> None:
    """Populate map_terrain_height from per-map layout parquets."""
    import duckdb
    from match_analysis.database.schema import migrate_terrain_height_table
    from match_analysis.database.terrain_height import populate_terrain_height

    ensure_match_db()
    migrate_terrain_height_table()

    map_dirs = _resolve_map_dirs(args)
    if map_dirs is None:
        return

    db_path = Path('match_analysis/metadata.db')
    conn = duckdb.connect(str(db_path))

    loaded = 0
    skipped = 0
    for map_dir in map_dirs:
        map_slug = map_dir.name

        result = conn.execute(
            "SELECT map_id FROM maps WHERE map_slug = ?", [map_slug]
        ).fetchone()
        if result is None:
            print(f"  Skip {map_slug}: not in maps table (run 'maps load' first)")
            skipped += 1
            continue
        map_id = result[0]

        n = populate_terrain_height(map_id, map_dir, conn)
        if n == 0:
            print(f"  Skip {map_slug}: no rows inserted (check warnings above)")
            skipped += 1
        else:
            print(f"  [OK] {map_slug}: {n} terrain height rows")
            loaded += 1

    conn.close()
    print(f"\nDone: {loaded} map(s) loaded, {skipped} skipped.")


def handle_authors(args) -> None:
    """Parse map.xml authors/contributors, look up Minecraft names, store in DB."""
    import json as _json
    import time
    import urllib.request
    import urllib.error
    import xml.etree.ElementTree as ET
    import duckdb
    from match_analysis.database.schema import migrate_authors_tables
    from ctw.common import PROJECT_ROOT

    ensure_match_db()
    migrate_authors_tables()

    db_path = Path('match_analysis/metadata.db')
    xml_root = Path(args.map_dir) if getattr(args, 'map_dir', None) else PROJECT_ROOT / 'map_folders'

    conn = duckdb.connect(str(db_path))

    # Resolve map slugs
    if args.map:
        slugs = [s.strip() for s in args.map.split(',') if s.strip()]
    else:
        slugs = [r[0] for r in conn.execute(
            "SELECT map_slug FROM maps ORDER BY map_slug"
        ).fetchall()]

    if not slugs:
        print("No maps found.")
        conn.close()
        return

    # Pass 1: collect all UUIDs per map
    map_uuid_roles: dict[str, list[tuple[str, str]]] = {}  # slug -> [(uuid, role)]
    skipped = 0
    for slug in slugs:
        result = conn.execute(
            "SELECT map_id FROM maps WHERE map_slug = ?", [slug]
        ).fetchone()
        if result is None:
            print(f"  Skip {slug}: not in maps table")
            skipped += 1
            continue

        xml_path = xml_root / slug / 'map.xml'
        if not xml_path.exists():
            print(f"  Skip {slug}: map.xml not found at {xml_path}")
            skipped += 1
            continue

        try:
            root = ET.parse(str(xml_path)).getroot()
        except ET.ParseError as e:
            print(f"  Skip {slug}: XML parse error — {e}")
            skipped += 1
            continue

        uuid_roles: list[tuple[str, str]] = []
        authors_el = root.find('authors')
        if authors_el is not None:
            for child in authors_el:
                uuid = child.get('uuid')
                if uuid:
                    uuid_roles.append((uuid.lower(), 'author'))
        contributors_el = root.find('contributors')
        if contributors_el is not None:
            for child in contributors_el:
                uuid = child.get('uuid')
                if uuid:
                    uuid_roles.append((uuid.lower(), 'contributor'))

        map_uuid_roles[slug] = uuid_roles

    # Pass 2: look up names for UUIDs not already cached
    all_uuids = {uuid for roles in map_uuid_roles.values() for uuid, _ in roles}
    if all_uuids:
        cached = {r[0] for r in conn.execute(
            f"SELECT uuid FROM uuid_name_cache WHERE uuid IN ({','.join('?' * len(all_uuids))})",
            list(all_uuids),
        ).fetchall()}
    else:
        cached = set()

    to_fetch = all_uuids - cached
    fetched: dict[str, str | None] = {}  # uuid -> name or None

    if to_fetch and not args.no_fetch:
        print(f"Fetching {len(to_fetch)} Minecraft name(s) from Mojang API...")
        for uuid in sorted(to_fetch):
            uuid_nodashes = uuid.replace('-', '')
            url = f"https://sessionserver.mojang.com/session/minecraft/profile/{uuid_nodashes}"
            try:
                with urllib.request.urlopen(url, timeout=5) as resp:
                    data = _json.loads(resp.read())
                    name = data.get('name')
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    name = None  # UUID not found (deleted/invalid account)
                else:
                    print(f"    Warning: HTTP {e.code} for {uuid}, skipping")
                    name = None
            except Exception as e:
                print(f"    Warning: request failed for {uuid} — {e}")
                name = None
            fetched[uuid] = name
            time.sleep(0.01)
    elif to_fetch:
        # --no-fetch: store NULLs without API calls
        fetched = {uuid: None for uuid in to_fetch}

    # Insert newly fetched UUIDs into cache
    now = datetime.now()
    for uuid, name in fetched.items():
        conn.execute("""
            INSERT INTO uuid_name_cache (uuid, name, fetched_at)
            VALUES (?, ?, ?)
            ON CONFLICT (uuid) DO UPDATE SET name = excluded.name, fetched_at = excluded.fetched_at
        """, [uuid, name, now])

    # Build full name lookup once (cached + freshly fetched)
    all_cached = {r[0]: r[1] for r in conn.execute(
        "SELECT uuid, name FROM uuid_name_cache"
    ).fetchall()}

    # Pass 3: insert map_authors rows
    loaded = 0
    for slug, uuid_roles in map_uuid_roles.items():
        map_id = conn.execute(
            "SELECT map_id FROM maps WHERE map_slug = ?", [slug]
        ).fetchone()[0]

        conn.execute("DELETE FROM map_authors WHERE map_id = ?", [map_id])

        for uuid, role in uuid_roles:
            name = all_cached.get(uuid)
            conn.execute("""
                INSERT INTO map_authors (map_id, uuid, name, role)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (map_id, uuid) DO UPDATE SET name = excluded.name, role = excluded.role
            """, [map_id, uuid, name, role])

        authors = [(uuid, role) for uuid, role in uuid_roles if role == 'author']
        contribs = [(uuid, role) for uuid, role in uuid_roles if role == 'contributor']
        name_list = ', '.join(
            all_cached.get(uuid) or uuid[:8] for uuid, _ in uuid_roles
        )
        print(f"  [OK] {slug}: {len(authors)} author(s), {len(contribs)} contributor(s) — {name_list}")
        loaded += 1

    conn.close()
    print(f"\nDone: {loaded} map(s) processed, {skipped} skipped.")


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


# ---------------------------------------------------------------------------
# maps geometry-graph
# ---------------------------------------------------------------------------


def _load_wool_pois_from_db(conn, map_slug: str) -> list[dict]:
    """Load DB-confirmed wool locations for map_slug from map_wool_locations.

    Mirrors the wool lookup in build_traffic_graph() step 7.  Returns an
    empty list if the table is absent or has no rows for this map.
    Each returned dict has keys: poi_type, coords, team, poi_color, island_id.
    """
    try:
        rows = conn.execute("""
            SELECT mwl.wool_id, mwl.x, mwl.z, mwl.wool_color, mwl.team
            FROM map_wool_locations mwl
            JOIN maps m ON m.map_id = mwl.map_id
            WHERE m.map_slug = ?
        """, [map_slug]).fetchall()
    except Exception:
        return []

    pois: list[dict] = []
    seen_colors: set[str] = set()
    for _wool_id, wx, wz, wool_color, team in rows:
        if wool_color and wool_color in seen_colors:
            continue
        if wool_color:
            seen_colors.add(wool_color)
        pois.append({
            "poi_type":  "wool",
            "coords":    [float(wx), float(wz)],
            "team":      team,
            "poi_color": wool_color,
            "island_id": None,
        })
    return pois


def handle_geometry_graph(args: object) -> None:
    """Build geometry-derived adjacency graph from map_context.json polygons."""
    import json as _json
    from map_analysis.grid_base import rasterize_map_polygons, _adaptive_grid_size
    from map_analysis.geometry_graph import build_geometry_graph, save_geometry_graph
    from match_analysis.traffic.graph import plot_traffic_graph

    map_dirs = _resolve_map_dirs(args)
    if map_dirs is None:
        return

    grid_size_arg: Optional[int] = getattr(args, 'grid_size', None)
    use_db_wools: bool = getattr(args, 'use_db_wools', False)
    no_plot: bool = getattr(args, 'no_plot', False)
    force: bool = getattr(args, 'force', False)

    conn = None
    if use_db_wools:
        import duckdb
        ensure_match_db()
        conn = duckdb.connect('match_analysis/metadata.db', read_only=True)

    try:
        for map_dir in map_dirs:
            map_slug = map_dir.name
            out_path = map_dir / 'geometry_graph.json'
            plot_path = map_dir / 'images' / 'geometry_graph.png'

            if out_path.exists() and not force:
                print(f"  [{map_slug}] already exists, skip (--force to overwrite)")
                continue
            context_path = map_dir / 'map_context.json'
            if not context_path.exists():
                print(f"  [{map_slug}] map_context.json not found, skipping")
                continue
            try:
                with open(context_path, encoding='utf-8') as fh:
                    map_context = _json.load(fh)

                grid_size = grid_size_arg
                if grid_size is None:
                    total_blocks = map_context.get('total_blocks', 5000)
                    grid_size = _adaptive_grid_size(total_blocks)

                grid_base = rasterize_map_polygons(map_context, map_slug, grid_size)

                wool_pois_override = None
                if use_db_wools and conn is not None:
                    wool_pois_override = _load_wool_pois_from_db(conn, map_slug)

                graph = build_geometry_graph(grid_base, wool_pois=wool_pois_override)
                save_geometry_graph(graph, out_path)
                print(
                    f"  [{map_slug}] {len(graph['nodes'])} nodes, "
                    f"{len(graph['edges'])} edges  (grid={grid_size})"
                )

                if not no_plot:
                    plot_path.parent.mkdir(parents=True, exist_ok=True)
                    plot_traffic_graph(graph, map_context, plot_path)
                    print(f"  [{map_slug}] plot saved: {plot_path}")

            except Exception as exc:
                print(f"  [{map_slug}] ERROR — {exc}")
    finally:
        if conn is not None:
            conn.close()
