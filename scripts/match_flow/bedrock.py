#!/usr/bin/env python3
"""Bedrock walls standing in front of a wool room, read from the world files.

Where a map offers a straight run of bedrock in front of a wool room, the
defence builds its wall on it — a wall on open ground can be undermined at its
base and a wall on bedrock cannot. 59 of 94 corpus maps have one; the median
outermost line stands 20 blocks in front of the wool, or about 13 in front of
the room face.

Two steps, because they cost very different amounts:

  cache    scan every world once for bedrock columns standing above the world
           floor, and write them to bedrock_columns.json
  lines    project those columns onto each room's approach and keep the
           distances carrying a contiguous lateral run

Usage
-----
    python scripts/match_flow/bedrock.py --cache
    python scripts/match_flow/bedrock.py --lines
    python scripts/match_flow/bedrock.py --lines --map kanto
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

import anvil18
import common

CACHE = Path(__file__).resolve().parent / 'bedrock_columns.json'
BEDROCK = 7

# where the map worlds live; override with CTW_MAP_WORLDS (colon-separated)
WORLD_ROOTS = [Path(p) for p in os.environ.get(
    'CTW_MAP_WORLDS',
    '/media/sf_repos/CommunityMaps:/media/sf_repos/PublicMaps:'
    + str(common.PROJECT_ROOT / 'map_folders')).split(':')]


def find_worlds() -> dict[str, Path]:
    worlds: dict[str, Path] = {}
    for root in WORLD_ROOTS:
        if not root.exists():
            continue
        for region in root.glob('**/region'):
            worlds.setdefault(region.parent.name, region.parent)
    return worlds


def bedrock_columns(region_dir: Path, x0: int, x1: int, z0: int, z1: int) -> dict:
    """(x, z) -> highest bedrock y in that column inside the box."""
    top: dict[tuple[int, int], int] = {}
    for name in os.listdir(region_dir):
        if not (name.startswith('r.') and name.endswith('.mca')):
            continue
        parts = name.split('.')
        try:
            rx, rz = int(parts[1]), int(parts[2])
        except ValueError:
            continue
        if (rx + 1) * 512 <= x0 or rx * 512 > x1 or (rz + 1) * 512 <= z0 or rz * 512 > z1:
            continue
        for chunk in anvil18.chunks(str(region_dir / name)):
            try:
                level = chunk['Level']
                cx, cz = level['xPos'].value, level['zPos'].value
            except Exception:
                continue
            bx, bz = cx * 16, cz * 16
            if bx + 15 < x0 or bx > x1 or bz + 15 < z0 or bz > z1 or 'Sections' not in level:
                continue
            for section in level['Sections']:
                sy = section['Y'].value * 16
                if sy > 48:
                    continue
                blocks = np.frombuffer(bytes(section['Blocks'].value), dtype=np.uint8)
                found = np.nonzero(blocks == BEDROCK)[0]
                if found.size == 0:
                    continue
                ys = sy + (found >> 8)
                zs = bz + ((found >> 4) & 15)
                xs = bx + (found & 15)
                keep = (xs >= x0) & (xs <= x1) & (zs >= z0) & (zs <= z1) & (ys <= 48)
                for x, y, z in zip(xs[keep], ys[keep], zs[keep]):
                    key = (int(x), int(z))
                    if y > top.get(key, -1):
                        top[key] = int(y)
    return top


def cache_all(con) -> None:
    worlds = find_worlds()
    rooms = common.load_wool_rooms()
    by_map: dict[str, list] = defaultdict(list)
    for (slug, _wool), rect in rooms.items():
        by_map[slug].append(rect)
    out = {}
    for index, (slug, rects) in enumerate(sorted(by_map.items())):
        world = worlds.get(slug)
        if world is None or not (world / 'region').is_dir():
            continue
        xs = [v for r in rects for v in (r[0], r[2])]
        zs = [v for r in rects for v in (r[1], r[3])]
        top = bedrock_columns(world / 'region', int(min(xs) - 100), int(max(xs) + 100),
                              int(min(zs) - 100), int(max(zs) + 100))
        if not top:
            continue
        floor = int(np.percentile(np.array(list(top.values())), 90))
        walls = [[x, z, y] for (x, z), y in top.items() if y >= floor + 3]
        out[slug] = {'floor': floor, 'walls': walls}
        print(f'[{index + 1:3d}] {slug:28s} floor={floor:3d} above-floor columns={len(walls):5d}',
              flush=True)
    CACHE.write_text(json.dumps(out))
    print(f'wrote {CACHE} for {len(out)} maps')


def wall_lines(columns: list, rect, approach_from, low: float = 1.0, high: float = 80.0,
               bin_width: int = 3, min_run: int = 8) -> list[float]:
    """Distances from the room FACE carrying a contiguous lateral bedrock run."""
    cx = (rect[0] + rect[2]) / 2
    cz = (rect[1] + rect[3]) / 2
    dx, dz = approach_from[0] - cx, approach_from[1] - cz
    norm = math.hypot(dx, dz) or 1.0
    dx, dz = dx / norm, dz / norm
    bins: dict[int, set] = defaultdict(set)
    for x, z, _y in columns:
        ahead = (x - cx) * dx + (z - cz) * dz
        lateral = (x - cx) * (-dz) + (z - cz) * dx
        if abs(lateral) > 40 or ahead < -5:
            continue
        face = common.distance_to_rect(x, z, rect)
        if face < low or face > high:
            continue
        bins[int(face // bin_width)].add(int(round(lateral)))
    lines = []
    for key, laterals in bins.items():
        ordered = sorted(laterals)
        best = run = 1
        for i in range(1, len(ordered)):
            run = run + 1 if ordered[i] <= ordered[i - 1] + 1 else 1
            best = max(best, run)
        if best >= min_run:
            lines.append(key * bin_width + bin_width / 2)
    return sorted(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--cache', action='store_true', help='rescan every world (slow)')
    parser.add_argument('--lines', action='store_true')
    parser.add_argument('--map')
    args = parser.parse_args()
    con = common.connect()

    if args.cache:
        cache_all(con)
        return
    if not args.lines:
        parser.error('give --cache or --lines')
    if not CACHE.exists():
        raise SystemExit(f'{CACHE} is missing; run --cache first')

    cached = json.loads(CACHE.read_text())
    rooms = common.load_wool_rooms()
    found = total = 0
    for (slug, wool_id), rect in sorted(rooms.items()):
        if args.map and slug != args.map:
            continue
        if slug not in cached:
            continue
        spawns = con.execute("""select s.x, s.z from map_spawns s join maps m using(map_id)
                                 where m.map_slug = ?""", [slug]).fetchall()
        if not spawns:
            continue
        # approach comes from whichever spawn is farther — the attacker's side
        approach = max(spawns, key=lambda s: math.hypot(s[0] - (rect[0] + rect[2]) / 2,
                                                        s[1] - (rect[1] + rect[3]) / 2))
        lines = wall_lines(cached[slug]['walls'], rect, approach)
        total += 1
        if lines:
            found += 1
            print(f'  {slug:28s} wool {wool_id:2d}  bedrock lines in front of the face: '
                  f'{[round(v) for v in lines]}')
    print(f'\n{found} of {total} rooms have a straight bedrock run in front of the face')


if __name__ == '__main__':
    main()
