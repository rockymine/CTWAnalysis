"""'purge' subcommand — delete per-map output folders and/or database records."""

import logging
import shutil
from pathlib import Path

from ctw.common import DEFAULT_OUTPUT_ROOT, PROJECT_ROOT

logger = logging.getLogger('ctw')

# Child tables that reference maps.map_id, in deletion order (children first).
_MAP_CHILD_TABLES = [
    'layout_block_inventory',
    'layout_layer_stats',
    'map_chest_contents',
    'map_chests',
    'map_kit_armor',
    'map_kit_items',
    'map_resource_blocks',
    'map_spawns',
    'wool_spawn_baselines',
]


def register(subparsers) -> None:
    p = subparsers.add_parser(
        'purge',
        help='Delete per-map output folders and/or database records',
    )
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument(
        '--map',
        metavar='NAME',
        help='Map slug(s) to purge (comma-separated)',
    )
    target.add_argument(
        '--all',
        action='store_true',
        dest='all',
        help='Purge ALL per-map output folders / database records',
    )
    target.add_argument(
        '--no-matches',
        action='store_true',
        dest='no_matches',
        help='Purge every map that has no match data in the database',
    )
    p.add_argument(
        '--output',
        default=None,
        help='Output root directory (default: output/)',
    )
    p.add_argument(
        '--db',
        action='store_true',
        help='Also remove map records from the database (maps table and all dependents)',
    )
    p.add_argument(
        '--yes', '-y',
        action='store_true',
        help='Skip confirmation prompt',
    )
    p.set_defaults(func=handler)


def _slugs_with_matches() -> set[str]:
    """Return the set of map slugs that have at least one match in the DB."""
    import duckdb
    db_path = PROJECT_ROOT / 'match_analysis' / 'metadata.db'
    if not db_path.exists():
        return set()
    con = duckdb.connect(str(db_path), read_only=True)
    rows = con.execute(
        'SELECT DISTINCT m.map_slug FROM maps m '
        'JOIN matches mt ON m.map_id = mt.map_id'
    ).fetchall()
    con.close()
    return {row[0] for row in rows}


def _slugs_to_db_rows(slugs: list[str]) -> list[tuple[int, str, str]]:
    """Return (map_id, map_slug, map_name) for slugs present in the DB."""
    import duckdb
    db_path = PROJECT_ROOT / 'match_analysis' / 'metadata.db'
    if not db_path.exists():
        return []
    con = duckdb.connect(str(db_path), read_only=True)
    placeholders = ', '.join('?' * len(slugs))
    rows = con.execute(
        f'SELECT map_id, map_slug, map_name FROM maps WHERE map_slug IN ({placeholders})',
        slugs,
    ).fetchall()
    con.close()
    return rows


def _collect_file_targets(args) -> list[Path]:
    output_root = Path(args.output) if args.output else DEFAULT_OUTPUT_ROOT
    if not output_root.exists():
        logger.warning(f'Output directory does not exist: {output_root}')
        return []

    all_dirs = sorted(p for p in output_root.iterdir() if p.is_dir())

    if args.all:
        return all_dirs
    if args.map:
        slugs = [s.strip() for s in args.map.split(',') if s.strip()]
        targets = []
        for slug in slugs:
            p = output_root / slug
            if p.is_dir():
                targets.append(p)
            else:
                logger.warning(f'Output folder not found, skipping: {p}')
        return targets
    if args.no_matches:
        has_matches = _slugs_with_matches()
        return [p for p in all_dirs if p.name not in has_matches]
    return []


def _collect_db_targets(args) -> list[tuple[int, str, str]]:
    """Return (map_id, slug, name) rows for maps to remove from the DB."""
    import duckdb
    db_path = PROJECT_ROOT / 'match_analysis' / 'metadata.db'
    if not db_path.exists():
        logger.warning('Database not found; skipping DB purge.')
        return []

    con = duckdb.connect(str(db_path), read_only=True)

    if args.all:
        rows = con.execute(
            'SELECT map_id, map_slug, map_name FROM maps ORDER BY map_name'
        ).fetchall()
    elif args.map:
        slugs = [s.strip() for s in args.map.split(',') if s.strip()]
        placeholders = ', '.join('?' * len(slugs))
        rows = con.execute(
            f'SELECT map_id, map_slug, map_name FROM maps '
            f'WHERE map_slug IN ({placeholders}) ORDER BY map_name',
            slugs,
        ).fetchall()
        found = {r[1] for r in rows}
        for slug in slugs:
            if slug not in found:
                logger.warning(f'Map slug not found in database, skipping: {slug}')
    elif args.no_matches:
        rows = con.execute(
            'SELECT m.map_id, m.map_slug, m.map_name FROM maps m '
            'LEFT JOIN matches mt ON m.map_id = mt.map_id '
            'WHERE mt.map_id IS NULL '
            'ORDER BY m.map_name'
        ).fetchall()
    else:
        rows = []

    con.close()
    return rows


def _purge_from_db(map_ids: list[int]) -> None:
    import duckdb
    db_path = PROJECT_ROOT / 'match_analysis' / 'metadata.db'
    con = duckdb.connect(str(db_path))
    placeholders = ', '.join('?' * len(map_ids))
    for table in _MAP_CHILD_TABLES:
        con.execute(f'DELETE FROM {table} WHERE map_id IN ({placeholders})', map_ids)
    con.execute(f'DELETE FROM maps WHERE map_id IN ({placeholders})', map_ids)
    con.close()


def handler(args) -> None:
    file_targets = _collect_file_targets(args)
    db_targets = _collect_db_targets(args) if args.db else []

    if not file_targets and not db_targets:
        logger.info('Nothing to purge.')
        return

    if file_targets:
        logger.info(f'Output folders to delete ({len(file_targets)}):')
        for p in file_targets:
            size_mb = sum(f.stat().st_size for f in p.rglob('*') if f.is_file()) / 1_048_576
            logger.info(f'  {p.name}  ({size_mb:.1f} MB)')

    if db_targets:
        logger.info(f'Database records to remove ({len(db_targets)}):')
        for _, slug, name in db_targets:
            logger.info(f'  {slug}  ({name})')

    if not args.yes:
        parts = []
        if file_targets:
            parts.append(f'{len(file_targets)} output folder(s)')
        if db_targets:
            parts.append(f'{len(db_targets)} database record(s)')
        try:
            answer = input(f'\nPurge {" and ".join(parts)}? [y/N] ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            logger.info('Aborted.')
            return
        if answer != 'y':
            logger.info('Aborted.')
            return

    if file_targets:
        n_ok = n_fail = 0
        for p in file_targets:
            try:
                shutil.rmtree(p)
                n_ok += 1
            except Exception as e:
                logger.warning(f'  Failed to delete {p}: {e}')
                n_fail += 1
        logger.info(f'Files: {n_ok} deleted, {n_fail} failed.')

    if db_targets:
        map_ids = [row[0] for row in db_targets]
        try:
            _purge_from_db(map_ids)
            logger.info(f'Database: {len(map_ids)} map(s) removed.')
        except Exception as e:
            logger.error(f'Database purge failed: {e}')
