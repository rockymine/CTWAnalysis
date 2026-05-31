"""Layout and output-data scanning diagnostics.

Public entry points:
- run_data(args):   scan output JSON files and report empty/missing fields
"""

import csv
import json
import sys
from pathlib import Path
from typing import Optional
def run_data(args: object) -> None:
    """Scan output JSON files across all maps and report empty/missing fields."""
    root = Path(args.dir)
    if not root.is_dir():
        print(f"Error: directory not found: {root}", file=sys.stderr)
        sys.exit(1)

    json_file = args.json_file
    missing_file = []
    issues: list[tuple[str, list[str]]] = []
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


def _handle_block_scan(root: Path, filename: str, csv_path: Optional[str]) -> None:
    import pandas as pd

    rows: list[tuple[str, list]] = []
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


def _handle_water(root: Path, filename: str) -> None:
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
        for i, water_poly in enumerate(sorted(water_polys, key=lambda p: p.area, reverse=True)):
            bounds = water_poly.bounds  # (minx, miny, maxx, maxy) = (minx, minz, maxx, maxz)
            print(f"    [{i}] area={water_poly.area:.0f}  "
                  f"bounds=({bounds[0]:.0f}, {bounds[1]:.0f})"
                  f"..({bounds[2]:.0f}, {bounds[3]:.0f})  "
                  f"holes={len(list(water_poly.interiors))}")

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

        br_polys = _coords_to_polygons(build_region.get('polygons', []))
        if not br_polys:
            print(f"  build_region polygons: could not reconstruct")
            continue

        br_geom = unary_union(br_polys)
        print(f"  build_region area: {br_geom.area:.0f}")

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
        if len(ext) < 4:
            continue
        holes = [h for h in entry.get('holes', []) if len(h) >= 4]
        try:
            poly = Polygon(ext, holes)
            if poly.is_valid and not poly.is_empty:
                polys.append(poly)
        except Exception:
            continue
    return polys
