#!/usr/bin/env python3
"""
CTW Analysis Toolkit - Unified Command-Line Interface.

Provides a single entry point for all map and match analysis operations.
Each subcommand delegates to existing library functions.

Usage:
    python ctw.py <command> [options]

Commands:
    run       Run the full analysis pipeline
    layout    Extract layout data from Minecraft region files
    islands   Detect islands and compute skeleton graphs
    xml       Parse map XML configuration
    match     Analyze a single match
    info      Show analysis status for a map
    docs      Generate API documentation
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent


# ---------------------------------------------------------------------------
# Map folder resolution
# ---------------------------------------------------------------------------

def resolve_map_folder(map_arg: str) -> Path:
    """Resolve a --map argument to a map folder Path.

    Tries the argument as a direct path first, then as a name
    under map_folders/.
    """
    candidate = Path(map_arg)
    if candidate.is_dir():
        return candidate.resolve()
    resolved = PROJECT_ROOT / 'map_folders' / map_arg
    if resolved.is_dir():
        return resolved
    print(f"Error: Map folder not found: {map_arg}", file=sys.stderr)
    print(f"  Tried: {candidate}", file=sys.stderr)
    print(f"  Tried: {resolved}", file=sys.stderr)
    sys.exit(1)


def _collect_map_folders(args) -> list:
    """Return list of map folder Paths from --map or --all."""
    if getattr(args, 'all', False):
        mf_dir = PROJECT_ROOT / 'map_folders'
        if not mf_dir.exists():
            print(f"Error: map_folders directory not found", file=sys.stderr)
            sys.exit(1)
        return sorted(f for f in mf_dir.iterdir() if f.is_dir())
    if getattr(args, 'map', None):
        return [resolve_map_folder(args.map)]
    print("Error: Must specify either --map or --all", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_run(args):
    """Run the full analysis pipeline."""
    from layout_analysis.services import analyze_layout, analyze_islands_step
    from xml_analysis.services import analyze_xml
    from match_analysis.services import analyze_matches

    map_folders = _collect_map_folders(args)
    match_history_path = Path(args.match_history)

    print("=" * 70)
    print("CTW ANALYSIS WORKFLOW")
    print("=" * 70)
    print(f"Maps to analyze: {len(map_folders)}")
    for folder in map_folders:
        print(f"  - {folder.name}")
    print()

    for map_folder in map_folders:
        print(f"\n{'=' * 70}")
        print(f"Processing: {map_folder.name}")
        print(f"{'=' * 70}")

        if not args.no_layout:
            analyze_layout(map_folder, force_rerun=args.force)
        else:
            print("\n[1/4] Layout Analysis: SKIPPED")

        if not args.no_islands:
            analyze_islands_step(
                map_folder, force_rerun=args.force,
                layout_type=args.island_layout,
                canonical_triangulation=args.canonical_triangulation,
            )
        else:
            print("\n[2/4] Island Analysis: SKIPPED")

        if not args.no_xml:
            analyze_xml(map_folder, force_rerun=args.force)
        else:
            print("\n[3/4] XML Analysis: SKIPPED")

        if not args.no_matches:
            if match_history_path.exists():
                analyze_matches(map_folder, match_history_path)
            else:
                print(f"\n[4/4] Match Analysis: SKIPPED (match history not found)")
        else:
            print("\n[4/4] Match Analysis: SKIPPED")

    print(f"\n{'=' * 70}")
    print("WORKFLOW COMPLETE")
    print(f"{'=' * 70}\n")


def cmd_layout(args):
    """Extract layout data from Minecraft region files."""
    map_folder = resolve_map_folder(args.map)

    if args.plots or args.output:
        # Full standalone mode: CSV + Parquet + plots
        import pandas as pd
        from layout_analysis import (
            RegionReader, Y0LayerExtractor, TopSurfaceExtractor,
            VerticalDensityExtractor, LowestBedrockExtractor,
        )
        from layout_analysis.plotting import save_all_plots

        region_folder = map_folder / 'region'
        if not region_folder.exists():
            print(f"Error: No region folder at {region_folder}", file=sys.stderr)
            sys.exit(1)

        output_dir = Path(args.output) if args.output else map_folder / 'layout_output'
        output_dir.mkdir(parents=True, exist_ok=True)

        print("=" * 70)
        print(f"LAYOUT EXTRACTION: {map_folder.name}")
        print("=" * 70)

        reader = RegionReader(str(region_folder))
        results = {}

        density_modes = []
        if not args.skip_density:
            for mode in args.density_mode.split(','):
                mode = mode.strip()
                if mode in ('run', 'count'):
                    density_modes.append(mode)

        if not args.skip_y0:
            print("  Extracting Y=0 layer...")
            df = Y0LayerExtractor(reader).extract()
            df.to_parquet(str(output_dir / 'y0_layer_points.parquet'))
            results['y0'] = df
        else:
            results['y0'] = pd.DataFrame()

        if not args.skip_surface:
            print("  Extracting top surface...")
            df = TopSurfaceExtractor(reader).extract()
            df.to_parquet(str(output_dir / 'top_surface_points.parquet'))
            results['top_surface'] = df
        else:
            results['top_surface'] = pd.DataFrame()

        density_results = {}
        for mode in density_modes:
            print(f"  Extracting density ({mode})...")
            df = VerticalDensityExtractor(reader, threshold=args.threshold, mode=mode).extract()
            name = f"{mode}_N{args.threshold}"
            df.to_parquet(str(output_dir / f'density_{name}_points.parquet'))
            density_results[name] = df

        if not args.skip_bedrock:
            print("  Extracting bedrock...")
            df = LowestBedrockExtractor(reader).extract()
            df.to_parquet(str(output_dir / 'lowest_bedrock_points.parquet'))
            results['bedrock'] = df
        else:
            results['bedrock'] = pd.DataFrame()

        if args.plots:
            print("  Generating plots...")
            save_all_plots(
                y0_df=results.get('y0', pd.DataFrame()),
                top_surface_df=results.get('top_surface', pd.DataFrame()),
                density_dfs=density_results,
                bedrock_df=results.get('bedrock', pd.DataFrame()),
                output_dir=str(output_dir),
            )

        print(f"  Output saved to: {output_dir}")
    else:
        # Simple workflow mode: parquets into map folder
        from layout_analysis.services import analyze_layout
        analyze_layout(map_folder, force_rerun=args.force)


def cmd_islands(args):
    """Detect islands and compute skeleton graphs."""
    map_folder = resolve_map_folder(args.map)

    if args.basic:
        from analyze_islands import analyze_map_islands

        layout_map = {
            'bedrock': 'layout_bedrock.parquet',
            'y0': 'layout_y0.parquet',
            'top': 'layout_top_surface.parquet',
            'density': 'layout_vertical_density.parquet',
        }
        bedrock_path = str(map_folder / layout_map.get(args.layout, 'layout_bedrock.parquet'))
        output_dir = str(map_folder / 'island_analysis')

        analyze_map_islands(
            bedrock_parquet=bedrock_path,
            output_dir=output_dir,
            map_name=map_folder.name,
            connectivity=args.connectivity,
            min_island_size=args.min_size,
            buffer_distance=args.buffer,
            simplify_tolerance=args.simplify,
            detect_holes=not args.no_holes,
        )
    else:
        from layout_analysis.services import analyze_islands_step
        analyze_islands_step(
            map_folder,
            force_rerun=args.force,
            simplify_tolerance=args.simplify,
            buffer_distance=args.buffer,
            layout_type=args.layout,
            canonical_triangulation=args.canonical_triangulation,
        )


def cmd_xml(args):
    """Parse map XML configuration."""
    map_folder = resolve_map_folder(args.map)
    xml_path = map_folder / 'map.xml'

    if not xml_path.exists():
        print(f"Error: No map.xml found at {xml_path}", file=sys.stderr)
        sys.exit(1)

    if args.visualize or args.category_plots:
        from xml_analysis import MapXMLParser, MapVisualizer, MapDataEncoder

        output_dir = map_folder
        parser = MapXMLParser(str(xml_path))
        map_data = parser.parse()
        categories = parser.identify_region_categories(map_data)

        visualizer = MapVisualizer(map_data)

        if not args.no_summary:
            visualizer.print_summary()

        if not args.no_json:
            map_name_safe = map_data.name.replace(' ', '_').lower()
            json_path = output_dir / f'map_data.json'
            MapDataEncoder.save_json(map_data, str(json_path), categories)

        map_name_safe = map_data.name.replace(' ', '_').lower()
        main_plot_path = output_dir / f'{map_name_safe}_layout.png'
        visualizer.plot_all(str(main_plot_path))

        if args.category_plots:
            visualizer.plot_by_category(str(output_dir), categories)

        print(f"  Visualizations saved to: {output_dir}")
    else:
        from xml_analysis.services import analyze_xml
        analyze_xml(map_folder, force_rerun=args.force)


def cmd_match(args):
    """Analyze a single match."""
    map_folder = resolve_map_folder(args.map)
    bedrock_path = map_folder / 'layout_bedrock.parquet'

    if not bedrock_path.exists():
        print(f"Error: Bedrock layout not found at {bedrock_path}", file=sys.stderr)
        print("  Run layout extraction first: python ctw.py layout --map " + args.map)
        sys.exit(1)

    match_id = args.match.replace('.parquet', '')
    output_dir = Path(args.output) if args.output else map_folder / 'matches' / match_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load map name from map_data.json if available
    json_file = map_folder / 'map_data.json'
    if json_file.exists():
        with open(json_file) as f:
            map_name = json.load(f).get('name', map_folder.name)
    else:
        map_name = map_folder.name

    from match_analysis.services import analyze_single_match
    success = analyze_single_match(map_name, args.match, bedrock_path, output_dir)

    if not success:
        print("Match analysis failed.", file=sys.stderr)
        sys.exit(1)

    # Path networks with custom params
    if not args.no_team_networks:
        try:
            from generate_path_networks import generate_path_networks
            generate_path_networks(
                match_file=args.match,
                bedrock_parquet=str(bedrock_path),
                output_dir=str(output_dir),
                resolution=args.resolution,
                cluster_radius=args.cluster_radius,
                generate_team_networks=True,
            )
        except Exception as e:
            print(f"  [!] Path network generation failed: {e}")

    print(f"  Match analysis saved to: {output_dir}")


def cmd_info(args):
    """Show analysis status and summary for a map."""
    map_folder = resolve_map_folder(args.map)

    # Check output files
    files = {
        'layout_y0.parquet': 'Layout Y0',
        'layout_bedrock.parquet': 'Layout Bedrock',
        'layout_top_surface.parquet': 'Layout Top Surface',
        'layout_vertical_density.parquet': 'Layout Vertical Density',
        'map_data.json': 'XML Data',
        'map_graph.json': 'Map Graph',
        'island_analysis/map_context.json': 'Map Context',
        'island_analysis/island_report.txt': 'Island Report',
        'island_analysis/map_connectivity.png': 'Connectivity Plot',
    }

    ctx_path = map_folder / 'island_analysis' / 'map_context.json'
    ctx = None
    if ctx_path.exists():
        with open(ctx_path) as f:
            ctx = json.load(f)

    if args.json:
        if ctx:
            print(json.dumps(ctx, indent=2))
        else:
            print("{}")
        return

    print(f"Map: {map_folder.name}")
    print(f"Path: {map_folder}")
    print()

    # File status
    print("Output files:")
    for rel_path, label in files.items():
        full = map_folder / rel_path
        status = "OK" if full.exists() else "--"
        print(f"  [{status:2s}] {label}")

    # Matches
    matches_dir = map_folder / 'matches'
    if matches_dir.exists():
        match_dirs = [d for d in matches_dir.iterdir() if d.is_dir()]
        print(f"\n  [{len(match_dirs):2d}] Match analyses")
    print()

    # Summary from map_context
    if ctx:
        print(f"Map name:    {ctx.get('map_name', 'N/A')}")
        print(f"Version:     {ctx.get('map_version', 'N/A')}")
        print(f"Objective:   {ctx.get('objective', 'N/A')}")
        print(f"Total blocks: {ctx.get('total_blocks', 0):,}")
        print(f"Islands:     {ctx.get('island_count', 0)}")

        teams = ctx.get('teams', [])
        if teams:
            team_str = ', '.join(f"{t['name']} ({t['color']})" for t in teams)
            print(f"Teams:       {team_str}")

        skel = ctx.get('skeleton', {})
        if skel:
            print(f"Skeleton:    {skel.get('total_nodes', 0)} nodes, "
                  f"{skel.get('total_edges', 0)} edges, "
                  f"{skel.get('unique_canonical_shapes', 0)} unique shapes")

        br = ctx.get('build_region')
        if br:
            print(f"Build region: source={br['source']}, "
                  f"void_area={br['buildable_void_area']}")

        bb = ctx.get('bounding_box')
        if bb:
            print(f"Bounding box: X[{bb[0]:.0f}, {bb[1]:.0f}] Z[{bb[2]:.0f}, {bb[3]:.0f}]")
    else:
        print("No map_context.json found. Run island analysis first.")


def cmd_docs(args):
    """Generate API documentation."""
    overview_path = PROJECT_ROOT / 'overview.py'
    if not overview_path.exists():
        print("Error: overview.py not found", file=sys.stderr)
        sys.exit(1)
    subprocess.run([sys.executable, str(overview_path)], cwd=str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Match analysis commands
# ---------------------------------------------------------------------------

def _ensure_match_db():
    """Initialize match DB if it doesn't exist yet."""
    db_path = Path('match_analysis/metadata.db')
    if not db_path.exists():
        from scripts.initialize_analysis_db import initialize_database
        initialize_database()


def cmd_matches_index(args):
    """Index all match files in the database."""
    _ensure_match_db()
    from match_analysis.match_indexer import index_match_files

    match_dir = args.match_dir or 'match_logs'
    indexed, skipped = index_match_files(match_dir)

    import duckdb
    conn = duckdb.connect('match_analysis/metadata.db')
    result = conn.execute(
        "SELECT COUNT(*) as total, COUNT(DISTINCT map_name) as maps FROM matches"
    ).fetchone()
    conn.close()

    print(f"\nTotal indexed: {result[0]} matches across {result[1]} maps")


def cmd_matches_process(args):
    """Process a specific match by ID."""
    _ensure_match_db()
    from match_analysis.trajectory_extractor import process_match
    process_match(args.match_id)


def cmd_matches_process_all(args):
    """Process all unprocessed matches."""
    _ensure_match_db()
    import duckdb
    from match_analysis.trajectory_extractor import process_match

    conn = duckdb.connect('match_analysis/metadata.db')

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


def cmd_matches_list(args):
    """List matches in the database."""
    _ensure_match_db()
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


def cmd_matches_stats(args):
    """Show match database statistics."""
    _ensure_match_db()
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


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands."""

    # Shared parent for --map and --force
    map_parent = argparse.ArgumentParser(add_help=False)
    map_parent.add_argument(
        '--map', required=True,
        help='Map name (e.g., tumbleweed) or path to map folder',
    )
    map_parent.add_argument(
        '--force', action='store_true',
        help='Force regeneration of existing outputs',
    )

    # Top-level parser
    parser = argparse.ArgumentParser(
        prog='ctw',
        description='CTW Analysis Toolkit — Unified CLI for map and match analysis',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ctw.py run --map tumbleweed --no-matches
  python ctw.py run --all --force --no-matches
  python ctw.py layout --map kanto
  python ctw.py islands --map segment --force
  python ctw.py xml --map aether --visualize
  python ctw.py match --map tumbleweed --match 2026-01-24_22-24-17_75.parquet
  python ctw.py info --map segment
  python ctw.py info --map segment --json
""",
    )
    subparsers = parser.add_subparsers(
        dest='command', required=True, metavar='<command>',
    )

    # --- run ---
    p = subparsers.add_parser(
        'run', help='Run the full analysis pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument('--map', help='Map name to analyze')
    p.add_argument('--all', action='store_true', help='Analyze all maps')
    p.add_argument('--force', action='store_true', help='Force regeneration')
    p.add_argument('--no-layout', action='store_true', help='Skip layout analysis')
    p.add_argument('--no-islands', action='store_true', help='Skip island analysis')
    p.add_argument('--no-xml', action='store_true', help='Skip XML analysis')
    p.add_argument('--no-matches', action='store_true', help='Skip match analysis')
    p.add_argument('--match-history', default='match_logs/match_history.txt',
                   help='Path to match history file')
    p.add_argument('--island-layout', choices=['bedrock', 'y0', 'top', 'density'],
                   default='bedrock', help='Layout file for island analysis')
    p.add_argument('--canonical-triangulation', action='store_true',
                   help='Use canonical-consistent triangulation')
    p.set_defaults(func=cmd_run)

    # --- layout ---
    p = subparsers.add_parser(
        'layout', parents=[map_parent],
        help='Extract layout data from Minecraft region files',
    )
    p.add_argument('--threshold', type=int, default=10,
                   help='Density threshold (default: 10)')
    p.add_argument('--density-mode', default='run,count',
                   help='Comma-separated density modes: run, count')
    p.add_argument('--skip-y0', action='store_true', help='Skip Y0 extraction')
    p.add_argument('--skip-surface', action='store_true', help='Skip top surface')
    p.add_argument('--skip-density', action='store_true', help='Skip density')
    p.add_argument('--skip-bedrock', action='store_true', help='Skip bedrock')
    p.add_argument('--output', help='Override output directory')
    p.add_argument('--plots', action='store_true',
                   help='Generate plots alongside data files')
    p.set_defaults(func=cmd_layout)

    # --- islands ---
    p = subparsers.add_parser(
        'islands', parents=[map_parent],
        help='Detect islands and compute skeleton graphs',
    )
    p.add_argument('--connectivity', type=int, default=8, choices=[4, 8],
                   help='Island connectivity (default: 8)')
    p.add_argument('--min-size', type=int, default=10,
                   help='Minimum island block count (default: 10)')
    p.add_argument('--buffer', type=float, default=0.0,
                   help='Buffer distance for smoothing (default: 0.0)')
    p.add_argument('--simplify', type=float, default=1.0,
                   help='Simplification tolerance (default: 1.0)')
    p.add_argument('--no-holes', action='store_true', help='Disable hole detection')
    p.add_argument('--layout', choices=['bedrock', 'y0', 'top', 'density'],
                   default='bedrock', help='Layout file to use')
    p.add_argument('--canonical-triangulation', action='store_true',
                   help='Use canonical-consistent triangulation')
    p.add_argument('--basic', action='store_true',
                   help='Basic mode: detection + triangulation only (no skeleton/POI)')
    p.set_defaults(func=cmd_islands)

    # --- xml ---
    p = subparsers.add_parser(
        'xml', parents=[map_parent],
        help='Parse map XML configuration',
    )
    p.add_argument('--visualize', action='store_true',
                   help='Generate visualization plots')
    p.add_argument('--category-plots', action='store_true',
                   help='Generate per-category region plots')
    p.add_argument('--no-summary', action='store_true', help='Skip text summary')
    p.add_argument('--no-json', action='store_true', help='Skip JSON output')
    p.set_defaults(func=cmd_xml)

    # --- match ---
    p = subparsers.add_parser(
        'match', parents=[map_parent],
        help='Analyze a single match',
    )
    p.add_argument('--match', required=True,
                   help='Match parquet filename')
    p.add_argument('--output', help='Override output directory')
    p.add_argument('--no-team-networks', action='store_true',
                   help='Skip team-specific path networks')
    p.add_argument('--no-pdf', action='store_true',
                   help='Skip PDF report generation')
    p.add_argument('--no-classification', action='store_true',
                   help='Skip segment classification')
    p.add_argument('--resolution', type=float, default=1.0,
                   help='Grid resolution for path networks (default: 1.0)')
    p.add_argument('--cluster-radius', type=float, default=5.0,
                   help='Waypoint clustering radius (default: 5.0)')
    p.set_defaults(func=cmd_match)

    # --- info ---
    p = subparsers.add_parser(
        'info', parents=[map_parent],
        help='Show analysis status for a map',
    )
    p.add_argument('--json', action='store_true',
                   help='Output raw JSON from map_context.json')
    p.set_defaults(func=cmd_info)

    # --- docs ---
    p = subparsers.add_parser('docs', help='Generate API documentation')
    p.set_defaults(func=cmd_docs)

    # --- matches ---
    matches_parser = subparsers.add_parser(
        'matches',
        help='Match data analysis commands',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Actions:
  index        Index all match parquet files into the database
  process      Process a specific match by ID
  process-all  Process all unprocessed matches
  list         List matches in the database
  stats        Show database statistics

Examples:
  python ctw.py matches index
  python ctw.py matches list
  python ctw.py matches process 57
  python ctw.py matches process-all
  python ctw.py matches stats
""",
    )
    matches_sub = matches_parser.add_subparsers(
        dest='matches_action', metavar='<action>',
    )

    # matches index
    p = matches_sub.add_parser('index', help='Index all match files')
    p.add_argument('--match-dir', help='Directory containing match parquet files (default: match_logs)')
    p.set_defaults(func=cmd_matches_index)

    # matches process
    p = matches_sub.add_parser('process', help='Process a specific match by ID')
    p.add_argument('match_id', type=int, help='Match ID to process')
    p.set_defaults(func=cmd_matches_process)

    # matches process-all
    p = matches_sub.add_parser('process-all', help='Process all unprocessed matches')
    p.add_argument('--map-name', help='Only process matches for this map')
    p.set_defaults(func=cmd_matches_process_all)

    # matches list
    p = matches_sub.add_parser('list', help='List matches in the database')
    p.add_argument('--map-name', help='Filter by map name')
    p.add_argument('--processed', action='store_true', help='Show only processed matches')
    p.add_argument('--unprocessed', action='store_true', help='Show only unprocessed matches')
    p.set_defaults(func=cmd_matches_list)

    # matches stats
    p = matches_sub.add_parser('stats', help='Show database statistics')
    p.set_defaults(func=cmd_matches_stats)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    os.chdir(PROJECT_ROOT)
    parser = build_parser()
    args = parser.parse_args()
    if not hasattr(args, 'func'):
        # Subcommand given without action (e.g. "matches" with no action)
        parser.parse_args([args.command, '--help'])
        return
    args.func(args)


if __name__ == '__main__':
    main()
