"""'debug' subcommand — diagnostic tools for layout parquet and output JSON files."""

import json
import sys
from pathlib import Path

from common.geometry import get_grid_extent, block_unit_square


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


_DEMO_ROLES = [
    'deep_attacker', 'defender', 'roamer', 'traversal',
    'high_killer', 'skybridge', 'bow_archer', 'builder',
]

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def handle_prepare_demo(args: object) -> None:
    """Build traffic graph assets for a map and copy them to docs/demo/assets/<slug>/."""
    import glob as glob_mod
    import shutil
    import subprocess

    map_slug   = args.map
    output_dir = _PROJECT_ROOT / args.output_root / map_slug
    assets_dir = _PROJECT_ROOT / args.assets_dir / map_slug

    if not output_dir.is_dir():
        print(f"Error: output directory not found: {output_dir}")
        print(f"  Run 'ctw run --map {map_slug}' first.")
        sys.exit(1)

    ctw_script = str(_PROJECT_ROOT / 'ctw.py')

    # ── Step 1: build / refresh traffic graph ────────────────────────────
    print(f"\n[1/3] Building traffic graph for '{map_slug}' ...")
    cmd = [sys.executable, ctw_script, 'matches', 'traffic-graph', '--map', map_slug]
    if args.force:
        cmd.append('--force')
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("  Error: traffic-graph build failed.")
        sys.exit(result.returncode)

    # ── Step 2: strategy comparison plot ─────────────────────────────────
    print(f"\n[2/3] Building strategy comparison for '{map_slug}' ...")
    cmd_cmp = [sys.executable, ctw_script, 'matches', 'traffic-graph',
               '--map', map_slug, '--compare']
    result = subprocess.run(cmd_cmp)
    if result.returncode != 0:
        print("  Error: strategy comparison failed.")
        sys.exit(result.returncode)

    # ── Step 3: life-segment diagnostics ─────────────────────────────────
    print(f"\n[3/3] Running life-segment diagnostics for '{map_slug}' ...")
    diag_script = _PROJECT_ROOT / 'scripts' / 'run_traffic_diagnostics.py'
    result = subprocess.run([sys.executable, str(diag_script), '--map', map_slug])
    if result.returncode != 0:
        print("  Error: diagnostics failed.")
        sys.exit(result.returncode)

    # ── Copy assets ───────────────────────────────────────────────────────
    assets_dir.mkdir(parents=True, exist_ok=True)
    copies: list[str] = []

    def _copy(src: Path, dst: Path) -> None:
        if src.exists():
            shutil.copy2(src, dst)
            copies.append(dst.name)
        else:
            print(f"  Warning: expected file not found: {src.name}")

    _copy(output_dir / 'images' / 'traffic_graph.png',
          assets_dir / 'traffic_graph_overview.png')
    _copy(output_dir / 'images' / 'traffic_strategy_comparison.png',
          assets_dir / 'traffic_strategy_comparison.png')

    diag_dir = output_dir / 'traffic_graph_diagnostics'
    # Group by role and pick the newest file for each (avoids duplicates from old runs)
    newest_per_role: dict[str, Path] = {}
    for png in glob_mod.glob(str(diag_dir / '*.png')):
        p = Path(png)
        for role in _DEMO_ROLES:
            if role in p.name:
                prev = newest_per_role.get(role)
                if prev is None or p.stat().st_mtime > prev.stat().st_mtime:
                    newest_per_role[role] = p
                break
    for role, src_path in newest_per_role.items():
        _copy(src_path, assets_dir / f'life_{role}.png')

    print(f"\nAssets written to: {assets_dir}")
    print(f"  {len(copies)} files copied: {', '.join(copies)}")


_AUDIT_LAYERS: list[tuple[str, str]] = [
    ('y0',           'layout_y0.parquet'),
    ('bedrock',      'layout_bedrock.parquet'),
    ('top_surface',  'layout_top_surface.parquet'),
    ('lowest_solid', 'layout_lowest_solid.parquet'),
]


def handle_audit(args: object) -> None:
    """Populate layout_layer_stats and layout_block_inventory in the database."""
    import duckdb
    import pandas as pd

    from ctw.common import ensure_match_db
    from match_analysis.database.schema import migrate_layout_audit_tables

    ensure_match_db()
    migrate_layout_audit_tables()

    output_root = Path(args.dir)
    if not output_root.is_dir():
        print(f"Error: directory not found: {output_root}", file=sys.stderr)
        sys.exit(1)

    if args.all_maps:
        map_slugs = [d.name for d in sorted(output_root.iterdir()) if d.is_dir()]
    else:
        map_slugs = [m.strip() for m in args.map.split(',') if m.strip()]

    conn = duckdb.connect('match_analysis/metadata.db')

    n_processed = 0
    n_skipped = 0

    for map_slug in map_slugs:
        map_dir = output_root / map_slug
        if not map_dir.is_dir():
            print(f"  Warning: output dir not found for '{map_slug}', skipping")
            n_skipped += 1
            continue

        row = conn.execute(
            "SELECT map_id FROM maps WHERE map_slug = ?", [map_slug]
        ).fetchone()
        if row is None:
            print(f"  Warning: '{map_slug}' not in maps table, skipping")
            n_skipped += 1
            continue

        map_id: int = row[0]

        for layer_name, filename in _AUDIT_LAYERS:
            parquet_path = map_dir / filename
            if not parquet_path.exists():
                continue

            try:
                df = pd.read_parquet(parquet_path)
            except Exception as e:
                print(f"  Warning: failed to read {parquet_path}: {e}")
                continue

            if df.empty:
                continue

            block_count = len(df)
            y_min: int | None = None
            y_max: int | None = None
            if 'y' in df.columns:
                y_min = int(df['y'].min())
                y_max = int(df['y'].max())

            # Upsert layer stats (delete + insert to handle re-runs)
            conn.execute(
                "DELETE FROM layout_layer_stats WHERE map_id = ? AND layer = ?",
                [map_id, layer_name],
            )
            conn.execute(
                """
                INSERT INTO layout_layer_stats (map_id, layer, block_count, y_min, y_max, scanned_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [map_id, layer_name, block_count, y_min, y_max],
            )

            # Refresh block inventory for this (map_id, layer)
            conn.execute(
                "DELETE FROM layout_block_inventory WHERE map_id = ? AND layer = ?",
                [map_id, layer_name],
            )
            if 'block_id' in df.columns:
                counts = (
                    df.groupby('block_id', sort=False)
                    .size()
                    .reset_index(name='cnt')
                )
                conn.executemany(
                    "INSERT INTO layout_block_inventory VALUES (?, ?, ?, ?)",
                    [
                        (map_id, layer_name, int(r['block_id']), int(r['cnt']))
                        for _, r in counts.iterrows()
                    ],
                )

        n_processed += 1
        if n_processed % 50 == 0:
            print(f"  {n_processed}/{len(map_slugs)} maps processed...")

    conn.close()
    print(f"\nAudit complete: {n_processed} maps processed, {n_skipped} skipped")


def handle_compare(args) -> None:
    from layout_analysis.layout_compare import run
    run(args)


def handle_symmetry(args):
    """Run symmetry analysis for one or all maps."""
    from symmetry_analysis import detect_symmetry
    from symmetry_analysis.report import format_symmetry_report

    root = Path(args.dir)

    if args.map is not None:
        _handle_symmetry_single(root, args.map)
    else:
        _handle_symmetry_all(root)


def _handle_symmetry_single(root: Path, map_name: str):
    """Full detailed report for a single map."""
    from symmetry_analysis import detect_symmetry
    from symmetry_analysis.report import format_symmetry_report

    ctx_path = root / map_name / 'map_context.json'
    if not ctx_path.exists():
        ctx_path = Path(map_name) / 'map_context.json'
        if not ctx_path.exists():
            print(f"Error: map_context.json not found for '{map_name}'", file=sys.stderr)
            print(f"  Tried: {root / map_name / 'map_context.json'}",
                  file=sys.stderr)
            print(f"  Run island analysis first: python ctw.py run --map {map_name}",
                  file=sys.stderr)
            sys.exit(1)

    result = detect_symmetry(str(ctx_path))
    report = format_symmetry_report(result)
    print(report)


def _handle_symmetry_all(root: Path):
    """Compact summary table across all maps."""
    from symmetry_analysis import detect_symmetry

    if not root.is_dir():
        print(f"Error: directory not found: {root}", file=sys.stderr)
        sys.exit(1)

    rows = []
    skipped = []

    for map_dir in sorted(root.iterdir()):
        if not map_dir.is_dir():
            continue
        ctx_path = map_dir / 'map_context.json'
        if not ctx_path.exists():
            skipped.append(map_dir.name)
            continue

        try:
            result = detect_symmetry(str(ctx_path))
        except Exception as e:
            rows.append((map_dir.name, f"ERROR: {e}", "", ""))
            continue

        # Global symmetry summary
        detected_global = [
            s for s in result["global_symmetry"] if s["detected"]
        ]
        if detected_global:
            primary = max(detected_global, key=lambda s: s["confidence"])
            global_str = f"{primary['type']} ({primary['confidence']:.0%})"
        else:
            global_str = "none"

        # Center type
        center_str = result["center"]["type"]

        # Intra-team summary
        intra = result.get("intra_team_symmetry", [])
        sym_teams = [t for t in intra if t.get("symmetry_detected")]
        if not intra:
            intra_str = "-"
        elif len(sym_teams) == len(intra) and intra:
            # All teams symmetric — show check type
            check = intra[0].get("check_type", "mirror_split")
            if check == "canonical_coverage":
                groups = intra[0].get("canonical_groups", "?")
                intra_str = f"all teams ({groups} groups)"
            else:
                iou = min(t.get("best_iou", 0) for t in sym_teams)
                intra_str = f"all teams (IoU>={iou:.0%})"
        elif sym_teams:
            names = ", ".join(t["team"] for t in sym_teams)
            intra_str = names
        else:
            intra_str = "none"

        rows.append((map_dir.name, global_str, center_str, intra_str))

    if not rows and not skipped:
        print(f"No map output folders found in {root}/")
        return

    # Print table
    if rows:
        col_w = [
            max(len(r[0]) for r in rows),
            max(len(r[1]) for r in rows),
            max(len(r[2]) for r in rows),
            max(len(r[3]) for r in rows),
        ]
        headers = ("map", "global symmetry", "center", "intra-team")
        col_w = [max(col_w[i], len(headers[i])) for i in range(4)]

        hdr = (f"  {headers[0]:<{col_w[0]}}  {headers[1]:<{col_w[1]}}  "
               f"{headers[2]:<{col_w[2]}}  {headers[3]}")
        sep = f"  {'-' * col_w[0]}  {'-' * col_w[1]}  {'-' * col_w[2]}  {'-' * col_w[3]}"
        print(hdr)
        print(sep)
        for name, gs, ct, it in rows:
            print(f"  {name:<{col_w[0]}}  {gs:<{col_w[1]}}  {ct:<{col_w[2]}}  {it}")

    if skipped:
        print(f"\n  Skipped (no map_context.json): {', '.join(skipped)}")

    print(f"\n  {len(rows)} maps analyzed")


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
