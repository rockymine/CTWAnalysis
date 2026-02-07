"""'matches' subcommand — match data analysis commands."""

import argparse
from pathlib import Path

from ctw.common import ensure_match_db


def _player_arg(value: str):
    """Accept an integer player ID or the literal 'ALL'."""
    if value.upper() == 'ALL':
        return 'ALL'
    try:
        return int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"'{value}' is not a valid player ID or 'ALL'"
        )


def _match_arg(value: str):
    """Accept an integer, comma-separated integers, or the literal 'ALL'."""
    if value.upper() == 'ALL':
        return 'ALL'
    try:
        return [int(x.strip()) for x in value.split(',')]
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"'{value}' is not a valid match ID, comma-separated IDs, or 'ALL'"
        )


def register(subparsers):
    matches_parser = subparsers.add_parser(
        'matches',
        help='Match data analysis commands',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Actions:
  parse        Parse a structured match log file into a history CSV
  scan         Scan a <map>/<files>.parquet folder tree into a history CSV
  index        Index all match parquet files into the database
  process      Process a specific match by ID
  process-all  Process all unprocessed matches
  list         List matches in the database
  stats        Show database statistics
  reset        Reset processing state (clears trajectory files)
  trace        Visualize player traces on map

Examples:
  python ctw.py matches parse --input match_logs/logs.txt --match-dir match_logs/
  python ctw.py matches scan --folder data/ --output data/match_history.csv
  python ctw.py matches index --match-dir data --history data/match_history.csv
  python ctw.py matches list
  python ctw.py matches process 57
  python ctw.py matches process-all --force
  python ctw.py matches reset
  python ctw.py matches stats
  python ctw.py matches trace --map Ingwaz --match 1 --player 0
  python ctw.py matches trace --map Ingwaz --match 1,2,3 --player ALL --color-mode team
  python ctw.py matches trace --map Ingwaz --match ALL --player 0
  python ctw.py matches trace --map Ingwaz --match 1 --player 0 --no-edges --color-mode location
""",
    )
    matches_sub = matches_parser.add_subparsers(
        dest='matches_action', metavar='<action>',
    )

    # matches parse
    p = matches_sub.add_parser('parse', help='Parse a structured match log file into a history CSV')
    p.add_argument('--input', required=True, help='Path to the structured text log file')
    p.add_argument('--match-dir', help='Directory for default output (writes match_history.csv there)')
    p.add_argument('--output', help='Output CSV path (overrides --match-dir default)')
    p.set_defaults(func=handle_parse)

    # matches scan
    p = matches_sub.add_parser(
        'scan',
        help='Scan a <map>/<files>.parquet folder tree into a history CSV',
    )
    p.add_argument('--folder', required=True,
                   help='Root folder containing per-map subdirectories of parquet files')
    p.add_argument('--output', help='Output CSV path (default: <folder>/match_history.csv)')
    p.set_defaults(func=handle_scan)

    # matches index
    p = matches_sub.add_parser('index', help='Index all match files')
    p.add_argument('--match-dir', help='Directory containing match parquet files (default: match_logs)')
    p.add_argument('--history', help='Path to history CSV (parquet_file,map_name) to set map names')
    p.set_defaults(func=handle_index)

    # matches process
    p = matches_sub.add_parser('process', help='Process a specific match by ID')
    p.add_argument('match_id', type=int, help='Match ID to process')
    p.add_argument('--force', action='store_true',
                   help='Reprocess even if already processed')
    p.set_defaults(func=handle_process)

    # matches process-all
    p = matches_sub.add_parser('process-all', help='Process all unprocessed matches')
    p.add_argument('--map-name', help='Only process matches for this map')
    p.add_argument('--force', action='store_true',
                   help='Reprocess all matches, not just unprocessed ones')
    p.set_defaults(func=handle_process_all)

    # matches reset
    p = matches_sub.add_parser('reset', help='Reset processing state for all matches')
    p.add_argument('--match-id', type=int, help='Reset only a specific match ID')
    p.set_defaults(func=handle_reset)

    # matches list
    p = matches_sub.add_parser('list', help='List matches in the database')
    p.add_argument('--map-name', help='Filter by map name')
    p.add_argument('--processed', action='store_true', help='Show only processed matches')
    p.add_argument('--unprocessed', action='store_true', help='Show only unprocessed matches')
    p.set_defaults(func=handle_list)

    # matches stats
    p = matches_sub.add_parser('stats', help='Show database statistics')
    p.set_defaults(func=handle_stats)

    # matches trace
    p = matches_sub.add_parser('trace', help='Visualize player traces on map')
    p.add_argument('--map', required=True,
                   help='Map name (e.g., Ingwaz) or path to map folder')
    p.add_argument('--match', required=True, type=_match_arg,
                   help='Match ID, comma-separated IDs (1,2,3), or ALL')
    p.add_argument('--player', required=True, type=_player_arg,
                   help='Player ID to visualize, or ALL for every player')
    p.add_argument('--output', help='Output PNG path (default: auto-generated)')
    p.add_argument('--snap-skeleton', action='store_true',
                   help='Snap on-island positions to skeleton paths')
    p.add_argument('--no-deaths', action='store_true',
                   help='Hide death markers')
    p.add_argument('--no-kills', action='store_true',
                   help='Hide kill markers')
    p.add_argument('--no-wool', action='store_true',
                   help='Hide wool event markers')
    p.add_argument('--no-edges', action='store_true',
                   help='Show position dots instead of trace lines')
    p.add_argument('--no-legend', action='store_true',
                   help='Hide the legend')
    p.add_argument('--no-stats', action='store_true',
                   help='Hide the stats box')
    p.add_argument('--color-mode', choices=['life', 'team', 'location'],
                   default='life',
                   help='Color scheme: life (per-segment), team (by spawn team), '
                        'location (by position type)')
    p.add_argument('--map-base', choices=['outline', 'blocks'],
                   default='outline',
                   help='Map base layer: outline (polygon outlines) or '
                        'blocks (individual blocks from layout parquet)')
    p.set_defaults(func=handle_trace)


def handle_parse(args):
    from match_analysis.match_log_parser import parse_match_log, write_csv

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: input file not found: {input_path}")
        return

    rows = parse_match_log(input_path)

    if not rows:
        print("No parquet/map pairs found.")
        return

    if args.output:
        output_path = Path(args.output)
    elif args.match_dir:
        output_path = Path(args.match_dir) / 'match_history.csv'
    else:
        output_path = Path('match_history.csv')

    write_csv(rows, output_path)
    print(f"Wrote {len(rows)} rows to {output_path}")


def handle_scan(args):
    from match_analysis.match_log_parser import scan_match_folder, write_csv

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"Error: folder not found: {folder}")
        return

    rows = scan_match_folder(folder)

    if not rows:
        print(f"No <map>/<file>.parquet entries found in {folder}")
        return

    maps = sorted(set(r['map_name'] for r in rows))
    print(f"Found {len(rows)} parquet files across {len(maps)} maps:")
    for m in maps:
        count = sum(1 for r in rows if r['map_name'] == m)
        print(f"  {m}: {count}")

    output_path = Path(args.output) if args.output else folder / 'match_history.csv'
    write_csv(rows, output_path)
    print(f"\nWrote {len(rows)} rows to {output_path}")


def handle_index(args):
    ensure_match_db()
    from match_analysis.match_indexer import index_match_files

    match_dir = args.match_dir or 'match_logs'
    history_csv = getattr(args, 'history', None)
    indexed, skipped = index_match_files(match_dir, history_csv=history_csv)

    import duckdb
    conn = duckdb.connect('match_analysis/metadata.db', read_only=True)
    result = conn.execute(
        "SELECT COUNT(*) as total, COUNT(DISTINCT map_name) as maps FROM matches"
    ).fetchone()
    conn.close()

    print(f"\nTotal indexed: {result[0]} matches across {result[1]} maps")


def handle_process(args):
    ensure_match_db()
    from match_analysis.trajectory_extractor import process_match

    if getattr(args, 'force', False):
        import duckdb
        conn = duckdb.connect('match_analysis/metadata.db')
        conn.execute(
            "UPDATE matches SET processed = FALSE WHERE match_id = ?",
            [args.match_id],
        )
        conn.close()

    process_match(args.match_id)


def handle_process_all(args):
    ensure_match_db()
    import duckdb
    from match_analysis.trajectory_extractor import process_match

    conn = duckdb.connect('match_analysis/metadata.db')

    if getattr(args, 'force', False):
        reset_query = "UPDATE matches SET processed = FALSE"
        reset_params = []
        if args.map_name:
            reset_query += " WHERE map_name = ?"
            reset_params.append(args.map_name)
        conn.execute(reset_query, reset_params)
        print("Reset processing flags (--force).")

    query = "SELECT match_id FROM matches WHERE processed = FALSE"
    params = []
    if args.map_name:
        query += " AND map_name = ?"
        params.append(args.map_name)
    query += " ORDER BY match_id"

    results = conn.execute(query, params).fetchall()
    conn.close()

    total = len(results)
    if total == 0:
        print("No unprocessed matches found.")
        return

    print(f"Processing {total} matches...")

    for i, (match_id,) in enumerate(results, 1):
        print(f"\n[{i}/{total}] Processing match {match_id}")
        process_match(match_id)


def handle_reset(args):
    ensure_match_db()
    import duckdb
    from pathlib import Path
    import shutil

    conn = duckdb.connect('match_analysis/metadata.db')

    if args.match_id:
        conn.execute(
            "UPDATE matches SET processed = FALSE, processed_at = NULL, processing_time = NULL WHERE match_id = ?",
            [args.match_id],
        )
        traj_file = Path(f'match_analysis/trajectories/{args.match_id}.parquet')
        if traj_file.exists():
            traj_file.unlink()
            print(f"Deleted {traj_file}")
        print(f"Reset match {args.match_id}.")
    else:
        conn.execute(
            "UPDATE matches SET processed = FALSE, processed_at = NULL, processing_time = NULL"
        )
        traj_dir = Path('match_analysis/trajectories')
        count = 0
        for f in traj_dir.glob('*.parquet'):
            f.unlink()
            count += 1
        print(f"Reset all matches. Deleted {count} trajectory files.")

    conn.close()


def handle_trace(args):
    import json
    import duckdb
    from ctw.common import resolve_map_folder, resolve_output_dir
    from match_analysis.services import get_match_file, get_match_player_ids
    from match_analysis.visualization import plot_player_traces

    ensure_match_db()

    map_folder = resolve_map_folder(args.map)
    map_name = map_folder.name
    map_output_dir = resolve_output_dir(map_folder, create=False)

    # --- resolve match IDs ------------------------------------------------
    if args.match == 'ALL':
        conn = duckdb.connect('match_analysis/metadata.db', read_only=True)
        rows = conn.execute(
            "SELECT match_id FROM matches WHERE map_name = ? ORDER BY match_id",
            [map_name],
        ).fetchall()
        conn.close()
        match_ids = [r[0] for r in rows]
        if not match_ids:
            print(f"No matches found for map '{map_name}'.")
            return
        print(f"Found {len(match_ids)} matches for map '{map_name}'.")
    else:
        match_ids = args.match  # list[int] from _match_arg

    # --- shared map setup (done once) -------------------------------------
    def _find_file(rel_path):
        """Check map_output_dir first, fall back to map_folder."""
        p = map_output_dir / rel_path
        if p.exists():
            return p
        p = map_folder / rel_path
        if p.exists():
            return p
        return None

    context_path = _find_file('island_analysis/map_context.json')
    if context_path is None:
        print(f"Error: map_context.json not found in {map_output_dir} or {map_folder}")
        print("Run 'ctw islands --map ...' first to generate map context.")
        return

    with open(context_path) as f:
        map_context = json.load(f)

    needs_graph = args.snap_skeleton or args.color_mode in ('team', 'location')
    map_graph = None
    if needs_graph:
        graph_path = _find_file('map_graph.json')
        if graph_path is None:
            print(f"Error: map_graph.json not found in {map_output_dir} or {map_folder}")
            print("Run 'ctw islands --map ...' first to generate map graph.")
            return
        with open(graph_path) as f:
            map_graph = json.load(f)

    layout_dir = map_output_dir if (map_output_dir / 'layout_bedrock.parquet').exists() else map_folder

    # --- per-match loop ---------------------------------------------------
    traced = 0
    for match_id in match_ids:
        try:
            match_file, db_map_name = get_match_file(match_id)
        except ValueError as e:
            print(f"Error: {e}")
            continue

        if db_map_name != map_name:
            print(f"Skipping match {match_id}: map is '{db_map_name}', not '{map_name}'")
            continue

        match_path = Path(match_file)
        if not match_path.exists():
            print(f"Error: match file not found: {match_file}")
            continue

        # Resolve player IDs
        if args.player == 'ALL':
            player_ids = get_match_player_ids(str(match_file))
            if not player_ids:
                print(f"No players found in match {match_id}.")
                continue
        else:
            player_ids = [args.player]

        # Determine output path
        if args.output and len(match_ids) == 1:
            output_path = Path(args.output)
        else:
            trace_dir = map_output_dir / 'match_analysis'
            player_label = 'all' if args.player == 'ALL' else f'player{args.player}'
            output_path = trace_dir / f"trace_{player_label}_match{match_id}.png"

        if len(match_ids) > 1:
            print(f"  Tracing match {match_id} ({len(player_ids)} players)...")

        plot_player_traces(
            map_context, str(match_file), player_ids, output_path,
            map_graph=map_graph,
            snap_skeleton=args.snap_skeleton,
            show_deaths=not args.no_deaths,
            show_kills=not args.no_kills,
            show_wool=not args.no_wool,
            show_edges=not args.no_edges,
            show_legend=not args.no_legend,
            show_stats=not args.no_stats,
            color_mode=args.color_mode,
            map_base=args.map_base,
            map_folder=layout_dir,
        )
        traced += 1

    if len(match_ids) > 1:
        print(f"\nTraced {traced}/{len(match_ids)} matches.")


def handle_list(args):
    ensure_match_db()
    import duckdb

    conn = duckdb.connect('match_analysis/metadata.db')

    query = "SELECT match_id, map_name, player_count, match_duration, processed FROM matches"
    conditions = []
    params = []

    if args.map_name:
        conditions.append("map_name = ?")
        params.append(args.map_name)
    if args.processed:
        conditions.append("processed = TRUE")
    elif args.unprocessed:
        conditions.append("processed = FALSE")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY match_id"

    results = conn.execute(query, params).fetchall()
    conn.close()

    print(f"\nFound {len(results)} matches:\n")
    print(f"{'ID':<6} {'Map':<15} {'Players':<8} {'Duration':<10} {'Processed'}")
    print("-" * 55)

    for match_id, map_name, players, duration, proc in results:
        duration_str = f"{duration:.0f}s" if duration else "N/A"
        proc_str = "yes" if proc else "no"
        print(f"{match_id:<6} {map_name:<15} {players:<8} {duration_str:<10} {proc_str}")


def handle_stats(args):
    ensure_match_db()
    import duckdb

    conn = duckdb.connect('match_analysis/metadata.db')

    result = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN processed THEN 1 ELSE 0 END) as processed,
            COUNT(DISTINCT map_name) as maps,
            SUM(player_count) as total_players,
            SUM(position_count) as total_positions
        FROM matches
    """).fetchone()

    total = result[0]
    if total == 0:
        print("No matches in database. Run 'ctw matches index' first.")
        conn.close()
        return

    print("\n=== Match Database Statistics ===\n")
    print(f"Total matches: {total}")
    print(f"Processed: {result[1]} ({result[1]/total*100:.1f}%)")
    print(f"Unique maps: {result[2]}")
    print(f"Total player records: {result[3]:,}")
    print(f"Total position records: {result[4]:,}")

    print("\n=== Matches by Map ===\n")
    results = conn.execute("""
        SELECT
            map_name,
            COUNT(*) as count,
            SUM(CASE WHEN processed THEN 1 ELSE 0 END) as processed
        FROM matches
        GROUP BY map_name
        ORDER BY count DESC
    """).fetchall()

    for map_name, count, processed in results:
        print(f"{map_name:<20} {count:>3} matches ({processed} processed)")

    conn.close()
