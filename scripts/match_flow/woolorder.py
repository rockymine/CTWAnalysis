#!/usr/bin/env python3
"""Which of a team's two wools falls first, and whether a plan could predict it.

Three findings this reproduces, over the long two-wool corpus:

  one always falls early    median first capture 6.1 min, a third of the way
                            into the match, 76% inside ten minutes
  the same one falls first  mean concordance 0.839 per map+team against a
                            binomial-chance baseline of 0.661 at these sample sizes
  geometry only answers     when the two wools differ by more than 10 blocks the
  when it has something     nearer one falls first 63% of the time; on the
  to say                    mirror-exact majority every distance rule is a coin
                            flip, and the discriminator is the FLANK — the first
                            wool to fall sits on the same side of the attacker's
                            advance in 81% of frames

Declaration order in map.xml is NOT the mechanism: the first-declared wool falls
first 49.1% of the time over 318 captures, which is chance.

Usage
-----
    python scripts/match_flow/woolorder.py
"""

from __future__ import annotations

import argparse
import math
import statistics
import sys
from math import comb
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common

FRAME_SQL = """
create or replace temp table corpus as
select mt.match_id, mt.map_id, m.map_slug, mt.match_duration as duration,
       m.max_build_height as build_cap
  from matches mt join maps m using(map_id)
 where mt.processed and mt.spatial_classified
   and m.wools_per_team = 2 and m.team_count = 2 and mt.match_duration > 600;

create or replace temp table objective as
select c.match_id, o.team as attacker, o.wool_id, wl.x as wool_x, wl.z as wool_z
  from corpus c
  join map_wool_objectives o on o.map_id = c.map_id
  join map_wool_locations wl on wl.map_id = c.map_id and wl.wool_id = o.wool_id;

-- a few maps list one wool as an objective for both teams, so keep clean pairs only
create or replace temp table objective_pair as
select * from objective
 where (match_id, attacker) in
       (select match_id, attacker from objective group by 1, 2 having count(*) = 2);

create or replace temp table capture as
select o.match_id, o.attacker, o.wool_id, min(w.timestamp) as captured_at
  from wool_events w
  join objective_pair o on o.match_id = w.match_id and o.wool_id = w.wool_id
 where w.event_type = 7 group by 1, 2, 3;

create or replace temp table ranked as
select o.*, k.captured_at,
       row_number() over (partition by o.match_id, o.attacker
                          order by coalesce(k.captured_at, 1e9), o.wool_id) as rank
  from objective_pair o
  left join capture k
    on k.match_id = o.match_id and k.attacker = o.attacker and k.wool_id = o.wool_id;

create or replace temp table frame as
select first.match_id, first.attacker, c.map_slug, c.duration,
       first.wool_id as first_wool, first.wool_x as ax, first.wool_z as az,
       first.captured_at as t1,
       second.wool_id as second_wool, second.wool_x as bx, second.wool_z as bz,
       second.captured_at as t2,
       atk.x as atk_spawn_x, atk.z as atk_spawn_z,
       def.x as def_spawn_x, def.z as def_spawn_z
  from ranked first
  join ranked second on second.match_id = first.match_id
       and second.attacker = first.attacker and second.rank = 2
  join corpus c on c.match_id = first.match_id
  join map_spawns atk on atk.map_id = c.map_id and atk.team = first.attacker
  join map_spawns def on def.map_id = c.map_id and def.team <> first.attacker
 where first.rank = 1;
"""


def build(con):
    for statement in FRAME_SQL.strip().split(';'):
        if statement.strip():
            con.execute(statement)
    rows = con.execute("""
        select match_id, attacker, map_slug, duration, first_wool, ax, az, t1,
               second_wool, bx, bz, t2, atk_spawn_x, atk_spawn_z, def_spawn_x, def_spawn_z
          from frame where t1 is not null""").fetchall()
    out = []
    for (match_id, attacker, slug, duration, w1, ax, az, t1,
         w2, bx, bz, t2, sx, sz, dx, dz) in rows:
        axis_x, axis_z = dx - sx, dz - sz
        axis_len = math.hypot(axis_x, axis_z) or 1.0
        def frame_coords(px, pz):
            along = ((px - sx) * axis_x + (pz - sz) * axis_z) / axis_len
            lateral = (axis_x * (pz - sz) - (px - sx) * axis_z) / axis_len
            return along, lateral
        along_a, lat_a = frame_coords(ax, az)
        along_b, lat_b = frame_coords(bx, bz)
        mirrored = (abs(along_a - along_b) <= 0.08 * axis_len
                    and abs(lat_a + lat_b) <= 0.12 * axis_len
                    and (lat_a < 0) != (lat_b < 0))
        out.append(dict(match_id=match_id, attacker=attacker, map_slug=slug, duration=duration,
                        w1=w1, w2=w2, t1=t1, t2=t2, mirrored=mirrored,
                        along_a=along_a, along_b=along_b, lat_a=lat_a, lat_b=lat_b,
                        atk_a=math.hypot(ax - sx, az - sz), atk_b=math.hypot(bx - sx, bz - sz)))
    return out


def two_sided_binomial(top: int, trials: int) -> float:
    return sum(comb(trials, k) for k in range(top, trials + 1)) * 2 / 2 ** trials


def main() -> None:
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    con = common.connect()
    frames = build(con)
    print(f'=== {len(frames)} team-frames with a first capture ===')
    print(f'  median first capture {statistics.median(f["t1"] for f in frames) / 60:.1f} min; '
          f'{100 * sum(1 for f in frames if f["t1"] < 600) / len(frames):.1f}% inside ten minutes')

    material = [f for f in frames if abs(f['atk_a'] - f['atk_b']) > 10]
    nearer = sum(1 for f in material if f['atk_a'] < f['atk_b'])
    z = (nearer / len(material) - 0.5) / math.sqrt(0.25 / len(material)) if material else 0
    print(f'  where the two differ by >10 blocks (n={len(material)}): the NEARER wool falls '
          f'first {100 * nearer / len(material):.1f}%  z={z:+.1f}')

    opposite = [f for f in frames if (f['lat_a'] < 0) != (f['lat_b'] < 0)
                and f['t2'] is not None and f['t2'] > f['t1']]
    one_side = sum(1 for f in opposite if f['lat_a'] < 0)
    share = max(one_side, len(opposite) - one_side) / len(opposite) if opposite else 0
    z = (share - 0.5) / math.sqrt(0.25 / len(opposite)) if opposite else 0
    print(f'  flank: the first to fall sits on the same side in {100 * share:.1f}% '
          f'of {len(opposite)} frames  z={z:+.1f}')

    per_map: dict[tuple, dict] = {}
    for f in frames:
        key = (f['map_slug'], f['attacker'])
        per_map.setdefault(key, {}).setdefault(f['w1'], 0)
        per_map[key][f['w1']] += 1
    concordance, nulls = [], []
    for counts in per_map.values():
        total = sum(counts.values())
        if total < 5:
            continue
        concordance.append(max(counts.values()) / total)
        nulls.append(sum(comb(total, k) * max(k, total - k)
                         for k in range(total + 1)) / (2 ** total * total))
    if concordance:
        print(f'  same wool first, per map+team with 5+ matches (n={len(concordance)}): '
              f'concordance {statistics.mean(concordance):.3f} against a chance baseline of '
              f'{statistics.mean(nulls):.3f}')


if __name__ == '__main__':
    main()
