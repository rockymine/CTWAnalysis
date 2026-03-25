# Chest Spatial Analysis

*Generated 2026-03-25 | Dataset: ~202 non-stub maps with defense chests; 15 maps with no defense chests*

---

## Executive Summary

Chest content categories align remarkably well with spatial zones: defense-zone chests are 98.8% defense items, spawn chests are 78% defense + 19% weapon (functioning as resupply stations), and wool-room chests show the richest mix — combat, wool, supply, and weapon all represented. A small number of maps completely dominate the item-count extremes: nextgen and blocks_ctw each have 288 defense chests stocked with ~500K items each, compared to a typical map with 8–32 chests holding a few thousand items. Fifteen maps have no defense chests at all, most of which are small pico/nano maps with simple layouts that likely rely on a single shared chest pool or none at all.

---

## Zone × Content Category Alignment

![Chest content category by spatial zone heatmap](figures/chest_zone_heatmap.png)

The heatmap shows how tightly content categories track spatial zones across the full dataset.

**Strong alignments:**

- **Defense zone → defense (98.8%)** — The classification pipeline is highly consistent here. The 1.2% weapon contribution (4 chests) is plausibly bows or swords stocked alongside building blocks, which the category model rounds into "weapon".
- **Wool room → combat (42.9%)** — Wool rooms are not just about wool retrieval; they are heavily contested and designers stock them accordingly. Combat items (swords, bows, potions) make up nearly half the chest content. Wool (21.7%), supply (15.8%), and weapon (13.2%) round out what is functionally an arena preparation zone.
- **Spawn → defense (77.9%) + weapon (18.7%)** — Spawn chests are resupply hubs. Players respawn and immediately restock on blocks and gear. The high weapon proportion (mostly swords/bows) makes sense as spawn is also where players tool up before pushing out.

**Surprises and nuances:**

- **Near-spawn → wool (15.4%)** — Fifteen percent of near-spawn chests contain wool items. This suggests some maps place mid-field wool collection near spawn rather than exclusively inside dedicated wool rooms, or that near-spawn and wool-room zones partially overlap on certain map geometries.
- **Spawn → weapon (18.7%)** — Higher than expected. This reflects maps that place a weapon chest at spawn rather than in the field, giving every respawner immediate combat gear.
- **Field → defense (57.1%)** — Over half of field chests are still classified as defense. This is not surprising on maps where defense materials are distributed across the whole layout rather than concentrated in a single room, but it means field chests are often not neutral resupply; they bias toward building blocks.
- **Field → wool (4.8%)** — A small but nonzero wool fraction in field chests implies some maps scatter wool pickups across the map rather than consolidating them.

---

## Defense Chest Distribution

![Defense chests vs. map size scatter plot](figures/defense_chests_vs_size.png)

There is a broadly positive relationship between map size (total blocks) and defense chest count, as expected — larger maps need more distributed resupply points. However, the log-log trend line hides enormous variance; map design philosophy dominates over raw size.

**Outliers above the trend (many chests relative to their size):**

- **nyxis** (micro, 21,881 blocks) leads in raw chest count at **326 chests** with only 40K items total — meaning each chest is small (averaging ~123 items). This is consistent with a map design that places many single-purpose or partially stocked chests throughout the layout rather than a few dense ones. With only 1 wool per team the defense is undivided.
- **nextgen** and **blocks_ctw** both hit **288 chests** but carry ~500K items each — massive stocked chests. nextgen is a milli map (9,000 blocks), unusually small for that item count, suggesting the defense chests are extremely dense in a compact area. blocks_ctw is a centi map (33K blocks) with a similarly extreme density.
- **madness_on_rails** (centi, 168 chests) and **fall_of_babylon** (centi, 164 chests) represent the high end of conventional large-map defense stocking.

**Outliers below the trend (few chests for their size):**

- **harbor_ctw** (centi, 46K blocks — one of the largest maps) has only 32 defense chests with 14K items. This map's size comes from a large open layout where combat happens at range rather than in defensible chokepoints, reducing the need for distributed resupply.
- **frost** (centi, 40K blocks) similarly has only 16 defense chests. Large maps do not automatically mean many defense chests.
- **ad_infinitum** (milli, 33K blocks, 108 chests) is an interesting case: many chests but very few items per chest (total 6,364 items = ~59 items each). This map distributes access without stocking heavily.

---

## Defense Intensity per Wool

![Defense items per wool vs. team size scatter plot](figures/defense_density_per_wool.png)

Normalising by wools per team reveals how much material is provisioned per objective — a proxy for how hard each wool is intended to be defended.

**Extreme outliers:**

| Map | Wools/team | Defense Items | Items/wool | Team size |
|-----|-----------|--------------|-----------|-----------|
| nextgen | 2 | 497,664 | 248,832 | 24 |
| blocks_ctw | 2 | 479,232 | 239,616 | 32 |
| madness_on_rails | 2 | 282,240 | 141,120 | 36 |
| race_for_victory_3 | 3 | 276,480 | 92,160 | 35 |
| split_strata | 2 | 172,596 | 86,298 | 24 |
| nextrace | 1 | 86,272 | 86,272 | 12 |
| exitium | 2 | 166,824 | 83,412 | 24 |
| gridlock_2 | 2 | 165,888 | 82,944 | 28 |

nextgen and blocks_ctw sit roughly 3–4× above the next cluster. These are maps where the wool room is a fundamentally different kind of obstacle — less "raid the chest, build a wall" and more "the chest IS the wall" (literal glass/piston/redstone mechanics).

**The bulk of the dataset** (maps with 2–4K items per wool) clusters in the lower-left: small teams, few items per wool, conventional defence stocking. The pattern suggests per-wool intensity scales weakly with team size — 35-player centi maps and 8-player nano maps can both have low item-per-wool counts. What drives extreme density is design philosophy, not player count.

**Maps with only 1 wool per team** show high variance: nyxis (40K items, 1 wool = 40K items/wool) is a modest number compared to nextrace (86K/wool). When there is only one wool to defend the stakes are higher and some designers stock accordingly.

---

## Material Composition Outliers

![Defense material composition for top 15 maps stacked bar chart](figures/defense_material_composition.png)

The stacked bar chart for the top 15 maps by total defense items reveals distinct design archetypes:

**Glass-wall maps:**
- **nextgen** (248K glass out of 498K total, ~50%) — The defence is built almost entirely from glass. On a milli map with only 9K total blocks, the glass volume implies enormous pre-placed or chest-stocked glass walls are the primary mechanic. Almost nothing else in the chests.
- **blocks_ctw** (111K glass out of 479K total) — Glass is the largest single material but shares the stacking with 18K redstone blocks and 18K pistons. This is the classic redstone-piston defence paradigm combined with glass barricades.
- **race_for_victory_3** (55K glass + 37K pistons) — Similar archetype, double-wool. Pistons and glass in roughly 2:1 ratio.

**Fence-dominated maps:**
- **madness_on_rails** (29K fences + 55K glass + 28K redstone) — The largest fence stockpile in the top 15 combined with heavy glass and redstone. This map uses all three structural materials simultaneously, suggesting layered defences.
- **ruedigers_octawool** (23K fences, almost nothing else) — An octawool pico map (7 wools, 5-player team). The entire defence budget goes to fences — perhaps wooden barriers around each of the 7 wool rooms with minimal other material.

**Piston-heavy maps:**
- **blocks_ctw** and **gridlock_2** (28K pistons) — Piston traps or retractable walls. gridlock_2 has 28K pistons and nothing else tracked, implying the entire defence mechanic is piston-based.

**Maps with near-zero tracked materials despite large item totals:**
- **exitium** (167K items, zero tracked materials) — All items fall into the "Other" category. This is likely dominated by building materials not in the tracked set (stone, wood, logs, planks, etc.). Exitium's defence is probably straightforward block-stacking.
- **summertime_at_browns_farms** (156K items, zero tracked) — Same pattern. A nano map with 8 players and 7 wools, suggesting many small chests stocked with basic blocks rather than specialised mechanics.
- **split_strata** (173K items, only 768 redstone blocks and 1280 fences tracked) — The vast majority of items are "other."

The "Other" category dominates many maps and likely includes common building materials (cobblestone, stone, wood planks, logs) that are not individually tracked in the current schema. Future analysis would benefit from expanding the tracked material list.

---

## Maps with No Defense Chests

The following 15 non-stub maps have no chests classified as `content_category = 'defense'`:

| Map | Size tier | Total blocks | Max players/team | Wools/team |
|-----|-----------|-------------|-----------------|-----------|
| 2d | nano | 1,428 | 8 | 1 |
| blossom_ctw | micro | 6,370 | 16 | 1 |
| cargo | micro | 6,088 | 16 | 2 |
| catscratch | nano | 4,016 | 12 | 1 |
| desert_eclipse | micro | 12,433 | 16 | 3 |
| fairy_tales_2_mini | nano | 5,219 | 10 | 2 |
| greenhill | micro | 8,066 | 16 | 2 |
| ingwaz | pico | 2,039 | 5 | 1 |
| no_mans_land | centi | 11,105 | 32 | 2 |
| ouroboros | nano | 10,335 | 10 | 1 |
| outlyne | nano | 4,362 | 8 | 1 |
| prisma_ctw | nano | 4,529 | 6 | 1 |
| stalactites_a_land_down_under | micro | 9,518 | 18 | 2 |
| curly_wools_ix | centi | 348 | 32 | 1 |
| cake_day | centi | 15,063 | 35 | 2 |

A few observations:

- **Most are small maps**: 12 of 15 are pico/nano/micro. The exceptions are no_mans_land, cake_day, and curly_wools_ix (all centi). These large maps without defense chests are interesting — they may deliberately present an open, unfortified wool room where the contest is about team combat rather than siege mechanics.
- **curly_wools_ix** has only 348 total blocks — almost certainly a stub or test map that slipped through the `stub = FALSE` filter. The centi tier assignment is probably a data entry error given the block count.
- **cake_day** and **no_mans_land** are legitimate full-size maps. Their lack of defense chests is a real design choice: players defend using the terrain and their starting gear rather than pre-placed chest supplies.
- These maps may rely on **spawn chests only** (classified under the spawn zone) for any resupply, or may have a design philosophy where raiding is straightforward and defense emerges from player skill rather than material fortification.

---

## Appendix: Notable Outliers — Top 10 Maps by Defense Chests

| Map | Tier | Total Blocks | Players/team | Wools/team | Defense Chests | Defense Items | Items/wool |
|-----|------|-------------|-------------|-----------|---------------|--------------|-----------|
| nyxis | micro | 21,881 | 20 | 1 | 326 | 40,242 | 40,242 |
| nextgen | milli | 9,000 | 24 | 2 | 288 | 497,664 | 248,832 |
| blocks_ctw | centi | 33,099 | 32 | 2 | 288 | 479,232 | 239,616 |
| madness_on_rails | centi | 21,432 | 36 | 2 | 168 | 282,240 | 141,120 |
| fall_of_babylon | centi | 46,904 | 34 | 2 | 164 | 83,388 | 41,694 |
| race_for_victory_3 | centi | 17,952 | 35 | 3 | 160 | 276,480 | 92,160 |
| split_strata | milli | 12,062 | 24 | 2 | 116 | 172,596 | 86,298 |
| exitium | milli | 12,472 | 24 | 2 | 112 | 166,824 | 83,412 |
| ad_infinitum | milli | 33,479 | 30 | 1 | 108 | 6,364 | 6,364 |
| summertime_at_browns_farms | nano | 22,356 | 8 | 7 | 104 | 156,096 | 22,299 |

**ad_infinitum** stands out as a contrast to the other top-10 entries: 108 defense chests but only 6,364 total items — an average of ~59 items per chest, the lowest density in this group by far. This map distributes access points widely but stocks them sparingly. **summertime_at_browns_farms** is the sole nano map here and the only map with 7 wools per team in the top 10; its 104 chests spread across 7 wool objectives average ~14 chests per wool, a very high ratio.
