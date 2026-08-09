#!/usr/bin/env python3
"""Find the walls and staircases players build, from position traffic alone.

Both structures leave a signature in where people habitually stand:

  staircase  a narrow run whose height climbs linearly ALONG its own long axis
  wall       an elevated run lying along a wool-room face, level along its length

Geometry alone does not separate them — on sanctum_wasser both room-adjacent
runs lie 2 degrees off a room face and span 63% of it. What separates them is
where the height gradient lives: along the long axis (stair) or nowhere
(wall). Ownership is the independent check, since nothing in the geometry
knows which team defends which room.

Clustering cells by ramp height works on some maps and fails on others, where
mid-height traffic is so widespread the cells fuse into one field. The detector
below fits a plane to the height field in a local neighbourhood of every cell
instead, and groups the cells whose gradient is strong and residual small.

Usage
-----
    python scripts/match_flow/structures.py --map sanctum_wasser --match 2174
    python scripts/match_flow/structures.py --sweep --min-minutes 45
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

import common


def ramp_runs(ctx: dict, min_count: int = 12, radius: int = 8,
              min_gradient: float = 0.35, max_residual: float = 3.0) -> list[dict]:
    """Connected groups of cells whose local height field has a consistent slope."""
    pos, cell = ctx['pos'], ctx['cell']
    usable = pos.dropna(subset=['rel'])
    if usable.empty:
        return []
    cap_rel = int(np.percentile(usable.rel, 99))
    grid = usable.groupby(['cx', 'cz']).agg(n=('rel', 'size'), h=('rel', 'median')).reset_index()
    grid = grid[(grid.n >= min_count) & (grid.h >= 2)]
    if len(grid) < 20:
        return []

    points = grid[['cx', 'cz']].to_numpy(float)
    heights = grid.h.to_numpy(float)
    gradient = np.zeros(len(grid))
    residual = np.full(len(grid), 9.0)
    for i in range(len(grid)):
        near = ((points - points[i]) ** 2).sum(1) <= radius * radius
        if near.sum() < 6:
            continue
        design = np.column_stack([points[near, 0] - points[i, 0],
                                  points[near, 1] - points[i, 1],
                                  np.ones(int(near.sum()))])
        coef, *_ = np.linalg.lstsq(design, heights[near], rcond=None)
        gradient[i] = math.hypot(coef[0], coef[1])
        residual[i] = float(np.std(heights[near] - design @ coef))

    grid = grid.assign(gradient=gradient, residual=residual)
    ramp = grid[(grid.gradient >= min_gradient) & (grid.residual <= max_residual)
                & (grid.h <= cap_rel - 2)]
    if ramp.empty:
        return []

    index = {(int(r.cx), int(r.cz)): i for i, r in enumerate(ramp.itertuples())}
    parent = list(range(len(ramp)))

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for (cx, cz), i in index.items():
        for dx in (-cell, 0, cell):
            for dz in (-cell, 0, cell):
                j = index.get((cx + dx, cz + dz))
                if j is not None:
                    union(i, j)

    groups: dict[int, list] = defaultdict(list)
    for key, i in index.items():
        groups[find(i)].append(key)
    lookup = ramp.set_index(['cx', 'cz'])

    runs = []
    for cells in groups.values():
        if len(cells) < 6:
            continue
        pts = np.array(cells, float)
        hs = np.array([lookup.loc[c, 'h'] for c in cells], float)
        ns = np.array([lookup.loc[c, 'n'] for c in cells], float)
        centre = pts.mean(0)
        _, _, basis = np.linalg.svd(pts - centre)
        along = (pts - centre) @ basis[0]
        across = (pts - centre) @ basis[1]
        design = np.column_stack([along, across, np.ones(len(along))])
        coef, *_ = np.linalg.lstsq(design, hs, rcond=None)
        g_long, g_across = abs(coef[0]), abs(coef[1])
        runs.append(dict(cells=cells, samples=int(ns.sum()),
                         cx=float(centre[0]), cz=float(centre[1]),
                         length=float(along.max() - along.min()),
                         width=float(across.max() - across.min()),
                         rise=float(hs.max() - hs.min()),
                         g_long=float(g_long), g_across=float(g_across),
                         ratio=float(g_long / max(g_across, 0.02))))
    runs.sort(key=lambda r: -r['samples'])
    return runs


def classify(run: dict, room_distance: float) -> str | None:
    """A stair climbs along itself; a wall sits by a room and does not."""
    if run['ratio'] >= 2.5 and run['g_long'] >= 0.45 and run['width'] <= 14:
        return 'stair'
    if (room_distance <= 25 and run['g_long'] <= 0.35 and run['ratio'] < 2.0
            and run['width'] <= 12 and run['length'] >= 8):
        return 'wall'
    return None


def describe(ctx: dict, runs: list[dict], top: int = 16) -> list[dict]:
    """Attach the nearest room, the nearest spawn, and who actually stands there."""
    pos = ctx['pos']
    out = []
    for run in runs[:top]:
        cells = set(map(tuple, run['cells']))
        here = pos[[(a, b) in cells for a, b in zip(pos.cx, pos.cz)]]
        if len(here) < 100:
            continue
        wool_id, room_distance, _ = min(
            ((w, common.distance_to_rect(run['cx'], run['cz'], rect), rect)
             for w, rect in ctx['rooms'].items()),
            key=lambda t: t[1], default=(None, 999.0, None))
        kind = classify(run, room_distance)
        if kind is None:
            continue
        spawn_team, spawn_distance = min(
            ((team, common.distance_to_rect(run['cx'], run['cz'], rect))
             for team, rect in ctx['spawns'].items()),
            key=lambda t: t[1], default=(None, 999.0))
        share = here.team.value_counts(normalize=True)
        owner, owner_share = share.index[0], float(share.iloc[0])
        attacker = ctx['attacker'].get(wool_id)
        role = ('defender' if attacker and owner != attacker
                else 'attacker' if attacker else '')
        out.append(dict(kind=kind, cx=run['cx'], cz=run['cz'], cells=run['cells'],
                        samples=run['samples'], length=run['length'], width=run['width'],
                        rise=run['rise'], g_long=run['g_long'], ratio=run['ratio'],
                        wool_id=wool_id, room_distance=room_distance,
                        spawn_team=spawn_team, spawn_distance=spawn_distance,
                        owner=owner, owner_share=owner_share, role=role,
                        bow=float((here.held_item == common.BOW).mean()),
                        detail=float(here.held_item.isin(list(common.DETAIL_MATERIALS)).mean())))
    return out


def analyse(con, map_slug: str, match_id: int) -> list[dict]:
    ctx = common.load_match(con, map_slug, match_id)
    if ctx is None or not ctx['rooms']:
        return []
    return describe(ctx, ramp_runs(ctx))


def _print(rows: list[dict]) -> None:
    for r in rows:
        print(f"  {r['kind']:6s} ({r['cx']:7.0f},{r['cz']:7.0f}) {r['owner']:8s} "
              f"{100 * r['owner_share']:3.0f}% {r['role']:8s} rise {r['rise']:4.1f} "
              f"gradient {r['g_long']:4.2f} ratio {r['ratio']:6.1f} "
              f"room {r['room_distance']:5.0f} spawn {r['spawn_distance']:5.0f} "
              f"bow {100 * r['bow']:3.0f}% detail {100 * r['detail']:4.1f}%")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--map')
    parser.add_argument('--match', type=int)
    parser.add_argument('--sweep', action='store_true',
                        help='run over the longest 2-second-sampled matches')
    parser.add_argument('--min-minutes', type=float, default=45)
    parser.add_argument('--limit', type=int, default=14)
    args = parser.parse_args()

    con = common.connect()
    if args.sweep:
        targets = con.execute(
            """select m.map_slug, mt.match_id, mt.match_duration
                 from matches mt join maps m using(map_id)
                where mt.spatial_classified and mt.log_interval = 2
                  and mt.match_duration > ? order by mt.match_duration desc limit ?""",
            [args.min_minutes * 60, args.limit]).fetchall()
        found = []
        for slug, match_id, duration in targets:
            rows = analyse(con, slug, match_id)
            found += rows
            print(f"{slug:28s} {match_id:5d} {duration / 60:5.0f}min  "
                  f"stairs={sum(1 for r in rows if r['kind'] == 'stair'):2d} "
                  f"walls={sum(1 for r in rows if r['kind'] == 'wall'):2d}")
        walls = [r for r in found if r['kind'] == 'wall' and r['role']]
        stairs = [r for r in found if r['kind'] == 'stair' and r['spawn_distance'] <= 45]
        print()
        if walls:
            defended = sum(1 for r in walls if r['role'] == 'defender')
            print(f"walls n={len(walls)}  held by the room's defender {defended}/{len(walls)}"
                  f"  median {np.median([r['room_distance'] for r in walls]):.0f} blocks off the room")
        if stairs:
            own = sum(1 for r in stairs if r['owner'] == r['spawn_team'])
            print(f"spawn stairs n={len(stairs)}  walked by their own team {own}/{len(stairs)}"
                  f"  median gradient {np.median([r['g_long'] for r in stairs]):.2f}")
        return

    if not (args.map and args.match):
        parser.error('give --map and --match, or --sweep')
    _print(analyse(con, args.map, args.match))


if __name__ == '__main__':
    main()
