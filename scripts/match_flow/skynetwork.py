#!/usr/bin/env python3
"""The sky network at the build ceiling, and the points where players get onto it.

The network is measured from ABSOLUTE height, not height above ground. The
terrain table covers land only, so a height-above-ground filter drops every
sample over the void — on outback that is a third of all ceiling activity and
more than half the cells of the network, which makes the map's sky look
disconnected when it is not.

An entry point is the foot of a climb: within one life, a player goes from
standing on the ground to standing at the ceiling, without dying in between.
The cell that climb started in is the entrance.

Usage
-----
    python scripts/match_flow/skynetwork.py --map outback_outback_edition --match 1862
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import common


def network(ctx: dict, cell: int = 4, min_samples: int = 3) -> pd.DataFrame:
    """Cells occupied at the build ceiling, counted from absolute height."""
    high = ctx['pos'][ctx['pos'].y >= common.ceiling(ctx)]
    if high.empty:
        return pd.DataFrame(columns=['gx', 'gz', 'n', 'over_void'])
    grid = high.assign(gx=(high.x // cell * cell).astype(int),
                       gz=(high.z // cell * cell).astype(int))
    out = grid.groupby(['gx', 'gz']).agg(
        n=('y', 'size'), over_void=('surface_y', lambda s: bool(s.isna().all()))).reset_index()
    return out[out.n >= min_samples]


def climbs(ctx: dict, ground_margin: int = 5, window: int = 90) -> pd.DataFrame:
    """One row per ground-to-ceiling ascent inside a single life."""
    top = common.ceiling(ctx)
    feet = []
    ordered = ctx['pos'].sort_values(['player_id', 'timestamp'])
    for player_id, group in ordered.groupby('player_id'):
        t = group.timestamp.to_numpy()
        y = group.y.to_numpy()
        surface = group.surface_y.to_numpy()
        x = group.x.to_numpy()
        z = group.z.to_numpy()
        team = group.team.iloc[0]
        died = np.array(ctx['deaths'].get(player_id, []))
        low = (~np.isnan(surface)) & (y - surface < ground_margin)
        i = 0
        while i < len(t):
            if not low[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(t) and t[j + 1] - t[i] <= window:
                j += 1
                if y[j] >= top:
                    if not (died.size and ((died > t[i]) & (died < t[j])).any()):
                        feet.append((team, int(x[i]), int(z[i]), int(t[i]), int(t[j] - t[i])))
                    break
                if low[j]:
                    i = j - 1
                    break
            i = max(i + 1, j)
    return pd.DataFrame(feet, columns=['team', 'x', 'z', 'timestamp', 'seconds'])


def entry_points(ctx: dict, climb_df: pd.DataFrame, cell: int = 4,
                 min_uses: int = 3) -> pd.DataFrame:
    if climb_df.empty:
        return climb_df
    grid = climb_df.assign(gx=(climb_df.x // cell * cell).astype(int),
                           gz=(climb_df.z // cell * cell).astype(int))
    out = grid.groupby(['gx', 'gz', 'team']).size().reset_index(name='n')
    return out[out.n >= min_uses].sort_values('n', ascending=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--map', required=True)
    parser.add_argument('--match', type=int, required=True)
    parser.add_argument('--cell', type=int, default=4)
    args = parser.parse_args()

    con = common.connect()
    ctx = common.load_match(con, args.map, args.match)
    if ctx is None:
        raise SystemExit('no terrain reference for that map')

    top = common.ceiling(ctx)
    sky = network(ctx, cell=args.cell)
    high = ctx['pos'][ctx['pos'].y >= top]
    print(f"{args.map} match {args.match}: ceiling y >= {top}")
    print(f"  ceiling samples {len(high):,}, of which over void or unsampled "
          f"{int(high.surface_y.isna().sum()):,}")
    print(f"  network cells {len(sky)}, of which wholly over void {int(sky.over_void.sum())}")

    climb_df = climbs(ctx)
    if climb_df.empty:
        print('  no climbs found')
        return
    distances = [common.distance_to_rect(r.x, r.z, ctx['spawns'][r.team])
                 if r.team in ctx['spawns'] else float('nan')
                 for r in climb_df.itertuples()]
    climb_df = climb_df.assign(spawn_distance=distances)
    entries = entry_points(ctx, climb_df, cell=args.cell)
    total = entries.n.sum()
    cumulative = entries.n.cumsum() / total
    print(f"  climbs {len(climb_df):,}, median {climb_df.seconds.median():.0f}s")
    print(f"  within 40 blocks of own spawn {100 * (climb_df.spawn_distance < 40).mean():.0f}%"
          f", median {climb_df.spawn_distance.median():.0f}")
    print(f"  entry cells {len(entries)}; half of all climbs at "
          f"{int((cumulative <= 0.5).sum()) + 1} of them")
    print('  busiest entries:')
    for r in entries.head(10).itertuples():
        spawn = ctx['spawns'].get(r.team)
        away = common.distance_to_rect(r.gx, r.gz, spawn) if spawn else float('nan')
        print(f"    ({r.gx:6d},{r.gz:6d}) {r.team:8s} {r.n:4d} climbs "
              f"{100 * r.n / total:4.1f}%   {away:5.0f} blocks from own spawn")

    # A climb time is only a stair time. Sprinting is ~5.6 blocks/s, so a 1:1
    # staircase to the ceiling is about 2*height/5.6 seconds; a 2:1 stair is
    # about 1.5*height/5.6. Nothing here implies a vertical mechanism.
    height = top - int(np.nanmedian(ctx['pos'].surface_y))
    print(f"  reference: sprinting a 1:1 stair {height} blocks up ~ {2 * height / 5.6:.0f}s, "
          f"a 2:1 stair ~ {1.5 * height / 5.6:.0f}s")


if __name__ == '__main__':
    main()
