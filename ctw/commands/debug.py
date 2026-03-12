"""'debug' subcommand — diagnostic tools for layout parquet and output JSON files."""

import csv
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
  layout       Scan a layout parquet across all maps and list unique block IDs
  data         Scan output JSON files across all maps and report empty/missing fields
  symmetry     Analyze map symmetry from preprocessed geometry
  compare      Compare layout layers side-by-side (y0 vs bedrock vs difference)
  prepare-demo Build traffic graph assets for a map and copy them to docs/demo/assets/
  resources    Plot chest and resource block locations on the map layout

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
  python ctw.py debug prepare-demo --map fourchette
  python ctw.py debug prepare-demo --map fourchette --force
  python ctw.py debug resources --map arabia
  python ctw.py debug resources --map arabia,tumbleweed
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


def handle_compare(args):
    """Compare layout layers (y0, bedrock, difference) for one or all maps."""
    root = Path(args.dir)
    if not root.is_dir():
        print(f"Error: directory not found: {root}", file=sys.stderr)
        sys.exit(1)

    diag_dir = Path(args.output_dir) if args.output_dir else root / 'diagnostics'
    diag_dir.mkdir(parents=True, exist_ok=True)

    if args.map is not None:
        # Single-map mode
        map_dir = root / args.map
        if not map_dir.is_dir():
            print(f"Error: map directory not found: {map_dir}", file=sys.stderr)
            sys.exit(1)
        save_path = diag_dir / f'{args.map}_layout.png'
        stats = _plot_layout_comparison(args.map, map_dir, save_path)
        if stats:
            print(f"Saved: {save_path}")
            _print_single_stats(args.map, stats)
    else:
        # Batch mode
        all_stats = []
        for map_dir in sorted(root.iterdir()):
            if not map_dir.is_dir():
                continue
            stats = _collect_layout_stats(map_dir.name, map_dir)
            if stats is None:
                continue
            all_stats.append(stats)

            if not args.summary:
                save_path = diag_dir / f'{map_dir.name}_layout.png'
                _plot_layout_comparison(map_dir.name, map_dir, save_path)
                print(f"  {map_dir.name}: saved {save_path}")

        if not all_stats:
            print("No maps with layout parquets found.")
            return

        if args.summary:
            _print_summary_table(all_stats)
        else:
            csv_path = diag_dir / 'layout_compare_summary.csv'
            _write_summary_csv(all_stats, csv_path)
            print(f"\n{len(all_stats)} maps processed. Summary CSV: {csv_path}")


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


def handle_layout(args):
    import pandas as pd

    root = Path(args.dir)
    if not root.is_dir():
        print(f"Error: directory not found: {root}", file=sys.stderr)
        sys.exit(1)

    filename = args.parquet
    if not filename.endswith('.parquet'):
        filename += '.parquet'

    if args.water:
        _handle_water(root, filename)
    else:
        _handle_block_scan(root, filename, args.csv_path)


def handle_data(args):
    root = Path(args.dir)
    if not root.is_dir():
        print(f"Error: directory not found: {root}", file=sys.stderr)
        sys.exit(1)

    json_file = args.json_file
    missing_file = []
    issues = []  # (map_name, list of "field=value" strings)
    scanned = 0

    for map_dir in sorted(root.iterdir()):
        if not map_dir.is_dir():
            continue
        json_path = map_dir / json_file
        if not json_path.exists():
            missing_file.append(map_dir.name)
            continue

        scanned += 1
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
        except Exception as e:
            issues.append((map_dir.name, [f"PARSE ERROR: {e}"]))
            continue

        if not isinstance(data, dict):
            issues.append((map_dir.name, [f"root is {type(data).__name__}, not dict"]))
            continue

        empty_fields = []
        for key, value in data.items():
            if value is None:
                empty_fields.append(f"{key}=null")
            elif value == []:
                empty_fields.append(f"{key}=[]")
            elif value == {}:
                empty_fields.append(f"{key}={{}}")
            elif value == "":
                empty_fields.append(f'{key}=""')

        if empty_fields:
            issues.append((map_dir.name, empty_fields))

    # Print results
    if missing_file:
        print(f"Maps missing file ({len(missing_file)}): {', '.join(missing_file)}")
        print()

    if issues:
        max_name = max(len(name) for name, _ in issues)
        max_name = max(max_name, len('map_name'))
        print(f"{'map_name':<{max_name}}  empty fields")
        print(f"{'-' * max_name}  {'-' * 30}")
        for name, fields in issues:
            print(f"{name:<{max_name}}  {', '.join(fields)}")
        print()

    total = scanned + len(missing_file)
    n_issues = len(issues)
    print(f"{scanned} maps scanned, {n_issues} with issues")


def _handle_block_scan(root: Path, filename: str, csv_path: str | None):
    import pandas as pd

    rows = []
    for map_dir in sorted(root.iterdir()):
        if not map_dir.is_dir():
            continue
        parquet_path = map_dir / filename
        if not parquet_path.exists():
            continue
        try:
            df = pd.read_parquet(parquet_path)
        except Exception as e:
            print(f"  Warning: failed to read {parquet_path}: {e}", file=sys.stderr)
            continue
        if df.empty or 'block_id' not in df.columns:
            rows.append((map_dir.name, []))
            continue
        ids = sorted(df['block_id'].unique().tolist())
        rows.append((map_dir.name, ids))

    if not rows:
        print(f"No {filename} files found under {root}/*/")
        return

    if csv_path:
        out_path = Path(csv_path)
        with open(out_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['map_name', 'blocks'])
            for name, ids in rows:
                writer.writerow([name, ids])
        print(f"Wrote {len(rows)} rows to {out_path}")
    else:
        max_name = max(len(r[0]) for r in rows)
        print(f"{'map_name':<{max_name}}  blocks")
        print(f"{'-' * max_name}  {'-' * 20}")
        for name, ids in rows:
            print(f"{name:<{max_name}}  {ids}")
        print(f"\n{len(rows)} maps scanned")


def _handle_water(root: Path, filename: str):
    """Analyze water blocks and check overlap with XML build regions."""
    import pandas as pd
    from shapely.geometry import Polygon, MultiPolygon
    from shapely.ops import unary_union
    from common.geometry import world_blocks_to_shapely

    maps_with_water = 0

    for map_dir in sorted(root.iterdir()):
        if not map_dir.is_dir():
            continue
        parquet_path = map_dir / filename
        if not parquet_path.exists():
            continue
        try:
            df = pd.read_parquet(parquet_path)
        except Exception:
            continue
        if df.empty or 'block_id' not in df.columns:
            continue

        water = df[df['block_id'].isin([8, 9])]
        if water.empty:
            continue

        maps_with_water += 1
        n_water = len(water)
        print(f"\n{'=' * 60}")
        print(f"{map_dir.name}: {n_water} water blocks")
        print(f"{'=' * 60}")

        # Build water polygons (exact, no simplification)
        water_geom = world_blocks_to_shapely(
            list(zip(water['world_x'], water['world_z']))
        )

        if isinstance(water_geom, Polygon):
            water_polys = [water_geom]
        elif isinstance(water_geom, MultiPolygon):
            water_polys = list(water_geom.geoms)
        else:
            print(f"  Unexpected geometry type: {type(water_geom).__name__}")
            continue

        print(f"  Water polygons: {len(water_polys)}")
        for i, wp in enumerate(sorted(water_polys, key=lambda p: p.area, reverse=True)):
            bounds = wp.bounds  # (minx, miny, maxx, maxy) = (minx, minz, maxx, maxz)
            print(f"    [{i}] area={wp.area:.0f}  "
                  f"bounds=({bounds[0]:.0f}, {bounds[1]:.0f})"
                  f"..({bounds[2]:.0f}, {bounds[3]:.0f})  "
                  f"holes={len(list(wp.interiors))}")

        # Load map_context.json
        ctx_path = map_dir / 'map_context.json'
        if not ctx_path.exists():
            print(f"  map_context.json: NOT FOUND")
            continue

        try:
            with open(ctx_path, 'r') as f:
                ctx = json.load(f)
        except Exception as e:
            print(f"  map_context.json: failed to load ({e})")
            continue

        build_region = ctx.get('build_region')
        if not build_region:
            print(f"  build_region: NONE")
            continue

        source = build_region.get('source', '?')
        print(f"  build_region: source={source}")

        # Reconstruct build-region polygon from stored coords
        br_polys = _coords_to_polygons(build_region.get('polygons', []))
        if not br_polys:
            print(f"  build_region polygons: could not reconstruct")
            continue

        br_geom = unary_union(br_polys)
        print(f"  build_region area: {br_geom.area:.0f}")

        # Check overlap
        water_union = unary_union(water_polys)
        intersection = water_union.intersection(br_geom)
        overlap_area = intersection.area

        water_only = water_union.difference(br_geom)
        water_only_area = water_only.area

        print(f"  water total area:       {water_union.area:.0f}")
        print(f"  overlap with build_rgn: {overlap_area:.0f}")
        print(f"  water outside build_rgn:{water_only_area:.0f}")

        if water_union.area > 0:
            pct = overlap_area / water_union.area * 100
            print(f"  overlap %:              {pct:.1f}%")

        if water_only_area > 0:
            print(f"  ** Water extends BEYOND xml build region **")

    if maps_with_water == 0:
        print(f"No maps with water blocks found in {root}/*/")
    else:
        print(f"\n{maps_with_water} maps with water blocks analyzed")


def _coords_to_polygons(coord_list: list) -> list:
    """Reconstruct Shapely polygons from map_context coordinate dicts."""
    from shapely.geometry import Polygon

    polys = []
    for entry in coord_list:
        ext = entry.get('exterior', [])
        if len(ext) < 4:  # need at least 3 points + closing
            continue
        holes = [h for h in entry.get('holes', []) if len(h) >= 4]
        try:
            p = Polygon(ext, holes)
            if p.is_valid and not p.is_empty:
                polys.append(p)
        except Exception:
            continue
    return polys


# ---------------------------------------------------------------------------
# compare helpers
# ---------------------------------------------------------------------------

_MATERIAL_NAMES: dict[int, str] | None = None


def _load_material_names() -> dict[int, str]:
    """Load block ID → name mapping from materials.txt."""
    global _MATERIAL_NAMES
    if _MATERIAL_NAMES is not None:
        return _MATERIAL_NAMES

    _MATERIAL_NAMES = {}
    mat_path = Path(__file__).resolve().parent.parent.parent / 'materials.txt'
    if not mat_path.exists():
        return _MATERIAL_NAMES
    with open(mat_path, 'r') as f:
        for line in f:
            line = line.strip()
            if ':' not in line:
                continue
            parts = line.split(':', 1)
            try:
                _MATERIAL_NAMES[int(parts[0])] = parts[1]
            except ValueError:
                continue
    return _MATERIAL_NAMES


# Colors for well-known block IDs
_BLOCK_COLORS = {
    7: '#888888',    # BEDROCK — gray
    36: '#FF2222',   # PISTON_MOVING_PIECE — bright red
    8: '#3366CC',    # WATER — blue
    9: '#3366CC',    # STATIONARY_WATER — blue
    10: '#FF6600',   # LAVA — orange
    11: '#FF6600',   # STATIONARY_LAVA — orange
    1: '#AAAAAA',    # STONE — light gray
    4: '#999977',    # COBBLESTONE — tan
    35: '#EEEEEE',   # WOOL — white
    0: '#000000',    # AIR — black
}


def _block_color(block_id: int, cmap, n_unique: int, idx: int):
    """Return RGBA color for a block_id."""
    if block_id in _BLOCK_COLORS:
        from matplotlib.colors import to_rgba
        return to_rgba(_BLOCK_COLORS[block_id])
    return cmap(idx / max(n_unique - 1, 1))


def _read_parquet_safe(path: Path):
    """Read a parquet file, returning None on missing/error."""
    import pandas as pd
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        return df if not df.empty else None
    except Exception:
        return None


def _collect_layout_stats(map_name: str, map_dir: Path) -> dict | None:
    """Collect layout statistics for a single map. Returns None if no data."""
    y0_df = _read_parquet_safe(map_dir / 'layout_y0.parquet')
    bed_df = _read_parquet_safe(map_dir / 'layout_bedrock.parquet')
    top_df = _read_parquet_safe(map_dir / 'layout_top_surface.parquet')

    if y0_df is None and bed_df is None:
        return None

    y0_blocks = len(y0_df) if y0_df is not None else 0
    y0_ids = sorted(y0_df['block_id'].unique().tolist()) if y0_df is not None and 'block_id' in y0_df.columns else []
    bed_blocks = len(bed_df) if bed_df is not None else 0
    bed_y_range = ''
    if bed_df is not None and 'y' in bed_df.columns:
        bed_y_range = f"{bed_df['y'].min()}-{bed_df['y'].max()}"
    top_blocks = len(top_df) if top_df is not None else 0

    # Coordinate sets for overlap analysis
    y0_set = set()
    bed_set = set()
    if y0_df is not None:
        y0_set = set(zip(y0_df['world_x'], y0_df['world_z']))
    if bed_df is not None:
        bed_set = set(zip(bed_df['world_x'], bed_df['world_z']))

    overlap = y0_set & bed_set
    y0_only = y0_set - bed_set
    bed_only = bed_set - y0_set

    has_block36 = 36 in y0_ids
    block36_count = 0
    if has_block36 and y0_df is not None:
        block36_count = int((y0_df['block_id'] == 36).sum())
    has_water9 = 9 in y0_ids or 8 in y0_ids

    return {
        'map_name': map_name,
        'y0_blocks': y0_blocks,
        'y0_block_ids': y0_ids,
        'bedrock_blocks': bed_blocks,
        'bedrock_y_range': bed_y_range,
        'top_blocks': top_blocks,
        'y0_only_count': len(y0_only),
        'bedrock_only_count': len(bed_only),
        'overlap_count': len(overlap),
        'has_block36': has_block36,
        'block36_count': block36_count,
        'has_water9': has_water9,
    }


def _categorize(stats: dict) -> str:
    """Assign a map to category A-E based on y0 characteristics."""
    y0_ids = stats['y0_block_ids']
    if stats['y0_blocks'] == 0:
        return 'D'  # empty
    if y0_ids == [36]:
        return 'A'  # only block 36
    if 36 in y0_ids and len(y0_ids) > 1:
        return 'B'  # block 36 mixed with others
    if y0_ids == [7]:
        return 'C'  # only bedrock
    return 'E'  # diverse blocks, no 36


_CATEGORY_LABELS = {
    'A': 'y0 only has block 36 — bedrock-only is essential',
    'B': 'y0 has block 36 mixed with other blocks — needs block 36 subtraction',
    'C': 'y0 only bedrock — y0 ~ bedrock, either works',
    'D': 'y0 empty — void/sky maps, need bedrock or top_surface',
    'E': 'y0 has diverse blocks, no 36 — y0 works well',
}


def _print_single_stats(map_name: str, stats: dict):
    """Print stats for a single map."""
    mat = _load_material_names()
    id_names = [f"{bid}({mat.get(bid, '?')})" for bid in stats['y0_block_ids']]
    cat = _categorize(stats)
    print(f"\n  Map:            {map_name}")
    print(f"  Category:       {cat} — {_CATEGORY_LABELS[cat]}")
    print(f"  Y0 blocks:      {stats['y0_blocks']}  ids={', '.join(id_names)}")
    print(f"  Bedrock blocks: {stats['bedrock_blocks']}  y_range={stats['bedrock_y_range']}")
    print(f"  Top blocks:     {stats['top_blocks']}")
    print(f"  Overlap:        {stats['overlap_count']}  "
          f"y0-only={stats['y0_only_count']}  bedrock-only={stats['bedrock_only_count']}")
    if stats['has_block36']:
        print(f"  Block 36 count: {stats['block36_count']}")


def _print_summary_table(all_stats: list[dict]):
    """Print categorized summary table for all maps."""
    from collections import defaultdict
    by_cat = defaultdict(list)
    for s in all_stats:
        by_cat[_categorize(s)].append(s)

    for cat in 'ABCDE':
        maps = by_cat.get(cat, [])
        print(f"\nCategory {cat}: {_CATEGORY_LABELS[cat]}")
        print(f"  Count: {len(maps)}")
        if not maps:
            continue
        # Column widths
        nw = max(len(s['map_name']) for s in maps)
        nw = max(nw, 8)
        print(f"  {'map':<{nw}}  y0_blk  bed_blk  y0only  bedonly  overlap  block36  water")
        print(f"  {'-'*nw}  ------  -------  ------  -------  -------  -------  -----")
        for s in maps:
            b36 = str(s['block36_count']) if s['has_block36'] else '-'
            w = 'yes' if s['has_water9'] else '-'
            print(f"  {s['map_name']:<{nw}}  {s['y0_blocks']:>6}  {s['bedrock_blocks']:>7}  "
                  f"{s['y0_only_count']:>6}  {s['bedrock_only_count']:>7}  "
                  f"{s['overlap_count']:>7}  {b36:>7}  {w:>5}")

    print(f"\nTotal: {len(all_stats)} maps")


def _write_summary_csv(all_stats: list[dict], csv_path: Path):
    """Write summary stats to CSV."""
    fields = [
        'map_name', 'category', 'y0_blocks', 'y0_block_ids', 'bedrock_blocks',
        'bedrock_y_range', 'top_blocks', 'y0_only_count', 'bedrock_only_count',
        'overlap_count', 'has_block36', 'block36_count', 'has_water9',
    ]
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for s in all_stats:
            row = dict(s)
            row['category'] = _categorize(s)
            row['y0_block_ids'] = ' '.join(str(x) for x in s['y0_block_ids'])
            writer.writerow(row)


def _plot_layout_comparison(map_name: str, map_dir: Path, save_path: Path) -> dict | None:
    """Generate a 3-panel layout comparison figure. Returns stats dict or None."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    from matplotlib.patches import Patch
    import numpy as np

    stats = _collect_layout_stats(map_name, map_dir)
    if stats is None:
        return None

    y0_df = _read_parquet_safe(map_dir / 'layout_y0.parquet')
    bed_df = _read_parquet_safe(map_dir / 'layout_bedrock.parquet')

    # Compute shared axis bounds from all available data
    all_x, all_z = [], []
    if y0_df is not None:
        mn_x, mx_x, mn_z, mx_z = get_grid_extent(y0_df['world_x'], y0_df['world_z'])
        all_x.extend([mn_x, mx_x])
        all_z.extend([mn_z, mx_z])
    if bed_df is not None:
        mn_x, mx_x, mn_z, mx_z = get_grid_extent(bed_df['world_x'], bed_df['world_z'])
        all_x.extend([mn_x, mx_x])
        all_z.extend([mn_z, mx_z])
    if not all_x:
        return stats

    x_min, x_max = min(all_x), max(all_x)
    z_min, z_max = min(all_z), max(all_z)
    pad = max((x_max - x_min) * 0.02, (z_max - z_min) * 0.02, 1)

    fig, axes = plt.subplots(1, 3, figsize=(20, 7))
    fig.suptitle(f'Layout Comparison: {map_name}', fontsize=14, fontweight='bold')

    mat = _load_material_names()

    for ax in axes:
        ax.set_xlim(x_min - pad, x_max + pad)
        ax.set_ylim(z_min - pad, z_max + pad)
        ax.set_aspect('equal')
        ax.invert_yaxis()

    # --- Panel 1: Y0 layer colored by block_id ---
    ax = axes[0]
    if y0_df is not None and 'block_id' in y0_df.columns:
        unique_ids = sorted(y0_df['block_id'].unique())
        cmap = plt.get_cmap('tab20')
        id_to_color = {}
        for i, bid in enumerate(unique_ids):
            id_to_color[bid] = _block_color(bid, cmap, len(unique_ids), i)

        verts = []
        colors = []
        for _, row in y0_df.iterrows():
            x, z = row['world_x'], row['world_z']
            verts.append(block_unit_square(x, z))
            colors.append(id_to_color[row['block_id']])

        pc = PolyCollection(verts, facecolors=colors, edgecolors='none', linewidths=0)
        ax.add_collection(pc)

        # Legend for block types
        legend_patches = [
            Patch(facecolor=id_to_color[bid],
                  label=f"{bid} {mat.get(bid, '?')}")
            for bid in unique_ids[:12]  # cap legend entries
        ]
        ax.legend(handles=legend_patches, fontsize=6, loc='upper right',
                  framealpha=0.8)
        ax.set_title(f'Y0 Layer — {len(y0_df)} blocks, {len(unique_ids)} types',
                     fontsize=10)
    else:
        ax.text(0.5, 0.5, 'No Y0 data', transform=ax.transAxes,
                ha='center', va='center', fontsize=14, color='gray')
        ax.set_title('Y0 Layer — empty', fontsize=10)

    # --- Panel 2: Bedrock layer colored by y level ---
    ax = axes[1]
    if bed_df is not None and 'y' in bed_df.columns:
        y_vals = bed_df['y'].values
        y_lo, y_hi = y_vals.min(), y_vals.max()
        cmap_bed = plt.get_cmap('YlOrBr')

        verts = []
        colors = []
        for _, row in bed_df.iterrows():
            x, z = row['world_x'], row['world_z']
            verts.append(block_unit_square(x, z))
            norm_y = (row['y'] - y_lo) / max(y_hi - y_lo, 1)
            colors.append(cmap_bed(norm_y))

        pc = PolyCollection(verts, facecolors=colors, edgecolors='none', linewidths=0)
        ax.add_collection(pc)

        # Colorbar
        sm = plt.cm.ScalarMappable(cmap=cmap_bed,
                                    norm=plt.Normalize(vmin=y_lo, vmax=y_hi))
        sm.set_array([])
        cb = fig.colorbar(sm, ax=ax, shrink=0.6, pad=0.02)
        cb.set_label('Y level', fontsize=8)

        ax.set_title(f'Bedrock Layer — {len(bed_df)} blocks, y={y_lo}..{y_hi}',
                     fontsize=10)
    else:
        ax.text(0.5, 0.5, 'No bedrock data', transform=ax.transAxes,
                ha='center', va='center', fontsize=14, color='gray')
        ax.set_title('Bedrock Layer — empty', fontsize=10)

    # --- Panel 3: Difference / overlap ---
    ax = axes[2]
    y0_set = set()
    bed_set = set()
    if y0_df is not None:
        y0_set = set(zip(y0_df['world_x'], y0_df['world_z']))
    if bed_df is not None:
        bed_set = set(zip(bed_df['world_x'], bed_df['world_z']))

    overlap = y0_set & bed_set
    y0_only = y0_set - bed_set
    bed_only = bed_set - y0_set

    diff_groups = [
        (overlap, '#88BB88', 'shared'),
        (y0_only, '#CC4444', 'y0 only'),
        (bed_only, '#4444CC', 'bedrock only'),
    ]
    for coords, color, label in diff_groups:
        if not coords:
            continue
        verts = [block_unit_square(x, z) for x, z in coords]
        pc = PolyCollection(verts, facecolors=color, edgecolors='none',
                            linewidths=0, alpha=0.7, label=label)
        ax.add_collection(pc)

    ax.legend(fontsize=8, loc='upper right', framealpha=0.8)
    ax.set_title(f'Difference — shared={len(overlap)}, '
                 f'y0-only={len(y0_only)}, bed-only={len(bed_only)}',
                 fontsize=10)

    plt.tight_layout()
    fig.savefig(str(save_path), dpi=150, bbox_inches='tight')
    plt.close(fig)

    return stats


# ── debug resources ────────────────────────────────────────────────────────


def handle_resources(args: object) -> None:
    """Plot chest and resource block locations for one or more maps."""
    map_names = [m.strip() for m in args.map.split(',') if m.strip()]
    output_root = Path(args.output)
    defense_buffer: float = args.defense_buffer
    near_spawn_buffer: float = args.near_spawn_buffer

    for map_name in map_names:
        map_output = output_root / map_name
        ctx_path = map_output / 'map_context.json'
        data_path = map_output / 'map_data.json'
        res_path = map_output / 'layout_resource_blocks.parquet'
        chest_path = map_output / 'layout_chest_contents.parquet'

        missing = [p for p in (ctx_path, data_path) if not p.exists()]
        if missing:
            print(f"[{map_name}] missing files: {[str(p) for p in missing]}", file=sys.stderr)
            continue

        with open(ctx_path) as f:
            map_context = json.load(f)
        with open(data_path) as f:
            map_data = json.load(f)

        images_dir = map_output / 'images'
        images_dir.mkdir(exist_ok=True)
        save_path = images_dir / 'resources_overview.png'
        _plot_resources_figure(
            map_name=map_name,
            map_context=map_context,
            map_data=map_data,
            res_path=res_path,
            chest_path=chest_path,
            save_path=save_path,
            defense_buffer=defense_buffer,
            near_spawn_buffer=near_spawn_buffer,
        )
        print(f"[{map_name}] saved: {save_path}")


def _plot_resources_figure(
    map_name: str,
    map_context: dict,
    map_data: dict,
    res_path: 'Path',
    chest_path: 'Path',
    save_path: 'Path',
    defense_buffer: float = 10.0,
    near_spawn_buffer: float = 15.0,
) -> None:
    """Draw resource block and chest locations on top of the map base layer."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import pandas as pd
    from shapely.plotting import plot_polygon

    from common.visualization.map_primitives import draw_map_base, map_base_legend_handles
    from layout_analysis.features import ZoneClassifier, ChestExtractor, detect_double_chests
    from common.geometry import block_centers

    # Load parquets if they exist
    res_df: pd.DataFrame | None = None
    chest_df: pd.DataFrame | None = None
    if res_path.exists():
        res_df = pd.read_parquet(res_path)
    if chest_path.exists():
        chest_df = pd.read_parquet(chest_path)

    # Zone-classify resource blocks and chests
    clf = ZoneClassifier(map_data, defense_buffer=defense_buffer,
                         near_spawn_buffer=near_spawn_buffer)
    if res_df is not None and not res_df.empty:
        res_df = clf.classify_dataframe(res_df)
    if chest_df is not None and not chest_df.empty:
        chest_df = clf.classify_dataframe(chest_df)
        chest_df = detect_double_chests(chest_df)
        # Unique chest locations (one row per chest position)
        chest_positions = (
            chest_df[['world_x', 'world_z', 'zone', 'team', 'is_double', 'chest_group_id']]
            .drop_duplicates(subset=['world_x', 'world_z'])
        )
    else:
        chest_positions = None

    fig, ax = plt.subplots(figsize=(14, 14))
    has_build = draw_map_base(ax, map_context)
    ax.set_aspect('equal')
    ax.invert_yaxis()
    ax.set_title(f'Resources: {map_name}', fontsize=14, fontweight='bold')

    # Zone polygon overlays (semi-transparent)
    _ZONE_FILL = {
        'spawn':     ('#3399FF', 0.20, 'Spawn region'),
        'wool_room': ('#FF44AA', 0.20, 'Wool room region'),
        'defense':   ('#FF8800', 0.12, 'Defense zone'),
        'near_spawn': ('#88CCFF', 0.12, 'Near-spawn zone'),
    }
    zone_handles: list = []
    for zone_key, (color, alpha, label) in _ZONE_FILL.items():
        geom = getattr(clf, f'_{zone_key}_geom', None)
        if geom is not None and not geom.is_empty:
            plot_polygon(geom, ax=ax, add_points=False, facecolor=color, edgecolor=color,
                         alpha=alpha, linewidth=0.5)
            zone_handles.append(mpatches.Patch(facecolor=color, alpha=0.5, label=label))

    # Resource block scatter
    _RES_COLOR = {
        'gold_block':    '#FFD700',
        'iron_block':    '#B8B8B8',
        'diamond_block': '#00BFFF',
    }
    res_handles: list = []
    if res_df is not None and not res_df.empty:
        for rtype, color in _RES_COLOR.items():
            mask = res_df['resource_type'] == rtype
            if not mask.any():
                continue
            sub = res_df[mask]
            xs = block_centers(sub['world_x'].to_numpy())
            zs = block_centers(sub['world_z'].to_numpy())
            ax.scatter(xs, zs, c=color, s=18, marker='s', zorder=4, label=rtype,
                       edgecolors='black', linewidths=0.3)
            res_handles.append(
                mpatches.Patch(facecolor=color, edgecolor='black', label=rtype.replace('_', ' '))
            )

    # Chest scatter — colored by zone, different marker for double chests
    _ZONE_CHEST_COLOR = {
        'spawn':      '#3399FF',
        'near_spawn': '#88CCFF',
        'wool_room':  '#FF44AA',
        'defense':    '#FF8800',
        'field':      '#888888',
    }
    chest_handles: list = []
    if chest_positions is not None and not chest_positions.empty:
        for zone_val, color in _ZONE_CHEST_COLOR.items():
            for is_double, marker, size, suffix in ((False, 'o', 40, ''), (True, 'D', 55, ' (double)')):
                mask = (chest_positions['zone'] == zone_val) & (chest_positions['is_double'] == is_double)
                if not mask.any():
                    continue
                sub = chest_positions[mask]
                xs = block_centers(sub['world_x'].to_numpy())
                zs = block_centers(sub['world_z'].to_numpy())
                ax.scatter(xs, zs, c=color, s=size, marker=marker, zorder=5,
                           edgecolors='black', linewidths=0.5)
            label = f'Chest ({zone_val.replace("_", " ")})'
            chest_handles.append(
                mpatches.Patch(facecolor=color, edgecolor='black', label=label)
            )

    # Legend
    base_handles = map_base_legend_handles(has_build_region=has_build)
    all_handles = base_handles + zone_handles + res_handles + chest_handles
    if all_handles:
        ax.legend(handles=all_handles, loc='upper right', fontsize=7,
                  framealpha=0.85, ncol=2)

    fig.tight_layout()
    fig.savefig(str(save_path), dpi=150, bbox_inches='tight')
    plt.close(fig)
