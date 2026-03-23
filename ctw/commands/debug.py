"""'debug' subcommand — diagnostic tools for layout parquet and output JSON files."""

import argparse

_RAW = argparse.RawDescriptionHelpFormatter


def register(subparsers):
    debug_parser = subparsers.add_parser(
        'debug',
        help='Diagnostic tools for map data inspection',
    )
    debug_sub = debug_parser.add_subparsers(
        dest='debug_action', metavar='<action>',
    )

    # debug layout-blocks
    p = debug_sub.add_parser(
        'layout-blocks',
        help='List unique block IDs found in a layout parquet across all maps',
        description=(
            'Reads the specified layout parquet for every map under --dir and prints '
            'the unique block IDs present. With --water, analyzes water blocks (IDs 8/9) '
            'and cross-checks their footprint against the XML build region stored in '
            'map_context.json. Use --csv to export results instead of printing.'
        ),
        formatter_class=_RAW,
        epilog="""\
Examples:
  python ctw.py debug layout-blocks --parquet layout_y0
  python ctw.py debug layout-blocks --parquet layout_y0 --water
  python ctw.py debug layout-blocks --parquet layout_y0 --csv blocks.csv
""",
    )
    p.add_argument('--parquet', required=True,
                   help='Parquet filename without extension (e.g. layout_y0)')
    p.add_argument('--dir', default='output',
                   help='Root directory containing per-map folders (default: output)')
    p.add_argument('--csv', default=None, dest='csv_path',
                   help='Write results to CSV file (default: print to stdout)')
    p.add_argument('--water', action='store_true',
                   help='Analyze water blocks (8/9) and check overlap with XML build regions')
    p.set_defaults(func=handle_layout)

    # debug data
    p = debug_sub.add_parser(
        'data',
        help='Scan output JSON files across all maps and report empty/missing fields',
        description=(
            'Walks every map directory under --dir, loads the specified JSON file, '
            'and reports fields whose value is null, an empty list, an empty dict, '
            'or an empty string. Useful for spotting incomplete pipeline outputs.'
        ),
        formatter_class=_RAW,
        epilog="""\
Examples:
  python ctw.py debug data --json map_data.json
  python ctw.py debug data --json map_context.json
""",
    )
    p.add_argument('--json', required=True, dest='json_file',
                   help='JSON filename relative to each map output dir (e.g. map_data.json)')
    p.add_argument('--dir', default='output',
                   help='Root directory containing per-map folders (default: output)')
    p.set_defaults(func=handle_data)

    # debug symmetry
    p = debug_sub.add_parser(
        'symmetry',
        help='Analyze map symmetry from preprocessed geometry (map_context.json)',
        description=(
            'With --map: runs full symmetry analysis and prints a detailed text report, '
            'then saves a two-panel debug image (decided layout layer + island polygon '
            'outlines with block-count annotations) to output/<map>/images/symmetry_debug.png. '
            'Without --map: prints a compact one-line-per-map summary table. '
            'Use --threshold to filter the table to only maps below a given confidence level.'
        ),
        formatter_class=_RAW,
        epilog="""\
Examples:
  python ctw.py debug symmetry --map tumbleweed
  python ctw.py debug symmetry
  python ctw.py debug symmetry --threshold 90
""",
    )
    p.add_argument('--map', default=None,
                   help='Map name (e.g. tumbleweed). Omit to scan all maps.')
    p.add_argument('--dir', default='output',
                   help='Root output directory (default: output)')
    p.add_argument('--threshold', type=float, default=None, metavar='PCT',
                   help='All-maps only: hide maps at or above this symmetry confidence '
                        '(e.g. 90 shows only maps below 90%%). Cannot be used with --map.')
    p.set_defaults(func=handle_symmetry)

    # debug prepare-demo
    p = debug_sub.add_parser(
        'prepare-demo',
        help='Build traffic graph assets for a map and copy them to docs/demo/assets/',
        description=(
            'Runs three steps in sequence: builds the traffic graph, generates the strategy '
            'comparison plot, and runs life-segment diagnostics. Then copies the resulting '
            'PNGs into docs/demo/assets/<slug>/. Use --force to rebuild even if outputs exist.'
        ),
        formatter_class=_RAW,
        epilog="""\
Examples:
  python ctw.py debug prepare-demo --map fourchette
  python ctw.py debug prepare-demo --map fourchette --force
""",
    )
    p.add_argument('--map', required=True,
                   help='Map slug (e.g. fourchette)')
    p.add_argument('--force', action='store_true',
                   help='Force rebuild of traffic graph even if output already exists')
    p.add_argument('--assets-dir', default='docs/demo/assets', dest='assets_dir',
                   help='Root directory for demo assets (default: docs/demo/assets)')
    p.add_argument('--output', default='output', dest='output_root',
                   help='Root output directory (default: output)')
    p.set_defaults(func=handle_prepare_demo)

    # debug resources
    p = debug_sub.add_parser(
        'resources',
        help='Plot chest and resource block locations on the map layout',
        description=(
            'Zone-classifies chest and resource block positions (gold, iron, diamond) '
            'relative to spawn, near-spawn, wool room, and defense zones, then plots '
            'them on top of the map base layer. Double chests are shown with a distinct '
            'marker. Saves to output/<map>/images/resources_overview.png.'
        ),
        formatter_class=_RAW,
        epilog="""\
Examples:
  python ctw.py debug resources --map arabia
  python ctw.py debug resources --map arabia,tumbleweed
  python ctw.py debug resources --map arabia --defense-buffer 15
""",
    )
    p.add_argument('--map', required=True,
                   help='Comma-separated map names (e.g. arabia,tumbleweed)')
    p.add_argument('--output', default='output',
                   help='Root output directory (default: output)')
    p.add_argument('--defense-buffer', type=float, default=10.0,
                   help='Defense zone width in blocks (default: 10)')
    p.add_argument('--near-spawn-buffer', type=float, default=15.0,
                   help='Near-spawn zone width in blocks (default: 15)')
    p.set_defaults(func=handle_resources)

    # debug layout-audit
    p = debug_sub.add_parser(
        'layout-audit',
        help='Populate layout audit tables in the database (layer stats + block inventory)',
        description=(
            'Reads layout parquets for each map and upserts rows into layout_layer_stats '
            '(block count and y-range per layer) and layout_block_inventory (per-block-ID '
            'counts). Re-running is safe: existing rows for the map/layer are replaced. '
            'Run ctw maps terrain-height first to populate the terrain height table.'
        ),
        formatter_class=_RAW,
        epilog="""\
Examples:
  python ctw.py debug layout-audit --all
  python ctw.py debug layout-audit --map acapulco
  python ctw.py debug layout-audit --map acapulco,arabia
""",
    )
    audit_group = p.add_mutually_exclusive_group(required=True)
    audit_group.add_argument('--map', default=None,
                             help='Comma-separated map names (e.g. acapulco,arabia)')
    audit_group.add_argument('--all', action='store_true', dest='all_maps',
                             help='Audit all maps in output/')
    p.add_argument('--dir', default='output',
                   help='Root directory containing per-map output folders (default: output)')
    p.set_defaults(func=handle_audit)

    # debug terrain-height
    p = debug_sub.add_parser(
        'terrain-height',
        help='Plot height_above_terrain distribution as a 4x2 visual grid',
        description=(
            'Queries position_events and map_terrain_height from the database and renders '
            'an 8-panel diagnostic figure: above-terrain heatmap, below-terrain depth, '
            'data coverage, vertical extremes, dominant location type, reference map, '
            'and terrain elevation. Requires ctw maps terrain-height to have been run first.'
        ),
        formatter_class=_RAW,
        epilog="""\
Examples:
  python ctw.py debug terrain-height --map arabia
  python ctw.py debug terrain-height --map arabia --save /tmp/debug.png
""",
    )
    p.add_argument('--map', required=True,
                   help='Map name (e.g. arabia)')
    p.add_argument('--output', default='output',
                   help='Root output directory (default: output)')
    p.add_argument('--save', default=None, dest='save_path',
                   help='Output PNG path '
                        '(default: output/<map>/images/terrain_height_debug.png)')
    p.set_defaults(func=handle_terrain_height)

    # debug activity-grid
    p = debug_sub.add_parser(
        'activity-grid',
        help='Heatmap of CTW match activity (24h × day, grouped by ISO week)',
        description=(
            'Queries the matches table and plots a heatmap where each cell represents '
            'one hour of one day, colored by the number of matches that started in that '
            'slot. Weeks are shown as columns so seasonal patterns and session clusters '
            'are easy to spot. Optionally filter by date range or minimum match duration.'
        ),
        formatter_class=_RAW,
        epilog="""\
Examples:
  python ctw.py debug activity-grid
  python ctw.py debug activity-grid --start 2026-01-18 --end 2026-03-08
  python ctw.py debug activity-grid --min-duration 60 --output figures/activity.png
""",
    )
    p.add_argument('--start', metavar='YYYY-MM-DD',
                   help='First date to include (default: earliest match in DB)')
    p.add_argument('--end', metavar='YYYY-MM-DD',
                   help='Last date to include (default: latest match in DB)')
    p.add_argument('--min-duration', type=int, default=None, dest='min_duration',
                   metavar='SECONDS',
                   help='Exclude matches shorter than this many seconds (e.g. 60)')
    p.add_argument('--output', default='match_activity_grid.png',
                   help='Output PNG path (default: match_activity_grid.png)')
    p.set_defaults(func=handle_activity_grid)

    # debug match-coverage
    p = debug_sub.add_parser(
        'match-coverage',
        help='Publication-quality overview of match counts across all maps',
        description=(
            'Queries the database for match counts per map and renders a two-panel '
            'figure: a histogram of the match count distribution (top) and a full '
            'per-map directory sorted by match count descending (bottom). Maps are '
            'color-coded by a six-step bucket scheme (1 / 2–5 / 6–15 / 16–30 / '
            '31–60 / 61+) using a YlOrRd palette.'
        ),
        formatter_class=_RAW,
        epilog="""\
Examples:
  python ctw.py debug match-coverage
  python ctw.py debug match-coverage --output figures/coverage.png
""",
    )
    p.add_argument(
        '--output', default=None, dest='coverage_output',
        help='Output PNG path (default: output/_debug/match_coverage.png)',
    )
    p.add_argument(
        '--db', default='match_analysis/metadata.db', dest='coverage_db',
        help='Path to the DuckDB database (default: match_analysis/metadata.db)',
    )
    p.add_argument(
        '--min-matches', type=int, default=1, dest='coverage_min_matches',
        metavar='N',
        help='Exclude maps with fewer than N qualifying matches (default: 1)',
    )
    p.add_argument(
        '--sampling', type=int, default=None, dest='coverage_sampling',
        metavar='SECONDS',
        choices=[2, 5],
        help='Only count matches logged at this interval in seconds (2 or 5). '
             'Requires matches extract to have run. NULL log_interval rows excluded.',
    )
    p.set_defaults(func=handle_match_coverage)

    # debug compare
    p = debug_sub.add_parser(
        'compare',
        help='Compare layout layers side-by-side (y0 vs bedrock vs difference)',
        description=(
            'For each map, reads layout_y0 and layout_bedrock parquets and produces a '
            '3-panel figure: y0 blocks colored by block ID, bedrock blocks colored by '
            'y-level, and an overlap diff panel (shared / y0-only / bedrock-only). '
            'Use --summary for a text-only table without generating images.'
        ),
        formatter_class=_RAW,
        epilog="""\
Examples:
  python ctw.py debug compare --map acapulco
  python ctw.py debug compare --all --summary
  python ctw.py debug compare --all
  python ctw.py debug compare --all --output-dir /tmp/compare/
""",
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--map', default=None,
                       help='Single map name (e.g. acapulco)')
    group.add_argument('--all', action='store_true', dest='all_maps',
                       help='Process all maps in output/')
    p.add_argument('--dir', default='output',
                   help='Root output directory (default: output)')
    p.add_argument('--summary', action='store_true',
                   help='Text-only summary table (no plots, use with --all)')
    p.add_argument('--output-dir', default=None, dest='output_dir',
                   help='Where to save PNGs (default: output/diagnostics/)')
    p.set_defaults(func=handle_compare)

    # debug layout-grid
    p = debug_sub.add_parser(
        'layout-grid',
        help='2×2 grid of all four layout layers for one or all maps',
        description=(
            'Renders a 2×2 figure showing layout_y0, layout_bedrock, layout_top_surface, '
            'and layout_lowest_solid for a map, using the canonical Minecraft block color '
            'palette. Each panel includes a legend of the most common block IDs. '
            'Saves to output/<map>/images/layout_case_study.png.'
        ),
        formatter_class=_RAW,
        epilog="""\
Examples:
  python ctw.py debug layout-grid --map arabia
  python ctw.py debug layout-grid --all-matches
  python ctw.py debug layout-grid --all-matches --workers 8
""",
    )
    lg_group = p.add_mutually_exclusive_group(required=True)
    lg_group.add_argument('--map', default=None,
                          help='Map name (e.g. arabia)')
    lg_group.add_argument('--all-matches', action='store_true', dest='all_matches',
                          help='Plot every map that has matches in the database')
    p.add_argument('--output', default='output',
                   help='Root output directory (default: output)')
    p.add_argument('--workers', type=int, default=4,
                   help='Parallel workers for --all-matches (default: 4)')
    p.set_defaults(func=handle_layout_grid)


def handle_prepare_demo(args: object) -> None:
    from layout_analysis.demo import run
    run(args)


def handle_audit(args: object) -> None:
    from layout_analysis.audit import run
    run(args)


def handle_compare(args: object) -> None:
    from layout_analysis.layout_compare import run
    run(args)


def handle_layout_grid(args: object) -> None:
    from layout_analysis.layout_grid import run
    run(args)


def handle_symmetry(args: object) -> None:
    from symmetry_analysis.report import run
    run(args)


def handle_layout(args: object) -> None:
    from layout_analysis.layout_scan import run_layout
    run_layout(args)


def handle_data(args: object) -> None:
    from layout_analysis.layout_scan import run_data
    run_data(args)


def handle_resources(args: object) -> None:
    from layout_analysis.resources_plot import run
    run(args)


def handle_terrain_height(args: object) -> None:
    from match_analysis.terrain_height_plot import run
    run(args)


def handle_activity_grid(args: object) -> None:
    from match_analysis.activity_grid import generate
    generate(args)


def handle_match_coverage(args: object) -> None:
    from match_analysis.match_coverage_viz import render_match_coverage
    from pathlib import Path
    output = Path(args.coverage_output) if args.coverage_output else Path("output/_debug/match_coverage.png")
    render_match_coverage(
        output, args.coverage_db,
        min_matches=args.coverage_min_matches,
        sampling=args.coverage_sampling,
    )
