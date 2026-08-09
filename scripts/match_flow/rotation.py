#!/usr/bin/env python3
"""Is a void rotated around, or merely present?

Scale-free, unlike a fixed gap threshold, which is blind to any map whose voids
are narrower than it: for every successful approach that genuinely skirts a
void, take the sign of its offset from the axis running spawn to wool. Both
signs present means the void is rotated around; one sign means the alternative
is on the map and declined.

Two gates keep it honest. The path must come within the void's own extent plus a
small margin, and the void must lie between where the approach starts and the
wool it is heading for — an approach to one objective passing near another's
void is noise.

What this found: outback's four corner voids are rotated around in 5 of 155
skirting approaches, while townside_mini's ring is rotated around in 23 of 59 at
one end and 16 of 56 at the other. Pooled by class over four maps, encased
voids see 22.7%, gap 13.6%, frontline 11.9% and middle 10.8% — but the spread
inside each class is wider than the difference between them, so the class does
not predict usage on its own.

Usage
-----
    python scripts/match_flow/rotation.py --map outback_outback_edition
    python scripts/match_flow/rotation.py --class-summary
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

import approaches
import common
import voidmap

DEFAULT_MAPS = ['kanto', 'outback_outback_edition', 'townside_mini', 'sanctum_wasser']


def sides(con, map_slug: str, min_bundle: int = 10) -> list[dict]:
    """One row per (void, wool, team): how many skirting approaches took each side."""
    labelled = voidmap.label_voids(con, map_slug)
    if not labelled:
        return []
    records = approaches.extract(con, map_slug)
    out = []
    for index, void in enumerate(labelled):
        a, b, c, d = void['span']
        half = max(b - a, d - c) / 2
        margin = half + 10
        tally = defaultdict(lambda: [0, 0])
        for record in records:
            path = np.array(record['path'], float)
            if len(path) < 3:
                continue
            distance = np.hypot(path[:, 0] - void['cx'], path[:, 1] - void['cz'])
            if distance.min() > margin:
                continue
            wx, wz = record['wool']
            sx, sz = record['spawn']
            ax, az = wx - sx, wz - sz
            length = math.hypot(ax, az) or 1.0
            ax, az = ax / length, az / length
            along_void = (void['cx'] - sx) * ax + (void['cz'] - sz) * az
            along_start = (path[0, 0] - sx) * ax + (path[0, 1] - sz) * az
            along_wool = (wx - sx) * ax + (wz - sz) * az
            if not (min(along_start, along_wool) - 5 <= along_void <= max(along_start, along_wool) + 5):
                continue
            i = int(np.argmin(distance))
            lateral = (path[i, 0] - void['cx']) * (-az) + (path[i, 1] - void['cz']) * ax
            tally[(record['wool_id'], record['team'])][0 if lateral >= 0 else 1] += 1
        for (wool_id, team), (one, other) in tally.items():
            if one + other >= min_bundle:
                out.append(dict(map=map_slug, void=index, cls=void['cls'], cells=void['cells'],
                                wool_id=wool_id, team=team, near=one + other,
                                rotated=min(one, other), share=min(one, other) / (one + other)))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--map', action='append')
    parser.add_argument('--class-summary', action='store_true')
    args = parser.parse_args()
    con = common.connect()
    slugs = args.map or DEFAULT_MAPS

    rows = []
    for slug in slugs:
        found = sides(con, slug)
        rows += found
        if not args.class_summary:
            print(f'=== {slug} ===')
            for r in sorted(found, key=lambda r: (r['cls'], -r['share'])):
                verdict = ('rotated' if r['share'] >= 0.10
                           else f"one side only ({r['rotated']} of {r['near']})")
                print(f"   {r['cls']:9s} void {r['void']:2d} ({r['cells']:5d} cells)  "
                      f"wool {r['wool_id']:2d} {r['team']:8s} n={r['near']:3d}  "
                      f"took the other side {r['rotated']:3d} ({100 * r['share']:4.1f}%)  {verdict}")
            print()
    if not rows:
        return
    agg = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        agg[r['cls']][0] += r['near']
        agg[r['cls']][1] += r['rotated']
        agg[r['cls']][2] += 1
    print('=== pooled by class ===')
    for cls, (near, rotated, n) in sorted(agg.items(), key=lambda t: -t[1][1] / max(t[1][0], 1)):
        print(f"   {cls:9s} {n:2d} objective-void pairs   {near:5d} skirting approaches, "
              f"{rotated:4d} rotated ({100 * rotated / near:4.1f}%)")


if __name__ == '__main__':
    main()
