"""'purge' subcommand — delete per-map output folders."""

import logging
import shutil
from pathlib import Path

from ctw.common import DEFAULT_OUTPUT_ROOT, PROJECT_ROOT

logger = logging.getLogger('ctw')


def register(subparsers) -> None:
    p = subparsers.add_parser(
        'purge',
        help='Delete per-map output folders',
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
        help='Purge ALL per-map output folders',
    )
    target.add_argument(
        '--no-matches',
        action='store_true',
        dest='no_matches',
        help='Purge output for every map that has no match data in the database',
    )
    p.add_argument(
        '--output',
        default=None,
        help='Output root directory (default: output/)',
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


def _collect_targets(args) -> list[Path]:
    output_root = Path(args.output) if args.output else DEFAULT_OUTPUT_ROOT

    if not output_root.exists():
        logger.warning(f'Output directory does not exist: {output_root}')
        return []

    all_output_dirs = sorted(p for p in output_root.iterdir() if p.is_dir())

    if args.all:
        return all_output_dirs

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
        return [p for p in all_output_dirs if p.name not in has_matches]

    return []


def handler(args) -> None:
    targets = _collect_targets(args)

    if not targets:
        logger.info('Nothing to purge.')
        return

    logger.info(f'Folders to delete ({len(targets)}):')
    for p in targets:
        size_mb = sum(f.stat().st_size for f in p.rglob('*') if f.is_file()) / 1_048_576
        logger.info(f'  {p.name}  ({size_mb:.1f} MB)')

    if not args.yes:
        try:
            answer = input(f'\nDelete {len(targets)} folder(s)? [y/N] ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            logger.info('Aborted.')
            return
        if answer != 'y':
            logger.info('Aborted.')
            return

    n_ok = 0
    n_fail = 0
    for p in targets:
        try:
            shutil.rmtree(p)
            logger.debug(f'  Deleted: {p}')
            n_ok += 1
        except Exception as e:
            logger.warning(f'  Failed to delete {p}: {e}')
            n_fail += 1

    logger.info(f'Purge complete: {n_ok} deleted, {n_fail} failed.')
