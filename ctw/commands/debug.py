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

Examples:
  python ctw.py debug layout --parquet layout_y0
  python ctw.py debug layout --parquet layout_y0 --water
  python ctw.py debug data --json map_data.json
  python ctw.py debug data --json island_analysis/map_context.json
  python ctw.py debug symmetry --map tumbleweed
  python ctw.py debug symmetry
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

    ctx_path = root / map_name / 'island_analysis' / 'map_context.json'
    if not ctx_path.exists():
        ctx_path = Path(map_name) / 'island_analysis' / 'map_context.json'
        if not ctx_path.exists():
            print(f"Error: map_context.json not found for '{map_name}'", file=sys.stderr)
            print(f"  Tried: {root / map_name / 'island_analysis' / 'map_context.json'}",
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
        ctx_path = map_dir / 'island_analysis' / 'map_context.json'
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
        ctx_path = map_dir / 'island_analysis' / 'map_context.json'
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
