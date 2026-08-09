#!/usr/bin/env python3
"""The pit: where defenders dig the ground away in front of the wall they build.

Method taken from `wool_excavation_plot.py`, which gets two things right that a
naive height-below-surface test does not.

**Only sub-surface positions count.** The floor of a cell is the lowest place a
player stood *below* that cell's own surface — `pe.y - (surface_y + 1) < 0`.
Feeding in every sample instead measures where people stood on the ground and
turns its one-block wobble into fake excavation: on outback that reports 91% of
cells as dug, against 17% when the filter is applied.

**A cell is only being dug if its floor VARIES between matches.** `floor_range =
MAX(match_floor_y) - MIN(match_floor_y)` over matches. A cell whose floor is
identical every time is static map geometry — a room interior, a ravine, a
building — no matter how far below the surface it sits.

Neither gate is a sample count; there is no minimum-observations threshold.

Depth is per cell, not per sample, so the result is not weighted by how much
players moved around in the hole.

Where `bedrock_ceiling_y` is populated, completeness normalises depth against it
so that cells over high and low bedrock compare — but only two maps in the corpus
have that column filled, so the raw depth is what is usually available.

Usage
-----
    python scripts/match_flow/excavation.py --map kanto
    python scripts/match_flow/excavation.py --corpus
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common

CELL_SQL = """
with per_match_cell as (
  select th.world_x, th.world_z, th.surface_y, th.bedrock_ceiling_y,
         pe.match_id, min(pe.y) as match_floor_y
    from position_events pe
    join matches mat on mat.match_id = pe.match_id
    join map_terrain_height th
      on th.map_id = mat.map_id
     and th.world_x = cast(pe.x as int)
     and th.world_z = cast(pe.z as int)
   where mat.map_id = ?
     and mat.spatial_classified
     and pe.y >= 1
     and (pe.y - (th.surface_y + 1)) < 0
   group by 1, 2, 3, 4, 5)
select world_x, world_z, surface_y,
       any_value(bedrock_ceiling_y)            as bedrock_ceiling_y,
       min(match_floor_y)                      as floor_y,
       surface_y - min(match_floor_y)          as excavation_depth,
       count(distinct match_id)                as match_count,
       max(match_floor_y) - min(match_floor_y) as floor_range
  from per_match_cell
 group by 1, 2, 3
"""


def cells(con, map_id: int) -> list[tuple]:
    return con.execute(CELL_SQL, [map_id]).fetchall()


def profile(con, map_slug: str, min_floor_range: int = 1) -> dict | None:
    """Excavation depth by distance from the nearest wool-room face, active cells only."""
    row = con.execute('select map_id from maps where map_slug = ?', [map_slug]).fetchone()
    if row is None:
        return None
    map_id = row[0]
    rooms = [rect for (slug, _wool), rect in common.load_wool_rooms().items() if slug == map_slug]
    if not rooms:
        return None
    rows = cells(con, map_id)
    if not rows:
        return None
    static = sum(1 for r in rows if r[7] == 0)
    bands: dict[int, list] = defaultdict(list)
    for x, z, surface_y, ceiling, floor_y, depth, matches, floor_range in rows:
        if floor_range < min_floor_range:
            continue
        distance = min(common.distance_to_rect(x, z, rect) for rect in rooms)
        if distance > 90:
            continue
        completeness = None
        if ceiling is not None and surface_y > ceiling:
            completeness = min(max((surface_y - floor_y) / (surface_y - ceiling), 0.0), 1.0)
        bands[int(distance // 5 * 5)].append((depth, completeness))
    return dict(map=map_slug, cells=len(rows), static=static, active=len(rows) - static, bands=bands)


def show(result: dict) -> None:
    print(f"=== {result['map']}: {result['cells']} cells with a sub-surface position — "
          f"{result['static']} static, {result['active']} active "
          f"({100 * result['active'] / max(result['cells'], 1):.0f}%)")
    print('    from the room face   active cells   median depth   share dug 5+ blocks')
    for band in sorted(result['bands']):
        values = result['bands'][band]
        if len(values) < 15:
            continue
        depths = [d for d, _ in values]
        deep = sum(1 for d in depths if d >= 5) / len(depths)
        print(f'    {band:3d}-{band + 4:3d} blocks  {len(values):8d}      '
              f'{statistics.median(depths):6.1f}        {100 * deep:5.1f}%  '
              f'{"#" * int(deep * 40)}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--map')
    parser.add_argument('--corpus', action='store_true')
    parser.add_argument('--min-floor-range', type=int, default=1)
    args = parser.parse_args()
    con = common.connect()

    if args.map:
        result = profile(con, args.map, args.min_floor_range)
        if result is None:
            raise SystemExit('no terrain rows or no wool rooms for that map')
        show(result)
        return
    if not args.corpus:
        parser.error('give --map or --corpus')

    slugs = [r[0] for r in con.execute("""
        select distinct m.map_slug
          from maps m join matches mt using(map_id)
         where mt.spatial_classified
           and m.map_id in (select distinct map_id from map_terrain_height)
           and m.wools_per_team = 2 and m.team_count = 2
         order by 1""").fetchall()]
    pooled: dict[int, list] = defaultdict(list)
    static = active = 0
    done = 0
    for slug in slugs:
        result = profile(con, slug, args.min_floor_range)
        if result is None:
            continue
        done += 1
        static += result['static']
        active += result['active']
        for band, values in result['bands'].items():
            pooled[band] += values
        if done % 20 == 0:
            print(f'  ...{done}/{len(slugs)}', flush=True)
    print(f"\n=== corpus: {done} maps — {static + active} cells with a sub-surface position, "
          f"{active} active ({100 * active / max(static + active, 1):.0f}%) ===")
    print('    from the room face   active cells   median depth   share dug 5+ blocks')
    for band in sorted(pooled):
        values = pooled[band]
        if len(values) < 200:
            continue
        depths = [d for d, _ in values]
        deep = sum(1 for d in depths if d >= 5) / len(depths)
        print(f'    {band:3d}-{band + 4:3d} blocks  {len(values):8d}      '
              f'{statistics.median(depths):6.1f}        {100 * deep:5.1f}%  '
              f'{"#" * int(deep * 40)}')


if __name__ == '__main__':
    main()
