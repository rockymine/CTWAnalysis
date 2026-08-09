# Match-flow scripts

Scripts behind the match-flow audit: testing a written account of how a CTW map
is played against the recorded matches. They read the processed DuckDB database,
the raw pgmlogger parquet files, and (for `bedrock.py`) the map worlds directly.

Everything here is analysis, not pipeline. Nothing writes to the database.

## The corpus these were built on

Every processed, spatially-classified match on a two-team two-wool map running
longer than ten minutes: 333 matches on 94 maps, giving 615 team-frames with a
first capture. Where a script needs raw `held_item` or `inventory_count` it is
restricted further to the two-second-sampled matches.

## Two things worth knowing before trusting a number

**The terrain table covers land only.** Anything computed as *height above
ground* silently drops play over the void — on outback that is a third of all
ceiling-height activity and a quarter of the cells of its sky network, which
makes the network look disconnected when it is not. `common.load_match` keeps
rows without a terrain reference and leaves `rel` as NaN for them, so a caller
can choose. Use absolute `y` whenever the whole network matters.

**Capture events are the reliable source for who attacks what.**
`map_wool_objectives` lists a single wool as an objective for both teams on a
few maps, which silently drops one team from any "exactly two objectives per
team" filter. `common.attacking_team` reads the captures first and falls back to
the objectives table.

Two smaller ones: `materials.txt` is indexed by Bukkit `Material.ordinal()`, not
by block id — they coincide for blocks and diverge for items, so held_item 209
is `IRON_SWORD` and not `BUCKET`. And player-to-team lookups must not key on
`start_timestamp = 0`, which loses everyone who joined mid-match.

## The scripts

| Script | What it does |
|---|---|
| `common.py` | database, match loading, team lookup, wool-room rectangles, material decode |
| `structures.py` | finds the walls and staircases players build, from position traffic |
| `skynetwork.py` | the sky layer at the build ceiling, and where players climb onto it |
| `excavation.py` | the pit dug in front of the defensive line, from height below the original terrain |
| `bedrock.py` | bedrock walls standing in front of a wool room, read from the world files |
| `woolorder.py` | which of a team's two wools falls first, and whether geometry predicts it |
| `approaches.py` | approach-route variance: does an objective get reached more than one way |
| `voidmap.py` | enclosed voids, labelled with `BoardDeriver`'s own classes |
| `rotation.py` | whether a void is actually rotated around, or merely present |
| `firstcapture.py` | what decides the first capture: flank, reception, population, ground |
| `backfill_bedrock_ceiling.py` | one-off: fill `bedrock_ceiling_y` from the bedrock parquets |
| `render_map.py` | top-down SVG of one match: structures, or the sky network |
| `render_design.py` | top-down SVG of a map: build regions, classified voids, every successful approach |
| `anvil18.py` | minimal Minecraft 1.8 region reader, used by `bedrock.py` |

## How wall and staircase are told apart

A staircase is a narrow run whose height climbs linearly along its own long
axis. A wall is an elevated run lying along a wool-room face, level along its
length. Geometry alone does not separate them — on sanctum_wasser both
room-adjacent runs lie 2° off a room face and span 63% of it. What separates
them is **where the height gradient lives**: fit height against position along
*both* axes and compare. A staircase gives a ratio of 3 to 38; a wall gives
about 1.

Ownership is the independent check, since nothing in the geometry knows which
team defends which room. Across the fourteen longest two-second matches the
classification finds 8 walls, defender-held in 6 of them at a median 92% of
samples, and 5 spawn staircases, walked by their own team in 4 of 5.

Clustering cells by ramp height works on some maps and fails on others where
mid-height traffic is widespread enough to fuse into one field; `structures.py`
fits a plane to the local height field instead, which is why it finds runs on
maps the simpler approach reports nothing for.

## Routes offered against routes taken

Only lives that touched a wool at its spawner say anything about which route
works, so `approaches.py` starts there. Resampling each approach by arc length
and looking for the widest gap in the bundle finds where a route forks, and
*where* the fork sits is the distinction that matters: inside 45 blocks it is a
second way in to the objective, beyond that a choice of lane made far from the
room. Over 490 bundles on 150 maps, 9% have the first, 35% the second, and **63%
are a single corridor end to end**.

A fixed gap threshold is blind to maps whose voids are narrower than it, which
is why `rotation.py` exists. Rather than measuring separation in blocks it takes
the sign of each approach's offset from the spawn-to-wool axis, so a six-block
void and a sixty-block one are read the same way. That correction matters: the
gap test calls `townside_mini` a single corridor, and the side test finds its
ring rotated around in 23 of 59 approaches at one end.

`voidmap.py` supplies the things routes fork around, labelled in the same
vocabulary the generator uses. Class does not predict use on its own — pooled
over four maps, encased voids see 22.7% rotation, gap 13.6%, frontline 11.9% and
middle 10.8%, with more spread inside each class than between them. The clearest
case is one class split down the middle: outback's corner gaps are rotated
around in 5 of 97 approaches, sanctum_wasser's in 22 of 101.

## Measuring excavation

Three things have to be right or the pit measure inverts itself, and the method
here follows `wool_excavation_plot.py` rather than inventing one.

A position counts toward a cell's floor only if it sits **below that cell's own
surface**. Without that filter the measure picks up where people stood on the
ground and reads its one-block wobble as digging — 91% of outback's cells report
as dug, against 17% with the filter. A cell is being dug only if its floor
**varies between matches**; a floor identical every time is static map geometry,
a room interior or a ravine, however deep it sits. And depth is counted per cell,
not per sample, so it is not weighted by how much players milled about in the
hole. Neither gate is a sample threshold; there is none.

Depth also has to be normalised. Raw depth rises with distance from the objective
purely because bedrock sits deeper out there; completeness — depth over the
surface-to-bedrock-ceiling column — peaks at 10–19 blocks from the room face and
falls away, which is the opposite conclusion. `bedrock_ceiling_y` is what makes
that possible and was populated on two maps until
`backfill_bedrock_ceiling.py` filled all 177 from the bedrock parquets. Note that
`match_analysis/database/terrain_height.py` had stopped writing the column
entirely, and its loader deletes a map's rows before reinserting — so running
`ctw maps terrain-height` against the old code silently dropped it.

One more denominator trap, in `firstcapture.py --ground`: completeness around a
room must be averaged over **every** diggable cell near it, with untouched cells
scoring zero. Averaging only over cells already dug scores a three-minute capture
on whichever few cells someone dug deeply, and reverses the finding.

## Running them

```bash
python scripts/match_flow/structures.py --map sanctum_wasser --match 2174
python scripts/match_flow/structures.py --sweep --min-minutes 45
python scripts/match_flow/skynetwork.py --map outback_outback_edition --match 1862
python scripts/match_flow/excavation.py --map kanto
python scripts/match_flow/woolorder.py
python scripts/match_flow/render_map.py --map sanctum_wasser --match 2174 --mode structures
python scripts/match_flow/bedrock.py --cache     # slow, once
python scripts/match_flow/bedrock.py --lines
python scripts/match_flow/approaches.py --map kanto
python scripts/match_flow/approaches.py --sweep
python scripts/match_flow/voidmap.py --map outback_outback_edition
python scripts/match_flow/rotation.py --map townside_mini
python scripts/match_flow/render_design.py --map sanctum_wasser
python scripts/match_flow/firstcapture.py --flank --reception --population
python scripts/match_flow/firstcapture.py --ground
```

Paths to the parquet corpus and the map worlds come from `CTW_MATCH_LOGS` and
`CTW_MAP_WORLDS`; the defaults point at the sibling checkouts.
