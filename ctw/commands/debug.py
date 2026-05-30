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

    # debug fork-layout
    p = debug_sub.add_parser(
        'fork-layout',
        help='Analyse fork topology of defending sides on 2-team, 2-wool maps',
        description=(
            'For every processed 2-team, 2-wool map that has a traffic graph, '
            'computes fork metrics for each team\'s home island: graph path distances '
            'from spawn to each defending wool, arm asymmetry, fork opening angle, '
            'and the lateral offset of spawn from the wool midpoint. '
            'Renders a 4-panel summary figure.'
        ),
        formatter_class=_RAW,
        epilog="""\
Examples:
  python ctw.py debug fork-layout
  python ctw.py debug fork-layout --save output/_debug/fork.png
""",
    )
    p.add_argument('--output', default='output',
                   help='Root output directory containing per-map folders (default: output)')
    p.add_argument('--db', default='match_analysis/metadata.db', dest='fork_db',
                   help='Path to the DuckDB database (default: match_analysis/metadata.db)')
    p.add_argument('--save', default=None, dest='save_path',
                   help='Output PNG path (default: output/_debug/fork_analysis.png)')
    p.set_defaults(func=handle_fork_layout)

    # debug profile-summary
    p = debug_sub.add_parser(
        'profile-summary',
        help='Print cross-map island type count table (console only)',
        formatter_class=_RAW,
        epilog="""\
Examples:
  python ctw.py debug profile-summary
  python ctw.py debug profile-summary --map arabia
""",
    )
    p.add_argument('--map', default=None,
                   help='Map slug (default: all maps with island_profiles.json)')
    p.add_argument('--output', default=None,
                   help='Output root directory (default: output/)')
    p.set_defaults(func=handle_profile_summary)

    # debug profile-landscape
    p = debug_sub.add_parser(
        'profile-landscape',
        help='Cross-map scatter of all canonical islands on feature axes',
        formatter_class=_RAW,
        epilog="""\
Examples:
  python ctw.py debug profile-landscape
  python ctw.py debug profile-landscape --feature-x rugosity --feature-y convexity
""",
    )
    p.add_argument('--map', default=None,
                   help='Map slug (default: all maps with island_profiles.json)')
    p.add_argument('--output', default=None,
                   help='Output root directory (default: output/)')
    p.add_argument('--feature-x', default='aspect_ratio', dest='feature_x',
                   help='Feature for x axis (default: aspect_ratio)')
    p.add_argument('--feature-y', default='compactness', dest='feature_y',
                   help='Feature for y axis (default: compactness)')
    p.set_defaults(func=handle_profile_landscape)

    # debug profile-mosaic
    p = debug_sub.add_parser(
        'profile-mosaic',
        help='Grid of island polygon shapes grouped by type, or per-type example images',
        formatter_class=_RAW,
        epilog="""\
Examples:
  python ctw.py debug profile-mosaic
  python ctw.py debug profile-mosaic --type linear
  python ctw.py debug profile-mosaic --examples
  python ctw.py debug profile-mosaic --examples --examples-dir docs/figures/island_shapes
""",
    )
    p.add_argument('--map', default=None,
                   help='Map slug (default: all maps with island_profiles.json)')
    p.add_argument('--output', default=None,
                   help='Output root directory (default: output/)')
    p.add_argument('--type', default=None, dest='island_type',
                   help='Only render islands of this type (default: all types)')
    p.add_argument('--examples', action='store_true',
                   help='Save 3 diverse example images per type to --examples-dir '
                        'instead of producing a mosaic')
    p.add_argument('--examples-dir', default='docs/figures/island_shapes',
                   dest='examples_dir',
                   help='Output directory for example images '
                        '(default: docs/figures/island_shapes)')
    p.set_defaults(func=handle_profile_mosaic)

    # debug profile-distributions
    p = debug_sub.add_parser(
        'profile-distributions',
        help='Feature distribution histograms stacked by type across all maps',
        formatter_class=_RAW,
        epilog="""\
Examples:
  python ctw.py debug profile-distributions
""",
    )
    p.add_argument('--map', default=None,
                   help='Map slug (default: all maps with island_profiles.json)')
    p.add_argument('--output', default=None,
                   help='Output root directory (default: output/)')
    p.set_defaults(func=handle_profile_distributions)


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


def handle_fork_layout(args: object) -> None:
    from layout_analysis.fork_analysis import run
    run(args)


# ---------------------------------------------------------------------------
# Island profile cross-map handlers
# ---------------------------------------------------------------------------


def _is_map_skipped(map_slug: str) -> bool:
    """Return True if the map is flagged skip:true in map_layouts.json."""
    from layout_analysis.map_layout_config import get_map_layout
    cfg = get_map_layout(map_slug)
    return cfg is not None and cfg.skip


def _load_profile_entries(args) -> list[tuple[str, object, dict]]:
    """Load (map_slug, IslandProfile, island_dict) triples from all relevant maps.

    island_dict is the representative island entry from map_context.json.
    Maps flagged skip:true in map_layouts.json are excluded.
    """
    import json as _json
    from pathlib import Path
    from island_analysis.profile import load_profiles
    from ctw.common import DEFAULT_OUTPUT_ROOT

    output_root = Path(args.output) if args.output else DEFAULT_OUTPUT_ROOT
    map_name = getattr(args, 'map', None)
    if map_name:
        map_dirs = [output_root / map_name]
    else:
        map_dirs = sorted(d for d in output_root.iterdir() if d.is_dir())

    entries: list[tuple[str, object, dict]] = []
    for map_dir in map_dirs:
        if _is_map_skipped(map_dir.name):
            continue
        profiles = load_profiles(map_dir / 'island_profiles.json')
        if profiles is None:
            continue
        context_path = map_dir / 'map_context.json'
        if not context_path.exists():
            continue
        with open(context_path, encoding='utf-8') as fh:
            map_context = _json.load(fh)
        island_by_id = {isl['id']: isl for isl in map_context.get('islands', [])}

        for profile in profiles:
            rep_id = profile.raw_island_ids[0] if profile.raw_island_ids else None
            if rep_id is None or rep_id not in island_by_id:
                continue
            entries.append((map_dir.name, profile, island_by_id[rep_id]))
    return entries


def _load_all_profiles(args) -> list[tuple[str, object]]:
    """Load (map_slug, IslandProfile) pairs (no island_dict) from all relevant maps."""
    return [(slug, profile) for slug, profile, _isl in _load_profile_entries(args)]


def handle_profile_summary(args: object) -> None:
    """Print cross-map island type count table."""
    from pathlib import Path
    from island_analysis.profile import _ALL_TYPES, load_profiles
    from ctw.common import DEFAULT_OUTPUT_ROOT

    output_root = Path(args.output) if args.output else DEFAULT_OUTPUT_ROOT
    map_name = getattr(args, 'map', None)
    if map_name:
        map_dirs = [output_root / map_name]
    else:
        map_dirs = sorted(d for d in output_root.iterdir() if d.is_dir())

    rows = []
    for map_dir in map_dirs:
        if _is_map_skipped(map_dir.name):
            continue
        profiles = load_profiles(map_dir / 'island_profiles.json')
        if profiles is None:
            continue
        counts: dict[str, int] = {t: 0 for t in _ALL_TYPES}
        for profile in profiles:
            counts[profile.island_type] = counts.get(profile.island_type, 0) + 1
        rows.append((map_dir.name, len(profiles), counts))

    if not rows:
        print('No island_profiles.json files found.')
        return

    type_cols = _ALL_TYPES
    header = f'  {"map":<24}  {"total":>5}  ' + '  '.join(f'{t[:6]:>6}' for t in type_cols)
    print(f'\n{header}')
    print(f'  {"-" * 24}  {"-" * 5}  ' + '  '.join('-' * 6 for _ in type_cols))
    for map_slug, total, counts in rows:
        row = f'  {map_slug:<24}  {total:>5}  '
        row += '  '.join(f'{counts.get(t, 0):>6}' for t in type_cols)
        print(row)
    total_all = sum(r[1] for r in rows)
    print(f'  {"-" * 24}  {"-" * 5}  ' + '  '.join('-' * 6 for _ in type_cols))
    total_by_type = {t: sum(r[2].get(t, 0) for r in rows) for t in type_cols}
    print(f'  {"TOTAL":<24}  {total_all:>5}  '
          + '  '.join(f'{total_by_type[t]:>6}' for t in type_cols))
    print()


def handle_profile_landscape(args: object) -> None:
    """Generate cross-map scatter landscape plot."""
    from pathlib import Path
    from island_analysis.profile import plot_profile_landscape
    from ctw.common import DEFAULT_OUTPUT_ROOT

    all_pairs = _load_all_profiles(args)
    if not all_pairs:
        print('No island_profiles.json files found.')
        return

    output_root = Path(args.output) if args.output else DEFAULT_OUTPUT_ROOT
    images_dir = output_root / '_debug'
    images_dir.mkdir(parents=True, exist_ok=True)

    feature_x = getattr(args, 'feature_x', 'aspect_ratio')
    feature_y = getattr(args, 'feature_y', 'compactness')
    out_path = str(images_dir / 'island_landscape.png')
    plot_profile_landscape(all_pairs, feature_x, feature_y, out_path)
    print(f'Saved: {out_path}')


def handle_profile_mosaic(args: object) -> None:
    """Generate island shape mosaic or per-type example images."""
    import json as _json
    from pathlib import Path
    from island_analysis.profile import plot_profile_mosaic, save_profile_examples
    from ctw.common import DEFAULT_OUTPUT_ROOT

    entries = _load_profile_entries(args)
    if not entries:
        print('No island profiles found.')
        return

    if getattr(args, 'examples', False):
        # --examples mode: save 3 diverse individual PNGs per type
        examples_dir = getattr(args, 'examples_dir', 'docs/figures/island_shapes')
        island_type_filter = getattr(args, 'island_type', None)
        if island_type_filter:
            entries = [(s, p, d) for s, p, d in entries if p.island_type == island_type_filter]
        metadata = save_profile_examples(entries, examples_dir)
        # Group output by type (one file per type, multiple entries per file)
        seen_files: set[str] = set()
        for item in metadata:
            fname = item['filename']
            if fname not in seen_files:
                seen_files.add(fname)
                print(f'  Saved: {examples_dir}/{fname}')
            f = item['features']
            print(
                f"    [{item['n']}] {item['map_slug']:<24}  "
                f"{item['canonical_key'][:12]}  "
                f"fill={f.get('bbox_fill_ratio', '?'):.3f}  "
                f"conv={f.get('convexity', '?'):.3f}  "
                f"ar={f.get('aspect_ratio', '?'):.2f}  "
                f"area={f.get('area', '?')}"
            )
        print(f'\nDone: {len(seen_files)} type images saved to {examples_dir}/')
    else:
        output_root = Path(args.output) if args.output else DEFAULT_OUTPUT_ROOT
        images_dir = output_root / '_debug'
        images_dir.mkdir(parents=True, exist_ok=True)
        out_template = str(images_dir / 'island_mosaic_{type}.png')
        island_type_filter = getattr(args, 'island_type', None)
        output_files = plot_profile_mosaic(entries, island_type_filter, out_template)
        for out_path in output_files:
            print(f'Saved: {out_path}')


def handle_profile_distributions(args: object) -> None:
    """Generate feature distribution histogram plot."""
    from pathlib import Path
    from island_analysis.profile import plot_feature_distributions
    from ctw.common import DEFAULT_OUTPUT_ROOT

    all_pairs = _load_all_profiles(args)
    if not all_pairs:
        print('No island_profiles.json files found.')
        return

    output_root = Path(args.output) if args.output else DEFAULT_OUTPUT_ROOT
    images_dir = output_root / '_debug'
    images_dir.mkdir(parents=True, exist_ok=True)
    out_path = str(images_dir / 'island_feature_distributions.png')
    plot_feature_distributions(all_pairs, out_path)
    print(f'Saved: {out_path}')
