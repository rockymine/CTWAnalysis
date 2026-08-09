#!/usr/bin/env python3
"""Approach-route variance: for every life that TOUCHED a wool, where did it come from?

Only lives that reached the wool at its spawner count — an approach that died on
the way says nothing about which route works. Each contributes the last stretch
of its path, resampled to a fixed number of points by arc length. At every point
along that bundle, project it onto its own principal lateral axis and look for
the largest gap leaving at least a fifth of the traffic on each side: that is
where a route genuinely forks.

Where the fork sits matters more than whether one exists. A fork inside 45
blocks is a second way IN to the objective; one beyond that is a choice of lane
made far from the room, and the two are not the same thing. Over 490 bundles on
150 maps, 9% have the first, 35% the second, and 63% are a single corridor end
to end.

A fixed gap threshold is blind to maps whose voids are narrower than it — see
rotation.py for the scale-free test.

Usage
-----
    python scripts/match_flow/approaches.py --map kanto
    python scripts/match_flow/approaches.py --sweep
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

import common

RESAMPLE = 14      # points per approach
REACH = 80.0       # how far back from the wool approaches are compared
MIN_SIDE = 0.20    # a fork must leave at least this share on each side


def extract(con, map_slug: str, radius: float = 30.0) -> list[dict]:
    """One record per life that reached a wool: its path, the wool, the toucher's team."""
    map_id = con.execute('select map_id from maps where map_slug = ?', [map_slug]).fetchone()[0]
    wools = {w: (x, z) for w, x, z in con.execute(
        'select wool_id, x, z from map_wool_locations where map_id = ?', [map_id]).fetchall()}
    spawns = {t: (x, z) for t, x, z in con.execute(
        'select team, x, z from map_spawns where map_id = ?', [map_id]).fetchall()}
    fallback = dict(con.execute(
        'select wool_id, team from map_wool_objectives where map_id = ?', [map_id]).fetchall())
    touches = con.execute("""
        select w.match_id, w.player_id, w.segment_idx, w.wool_id, w.timestamp, ts.team
          from wool_events w
          join matches mt using(match_id)
          join player_team_segments ts
            on ts.match_id = w.match_id and ts.player_id = w.player_id
           and w.timestamp >= ts.start_timestamp
           and w.timestamp <= coalesce(ts.end_timestamp, 2147483647)
         where w.event_type = 6 and mt.spatial_classified and mt.map_id = ?
         order by w.match_id, w.timestamp""", [map_id]).fetchall()

    out = []
    for match_id, player_id, segment_idx, wool_id, timestamp, team in touches:
        if wool_id not in wools:
            continue
        wx, wz = wools[wool_id]
        # the team that actually touched it, never the objectives table alone
        attacker = team if team in spawns else fallback.get(wool_id)
        if attacker not in spawns:
            continue
        sx, sz = spawns[attacker]
        rows = con.execute("""
            select timestamp, x, z from position_events
             where match_id = ? and player_id = ? and segment_idx = ? and timestamp <= ?
             order by timestamp""", [match_id, player_id, segment_idx, timestamp]).fetchall()
        if len(rows) < 4:
            continue
        distance = [math.hypot(x - wx, z - wz) for _, x, z in rows]
        if distance[-1] > radius:
            continue
        crossing = next((i for i in range(len(rows) - 1, -1, -1) if distance[i] > radius), None)
        if crossing is None:
            continue
        out.append(dict(match_id=match_id, wool_id=wool_id, team=attacker,
                        wool=(wx, wz), spawn=(sx, sz),
                        path=[(x, z) for _, x, z in rows[max(0, crossing - 40):]]))
    return out


def resample(path, wool, reach: float = REACH, k: int = RESAMPLE):
    """Fixed-count points along the last `reach` blocks of an approach."""
    pts = [(x, z) for x, z in path if math.hypot(x - wool[0], z - wool[1]) <= reach]
    if len(pts) < 4:
        return None
    arc = [0.0]
    for i in range(1, len(pts)):
        arc.append(arc[-1] + math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
    if arc[-1] < 20:
        return None
    out, j = [], 0
    for target in np.linspace(0, arc[-1], k):
        while j + 1 < len(arc) and arc[j + 1] < target:
            j += 1
        out.append(pts[min(j, len(pts) - 1)])
    return np.array(out, float)


def split_profile(curves, wool) -> list[dict]:
    """Per resample point: the widest gap that leaves MIN_SIDE on each side."""
    stack = np.stack(curves)
    profile = []
    for i in range(stack.shape[1]):
        pts = stack[:, i, :]
        if len(pts) < 8:
            continue
        centred = pts - pts.mean(0)
        _, _, basis = np.linalg.svd(centred)
        proj = np.sort(centred @ basis[0])
        low = max(1, int(MIN_SIDE * len(proj)))
        best = (0.0, low)
        for k in range(low, len(proj) - low + 1):
            gap = proj[k] - proj[k - 1]
            if gap > best[0]:
                best = (gap, k)
        gap, k = best
        profile.append(dict(index=i, gap=float(gap),
                            minority=min(k, len(proj) - k) / len(proj),
                            spread=float(proj.max() - proj.min()),
                            distance=float(np.mean(np.linalg.norm(pts - np.array(wool), axis=1)))))
    return profile


def analyse(con, map_slug: str, min_bundle: int = 10) -> list[dict]:
    """Split profiles per (wool, attacking team). Bundles must not mix attackers."""
    records = extract(con, map_slug)
    bundles = defaultdict(list)
    for record in records:
        curve = resample(record['path'], record['wool'])
        if curve is not None:
            bundles[(record['wool_id'], record['team'])].append((curve, record))
    out = []
    for (wool_id, team), items in sorted(bundles.items()):
        if len(items) < min_bundle:
            continue
        curves = [c for c, _ in items]
        profile = split_profile(curves, items[0][1]['wool'])
        if not profile:
            continue
        inner = [p for p in profile if p['distance'] <= 45]
        outer = [p for p in profile if p['distance'] > 45]
        out.append(dict(wool_id=wool_id, team=team, n=len(curves), profile=profile,
                        approach=max(inner, key=lambda p: p['gap']) if inner else None,
                        lane=max(outer, key=lambda p: p['gap']) if outer else None,
                        curves=curves, records=[r for _, r in items]))
    return out


def is_split(point) -> bool:
    return bool(point) and point['gap'] >= 12 and point['minority'] >= MIN_SIDE


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--map')
    parser.add_argument('--sweep', action='store_true')
    parser.add_argument('--min-touches', type=int, default=40)
    args = parser.parse_args()
    con = common.connect()

    if args.map:
        for res in analyse(con, args.map):
            fmt = lambda p: '  --  ' if p is None else f"{p['gap']:5.1f}b/{100 * p['minority']:2.0f}%"
            verdict = 'TWO ROUTES' if is_split(res['approach']) or is_split(res['lane']) else 'one corridor'
            print(f"  wool {res['wool_id']:2d} {res['team']:8s} n={res['n']:3d}  "
                  f"approach split {fmt(res['approach'])}  lane split {fmt(res['lane'])}  -> {verdict}")
        return
    if not args.sweep:
        parser.error('give --map or --sweep')

    slugs = [r[0] for r in con.execute("""
        select m.map_slug from wool_events w join matches mt using(match_id) join maps m using(map_id)
         where w.event_type = 6 and mt.spatial_classified
         group by 1 having count(*) >= ? order by count(*) desc""", [args.min_touches]).fetchall()]
    rows = []
    for i, slug in enumerate(slugs):
        try:
            for res in analyse(con, slug):
                rows.append(dict(map=slug, wool=res['wool_id'], team=res['team'], n=res['n'],
                                 approach=is_split(res['approach']), lane=is_split(res['lane'])))
        except Exception as exc:
            print(f'  {slug}: {exc}', flush=True)
        if (i + 1) % 25 == 0:
            print(f'  ...{i + 1}/{len(slugs)}', flush=True)
    big = [r for r in rows if r['n'] >= 15]
    print(f"\nbundles with 15+ successful approaches: {len(big)} over {len({r['map'] for r in big})} maps")
    print(f"  a second way in at the objective  {sum(1 for r in big if r['approach']):3d} "
          f"({100 * sum(1 for r in big if r['approach']) / len(big):2.0f}%)")
    print(f"  a second lane further out         {sum(1 for r in big if r['lane']):3d} "
          f"({100 * sum(1 for r in big if r['lane']) / len(big):2.0f}%)")
    neither = [r for r in big if not r['approach'] and not r['lane']]
    print(f"  one corridor end to end           {len(neither):3d} ({100 * len(neither) / len(big):2.0f}%)")
    json.dump(rows, open('approach_sweep.json', 'w'))


if __name__ == '__main__':
    main()
