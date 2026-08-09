#!/usr/bin/env python3
"""What decides the first capture.

Four things, and they are not four independent causes.

Two are **conditions** of the opening window. The ground is unexcavated — median
completeness around a room is 0.010 when its wool falls inside five minutes,
against 0.336 past forty, and late captures land on more-dug ground on 42 of 43
maps. And the board is sometimes thinly populated: a match starts at a median 72%
of the players it will eventually hold and climbs from 26 to 44 over an hour, and
with under ten present the first wool falls at a median 1.77 minutes against 3.67
with twenty or more.

One is the **mechanism**. Both teams take the same hand in their own frame on
67.8% of matches, which on a mirrored or rotated board means opposite physical
flanks. It buys no reduction in collisions — deaths in the middle third before
the first capture are a median zero either way — but a thinner reception, and a
capture 0.79 minutes sooner.

The fourth, that thin reception, is the mechanism's effect rather than a separate
reason: 34.9% of the players near the falling wool are defenders when the flanks
are opposite against 43.1% when they are shared.

Modes
-----
    --flank        the side each team attacks, and whether both pick the same hand
    --reception    who is standing at the wool in the ninety seconds before it falls
    --population   the fill curve, and what it does to capture time
    --ground       excavation around a room at the moment its wool is taken

Usage
-----
    python scripts/match_flow/firstcapture.py --flank --reception
    python scripts/match_flow/firstcapture.py --ground
"""

from __future__ import annotations

import argparse
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

import common

CORPUS = """
create or replace temp table corpus as
select mt.match_id, m.map_id, m.map_slug, m.symmetry_type,
       mt.match_duration as dur, mt.player_count
  from matches mt join maps m using(map_id)
 where mt.processed and mt.spatial_classified
   and m.wools_per_team = 2 and m.team_count = 2
"""


def _frame(con):
    """Per (match, team): the median lateral offset of its attacking travel before
    the first capture, in that team's own spawn -> enemy-spawn frame."""
    con.execute(CORPUS)
    spawns = defaultdict(dict)
    for map_id, team, x, z in con.execute("""select map_id, team, x, z from map_spawns
      where map_id in (select map_id from corpus)""").fetchall():
        spawns[map_id][team] = (x, z)
    first = dict(con.execute("""select w.match_id, min(w.timestamp) from wool_events w
      join corpus using(match_id) where w.event_type = 7 group by 1""").fetchall())
    map_of = dict(con.execute('select match_id, map_id from corpus').fetchall())

    lateral = defaultdict(list)
    for match_id, team, x, z, timestamp in con.execute("""
      select p.match_id, ts.team, p.x, p.z, p.timestamp
        from position_events p join corpus using(match_id)
        join player_team_segments ts on ts.match_id = p.match_id and ts.player_id = p.player_id
         and p.timestamp >= ts.start_timestamp
         and p.timestamp <= coalesce(ts.end_timestamp, 2147483647)
       where p.timestamp <= 900""").fetchall():
        t1 = first.get(match_id)
        if t1 is None or timestamp > t1:
            continue
        sp = spawns.get(map_of[match_id], {})
        if team not in sp or len(sp) != 2:
            continue
        sx, sz = sp[team]
        ex, ez = next(v for k, v in sp.items() if k != team)
        ax, az = ex - sx, ez - sz
        length = math.hypot(ax, az) or 1.0
        ax, az = ax / length, az / length
        along = (x - sx) * ax + (z - sz) * az
        # only the attack: inside the enemy half, short of their spawn
        if along < 0.55 * length or along > 0.95 * length:
            continue
        lateral[(match_id, team)].append((x - sx) * (-az) + (z - sz) * ax)

    sides = defaultdict(dict)
    for (match_id, team), values in lateral.items():
        if len(values) >= 15:
            sides[match_id][team] = float(np.median(values))
    return {m: v for m, v in sides.items() if len(v) == 2}, first, spawns, map_of


def flank(con) -> None:
    both, first, _spawns, _map_of = _frame(con)
    symmetry = dict(con.execute('select match_id, symmetry_type from corpus').fetchall())
    same = sum(1 for v in both.values() if len({x >= 0 for x in v.values()}) == 1)
    print(f'=== flank: {len(both)} matches with both attacks measured ===')
    print(f'  both teams on the same hand in their own frame: {same} ({100 * same / len(both):.1f}%)')
    agg = defaultdict(lambda: [0, 0])
    for match_id, v in both.items():
        key = symmetry.get(match_id) or 'unknown'
        agg[key][0] += 1
        if len({x >= 0 for x in v.values()}) == 1:
            agg[key][1] += 1
    for key, (n, k) in sorted(agg.items(), key=lambda t: -t[1][0]):
        print(f'    {key:12s} {k:4d} of {n:4d}  ({100 * k / n:5.1f}%)')


def reception(con) -> None:
    both, first, spawns, map_of = _frame(con)
    wools = defaultdict(dict)
    for map_id, wool_id, x, z in con.execute("""select map_id, wool_id, x, z
      from map_wool_locations where map_id in (select map_id from corpus)""").fetchall():
        wools[map_id][wool_id] = (x, z)
    attacker = {}
    for map_id, wool_id, team in con.execute("""select map_id, wool_id, team
      from map_wool_objectives where map_id in (select map_id from corpus)""").fetchall():
        attacker[(map_id, wool_id)] = team
    fallen = {}
    for match_id, wool_id, timestamp in con.execute("""select w.match_id, w.wool_id, min(w.timestamp)
      from wool_events w join corpus using(match_id) where w.event_type = 7
      group by 1, 2""").fetchall():
        if match_id not in fallen or timestamp < fallen[match_id][1]:
            fallen[match_id] = (wool_id, timestamp)

    near = defaultdict(lambda: [0, 0])
    for match_id, team, x, z, timestamp in con.execute("""
      select p.match_id, ts.team, p.x, p.z, p.timestamp
        from position_events p join corpus using(match_id)
        join player_team_segments ts on ts.match_id = p.match_id and ts.player_id = p.player_id
         and p.timestamp >= ts.start_timestamp
         and p.timestamp <= coalesce(ts.end_timestamp, 2147483647)
       where p.timestamp <= 900""").fetchall():
        entry = fallen.get(match_id)
        if entry is None or match_id not in both:
            continue
        wool_id, t1 = entry
        if not (t1 - 90 <= timestamp <= t1):
            continue
        wool = wools.get(map_of[match_id], {}).get(wool_id)
        if wool is None or math.hypot(x - wool[0], z - wool[1]) > 40:
            continue
        atk = attacker.get((map_of[match_id], wool_id))
        near[match_id][0 if team == atk else 1] += 1

    rows = []
    for match_id, v in both.items():
        a, d = near.get(match_id, [0, 0])
        if a + d < 10:
            continue
        rows.append((len({x >= 0 for x in v.values()}) == 1, d / (a + d)))
    print(f'=== reception: {len(rows)} matches with 10+ samples at the falling wool ===')
    for label, want in (('opposite flanks (same hand)', True), ('shared flank', False)):
        sel = [share for same, share in rows if same is want]
        if sel:
            print(f'  {label:28s} n={len(sel):4d}   defenders are '
                  f'{100 * statistics.median(sel):5.1f}% of the players there')


def population(con) -> None:
    con.execute(CORPUS)
    rows = con.execute("""select p.match_id, cast(p.timestamp / 60 as int) as minute,
             count(distinct p.player_id)
        from position_events p join corpus using(match_id) group by 1, 2""").fetchall()
    curve = defaultdict(dict)
    for match_id, minute, players in rows:
        curve[match_id][minute] = players
    dur = dict(con.execute('select match_id, dur from corpus').fetchall())
    long = [m for m in curve if dur.get(m, 0) > 1200]
    print(f'=== population: {len(long)} matches past twenty minutes ===')
    for minute in (0, 10, 20, 30, 45, 60):
        vals = [curve[m][minute] for m in long if minute in curve[m]]
        if len(vals) >= 10:
            print(f'  minute {minute:3d}  median {statistics.median(vals):5.1f} present  (n={len(vals)})')
    ratios = [max((curve[m].get(k, 0) for k in (0, 1, 2)), default=0) / max(curve[m].values())
              for m in long if max(curve[m].values()) >= 8]
    if ratios:
        print(f'  median share of the peak present in the first three minutes: '
              f'{statistics.median(ratios):.2f}')
    first = dict(con.execute("""select w.match_id, min(w.timestamp) from wool_events w
      join corpus using(match_id) where w.event_type = 7 group by 1""").fetchall())
    buckets = defaultdict(list)
    for match_id, c in curve.items():
        t1 = first.get(match_id)
        early = max((c.get(k, 0) for k in (0, 1, 2)), default=0)
        if t1 is None or t1 < 30 or early < 2:
            continue
        key = 'under 10' if early < 10 else ('10-19' if early < 20 else '20 or more')
        buckets[key].append(t1 / 60)
    print('  first capture by how many were present in the first three minutes:')
    for key in ('under 10', '10-19', '20 or more'):
        if key in buckets:
            print(f'    {key:12s} n={len(buckets[key]):4d}   median {statistics.median(buckets[key]):5.2f} min')


def ground(con) -> None:
    """Excavation around a room at the moment its wool falls.

    The denominator is every diggable cell within 25 blocks, with untouched cells
    scoring zero. Averaging only over cells already dug scores a three-minute
    capture on whichever few cells someone dug deeply, and inverts the result.
    """
    con.execute(CORPUS)
    con.execute("""create or replace temp table diggable as
        select c.map_slug, th.world_x, th.world_z, th.surface_y, th.bedrock_ceiling_y
          from (select distinct map_slug, map_id from corpus) c
          join map_terrain_height th on th.map_id = c.map_id
         where th.bedrock_ceiling_y is not null and th.surface_y > th.bedrock_ceiling_y""")
    rooms_all = common.load_wool_rooms()
    terrain = defaultdict(dict)
    for slug, x, z, surface_y, ceiling in con.execute('select * from diggable').fetchall():
        terrain[slug][(x, z)] = (surface_y, ceiling)
    near = defaultdict(list)
    for (slug, wool_id), rect in rooms_all.items():
        for (x, z), (surface_y, ceiling) in terrain.get(slug, {}).items():
            if common.distance_to_rect(x, z, rect) <= 25:
                near[(slug, wool_id)].append((x, z, surface_y, ceiling))

    floors = defaultdict(dict)
    for match_id, x, z, floor_y, first_ts in con.execute("""
      select pe.match_id, th.world_x, th.world_z, min(pe.y), min(pe.timestamp)
        from position_events pe join corpus c on c.match_id = pe.match_id
        join map_terrain_height th on th.map_id = c.map_id
         and th.world_x = cast(pe.x as int) and th.world_z = cast(pe.z as int)
       where pe.y >= 1 and (pe.y - (th.surface_y + 1)) < 0
         and th.bedrock_ceiling_y is not null
       group by 1, 2, 3""").fetchall():
        floors[match_id][(x, z)] = (floor_y, first_ts)

    slug_of = dict(con.execute('select match_id, map_slug from corpus').fetchall())
    out = []
    for match_id, wool_id, t_cap in con.execute("""select w.match_id, w.wool_id, min(w.timestamp)
      from wool_events w join corpus using(match_id) where w.event_type = 7
      group by 1, 2""").fetchall():
        cells = near.get((slug_of.get(match_id), wool_id))
        if not cells or len(cells) < 40:
            continue
        dug = floors.get(match_id, {})
        values = []
        for x, z, surface_y, ceiling in cells:
            entry = dug.get((x, z))
            if entry is None or entry[1] > t_cap:
                values.append(0.0)
            else:
                values.append(min(max((surface_y - entry[0]) / (surface_y - ceiling), 0.0), 1.0))
        out.append((slug_of[match_id], t_cap, sum(values) / len(values)))

    print(f'=== ground: {len(out)} captures on {len({s for s, _, _ in out})} maps ===')
    print('  when the wool fell    captures   completeness of the ground around it')
    for lo, hi, label in ((0, 300, 'inside 5 min'), (300, 600, '5-10 min'),
                          (600, 1200, '10-20 min'), (1200, 2400, '20-40 min'),
                          (2400, 10 ** 9, 'past 40 min')):
        sel = [c for _, t, c in out if lo <= t < hi]
        if len(sel) >= 5:
            print(f'   {label:18s} {len(sel):6d}      {statistics.median(sel):5.3f}')
    per_map = defaultdict(lambda: {'early': [], 'late': []})
    for slug, t, c in out:
        per_map[slug]['early' if t <= 600 else 'late'].append(c)
    both = {k: v for k, v in per_map.items() if len(v['early']) >= 3 and len(v['late']) >= 3}
    diffs = [statistics.median(v['late']) - statistics.median(v['early']) for v in both.values()]
    if diffs:
        print(f'  late captures on more-dug ground in '
              f'{sum(1 for d in diffs if d > 0)}/{len(diffs)} maps')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--flank', action='store_true')
    parser.add_argument('--reception', action='store_true')
    parser.add_argument('--population', action='store_true')
    parser.add_argument('--ground', action='store_true')
    args = parser.parse_args()
    if not any((args.flank, args.reception, args.population, args.ground)):
        parser.error('give at least one of --flank --reception --population --ground')
    con = common.connect()
    for wanted, fn in ((args.flank, flank), (args.reception, reception),
                       (args.population, population), (args.ground, ground)):
        if wanted:
            fn(con)
            print()


if __name__ == '__main__':
    main()
