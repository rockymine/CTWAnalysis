#!/usr/bin/env python3
"""Enclosed voids on a real map, labelled the way BoardDeriver labels a generated one.

A route can only fork around something, and on a real map that something is a
hole in the playable surface. Rasterise the terrain footprint from
map_terrain_height, rasterise the declared build-region polygons on top, then
flood the complement inward from the border: whatever the flood cannot reach is
enclosed.

The classes are BoardDeriver's own, decided by what borders the hole:

  middle     contested — anchored terrain of two teams rings it, or no anchored
             terrain but a non-intra-team build region or two teams' build does
  encased    uncontested and touching no build region at all
  frontline  uncontested, touching build, at least one of it non-intra-team
  gap        uncontested, touching only intra-team build

An island is anchored when it holds a spawn or a wool room. A wool's island
belongs to the team DEFENDING it, which is the team that does not attack it.

Validated against an author's own counts: kanto 5, outback 10, townside_mini 3,
sanctum_wasser 8 — the last as four mirrored pairs, which is a whole-map count
of the four a single team faces.

Usage
-----
    python scripts/match_flow/voidmap.py --map kanto
    python scripts/match_flow/voidmap.py --map outback_outback_edition --map sanctum_wasser
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict, deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

import common

MIN_CELLS = 12


def polygon_mask(ring, x0: int, z0: int, w: int, h: int):
    """Even-odd scanline fill of one ring."""
    mask = np.zeros((h, w), bool)
    pts = [(x - x0, z - z0) for x, z in ring]
    n = len(pts)
    for row in range(h):
        y = row + 0.5
        crossings = []
        for i in range(n):
            (x1, z1), (x2, z2) = pts[i], pts[(i + 1) % n]
            if (z1 > y) != (z2 > y):
                crossings.append(x1 + (y - z1) * (x2 - x1) / (z2 - z1))
        crossings.sort()
        for i in range(0, len(crossings) - 1, 2):
            a = int(math.ceil(crossings[i] - 0.5))
            b = int(math.floor(crossings[i + 1] - 0.5))
            if b >= 0 and a < w:
                mask[row, max(a, 0):min(b + 1, w)] = True
    return mask


def surface(con, map_slug: str, pad: int = 6):
    """(playable mask, x origin, z origin, map_id) — terrain plus declared build."""
    map_id = con.execute('select map_id from maps where map_slug = ?', [map_slug]).fetchone()[0]
    land = con.execute('select world_x, world_z from map_terrain_height where map_id = ?',
                       [map_id]).fetchall()
    if not land:
        return None
    path = common.OUTPUT_DIR / map_slug / 'map_data.json'
    polys = []
    try:
        polys = (json.loads((common.OUTPUT_DIR / map_slug / 'map_context.json').read_text())
                 .get('build_region') or {}).get('polygons') or []
    except Exception:
        pass
    xs = [p[0] for p in land] + [c[0] for poly in polys for c in poly['exterior']]
    zs = [p[1] for p in land] + [c[1] for poly in polys for c in poly['exterior']]
    x0, z0 = int(min(xs)) - pad, int(min(zs)) - pad
    w = int(max(xs)) + pad - x0 + 1
    h = int(max(zs)) + pad - z0 + 1
    mask = np.zeros((h, w), bool)
    for x, z in land:
        mask[z - z0, x - x0] = True
    for poly in polys:
        mask |= polygon_mask([tuple(c) for c in poly['exterior']], x0, z0, w, h)
        for hole in poly.get('holes') or []:
            mask &= ~polygon_mask([tuple(c) for c in hole], x0, z0, w, h)
    return mask, x0, z0, map_id, polys


def holes(mask, min_cells: int = MIN_CELLS) -> list[list]:
    """Empty components the border flood cannot reach."""
    h, w = mask.shape
    outside = np.zeros_like(mask)
    queue = deque()
    for x in range(w):
        for z in (0, h - 1):
            if not mask[z, x] and not outside[z, x]:
                outside[z, x] = True
                queue.append((z, x))
    for z in range(h):
        for x in (0, w - 1):
            if not mask[z, x] and not outside[z, x]:
                outside[z, x] = True
                queue.append((z, x))
    while queue:
        z, x = queue.popleft()
        for dz, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nz, nx = z + dz, x + dx
            if 0 <= nz < h and 0 <= nx < w and not mask[nz, nx] and not outside[nz, nx]:
                outside[nz, nx] = True
                queue.append((nz, nx))
    found, seen = [], np.zeros_like(mask)
    for z in range(h):
        for x in range(w):
            if mask[z, x] or outside[z, x] or seen[z, x]:
                continue
            comp, queue = [], deque([(z, x)])
            seen[z, x] = True
            while queue:
                cz, cx = queue.popleft()
                comp.append((cz, cx))
                for dz, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nz, nx = cz + dz, cx + dx
                    if (0 <= nz < h and 0 <= nx < w and not mask[nz, nx]
                            and not outside[nz, nx] and not seen[nz, nx]):
                        seen[nz, nx] = True
                        queue.append((nz, nx))
            if len(comp) >= min_cells:
                found.append(comp)
    return sorted(found, key=len, reverse=True)


def islands(con, map_id: int, x0: int, z0: int, shape) -> tuple:
    """Connected land, and the team of each island that holds a spawn or a wool room."""
    h, w = shape
    land = np.zeros(shape, bool)
    for x, z in con.execute('select world_x, world_z from map_terrain_height where map_id = ?',
                            [map_id]).fetchall():
        land[z - z0, x - x0] = True
    label = -np.ones(shape, int)
    count = 0
    for z in range(h):
        for x in range(w):
            if land[z, x] and label[z, x] < 0:
                queue = deque([(z, x)])
                label[z, x] = count
                while queue:
                    cz, cx = queue.popleft()
                    for dz, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nz, nx = cz + dz, cx + dx
                        if 0 <= nz < h and 0 <= nx < w and land[nz, nx] and label[nz, nx] < 0:
                            label[nz, nx] = count
                            queue.append((nz, nx))
                count += 1
    team_of = {}
    for team, x, z in con.execute('select team, x, z from map_spawns where map_id = ?',
                                  [map_id]).fetchall():
        iz, ix = int(z) - z0, int(x) - x0
        if 0 <= iz < h and 0 <= ix < w and label[iz, ix] >= 0:
            team_of[label[iz, ix]] = team
    attacker = dict(con.execute('select wool_id, team from map_wool_objectives where map_id = ?',
                                [map_id]).fetchall())
    teams = {t for t, in con.execute('select distinct team from map_spawns where map_id = ?',
                                     [map_id]).fetchall()}
    for wool_id, x, z in con.execute('select wool_id, x, z from map_wool_locations where map_id = ?',
                                     [map_id]).fetchall():
        iz, ix = int(z) - z0, int(x) - x0
        if not (0 <= iz < h and 0 <= ix < w) or label[iz, ix] < 0:
            continue
        defenders = teams - {attacker.get(wool_id)}
        if len(defenders) == 1:
            team_of.setdefault(label[iz, ix], next(iter(defenders)))
    return label, team_of


def label_voids(con, map_slug: str) -> list[dict] | None:
    built = surface(con, map_slug)
    if built is None:
        return None
    mask, x0, z0, map_id, polys = built
    h, w = mask.shape
    island, team_of = islands(con, map_id, x0, z0, mask.shape)

    region = -np.ones(mask.shape, int)
    for ri, poly in enumerate(polys):
        filled = polygon_mask([tuple(c) for c in poly['exterior']], x0, z0, w, h)
        region[filled & (island < 0)] = ri
    region_islands = defaultdict(set)
    for z in range(h):
        for x in range(w):
            if region[z, x] < 0:
                continue
            for dz, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nz, nx = z + dz, x + dx
                if 0 <= nz < h and 0 <= nx < w and island[nz, nx] >= 0:
                    region_islands[region[z, x]].add(island[nz, nx])
    intra = {ri: len({team_of[i] for i in region_islands.get(ri, set()) if i in team_of}) <= 1
             for ri in range(len(polys))}

    out = []
    for comp in holes(mask):
        cells = set(comp)
        terrain_teams, build_teams, border_regions = set(), set(), set()
        touches_build = touches_frontline = False
        for cz, cx in comp:
            for dz, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nz, nx = cz + dz, cx + dx
                if not (0 <= nz < h and 0 <= nx < w) or (nz, nx) in cells:
                    continue
                if island[nz, nx] >= 0:
                    if island[nz, nx] in team_of:
                        terrain_teams.add(team_of[island[nz, nx]])
                elif region[nz, nx] >= 0:
                    touches_build = True
                    ri = region[nz, nx]
                    border_regions.add(ri)
                    if not intra[ri]:
                        touches_frontline = True
                    build_teams |= {team_of[i] for i in region_islands.get(ri, set()) if i in team_of}
        contested = len(terrain_teams) >= 2 or (
            not terrain_teams and (touches_frontline or len(build_teams) >= 2))
        cls = ('middle' if contested else 'encased' if not touches_build
               else 'frontline' if touches_frontline else 'gap')
        zs = [c[0] + z0 for c in comp]
        xs = [c[1] + x0 for c in comp]
        out.append(dict(cls=cls, cells=len(comp), cx=float(np.mean(xs)), cz=float(np.mean(zs)),
                        span=(min(xs), max(xs), min(zs), max(zs)),
                        terrain_teams=sorted(terrain_teams), border_regions=len(border_regions)))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--map', action='append', required=True)
    args = parser.parse_args()
    con = common.connect()
    for slug in args.map:
        rows = label_voids(con, slug)
        if rows is None:
            print(f'{slug}: no terrain rows'); continue
        tally = defaultdict(int)
        for r in rows:
            tally[r['cls']] += 1
        print(f"=== {slug}: {len(rows)} voids — " +
              ', '.join(f'{n} {k}' for k, n in sorted(tally.items(), key=lambda t: -t[1])))
        for r in sorted(rows, key=lambda r: -r['cells']):
            a, b, c, d = r['span']
            print(f"    {r['cls']:9s} {r['cells']:5d} cells  x {a:5d}..{b:5d}  z {c:5d}..{d:5d}  "
                  f"terrain teams {r['terrain_teams']}  bordering build zones {r['border_regions']}")
        print()


if __name__ == '__main__':
    main()
