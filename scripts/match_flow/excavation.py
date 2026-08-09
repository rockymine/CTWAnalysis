#!/usr/bin/env python3
"""The pit: where defenders dig the ground away in front of the wall they build.

No block log is needed. Join every ground position to the map's ORIGINAL terrain
height and ask how far below it the player is standing; a band where a large
share of samples sit three or more blocks under the shipped terrain is the
excavation in front of the defensive line.

Measured from the wool-room face rather than the wool block, because the wool
sits a median nine blocks behind its own room mouth.

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

PHASE2_FRAME = """
with objectives as (
  select mt.match_id, m.map_id, m.map_slug, mt.match_duration, m.max_build_height,
         o.team as attacker, o.wool_id, wl.x as wool_x, wl.z as wool_z
    from matches mt
    join maps m using(map_id)
    join map_wool_objectives o on o.map_id = m.map_id
    join map_wool_locations wl on wl.map_id = m.map_id and wl.wool_id = o.wool_id
   where mt.processed and mt.spatial_classified
     and m.wools_per_team = 2 and m.team_count = 2 and mt.match_duration > 600
)
select * from objectives
"""


def profile(con, map_slug: str | None = None, min_samples: int = 300) -> dict[int, tuple[int, float]]:
    """Distance band from the room face -> (samples, share dug 3+ blocks under)."""
    rooms = common.load_wool_rooms()
    where = "and m.map_slug = ?" if map_slug else ""
    params = [map_slug] if map_slug else []
    rows = con.execute(f"""
        select m.map_slug, o.wool_id, p.x, p.z, p.y, th.surface_y
          from matches mt
          join maps m using(map_id)
          join map_wool_objectives o on o.map_id = m.map_id
          join position_events p on p.match_id = mt.match_id
          join map_terrain_height th
            on th.map_id = m.map_id and th.world_x = p.x and th.world_z = p.z
         where mt.processed and mt.spatial_classified
           and m.wools_per_team = 2 and m.team_count = 2 and mt.match_duration > 600
           and p.y < coalesce(m.max_build_height, 99) - 6 {where}
    """, params).fetchall()

    bands: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for slug, wool_id, x, z, y, surface in rows:
        rect = rooms.get((slug, wool_id))
        if rect is None:
            continue
        band = int(common.distance_to_rect(x, z, rect) // 5 * 5)
        if band > 90:
            continue
        bands[band][0] += 1
        if y - surface <= -3:
            bands[band][1] += 1
    return {band: (n, 100.0 * dug / n) for band, (n, dug) in bands.items() if n >= min_samples}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--map')
    parser.add_argument('--corpus', action='store_true')
    args = parser.parse_args()
    con = common.connect()

    result = profile(con, None if args.corpus else args.map)
    if not result:
        raise SystemExit('no samples with a terrain reference')
    label = 'corpus' if args.corpus else args.map
    print(f'=== excavation in front of the wool-room face — {label} ===')
    print('    band        samples   dug 3+ blocks under the original surface')
    for band in sorted(result):
        n, pct = result[band]
        print(f'    {band:3d}-{band + 4:3d}  {n:9,d}   {pct:5.1f}%  {"#" * int(pct / 2)}')
    peak = max(result, key=lambda b: result[b][1])
    baseline = statistics.median(p for _, p in result.values())
    print(f'    peak at {peak}-{peak + 4} blocks ({result[peak][1]:.1f}%), '
          f'baseline {baseline:.1f}%')


if __name__ == '__main__':
    main()
