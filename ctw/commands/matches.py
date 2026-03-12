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
  parse          Parse a structured match log file into a history CSV
  scan           Scan a <map>/<files>.parquet folder tree into a history CSV
  index          Index all match parquet files into the database
  process        Process a specific match by ID
  process-all    Process all unprocessed matches
  list           List matches in the database
  stats          Show database statistics
  reset          Reset processing state (clears trajectory files)
  post-process   Build life_segment_features from processed matches
  trace          Visualize player traces on map
  kills          Visualize kill-death pairs on map
  traffic-graph  Build data-driven traffic graph from player position traces (--map or --all)

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
  python ctw.py matches trace --map Ingwaz --match ALL --player ALL --overlay
  python ctw.py matches kills --map Ingwaz --match 406
  python ctw.py matches kills --map Ingwaz --match ALL --overlay
  python ctw.py matches kills --map Ingwaz --match ALL --overlay --color-mode distance
  python ctw.py matches post-process --match 1
  python ctw.py matches post-process --all
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
    p.add_argument('--overlay', action='store_true',
                   help='Overlay all matches onto a single plot '
                        '(use with --match ALL)')
    p.set_defaults(func=handle_trace)

    # matches post-process
    p = matches_sub.add_parser(
        'post-process',
        help='Run post-processing to build life segment features',
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument(
        '--match', type=int, metavar='ID',
        help='Post-process a specific match by ID',
    )
    group.add_argument(
        '--all', action='store_true',
        help='Post-process all processed matches',
    )
    p.set_defaults(func=handle_post_process)

    # matches kills
    p = matches_sub.add_parser('kills', help='Visualize kill-death pairs on map')
    p.add_argument('--map', required=True,
                   help='Map name (e.g., Ingwaz) or path to map folder')
    p.add_argument('--match', required=True, type=_match_arg,
                   help='Match ID, comma-separated IDs (1,2,3), or ALL')
    p.add_argument('--output', help='Output PNG path (default: auto-generated)')
    p.add_argument('--overlay', action='store_true',
                   help='Overlay all matches onto a single plot '
                        '(use with --match ALL)')
    p.add_argument('--no-legend', action='store_true',
                   help='Hide the legend')
    p.add_argument('--no-stats', action='store_true',
                   help='Hide the stats box')
    p.add_argument('--color-mode', choices=['team', 'distance'],
                   default='team',
                   help='Color scheme: team (by killer team) or '
                        'distance (green-red gradient by kill range)')
    p.add_argument('--map-base', choices=['outline', 'blocks'],
                   default='outline',
                   help='Map base layer: outline (polygon outlines) or '
                        'blocks (individual blocks from layout parquet)')
    p.set_defaults(func=handle_kills, color_mode='team')

    # matches traffic-graph
    p = matches_sub.add_parser(
        'traffic-graph',
        help='Build data-driven traffic graph from player position traces',
    )
    map_group = p.add_mutually_exclusive_group(required=True)
    map_group.add_argument('--map',
                           help='Map slug (e.g. tumbleweed) to build the graph for')
    map_group.add_argument('--all', action='store_true',
                           help='Build traffic graphs for all maps with recorded matches')
    p.add_argument('--grid-size', type=int, default=None,
                   help='Block-side of each grid cell (default: auto from map size)')
    p.add_argument('--min-occupation', type=int, default=5,
                   help='Min position ticks to keep a node (default: 5)')
    p.add_argument('--min-transitions', type=int, default=2,
                   help='Min crossings to keep an edge (default: 2)')
    p.add_argument('--log-interval', type=int, default=2, choices=[2, 5],
                   help='Only use matches logged at this interval in seconds (default: 2)')
    p.add_argument('--strategy', default='grid', choices=['grid', 'voronoi'],
                   help='Graph construction strategy: grid (default) or voronoi (k-means)')
    p.add_argument('--compare', action='store_true',
                   help='Generate strategy comparison plot instead of building the graph')
    p.add_argument('--force', action='store_true',
                   help='Overwrite existing traffic_graph.json')
    p.set_defaults(func=handle_traffic_graph)


def handle_parse(args):
    from match_analysis.database.log_parser import parse_match_log, write_csv

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
    from match_analysis.database.log_parser import scan_match_folder, write_csv

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
    from match_analysis.database.indexer import index_match_files

    match_dir = args.match_dir or 'match_logs'
    history_csv = getattr(args, 'history', None)
    indexed, skipped = index_match_files(match_dir, history_csv=history_csv)

    import duckdb
    conn = duckdb.connect('match_analysis/metadata.db', read_only=True)
    result = conn.execute(
        "SELECT COUNT(*) as total, COUNT(DISTINCT map_id) as maps FROM matches"
    ).fetchone()
    conn.close()

    print(f"\nTotal indexed: {result[0]} matches across {result[1]} maps")


def handle_process(args):
    ensure_match_db()
    from match_analysis.processing.processor import process_match

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
    from match_analysis.processing.processor import process_match

    conn = duckdb.connect('match_analysis/metadata.db')

    if getattr(args, 'force', False):
        reset_query = "UPDATE matches SET processed = FALSE"
        reset_params = []
        if args.map_name:
            map_id = conn.execute(
                "SELECT map_id FROM maps WHERE map_slug = ?",
                [args.map_name],
            ).fetchone()
            if map_id is None:
                print(f"Error: map '{args.map_name}' not found in maps table")
                conn.close()
                return
            reset_query += " WHERE map_id = ?"
            reset_params.append(map_id[0])
        conn.execute(reset_query, reset_params)
        print("Reset processing flags (--force).")

    query = "SELECT match_id FROM matches WHERE processed = FALSE"
    params = []
    if args.map_name:
        map_id = conn.execute(
            "SELECT map_id FROM maps WHERE map_slug = ?",
            [args.map_name],
        ).fetchone()
        if map_id is None:
            print(f"Error: map '{args.map_name}' not found in maps table")
            conn.close()
            return
        query += " AND map_id = ?"
        params.append(map_id[0])
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


def handle_post_process(args):
    ensure_match_db()
    import duckdb
    from match_analysis.processing.post_processor import run_post_processing

    conn = duckdb.connect('match_analysis/metadata.db')

    try:
        if getattr(args, 'all', False):
            rows = conn.execute(
                "SELECT match_id FROM matches WHERE processed = TRUE ORDER BY match_id"
            ).fetchall()
            if not rows:
                print("No processed matches found. Run 'ctw matches process' first.")
                conn.close()
                return
            print(f"Post-processing {len(rows)} match(es)...")
            for (match_id,) in rows:
                run_post_processing(conn, match_id)
        else:
            run_post_processing(conn, args.match)
    finally:
        conn.close()


def _find_map_file(map_output_dir: Path, map_folder: Path, rel_path: str):
    """Check map_output_dir first, fall back to map_folder.

    Returns the resolved Path or None if not found in either location.
    """
    p = map_output_dir / rel_path
    if p.exists():
        return p
    p = map_folder / rel_path
    if p.exists():
        return p
    return None


def _load_map_context(map_output_dir: Path, map_folder: Path):
    """Load map_context.json, returning the parsed dict or None on error."""
    import json

    context_path = _find_map_file(map_output_dir, map_folder,
                                  'map_context.json')
    if context_path is None:
        print(f"Error: map_context.json not found in {map_output_dir} or {map_folder}")
        print("Run 'ctw islands --map ...' first to generate map context.")
        return None

    with open(context_path) as f:
        return json.load(f)


def _load_map_graph(map_output_dir: Path, map_folder: Path, required: bool = False):
    """Load map_graph.json if available, returning the parsed dict or None."""
    import json

    graph_path = _find_map_file(map_output_dir, map_folder, 'map_graph.json')
    if graph_path is None:
        if required:
            print(f"Error: map_graph.json not found in {map_output_dir} or {map_folder}")
            print("Run 'ctw islands --map ...' first to generate map graph.")
        return None

    with open(graph_path) as f:
        return json.load(f)


def _resolve_layout_dir(map_output_dir: Path, map_folder: Path) -> Path:
    """Return the directory containing layout_bedrock.parquet."""
    if (map_output_dir / 'layout_bedrock.parquet').exists():
        return map_output_dir
    return map_folder


def handle_trace(args):
    from ctw.common import resolve_map_folder, resolve_output_dir
    from match_analysis.database.queries import (
        get_match_player_ids, resolve_match_ids, validate_match_ids,
    )
    from match_analysis.visualization import plot_player_traces

    ensure_match_db()

    map_folder = resolve_map_folder(args.map)
    map_slug = map_folder.name
    map_output_dir = resolve_output_dir(map_folder, create=False)

    # --- resolve and validate match IDs -----------------------------------
    match_ids = resolve_match_ids(args.match, map_slug)
    if match_ids is None:
        print(f"No processed matches found for map '{map_slug}'.")
        return

    valid_match_ids = validate_match_ids(match_ids, map_slug)
    if not valid_match_ids:
        print("No valid matches found.")
        return

    # --- load map data ----------------------------------------------------
    map_context = _load_map_context(map_output_dir, map_folder)
    if map_context is None:
        return

    map_graph = None
    if args.color_mode in ('team', 'location'):
        map_graph = _load_map_graph(map_output_dir, map_folder, required=True)
        if map_graph is None:
            return

    layout_dir = _resolve_layout_dir(map_output_dir, map_folder)

    # --- overlay mode: all matches on a single plot -----------------------
    if getattr(args, 'overlay', False):
        trace_dir = map_output_dir / 'match_analysis'
        output_path = trace_dir / f"trace_overlay_{len(valid_match_ids)}matches.png"
        if args.output and not Path(args.output).is_dir():
            output_path = Path(args.output)

        print(f"Overlaying {len(valid_match_ids)} matches onto a single plot...")

        plot_player_traces(
            map_context, valid_match_ids[0], [], output_path,
            match_ids=valid_match_ids,
            map_graph=map_graph,
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
        return

    # --- per-match loop ---------------------------------------------------
    traced = 0
    for match_id in valid_match_ids:
        # Resolve player IDs
        if args.player == 'ALL':
            player_ids = get_match_player_ids(match_id)
            if not player_ids:
                print(f"No players found in match {match_id}.")
                continue
        else:
            player_ids = [args.player]

        # Determine output path
        explicit_output = (
            args.output and len(valid_match_ids) == 1
            and not Path(args.output).is_dir()
        )
        if explicit_output:
            output_path = Path(args.output)
        else:
            trace_dir = map_output_dir / 'match_analysis'
            player_label = 'all' if args.player == 'ALL' else f'player{args.player}'
            output_path = trace_dir / f"trace_{player_label}_match{match_id}.png"

        if len(valid_match_ids) > 1:
            print(f"  Tracing match {match_id} ({len(player_ids)} players)...")

        plot_player_traces(
            map_context, match_id, player_ids, output_path,
            map_graph=map_graph,
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

    if len(valid_match_ids) > 1:
        print(f"\nTraced {traced}/{len(valid_match_ids)} matches.")


def handle_kills(args):
    from ctw.common import resolve_map_folder, resolve_output_dir
    from match_analysis.database.queries import (
        get_kill_death_pairs, resolve_match_ids, validate_match_ids,
    )
    from match_analysis.visualization import plot_kill_death_pairs

    ensure_match_db()

    # Argparse default leaks from sibling 'trace' subparser; normalize here
    if args.color_mode not in ('team', 'distance'):
        args.color_mode = 'team'

    map_folder = resolve_map_folder(args.map)
    map_slug = map_folder.name
    map_output_dir = resolve_output_dir(map_folder, create=False)

    # --- resolve and validate match IDs -----------------------------------
    match_ids = resolve_match_ids(args.match, map_slug)
    if match_ids is None:
        print(f"No processed matches found for map '{map_slug}'.")
        return

    valid_match_ids = validate_match_ids(match_ids, map_slug)
    if not valid_match_ids:
        print("No valid matches found.")
        return

    # --- load map data ----------------------------------------------------
    map_context = _load_map_context(map_output_dir, map_folder)
    if map_context is None:
        return

    map_graph = None
    if args.color_mode == 'team':
        map_graph = _load_map_graph(map_output_dir, map_folder)

    layout_dir = _resolve_layout_dir(map_output_dir, map_folder)

    # --- overlay mode: all matches on a single plot -----------------------
    if getattr(args, 'overlay', False):
        pairs_df = get_kill_death_pairs(match_ids=valid_match_ids)
        trace_dir = map_output_dir / 'match_analysis'
        output_path = trace_dir / f"kills_overlay_{len(valid_match_ids)}matches.png"
        if args.output and not Path(args.output).is_dir():
            output_path = Path(args.output)

        print(f"Overlaying kills from {len(valid_match_ids)} matches "
              f"({len(pairs_df)} pairs)...")

        plot_kill_death_pairs(
            map_context, pairs_df, output_path,
            match_ids=valid_match_ids,
            map_graph=map_graph,
            show_legend=not args.no_legend,
            show_stats=not args.no_stats,
            color_mode=args.color_mode,
            map_base=args.map_base,
            map_folder=layout_dir,
        )
        return

    # --- per-match loop ---------------------------------------------------
    plotted = 0
    for match_id in valid_match_ids:
        pairs_df = get_kill_death_pairs(match_id=match_id)

        explicit_output = (
            args.output and len(valid_match_ids) == 1
            and not Path(args.output).is_dir()
        )
        if explicit_output:
            output_path = Path(args.output)
        else:
            trace_dir = map_output_dir / 'match_analysis'
            output_path = trace_dir / f"kills_match{match_id}.png"

        if len(valid_match_ids) > 1:
            print(f"  Plotting match {match_id} ({len(pairs_df)} pairs)...")

        plot_kill_death_pairs(
            map_context, pairs_df, output_path,
            match_id=match_id,
            map_graph=map_graph,
            show_legend=not args.no_legend,
            show_stats=not args.no_stats,
            color_mode=args.color_mode,
            map_base=args.map_base,
            map_folder=layout_dir,
        )
        plotted += 1

    if len(valid_match_ids) > 1:
        print(f"\nPlotted kills for {plotted}/{len(valid_match_ids)} matches.")


def _build_traffic_graph_for_slug(args, map_slug: str) -> None:
    import duckdb
    from ctw.common import DEFAULT_OUTPUT_ROOT
    from match_analysis.traffic.graph import (
        build_traffic_graph, save_traffic_graph, plot_traffic_graph,
    )
    from match_analysis.traffic.strategy_plot import (
        plot_traffic_strategy_comparison, _adaptive_grid_size,
    )

    map_folder_candidate = Path(__file__).parent.parent.parent / 'map_folders' / map_slug
    if not map_folder_candidate.is_dir():
        map_folder_candidate = None

    map_output_dir = DEFAULT_OUTPUT_ROOT / map_slug
    if not map_output_dir.is_dir():
        print(f"Error: No output directory found for '{map_slug}' at {map_output_dir}")
        print("Run 'ctw run --map ...' first, or ensure the map has been processed.")
        return
    map_output_dir.mkdir(parents=True, exist_ok=True)

    fallback = map_folder_candidate if map_folder_candidate else map_output_dir
    map_context = _load_map_context(map_output_dir, fallback)

    log_interval  = getattr(args, 'log_interval', 2)
    strategy      = getattr(args, 'strategy', 'grid')
    do_compare    = getattr(args, 'compare', False)

    # ── Strategy comparison mode ────────────────────────────────────────────
    if do_compare:
        import pandas as pd
        conn = duckdb.connect('match_analysis/metadata.db', read_only=True)
        try:
            pos_df = conn.execute("""
                SELECT pe.player_id, pe.match_id, pe.segment_idx,
                       pe.timestamp, pe.x, pe.z, pe.y, pe.location_type
                FROM position_events pe
                JOIN matches mat ON mat.match_id = pe.match_id
                JOIN maps m      ON m.map_id = mat.map_id
                WHERE m.map_slug = ?
                  AND mat.processed = TRUE
                  AND (mat.log_interval = ? OR mat.log_interval IS NULL)
                  AND pe.y > 0
                ORDER BY pe.player_id, pe.match_id, pe.segment_idx, pe.timestamp
            """, [map_slug, log_interval]).df()
            total_blocks = conn.execute(
                "SELECT total_blocks FROM maps WHERE map_slug = ?", [map_slug]
            ).fetchone()
            total_blocks = int(total_blocks[0]) if total_blocks and total_blocks[0] else 5000
            n_matches = int(pos_df["match_id"].nunique()) if not pos_df.empty else 0
        finally:
            conn.close()

        if pos_df.empty:
            print(f"No position data for '{map_slug}' with log_interval={log_interval}.")
            return

        out_compare = map_output_dir / "traffic_strategy_comparison.png"
        plot_traffic_strategy_comparison(
            map_slug=map_slug,
            pos_df=pos_df,
            total_blocks=total_blocks,
            n_matches=n_matches,
            map_context=map_context,
            min_occupation=args.min_occupation,
            min_transitions=args.min_transitions,
            output_path=out_compare,
        )
        print(f"Saved: {out_compare}")
        return

    # ── Normal graph build mode ─────────────────────────────────────────────
    out_json = map_output_dir / "traffic_graph.json"
    out_png  = map_output_dir / "traffic_graph.png"

    if out_json.exists() and not getattr(args, 'force', False):
        print(f"Skipping '{map_slug}': traffic_graph.json already exists (use --force to rebuild).")
        return

    # Resolve grid_size: explicit > adaptive
    grid_size = getattr(args, 'grid_size', None)
    if grid_size is None:
        conn_tmp = duckdb.connect('match_analysis/metadata.db', read_only=True)
        tb = conn_tmp.execute(
            "SELECT total_blocks FROM maps WHERE map_slug = ?", [map_slug]
        ).fetchone()
        conn_tmp.close()
        total_blocks = int(tb[0]) if tb and tb[0] else 5000
        grid_size = _adaptive_grid_size(total_blocks)
        print(f"  grid_size auto-set to {grid_size} (total_blocks={total_blocks})")

    conn = duckdb.connect('match_analysis/metadata.db', read_only=True)
    try:
        graph = build_traffic_graph(
            map_slug,
            conn,
            output_dir      = map_output_dir,
            grid_size       = grid_size,
            min_occupation  = args.min_occupation,
            min_transitions = args.min_transitions,
            log_interval    = log_interval,
        )
    finally:
        conn.close()

    save_traffic_graph(graph, out_json)
    print(f"Saved: {out_json}  ({len(graph['nodes'])} nodes, {len(graph['edges'])} edges)")

    plot_traffic_graph(graph, map_context, out_png)
    print(f"Saved: {out_png}")


def handle_traffic_graph(args):
    import logging
    import duckdb

    ensure_match_db()
    logging.basicConfig(level=logging.INFO)

    if getattr(args, 'all', False):
        conn = duckdb.connect('match_analysis/metadata.db', read_only=True)
        slugs = [
            row[0] for row in conn.execute(
                "SELECT DISTINCT m.map_slug FROM matches mat "
                "JOIN maps m ON mat.map_id = m.map_id ORDER BY m.map_slug"
            ).fetchall()
        ]
        conn.close()
        if not slugs:
            print("No maps with matches found in the database.")
            return
        print(f"Building traffic graphs for {len(slugs)} map(s): {', '.join(slugs)}")
        for slug in slugs:
            print(f"\n--- {slug} ---")
            _build_traffic_graph_for_slug(args, slug)
    else:
        _build_traffic_graph_for_slug(args, args.map)


def handle_list(args):
    ensure_match_db()
    import duckdb

    conn = duckdb.connect('match_analysis/metadata.db')

    query = ("SELECT mat.match_id, m.map_slug, mat.player_count, "
             "mat.match_duration, mat.processed "
             "FROM matches mat JOIN maps m ON mat.map_id = m.map_id")
    conditions = []
    params = []

    if args.map_name:
        conditions.append("m.map_slug = ?")
        params.append(args.map_name)
    if args.processed:
        conditions.append("mat.processed = TRUE")
    elif args.unprocessed:
        conditions.append("mat.processed = FALSE")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY mat.match_id"

    results = conn.execute(query, params).fetchall()
    conn.close()

    print(f"\nFound {len(results)} matches:\n")
    print(f"{'ID':<6} {'Map':<15} {'Players':<8} {'Duration':<10} {'Processed'}")
    print("-" * 55)

    for match_id, map_slug, players, duration, proc in results:
        duration_str = f"{duration:.0f}s" if duration else "N/A"
        proc_str = "yes" if proc else "no"
        print(f"{match_id:<6} {map_slug:<15} {players:<8} {duration_str:<10} {proc_str}")


def handle_stats(args):
    ensure_match_db()
    import duckdb

    conn = duckdb.connect('match_analysis/metadata.db')

    result = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN processed THEN 1 ELSE 0 END) as processed,
            COUNT(DISTINCT map_id) as maps,
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
            m.map_slug,
            COUNT(*) as count,
            SUM(CASE WHEN mat.processed THEN 1 ELSE 0 END) as processed
        FROM matches mat
        JOIN maps m ON mat.map_id = m.map_id
        GROUP BY m.map_slug
        ORDER BY count DESC
    """).fetchall()

    for map_slug, count, processed in results:
        print(f"{map_slug:<20} {count:>3} matches ({processed} processed)")

    conn.close()
