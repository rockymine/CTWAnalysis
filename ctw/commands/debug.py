"""'debug' subcommand — diagnostic tools for layout parquet and output JSON files."""


def register(subparsers):
    debug_parser = subparsers.add_parser(
        'debug',
        help='Diagnostic tools for map data inspection',
        formatter_class=__import__('argparse').RawDescriptionHelpFormatter,
        epilog="""
Actions:
  layout         Scan a layout parquet across all maps and list unique block IDs
  data           Scan output JSON files across all maps and report empty/missing fields
  symmetry       Analyze map symmetry from preprocessed geometry
  compare        Compare layout layers side-by-side (y0 vs bedrock vs difference)
  audit          Populate layout audit tables in the database (layer stats + block inventory)
  prepare-demo   Build traffic graph assets for a map and copy them to docs/demo/assets/
  resources      Plot chest and resource block locations on the map layout
  terrain-height Plot height_above_terrain distribution as a 2x2 visual grid
  activity-grid  Heatmap of CTW match activity (24h × day, grouped by week)
  layout-grid    2×2 grid of all four layout layers for one or all maps

Examples:
  python ctw.py debug layout --parquet layout_y0
  python ctw.py debug layout --parquet layout_y0 --water
  python ctw.py debug data --json map_data.json
  python ctw.py debug data --json map_context.json
  python ctw.py debug symmetry --map tumbleweed
  python ctw.py debug symmetry
  python ctw.py debug compare --map acapulco
  python ctw.py debug compare --all --summary
  python ctw.py debug compare --all
  python ctw.py debug audit --all
  python ctw.py debug audit --map acapulco
  python ctw.py debug prepare-demo --map fourchette
  python ctw.py debug prepare-demo --map fourchette --force
  python ctw.py debug resources --map arabia
  python ctw.py debug resources --map arabia,tumbleweed
  python ctw.py debug terrain-height --map arabia
  python ctw.py debug activity-grid
  python ctw.py debug activity-grid --start 2026-01-18 --end 2026-03-08
  python ctw.py debug activity-grid --min-duration 60 --output figures/activity.png
  python ctw.py debug layout-grid --map arabia
  python ctw.py debug layout-grid --all-matches
  python ctw.py debug layout-grid --all-matches --workers 8
""",
    )
    debug_sub = debug_parser.add_subparsers(
        dest='debug_action', metavar='<action>',
    )

    # debug layout
    p = debug_sub.add_parser(
        'layout',
        help='Scan a layout parquet across all maps and list unique block IDs',
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
    )
    p.add_argument('--map', default=None,
                   help='Map name (e.g. tumbleweed). Omit to scan all maps.')
    p.add_argument('--dir', default='output',
                   help='Root output directory (default: output)')
    p.set_defaults(func=handle_symmetry)

    # debug prepare-demo
    p = debug_sub.add_parser(
        'prepare-demo',
        help='Build traffic graph assets for a map and copy them to docs/demo/assets/',
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

    # debug audit
    p = debug_sub.add_parser(
        'audit',
        help='Populate layout audit tables in the database (layer stats + block inventory)',
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
        help='Plot height_above_terrain distribution as a 2x2 visual grid',
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

    # debug compare
    p = debug_sub.add_parser(
        'compare',
        help='Compare layout layers side-by-side (y0 vs bedrock vs difference)',
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
                   help='Where to save PNGs (default: output/<map>/diagnostics/)')
    p.set_defaults(func=handle_compare)

    # debug layout-grid
    p = debug_sub.add_parser(
        'layout-grid',
        help='2×2 grid of all four layout layers for one or all maps',
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


def handle_compare(args) -> None:
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

# ── debug resources ────────────────────────────────────────────────────────


def handle_resources(args: object) -> None:
    from layout_analysis.resources_plot import run
    run(args)


# ── terrain-height debug ──────────────────────────────────────────────────────

def handle_terrain_height(args: object) -> None:
    from match_analysis.terrain_height_plot import run
    run(args)


def handle_activity_grid(args: object) -> None:
    """Generate a CTW match activity heatmap (24h × day, grouped by ISO week)."""
    from match_analysis.activity_grid import generate
    generate(args)
