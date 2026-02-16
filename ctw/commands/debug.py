"""'debug' subcommand — diagnostic tools for layout parquet and output JSON files."""

import csv
import json
import sys
from pathlib import Path


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
    from shapely.geometry import box, Polygon, MultiPolygon
    from shapely.ops import unary_union

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
        squares = [
            box(x, z, x + 1, z + 1)
            for x, z in zip(water['world_x'], water['world_z'])
        ]
        water_geom = unary_union(squares)

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
        all_x.extend([y0_df['world_x'].min(), y0_df['world_x'].max() + 1])
        all_z.extend([y0_df['world_z'].min(), y0_df['world_z'].max() + 1])
    if bed_df is not None:
        all_x.extend([bed_df['world_x'].min(), bed_df['world_x'].max() + 1])
        all_z.extend([bed_df['world_z'].min(), bed_df['world_z'].max() + 1])
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
            verts.append([(x, z), (x+1, z), (x+1, z+1), (x, z+1)])
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
            verts.append([(x, z), (x+1, z), (x+1, z+1), (x, z+1)])
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
        verts = [[(x, z), (x+1, z), (x+1, z+1), (x, z+1)] for x, z in coords]
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
