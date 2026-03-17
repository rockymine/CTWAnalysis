# CTW Match Analysis — Research Roadmap

_Last updated: 2026-03-17_

_See also: `docs/glossary.md` for definitions of all gameplay and analysis terms._

---

## Purpose

This document is a working research roadmap for the CTW match analysis project.
It sets out the questions we are asking, the hypotheses we are testing, the signals
available to us, and a suggested order of work.  It is deliberately opinionated —
each section should evolve as we learn from the data.

The analysis is grounded in the data accumulated so far: **81 maps with ten or more
processed matches**, all spatial-classified, covering everything from 5v5 pico maps
that end in under two minutes to 24v24 milli maps that occasionally grind for over
two hours.  The traffic graph pipeline is now stable and the wool/spawn positions are
accurate.  We are ready to do real analytical work.

---

## Research Goals

1. **Understand how CTW matches actually play out** — validate or refute the phase
   model described in `docs/gameplay_mechanics.md` against real positional data.
2. **Classify player behaviour per life segment** — who was rushing, who was
   defending, who was skybridging?  No machine learning; purely signal thresholds and
   traffic-graph geometry.
3. **Build a match-level time series picture** — how does the distribution of roles
   shift during a match?  Can we detect a push wave, a defensive collapse, the
   transition from ground attack to skybridge?
4. **Characterise each map's typical gameplay pattern** — does `arabia` always play
   as a long stalemate?  Does `fairy_tales_2_mini` almost always end on a quick wool
   capture?  What is the typical and the unusual match for each map?
5. **Test concrete hypotheses** stated below against the data.
6. **Produce a match report prototype** — a structured, human-readable summary of a
   single match: who did what, when did the key transitions happen, how did it end.

The eventual audience is both personal research and public forum posts.
Cross-map comparison is a medium-term goal; single-map depth comes first.

---

## Data Foundation

### Tables and what they contain

| Table | Primary use |
|---|---|
| `life_segments` | One row per player life. Duration, outcome, spawn position, kill/wool counts. The core unit of analysis. |
| `position_events` | Spatial track at 2-5 s intervals. `x`, `y`, `z`, `location_type` (`island`/`build_region`/`void`), `island_id`. |
| `life_segment_traffic_features` | Per-life traffic metrics: `snapped_sequence` (ordered node ID list), `max_attack_depth`, `death_region`. |
| `wool_events` | Touch (type 6) and capture (type 7) events with exact coordinates. |
| `combat_events` | Kill and death events with position. |
| `wool_carry_chains` | Consecutive carry attempts grouped into waves. |
| `player_team_segments` | Team membership over time (inferred from spawn). |
| `map_wool_locations` | Accurate wool chest positions from first-touch median clustering. |
| `map_wool_monuments` | Accurate monument positions from capture events. |
| `map_spawns` | Spawn block positions per team. |
| `maps` | `wools_per_team`, `team_count`, `max_players_per_team`, `max_build_height`, `size_tier`, `island_count`, `symmetry_type`. |

### Layout parquets (`output/<map>/layout_*.parquet`)

Per-map raster layers, one row per (x, z) cell with `y`, `block_id`, `block_data`:

| File | Content |
|---|---|
| `layout_top_surface.parquet` | Highest non-air block — the surface a player walks on |
| `layout_lowest_solid.parquet` | Lowest non-air block — bottom of terrain column |
| `layout_bedrock.parquet` | Bedrock positions |
| `layout_decided.parquet` | Layer chosen by island classifier; includes `island_id` |
| `layout_y0.parquet` | Block type at y = 0 |
| `layout_resource_blocks.parquet` | Ore and resource block positions |
| `layout_chest_contents.parquet` | Chest positions and parsed contents |

The outer vertical extent of terrain at each cell is defined by `top_surface.y` and
`lowest_solid.y`.  Intermediate navigable floors (tunnels, stacked islands) are not
yet extracted — see Layer 0 in Analysis Modules.

### Traffic graph JSON (`output/<map>/traffic_graph.json`)

Used alongside the DB for:
- Full node/edge topology for Dijkstra distances
- POI node positions (spawn, wool) with correct world coordinates
- `node_info` dict for fast snap-and-measure operations

The snapped sequence in `life_segment_traffic_features` references the node IDs in
this graph.  It is the backbone of spatial movement analysis.

### State of the data (2026-03-17)

- **81 maps** with ≥ 10 processed matches, all spatial-classified.
- Duration range across the dataset: 12 seconds (`honeycombed` fastest match) to
  166 minutes (`brittlebush_ii` longest).
- All maps have accurate wool and spawn positions in `map_wool_locations` and
  `map_spawns` (including the previously-broken `emergency_meeting`).
- `life_segment_traffic_features` is populated for all classified matches.

---

## Map Landscape

Understanding which maps to prioritise requires knowing their structural properties.
The 81-map dataset naturally partitions into tiers:

### Fast / rush-dominant maps (1 wool, avg < 3 min)

These are the maps where Phase 1 almost always decides the match.  Defence setup
rarely completes; skybridging is essentially absent.

Representative examples with good sample sizes:

| Map | Matches | Avg (min) | Stddev | Notes |
|---|---|---|---|---|
| `pirates_i` | 131 | 1.7 | 2.1 | 5v5 pico; reference for pure rush |
| `flush_vibes_ii` | 129 | 1.8 | 1.2 | 5v5 pico; very consistent |
| `honeycombed` | 120 | 1.8 | 2.4 | 5v5 pico; occasionally goes long (21 min outlier) |
| `ingwaz` | 102 | 2.1 | 1.3 | 5v5 pico |
| `amphitheater` | 78 | 1.9 | 1.5 | 6v6 nano |
| `desolate_gully_ctw` | 78 | 1.7 | 1.2 | 6v6 nano; very tight distribution |

High match counts + tight distributions make these ideal **baseline maps** — if a
hypothesis doesn't hold cleanly here, it probably won't hold anywhere.

### Medium maps (1 wool, avg 3–10 min)

The match can go either way.  Ground rush is common but defence sometimes forms.
Skybridge is rare but not impossible.  Wide variance in outcome.

| Map | Matches | Avg (min) | Stddev | Notes |
|---|---|---|---|---|
| `dynamo` | 39 | 4.7 | 3.3 | 8v8 nano |
| `dromedary` | 45 | 4.7 | 4.4 | 7v7 nano; high variance for its size |
| `vertex` | 48 | 3.6 | 3.1 | 7v7 nano |
| `research_base` | 30 | 5.4 | 4.7 | 8v8 nano; sometimes long |

### Stalemate-prone maps (2 wool, avg > 10 min)

These are where the full phase model plays out.  The data is inherently noisier
(fewer matches, longer durations → fewer samples per minute of match time).

| Map | Matches | Avg (min) | Stddev | Max (min) | Notes |
|---|---|---|---|---|---|
| `brittlebush_ii` | 12 | 24.3 | 45.6 | 166 | Extreme bimodal: some fast, some epic |
| `kanto` | 13 | 22.5 | 26.2 | 100 | Classic long-form |
| `desert_country` | 12 | 21.2 | 38.2 | 140 | Very high variance |
| `clearcut` | 19 | 14.4 | 29.2 | 130 | Bimodal |
| `arabia` | 15 | 13.1 | 17.6 | 75 | Main development target; well-understood |
| `empire` | 15 | 12.8 | 12.3 | 44 | Spawn position now fixed |

High-stddev 2-wool maps are analytically the most interesting: **the same map
produces radically different matches**.  Understanding why is one of the central
questions of this project.

### Multi-team / multi-wool maps

A distinct category with unique dynamics.

| Map | Wools/team | Teams | Matches | Avg (min) | Notes |
|---|---|---|---|---|---|
| `oumuamua` | 3 | 4 | 21 | 8.3 | Pico 4-team; good for multi-wool loop test |
| `emergency_meeting` | 3 | 4 | 13 | 6.6 | Wool positions now corrected |
| `enchanted` | 3 | 4 | 13 | 3.6 | Fast 4-team |
| `fourchette` | 3 | 2 | 15 | 7.7 | 3-wool 2-team; unusual format |
| `ouroboros` | 1 | 4 | 10 | 4.6 | 4-team single wool |

---

## Hypotheses

The following are stated as testable claims.  Each one generates concrete queries or
analysis steps.

### H1 — Early push rate predicts first-wool timing on 2-wool maps

On 2-wool maps, the first wool capture very often happens early relative to overall
match duration.  The team that loses their first wool does so within the first
one-third of the match in the majority of cases.

_Why this matters:_ Validates that 2-wool matches follow the phase model — the first
wool is decided by Phase 1/2 dynamics, the second by attrition.  If false (both
wools fall close together), the phase model needs revision.

_Signals needed:_ `wool_events` capture timestamps vs `matches.match_duration`.

---

### H2 — On 2-wool maps, one wool is structurally easier

One of the two wools is captured first in the overwhelming majority of matches, and
it is the **same wool** each time.  This implies that one side of the map is
geometrically easier to attack (shorter path, less defensible).

_This is testable_ because captures are tagged with `wool_id`, which maps directly
to colour.  If one wool colour is consistently captured first across 10+ matches,
the hypothesis holds.

_Null hypothesis:_ The two wools are captured in random order → each is first in
roughly 50% of matches.

_Maps to test on:_ `fairy_tales_2_mini` (27 matches, good sample), `arabia` (15),
`tranquility` (27), any 2-wool map with n ≥ 15.

---

### H3 — Multi-wool loop captures exist but are rare

A loop capture is defined as: a player touches wool A, then travels to wool B and
touches it, then returns to their monument to capture both — without dying in
between.  It is detectable from the `wool_events` table as two distinct touch events
(event_type=6) on different `wool_id`s in the same life segment, followed by two
capture events (event_type=7).

The hypothesis is that this happens in fewer than 5% of matches on 2-wool maps.
On 3-wool 4-team maps (`oumuamua`, `emergency_meeting`), it should be similarly
rare but slightly more common due to shorter inter-wool distances.

_For 4-team maps, the extreme case_ would be a player capturing all three wools
their team needs in a single run.  This should be vanishingly rare — perhaps one or
two occurrences across the entire dataset.

---

### H4 — Long match duration correlates with sustained skybridge activity

On 2-wool maps where the match exceeds the 75th percentile duration for that map,
at least one extended skybridge (5+ consecutive position events at or near
`max_build_height`) appears in the `position_events` data.

The weaker form: average `y` across all position events in long matches is
measurably higher than in short matches on the same map.

_Also interesting:_ Does the skybridge actually reach close to the wool room?
A successful skybridge attack should show a player's snapped sequence terminating
at a node close to the enemy wool POI node (high `max_attack_depth` in the traffic
features).

---

### H5 — Maps with high duration variance are bimodal, not uniformly distributed

Maps like `brittlebush_ii` (stddev 45.6), `clearcut` (stddev 29.2), and
`desert_country` (stddev 38.2) have very high variance relative to their mean.
The hypothesis is that these maps are **not** uniformly distributed across duration
— instead they have two clusters: a fast-ending cohort (rush succeeded) and a
slow-ending cohort (stalemate formed).

A bimodal distribution would imply two structurally distinct match types for the
same map.  Identifying which cluster a match belongs to early (e.g. from the first
3 minutes of position data) is a longer-term goal.

---

### H6 — Death region is a reliable proxy for player role

The `death_region` field in `life_segment_traffic_features` classifies each death as
`home_island`, `enemy_island`, `bridge`, or `void`.

Hypothesis: players dying on `enemy_island` are overwhelmingly attackers/rushers in
their final moments.  Players dying on `home_island` are overwhelmingly defenders.
Players dying on `bridge` include both skybridgers and ground attackers who were
intercepted mid-map.

This is testable by cross-referencing with `wool_touches` and `max_attack_depth`.

---

### H7 — snapped_sequence alone is sufficient for role inference without reconstruction

The full path reconstruction used in `run_traffic_diagnostics.py` is detailed but
slow and requires loading the traffic graph topology per match.  The snapped sequence
is much lighter — it is a raw ordered list of visited node IDs.

The hypothesis is that for the purpose of role classification, the snapped sequence
provides enough information:
- Which island a player started and ended on
- Whether they ever visited an enemy-team node (wool or near-wool node)
- How many distinct nodes they visited (mobility proxy)
- Whether their sequence is monotonically advancing toward the enemy or bouncing back
  and forth (attacker vs roamer vs defender)

Reconstruction is valuable for visualisation and path similarity, but the snapped
sequence should be the primary analysis signal.

**Known limitation (confirmed):** The traffic graph is 2D (x/z only).  The snapped
sequence cannot distinguish ground-level movement from skybridge movement at the same
x/z position.  The SKYBRIDGER and SKY_DEFENDER roles require y-coordinate data from
`position_events` as a complement.  H7 holds with this stated exception.

A further complication arises on vertically complex maps (e.g. `golden_drought_v`):
the `y ≥ max_build_height − 2` heuristic for skybridge detection produces false
positives for players standing on elevated terrain platforms that are close to the
build limit.  Resolving this requires a **terrain height map** per map (see Layer 0
in Analysis Modules below).

---

### H8 — Drop-down attack is detectable as a y-profile signature

A player who uses a skybridge as a launch platform and then drops to enemy territory
has a characteristic y-signature within a single life segment: y rises steeply near
home spawn, plateaus near max_build_height, then drops sharply before ground-level
movement resumes near the enemy island.  This profile is distinct from pure
skybridging (y stays high throughout) and pure ground rushing (y stays flat).

The hypothesis is that drop-down attacks are a non-trivial fraction of successful
wool carries on long 2-wool matches — particularly in late-match life segments where
the ground route is heavily defended and drop-down provides the cleaner approach.

_Signals needed:_ `position_events.y` per life segment, segmented into thirds (early,
mid, late within the life).  Rise-plateau-drop = drop-down signature.  Cross-reference
with `death_region = enemy_island` and `wool_touches ≥ 1` to confirm intent.
Terrain height map (Layer 0) required for robust floor classification on maps where
build limit and terrain elevation are close.

---

### H9 — Defence accumulation is measurable via death_region shift over match time

On long matches (> 75th percentile duration for that map), the fraction of attacker
lives ending on `enemy_island` in the late third of the match
(start_timestamp > 0.66 × match_duration) is measurably lower than in the early third
(start_timestamp < 0.33 × match_duration).

This reflects the defence scaling dynamic: physical defences accumulate (pit depth,
wall complexity) and attackers are intercepted progressively further from the wool
room as the match advances.

_Signals needed:_ `life_segment_traffic_features.death_region` joined to
`life_segments.start_timestamp` normalised by `matches.match_duration`.  Group by
match third; compare `death_region` distributions.  Test on all 2-wool maps with
≥ 15 matches; compare high-variance maps (`brittlebush_ii`, `clearcut`) against
low-variance maps (`pirates_i`).

---

### H10 — Skybridge activation precedes first wool capture on long matches

On 2-wool maps where the match exceeds the 75th percentile duration for that map, the
first skybridge activation event (any player's y ≥ max_build_height − 2 for 3+
consecutive ticks) precedes the first wool capture (event_type = 7 in `wool_events`)
by more than 2 minutes in the majority of matches.

This tests whether the skybridge is structurally _necessary_ for late-match progress
on stalemate maps — complementing H4 (which tests only whether skybridge activity is
present at all in long matches).

_Signals needed:_ `position_events.y` (first timestamp per match where sky condition
met) vs `wool_events` (first timestamp where event_type = 7).  Both joined via
`matches.match_id`.  Requires `maps.max_build_height` per map.  Terrain height map
(Layer 0) would reduce false positives from elevated terrain being misclassified
as skybridge.

---

### H12 — First wool captures by opposing teams tend to be on diagonally opposite flanks

In matches on 2-wool maps where **both** teams capture at least one wool, the two
first captures are more often on diagonally opposite flanks (different lateral
positions relative to the map's attack axis) than on the same flank.

**Reasoning:** If both teams' attackers target the same lateral side simultaneously,
they are likely to encounter each other mid-map, increasing mutual disruption and
reducing the probability of both succeeding.  Attackers who take different flanks
face less opposition from enemy attackers and more likely succeed independently.
This would produce a systematic preference for diagonal captures in the data.

**Methodology:**

Lateral position (left/right) is defined relative to the map's attack axis (the
line between the two teams) using `map_wool_locations.x/z` and `maps.symmetry_type`:

- **mirror_x** (53 maps): the two wools of each team differ primarily in x.
  Each wool is "left" if its x < the team's other wool's x, else "right".
  Mirror pairs share the same x position but differ in z sign.
  _Same flank_ = both first captures share the same x.
  _Diagonal_ = first captures have different x positions.

- **mirror_z** (10 maps): same logic applied to z instead of x.

- **rot_180** (31 maps): compute each wool's angle from the map centroid
  (centroid of all 4 wool positions).  Each team's two wools are ≈180° apart
  from the other team's wools.  Within a team's pair, the wool with smaller
  angular offset from its team's centroid is "left"; larger offset is "right".
  _Same flank_ = first captures are in the same angular half; _Diagonal_ = opposite.

**Null hypothesis:** Diagonal and same-flank captures occur equally (50/50).

_Signals needed:_ `wool_events` (event_type=7), `player_team_segments` (team of
capturing player), `map_wool_locations` (wool positions and team), `maps.symmetry_type`.
Requires resolving the NULL team issue in `map_wool_locations` for accurate pairing.

---

### H11 — Ground route traversal becomes slower over match time

As block spamming, pit digging, and defensive construction accumulate, the ground-level
path becomes more tortuous.  This should appear as an increase in snapped sequence
length for life segments that successfully reach enemy territory, comparing early-match
to late-match segments on the same map.

Formally: for life segments with `death_region = enemy_island`, the mean
`len(snapped_sequence)` in late-match segments (start_timestamp > 0.5 × match_duration)
is higher than in early-match segments (start_timestamp < 0.25 × match_duration).

The traffic graph was built from all player movement across all matches, meaning
accumulated block debris and player-constructed terrain are implicitly captured in node
density.  More nodes visited per crossing = more tortuous effective path.

_Signals needed:_ `life_segment_traffic_features.snapped_sequence` length joined to
`life_segments.start_timestamp` normalised by match duration.  Filter to
`death_region = enemy_island` to control for incomplete crossings.

---

## Analysis Modules

The work is structured into four layers, loosely ordered by dependency.

---

### Layer 0 — Terrain Geometry (Prerequisite for Vertical Analysis)

**Goal:** For each x/z cell, determine all distinct navigable y-levels — positions
where a player can stand (solid block at y, two air blocks at y+1 and y+2) —
including intermediate floors that lie _between_ the surface and bedrock.

#### What the existing parquets already give us

The pipeline already outputs per-map layout parquets, each with `(world_x, world_z, y, block_id, block_data)`:

| File | Content |
|---|---|
| `layout_top_surface.parquet` | Highest non-air block at each (x, z) — the surface a player walks on |
| `layout_lowest_solid.parquet` | Lowest non-air block at each (x, z) — bottom of terrain |
| `layout_bedrock.parquet` | Bedrock positions |
| `layout_decided.parquet` | The layer selected by the island classifier (+ `island_id`) |
| `layout_y0.parquet` | Block type at y = 0 |

`top_surface.y` and `lowest_solid.y` together describe the **vertical extent** of
terrain at each cell.  When `top_surface.y − lowest_solid.y` is small, the column
is essentially solid.  When the gap is large, there may be internal air spaces —
but from these layers alone we cannot tell if they are empty voids or contain
additional navigable surfaces.

#### What is still missing

The gap between `lowest_solid.y` and `top_surface.y` gives a signal — large gap
= potential internal structure — but does not reveal whether intermediate navigable
surfaces exist.  This matters for:

- **Tunnels:** A hollow passage through terrain has a floor below and a ceiling
  above.  `top_surface` shows the ceiling; the floor is not captured.
- **Stacked islands:** An island platform at y=10 with another platform at y=25
  above it.  `top_surface` shows y=25; the lower platform at y=10 is invisible.
- **Near-build-limit terrain:** On `golden_drought_v`, mid-map islands are raised
  at +1, +3, and +8 blocks above the map base, while `max_build_height` is ~20
  blocks above base.  A player at `top_surface.y + 1` on the highest raised island
  and a player on a constructed skybridge are within 2–3 y-blocks of each other.
  The global threshold `y ≥ max_build_height − 2` is unreliable here — it would
  misclassify players standing on elevated terrain as skybridgers.

#### Method A — Region file parsing (ground truth)

Minecraft maps store terrain in `.mca` region files.  `PublicMaps/ctw/golden_drought_v`
is available as the reference test case.

Algorithm:
1. Parse all chunks using `anvil-parser` (or equivalent Python `.mca` library).
2. For each (x, z), collect all y where block(y) is solid AND block(y+1) and
   block(y+2) are both air (walkable surface condition).
3. Store as a per-cell list: `navigable_floors[(x, z)] = [y1, y2, …]` (sorted).
4. Classify cells:
   - Single floor: flat terrain
   - Multiple floors: stacked islands or tunnel section — each floor is a distinct
     navigable surface
   - Top floor close to `max_build_height`: elevated island near build limit

Output: `layout_navigable_floors.parquet` with `(world_x, world_z, floor_y_list)`.
The top value of `floor_y_list` at each cell would match `layout_top_surface.parquet`,
providing a validation check.

#### Method B — Empirical y-floor inference from position_events (proxy)

For maps that have accumulated match data, player movement approximates terrain floors:
1. Per (x, z) bucket (2-block resolution), collect all y values from `position_events`
   across all matches for that map.
2. Apply 1D gap detection (gap > 3 blocks between consecutive y-values in a histogram)
   to identify distinct floor clusters.
3. Lower cluster(s) ≈ terrain floors; top cluster near `max_build_height` ≈ skybridge zone.

Works from the existing DB without additional parsing.  Limitation: sparse coverage
in low-traffic cells.  Validation: compare against Method A on `golden_drought_v`.

#### Impact on downstream skybridge detection

With a navigable floor map, the per-cell skybridge threshold becomes:

```
skybridge_y_threshold(x, z) = max(navigable_floors[x, z]) + Δ
```

where Δ is a small margin (e.g. 3 blocks) above the highest natural surface at that
cell.  A player at `y > skybridge_y_threshold(x, z)` is on a constructed structure,
not terrain.  On flat maps the formula reduces to the existing global threshold; on
`golden_drought_v`-style maps it correctly separates elevated terrain from skybridge.

Tunnel detection follows: `y < min(navigable_floors[x, z]) − Δ` where terrain exists
overhead.

---

### Layer 1 — Life Segment Role Classification

The life segment (`life_segments` joined to `life_segment_traffic_features` +
`position_events` aggregates) is the atomic unit of analysis.

**Goal:** Assign each life segment a primary role label.

**Available signals per segment:**

| Signal | Source | How derived |
|---|---|---|
| `duration` | `life_segments` | Direct |
| `kill_count` | `life_segments` | Direct |
| `wool_touches`, `wool_captures` | `life_segments` | Direct |
| `death_region` | `life_segment_traffic_features` | Direct |
| `max_attack_depth` | `life_segment_traffic_features` | Direct — lower = deeper into enemy |
| `snapped_sequence` length | `life_segment_traffic_features` | `len(parse_json(snapped_sequence))` |
| Unique nodes visited | `life_segment_traffic_features` | `len(set(snapped_sequence))` |
| Start island vs end island | `life_segment_traffic_features` + graph node metadata | Did the player end on a different island than they started? |
| Y-level stats | `position_events` | avg, max, fraction at `max_build_height` |
| Island-time fractions | `position_events` (island_id) | Fraction of ticks on home island vs other vs void |
| Match start time | `life_segments.start_timestamp` / `matches.match_duration` | Relative match position (early / mid / late) |
| `inv_count` trend | Not currently in DB (future: raw parquet) | Building (decreasing), digging (increasing) |

**Proposed role taxonomy:**

Each role is defined by a combination of thresholds on the signals above.  These
are starting points, not final values — empirical calibration is needed.

```
RUSHER
  - start_island == home_island  (always true — everyone spawns home)
  - end_island OR death_region == enemy_island OR bridge
  - max_attack_depth < (map_specific threshold, initially 0.4)
  - match_start_fraction < 0.5  (early-to-mid match)
  - wool_touches >= 0  (may or may not have gotten the wool)

WOOL_CARRIER
  - wool_touches >= 1 in this segment
  - death_region == bridge OR enemy_island  (died on the way home with wool)
  - OR: wool_captures >= 1 (made it home)
  — sub-cases: successful return, failed extraction, trapped in room

DEFENDER
  - fraction_time_on_home_island > 0.7
  - max_attack_depth > 0.6  (stayed far from enemy wool)
  - death_region == home_island OR bridge (died defending)
  - unique_nodes < median_unique_for_map  (low mobility)

SKYBRIDGER
  - frac_position_at_max_build_height > 0.3  (Y ≥ max_build_height - 2)
  - snapped_sequence contains nodes at high elevation (or mid-map bridge nodes)
  - match_start_fraction > 0.3  (not a Phase 1 activity)
  - span_m > 20 blocks

ROAMER / SUPPORT
  - Doesn't meet any of the above cleanly
  - High unique_node count + mid-range attack depth
  - Kill events scattered across the map
  - Functions as a mid-fielder, supporting both attack and defence
```

**Important design note:** A player may start a life as a defender and then pivot to
attack mid-segment (e.g. after a teammate creates an opening).  The snapped sequence
captures this — the sequence will show a home-island start followed by an advance
toward the enemy.  Role classification should be sensitive to the *trajectory* of the
sequence, not just the aggregate statistics.

One promising approach: segment the snapped sequence into thirds (early, mid, late
within the life) and check whether the attack depth is monotonically increasing
(attacker), flat (defender/roamer), or decreasing (retreater after failed push).

---

### Layer 2 — Match-Level Time Series

**Goal:** Understand how the distribution of activity shifts during a match.

The fundamental question is: at time T (absolute or relative), what fraction of
active players are:
- On their home island (defending / staging)?
- On a bridge or in void (crossing)?
- On an enemy island (attacking)?

This is directly derivable from `position_events.island_id` and `location_type`,
bucketed by timestamp.

**Team push detection:**

A "push wave" is defined as a cluster of 2+ players from the same team crossing
from their home island to a bridge within a short time window (e.g. 30 seconds).
This is detectable from `player_team_segments` + `position_events` by looking for
simultaneous `location_type` transitions from `island` → `build_region`/`void`.

This doesn't require all players to move together — defenders will stay home.  A push
wave is simply the attack subset moving in temporal coordination.

**Skybridge timeline:**

For each match, a skybridge activation timestamp can be identified as the first moment
a player's y-position exceeds `max_build_height - 3` for at least 3 consecutive ticks.
Across all matches of a map, plotting the distribution of skybridge activation times
tells us at what point in a typical match the skybridge phase begins.

**Wool carry timeline:**

`wool_carry_chains` already groups carry attempts into waves.  Overlaying the carry
wave timestamps with the skybridge timeline and the team push timestamps can reveal
whether there is a coordination pattern: do pushes precede successful carries?

---

### Layer 3 — Map Behavioural Fingerprint

**Goal:** Characterise each map as a distribution over match archetypes, not just
an average duration.

For any map with n ≥ 10 matches, we can compute:

1. **Duration distribution** — histogram, median, IQR.  Is it unimodal?  Bimodal?
   Log-normal (as suggested by the gameplay mechanics — rush ends fast, stalemate
   is long)?
2. **First-wool timing** (2-wool maps) — at what fraction of match duration is
   the first wool captured?  Consistent early capture → Phase 1 dominant.
   Late capture → the match has a genuine mid-game.
3. **Skybridge prevalence** — fraction of matches in which at least one skybridge
   occurs (y ≥ max_build_height - 2 for 3+ consecutive ticks by any player).
4. **Death region distribution** — across all life segments for this map, the
   fraction that end in each region.  A defender-heavy map will have most deaths on
   `home_island`; an aggressor-heavy map will have more on `bridge`/`enemy_island`.
5. **Average max_attack_depth** — are players generally close to the enemy wool or
   far?

These five numbers form a "fingerprint" that characterises the map's typical
gameplay.  Plotting them together across all 81 maps will give a high-level view
of the dataset's diversity.

**Match consistency within a map:**

For the high-variance maps (`brittlebush_ii`, `clearcut`, `desert_country`), the key
question is whether the variance is noise (random) or structural (two distinct match
types).  A simple k-means or manual threshold on duration + first-wool-timing would
cluster these matches.  No ML needed — the separation, if real, should be visually
obvious on a scatter plot.

---

### Layer 4 — Specific Event Analyses

These are narrower, question-driven analyses that can run independently.

#### 4a — Wool capture ordering on 2-wool maps (H2)

The correct unit of analysis is **per defending team per match**, not per match
overall.  `map_wool_locations.team` identifies which team defends each wool.

```sql
-- For each 2-wool map, per defending team: which of their wools is captured first?
WITH first_wool_per_team AS (
    SELECT
        mat.match_id, mat.map_id,
        tw.team AS defending_team,
        tw.wool_id, tw.wool_color
    FROM matches mat
    JOIN maps m ON m.map_id = mat.map_id AND m.wools_per_team = 2 AND m.team_count = 2
    JOIN map_wool_locations tw ON tw.map_id = mat.map_id
    JOIN wool_events we ON we.match_id = mat.match_id
        AND we.wool_id = tw.wool_id AND we.event_type = 7
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY mat.match_id, tw.team ORDER BY we.timestamp
    ) = 1
),
team_totals AS (
    SELECT map_id, defending_team, COUNT(*) AS n
    FROM first_wool_per_team GROUP BY map_id, defending_team
)
SELECT
    m.map_slug, fwt.defending_team, fwt.wool_color, fwt.wool_id,
    COUNT(*) AS times_first, tt.n,
    ROUND(COUNT(*) * 100.0 / tt.n, 1) AS pct
FROM first_wool_per_team fwt
JOIN team_totals tt ON tt.map_id = fwt.map_id AND tt.defending_team = fwt.defending_team
JOIN maps m ON m.map_id = fwt.map_id
WHERE tt.n >= 5
GROUP BY m.map_slug, fwt.defending_team, fwt.wool_color, fwt.wool_id, tt.n
ORDER BY m.map_slug, fwt.defending_team, times_first DESC
```

**Data quality note:** approximately one wool per map has `team = NULL` in
`map_wool_locations`.  This means H2 analysis currently sees only one of a team's
two wools for the affected team.  Before finalising H2 results the NULL team wools
should be inferred (e.g. from which team captured the wool in match data) and
backfilled.

**Preliminary findings (15 qualifying maps, ≥ 5 captures per team):**

| Map | Team | Dominant wool | Pct | Notes |
|---|---|---|---|---|
| `sakura_garden` | both | 100% each | Perfect single-wool dominance |
| `kanto` | red-team | purple | 100% | 12 matches |
| `clearcut` | red-team | cyan | 100% | 15 matches |
| `wholething` | blue | pink | 100% | 8 matches |
| `fairy_tales_metamorphose` | blue | lime | 100% | 11 matches |
| `brittlebush_ii` | both | ~90% each | Strong on both sides |
| `split_strata` | both | 92% / 85% | Strong on both sides |
| `tranquility` | both | ~57–60% | Genuinely symmetric — H2 fails |
| `arabia` | team-1 | pink | 58% | Essentially 50/50 |
| `desert_country` | blue 90%, green 55% | Intra-map asymmetry: one side has clear easier wool, the other is balanced |

**Conclusion:** H2 holds strongly for the majority of map/team pairs.  Exceptions
are genuinely symmetric maps (`tranquility`) and one side of otherwise asymmetric
maps (`desert_country` green-team, `fairy_tales_2_mini` green-team).

**Next step — spatial left/right classification:** The per-team approach tells us
*which wool_id* goes first but not *which geometric side*.  To ask "is the left wool
or the right wool consistently easier?", we need to classify each wool as left/right
relative to the attack axis using `map_wool_locations.x/z` and `maps.symmetry_type`
(mirror_x: 53 maps, rot_180: 31, mirror_z: 10).  For mirror_x maps the two wools
of each team differ in x; mirror pairs share the same x but differ in z.  A wool
is "left" if its x is lower than its team-mate's.  This classification should be
computed before the next round of H2 analysis.  See also H12 below.

#### 4b — Multi-wool loop capture detection (H3)

**H3 as originally stated is decisively false.**  Multi-wool touch events (touching
2+ distinct wool_ids in a single life) are extremely common — occurring in 50–100%
of matches on multi-wool maps and in 40–70% of matches on many 2-wool maps.

The phenomenon has two distinct sub-types that must be separated:

1. **Multi-touch only (no double-cap):** 55.9% of multi-touch segments — player
   touched 2+ wools but died or dropped one without capturing it.  Very common.
2. **Single capture from multi-touch:** 27.4% — player touched 2 wools and
   captured 1.  Often reflects team play (safety placement picked up later, or a
   teammate captured the other wool independently — see wool sharing below).
3. **Genuine double-cap (touched and captured 2+ wools):** 15.1% of multi-touch
   segments — player delivered 2 wools in one life.
4. **Triple or quad-cap:** 1.5% combined — vanishingly rare.

The original <5% threshold applies only to genuine double-caps as a fraction of
multi-touch segments (15%), and even that is not rare.  H3 should be reformulated.

**Touch ordering in single-capture multi-touch segments:**  59.5% of the time, the
first-touched wool was the one captured (player touched A, grabbed B en route home,
captured A, dropped/lost B).  40.5% of the time, the second-touched wool was
captured — consistent with the wool-sharing scenario: player touched A, placed it
as a safety or a teammate grabbed it, then captured B.

```sql
-- Multi-touch segments and their capture outcomes
WITH multi_touch AS (
    SELECT match_id, player_id, segment_idx
    FROM wool_events WHERE event_type = 6
    GROUP BY match_id, player_id, segment_idx
    HAVING COUNT(DISTINCT wool_id) >= 2
)
SELECT
    COUNT(DISTINCT we.wool_id) AS wools_captured,
    COUNT(*) AS segment_count
FROM multi_touch mt
LEFT JOIN wool_events we ON we.match_id = mt.match_id
    AND we.player_id = mt.player_id
    AND we.segment_idx = mt.segment_idx
    AND we.event_type = 7
GROUP BY mt.match_id, mt.player_id, mt.segment_idx, wools_captured  -- then aggregate
```

#### 4c — Skybridge characterisation (H4)

For each life segment, the skybridge signal is:
```sql
SELECT
    ls.segment_id, ls.match_id, ls.duration,
    COUNT(*) FILTER (WHERE pe.y >= m.max_build_height - 2) AS ticks_at_height,
    COUNT(*) AS total_ticks,
    MAX(pe.y) AS max_y
FROM life_segments ls
JOIN position_events pe ON pe.match_id = ls.match_id
    AND pe.player_id = ls.player_id AND pe.segment_idx = ls.segment_idx
JOIN matches mat ON mat.match_id = ls.match_id
JOIN maps m ON m.map_id = mat.map_id
WHERE m.map_slug = 'arabia'  -- or any 2-wool map
GROUP BY ls.segment_id, ls.match_id, ls.duration, m.max_build_height
HAVING COUNT(*) FILTER (WHERE pe.y >= m.max_build_height - 2) >= 3
```

Combining this with `max_attack_depth` from the traffic features tells us whether
the skybridge actually advanced toward the enemy.

#### 4d — Role distribution shift over match time

For each match, bucket all life segments by `start_timestamp` relative to
`match_duration`, then aggregate role labels within each bucket.  Plotting fraction
of each role over normalised match time (0–1) across many matches on the same map
should reveal the phase transition structure: mostly rushers early, a peak in
defenders mid-game, skybridgers appearing late.

---

## The Snapped Sequence as Primary Signal

The `snapped_sequence` (JSON array of node IDs in `life_segment_traffic_features`)
is the most information-dense field we have for spatial movement.  The full path
reconstruction in `run_traffic_diagnostics.py` is useful for visualisation but is
not needed for most analytical questions.

### What the snapped sequence gives us directly

- **Start node** → which island the player began on (always home)
- **End node** → which island the player died on (`death_region` is a coarser version
  of this)
- **Max penetration** → the node closest to the enemy wool in the sequence,
  already materialised as `max_attack_depth`
- **Island transitions** → by checking consecutive node island_ids (stored in the
  graph JSON), we can identify when a player crossed from one island to another
  and infer they crossed a build region or void gap
- **Node visit frequency** → which nodes are visited most often in a life, and across
  many lives, identifies high-traffic chokepoints on the map
- **Sequence direction** → is attack depth monotonically increasing (committed push),
  oscillating (back-and-forth fighting), or declining after a peak (retreat)?

### What the snapped sequence cannot give us

The traffic graph is 2D (x/z only).  Sky and ground movement at the same x/z snap
to the same nodes.  Two signals require `position_events.y` as a complement:

1. **Skybridge vs ground distinction** — a player crossing at build height and a
   player crossing at map floor level produce identical snapped sequences.  Only y
   separates them.  This affects the SKYBRIDGER and SKY_DEFENDER role assignments.

2. **Drop-down attack signature** — a player who ascends via skybridge then drops
   to enemy territory shows a characteristic y-profile within a single life segment:
   rise near home spawn → plateau at max_build_height → sharp drop near enemy island.
   The snapped sequence will show a valid crossing trajectory with no visible break;
   only the y-profile reveals the transport mode used.  These two signals are
   complementary, not redundant.

### Island transition inference

The node metadata in `traffic_graph.json` stores each node's `island_id`.  Given
the snapped sequence and this lookup, we can reconstruct the sequence of islands
visited per life.  Consecutive ticks on two different islands always imply a crossing
through void or a build region — the `location_type` data in `position_events`
confirms which.

This provides a compact representation: `[home, bridge, bridge, enemy, enemy, bridge,
home]` — a sequence of zone labels rather than individual coordinates.  This is likely
the right level of abstraction for role classification.

### Population-level path lookup tables

An interesting extension: across all matches for a given map, build a lookup table
of **which nodes appear in sequences that also contain a wool capture**.  This
identifies the "wool delivery corridor" — the set of nodes that are part of a
successful capture route.  A player's sequence can then be scored by how much overlap
it has with this set.

Similarly, building a **node co-occurrence matrix** (which nodes tend to appear
together in the same life segment) may reveal natural route clusters — the left-side
attack route vs the right-side route on a symmetric map, for example.

These computations are entirely in-memory with the existing data and do not require
new DB tables.

---

## Match Report Prototype

A match report is the concrete output that unifies all the above.  The target format
is a structured text document (potentially rendered as HTML) covering:

```
MATCH REPORT — Arabia — 2024-MM-DD — 18 min
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Team A (Red)                    Team B (Blue)
  Role distribution:              Role distribution:
    2 Rushers                       1 Rusher
    4 Defenders                     5 Defenders
    1 Skybridger                    1 Skybridger
    2 Roamers                       2 Roamers

Timeline:
  0:00  Match start
  1:30  First push detected (Team A, 3 players)
  2:45  Wool touch: Red Wool (Team B side) — player P3
  8:10  Skybridge activated: Team B (y=78)
 11:20  Wool capture: Yellow Wool captured by Team A
 12:00  Counter-push: Team B, 4 players cross bridge
 15:40  Skybridge captured point: Team A establishes height advantage
 18:00  Match end — Team A wins (2–0)

Key moments:
  - Player P3 (Team A): 3 wool touches in a single life segment (trapped)
  - Player P7 (Team B): highest attack depth (reached yellow wool room)
  - Skybridging phase lasted ~8 minutes (longest of any Arabia match in dataset)
```

This is achievable with the data we have today.  The role labels, timeline events, and
key moments all derive directly from `life_segments`, `wool_events`, `position_events`,
and `life_segment_traffic_features`.  The "trapped" detection (3 touches, same wool,
same life, no capture) is a special case of the carry chain analysis.

---

## Suggested Work Order

### Phase A — Foundation queries (lowest effort, highest validation value)

1. **Wool capture ordering analysis** (H2) — write the SQL, run it across all
   2-wool maps, publish a table of "first-captured wool" by map.  Fast win,
   immediately interesting.

2. **Loop capture search** (H3) — single SQL query.  Verify the result against
   a known match by looking at the raw parquet.  Confirms data quality.

3. **Duration distribution plots** — histogram per map for all 81 maps in a grid.
   Immediately reveals which maps are bimodal.  Use `match_duration` from `matches`.

4. **Death region distribution** across all maps — quick summary of what fraction
   of lives end where.  First sanity check on the classification quality.

### Phase B — Life segment classification

5. **Compute the "zone sequence"** for each segment from `snapped_sequence` +
   graph node island metadata.  Store as a derived column or a small in-memory
   dict.

6. **Implement role classifier** as a Python function that takes a segment row
   (all traffic features + y aggregates) and returns a role label + confidence.
   Test on `pirates_i` first (should be ~100% rushers with some defenders).

7. **Aggregate role distribution per match** and validate manually on 5–10
   Arabia matches.

### Phase C — Time series and match dynamics

8. **Island occupancy time series** — for each match, compute team A vs team B
   occupancy of enemy island at every 10-second bucket.  Produces the "push wave"
   picture.

9. **Skybridge activation time** — compute for all 2-wool maps; plot distribution
   vs match duration.

10. **Carry wave overlay** — integrate `wool_carry_chains` with the above to test
    whether pushes precede successful carries.

### Phase D — Match report prototype

11. **Build the report generator** for a single map (Arabia).  Hard-code the
    thresholds from Phase B, produce a text report for each match.

12. **Review outputs** — read the reports, find the obviously wrong labels, tighten
    the thresholds.

13. **Extend to 5 additional maps** across different size tiers.

---

## Open Questions

1. **Intermediate navigable floors not yet extracted** — the pipeline already
   produces `layout_top_surface.parquet` (surface y), `layout_lowest_solid.parquet`
   (bottom of terrain), and `layout_decided.parquet` (island classifier layer).
   These cover the outer vertical extent of terrain at each (x, z) cell.  What
   is missing is the detection of navigable floors _between_ the surface and the
   lowest solid — needed for tunnel floors and stacked island platforms.  The planned
   solution (Layer 0) is to parse `.mca` region files from `PublicMaps/ctw/golden_drought_v`
   as a ground-truth reference, validated against an empirical proxy derived from
   y-clustering in `position_events`.  Until Layer 0 is available, skybridge detection
   on maps with elevated terrain close to the build limit (like `golden_drought_v`)
   should be treated as approximate.

2. **inv_count is not in `position_events`** — the building/digging signal is
   currently missing from the DB.  It is available in the raw parquet files
   (Minecraft item count is a type-5 event field).  If the analysis needs it,
   a small extraction step can add it.  Deferred for now since the traffic graph
   geometry already provides strong spatial signals.

2. **Held-item data is also not in the DB** — `run_traffic_diagnostics.py` loads
   it from parquet at runtime.  Same situation.  Bow-archer and builder roles
   benefit from this but can be approximated from Y-level and node coverage
   patterns in the meantime.

3. **player_id is match-scoped** — there is no cross-match player tracking.  All
   "player" analysis is per-match.  This is a fundamental constraint of the
   data, not a gap.  Per-map role frequency is meaningful; per-player career
   statistics are not.

4. **Kit and renewable resources not parsed** — the materials available in chests
   determine whether defenders can build a water wall, dig a pit effectively, or
   sustain a skybridge.  Parsing the XML `<kits>` and `<renewables>` modules
   would enable resource-aware role classification and is the most valuable
   unparsed XML gap.

5. **Wool drop on death and safety placement** — knowing whether wool drops on
   death affects how carry chains should be interpreted (a "dropped" wool may be
   picked up by a teammate without a new touch event).  Also deferred.

6. **`wool_spawn_baselines` accuracy** — this table was populated from `map_context.json`
   (XML-derived) rather than `map_wool_locations`.  It is only used in
   `generate_demo.py` and not in the core analysis pipeline.  It should be
   recomputed from `map_wool_locations` before the demo script is used for
   any map where XML wool positions are known to be wrong (e.g. `emergency_meeting`).

---

## Hypotheses Summary Table

| ID | Hypothesis | Maps | Primary signal | Status |
|---|---|---|---|---|
| H1 | First wool captured in first third of 2-wool matches | 2-wool maps | wool_events timestamps | Untested |
| H2 | One wool is structurally easier (consistently captured first) | 2-wool maps | wool_id of first capture, per defending team | Partially confirmed — strong dominance on most maps; spatial left/right classification pending; NULL team data quality issue to resolve |
| H3 | Multi-wool loop captures are rare (<5% of matches) | 2-wool and 4-team | wool_events, same segment_idx | Refuted as stated — multi-touch ubiquitous; genuine double-caps = 15% of multi-touch segments; hypothesis needs reformulation |
| H4 | Long matches correlate with sustained skybridge activity | 2-wool maps, high-stddev | position_events y vs max_build_height | Untested |
| H5 | High-variance maps have bimodal duration distributions | clearcut, brittlebush_ii, etc. | match_duration histogram | Preliminary confirmation — clearcut median 4.8 min vs mean 14.4, brittlebush_ii median 9.4 vs mean 24.3; strongly bimodal pattern |
| H6 | death_region is a reliable role proxy | All maps | life_segment_traffic_features.death_region | Preliminary data: 39% enemy_island, 23% home_island, 21% bridge, 18% void overall; per-map breakdown still needed |
| H7 | Snapped sequence sufficient for role inference (except sky roles) | All maps | snapped_sequence + position_events y for sky roles | Partially validated; y-limitation confirmed |
| H8 | Drop-down attack detectable as rise-plateau-drop y-profile | 2-wool maps | position_events y segmented within life | Untested |
| H9 | Defence accumulation measurable via death_region shift over match time | 2-wool maps, long matches | death_region × match_third | Untested |
| H10 | Skybridge activation precedes first wool capture on long matches | 2-wool maps, >P75 duration | position_events y + wool_events timestamps | Untested |
| H11 | Ground route traversal slows over match time (snapped sequence lengthens) | 2-wool maps, long matches | snapped_sequence length × match stage | Untested |
| H12 | First wool captures by opposing teams tend to be on diagonally opposite flanks | 2-wool maps, both-team-capture matches | wool positions × symmetry_type | Untested |

---

### Wool sharing / safety pickup detection

Wool touch events (event_type=6) occurring within ~40 blocks of the touching
player's spawn and >80 blocks from the wool room position are safety pickups, not
primary touches.  Proximity is computed from `wool_events.(x,z)` vs
`player_team_segments.spawn_x/spawn_z` (joined without timestamp filter — 99.8%
of records have NULL `end_timestamp` so a timestamp-range join silently drops
almost all data).

Preliminary measurement: ~1–2% of all touch events are safety pickups.  They cluster
tightly at 0–30 blocks from spawn with average 100–140 blocks from the wool room.
Small enough not to bias touch-count analysis but detectable and meaningful for
understanding team coordination patterns (raindrop farming, coordinated wool handoffs).

---

_This document is intended to be updated as hypotheses are tested and results accumulate._

_Last analysis run: 2026-03-17._
