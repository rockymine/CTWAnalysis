#!/usr/bin/env python3
"""Backfill bedrock_ceiling_y in place, without touching any existing terrain row.

Run once. Writes to the database.


The loader path needs island_id from a clustering parquet that several maps no
longer carry, and re-running `ctw run` to regenerate it would rewrite outputs
other analyses depend on. bedrock_ceiling_y needs none of that — it is a pure
per-column value from layout_bedrock.parquet, so it can be joined onto the rows
that already exist.
"""
import duckdb, pandas as pd
from pathlib import Path

from pathlib import Path as _P
DB = str(_P(__file__).resolve().parent.parent.parent / 'match_analysis' / 'metadata.db')
con = duckdb.connect(DB)
con.execute("ALTER TABLE map_terrain_height ADD COLUMN IF NOT EXISTS bedrock_ceiling_y INTEGER")

maps = con.execute("""select m.map_id, m.map_slug, count(th.world_x)
    from maps m join map_terrain_height th using(map_id) group by 1,2 order by 2""").fetchall()
print(f'maps with terrain rows: {len(maps)}')
filled = skipped = 0
for map_id, slug, n in maps:
    path = _P(DB).parent.parent / 'output' / slug / 'layout_bedrock.parquet'
    if not path.exists():
        skipped += 1
        continue
    df = pd.read_parquet(path)
    if 'height' not in df.columns:
        skipped += 1
        continue
    ceiling = (df[['world_x', 'world_z', 'y', 'height']]
               .assign(bedrock_ceiling_y=lambda d: d['y'] + d['height'] - 1)
               [['world_x', 'world_z', 'bedrock_ceiling_y']])
    con.register('ceiling_df', ceiling)
    con.execute("""update map_terrain_height th
                      set bedrock_ceiling_y = c.bedrock_ceiling_y
                     from ceiling_df c
                    where th.map_id = ?
                      and th.world_x = c.world_x
                      and th.world_z = c.world_z""", [map_id])
    con.unregister('ceiling_df')
    filled += 1
con.commit()
done = con.execute("""select count(distinct map_id) from map_terrain_height
                       where bedrock_ceiling_y is not null""").fetchone()[0]
rows = con.execute("""select count(*) from map_terrain_height
                       where bedrock_ceiling_y is not null""").fetchone()[0]
print(f'  parquet found and joined for {filled} maps, {skipped} skipped')
print(f'  bedrock_ceiling_y now populated on {done} maps, {rows:,} cells')
for slug in ('outback_outback_edition', 'kanto', 'sanctum_wasser', 'arabia'):
    r = con.execute("""select count(*), count(bedrock_ceiling_y),
                              median(surface_y - bedrock_ceiling_y)
                         from map_terrain_height th join maps m using(map_id)
                        where m.map_slug = ?""", [slug]).fetchone()
    print(f'   {slug:26s} cells {r[0]:6d}  with ceiling {r[1]:6d}  median diggable depth {r[2]}')
con.close()
