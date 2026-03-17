# CTW Match Analysis — Research Roadmap

_Last updated: 2026-03-17_

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

---

## Analysis Modules

The work is structured into four layers, loosely ordered by dependency.

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

```sql
-- For each 2-wool map, which wool_id is captured first, and how often?
SELECT
    m.map_slug,
    mwl.wool_color,
    we.wool_id,
    COUNT(*) AS times_captured_first
FROM wool_events we
JOIN (
    -- rank captures by timestamp within each match
    SELECT match_id, wool_id,
           ROW_NUMBER() OVER (PARTITION BY match_id ORDER BY timestamp) AS rn
    FROM wool_events WHERE event_type = 7
) ranked ON ranked.match_id = we.match_id AND ranked.wool_id = we.wool_id AND ranked.rn = 1
JOIN matches mat ON mat.match_id = we.match_id
JOIN maps m ON m.map_id = mat.map_id
JOIN map_wool_locations mwl ON mwl.map_id = mat.map_id AND mwl.wool_id = we.wool_id
WHERE m.wools_per_team = 2 AND m.team_count = 2
GROUP BY m.map_slug, mwl.wool_color, we.wool_id
ORDER BY m.map_slug, times_captured_first DESC
```

If one wool colour dominates the "first capture" count by a large margin, H2 holds
for that map.  If roughly 50/50, the wools are symmetric in practice.

#### 4b — Multi-wool loop capture detection (H3)

A loop capture by a single player in a single life requires:
1. Touch event on wool_id A (event_type=6, segment_idx=X)
2. Touch event on wool_id B (event_type=6, same segment_idx=X, wool_id ≠ A)
3. No death event between the two touches (same segment_idx confirms this)

```sql
-- Find life segments with touches on 2+ distinct wools
SELECT match_id, player_id, segment_idx, COUNT(DISTINCT wool_id) AS distinct_wools_touched
FROM wool_events
WHERE event_type = 6
GROUP BY match_id, player_id, segment_idx
HAVING COUNT(DISTINCT wool_id) >= 2
```

Followed by checking whether both wool_ids were also captured (event_type=7) in the
same life or a subsequent one.

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

1. **inv_count is not in `position_events`** — the building/digging signal is
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
| H2 | One wool is structurally easier (consistently captured first) | 2-wool maps | wool_id of first capture | Untested |
| H3 | Multi-wool loop captures are rare (<5% of matches) | 2-wool and 4-team | wool_events, same segment_idx | Untested |
| H4 | Long matches correlate with sustained skybridge activity | 2-wool maps, high-stddev | position_events y vs max_build_height | Untested |
| H5 | High-variance maps have bimodal duration distributions | clearcut, brittlebush_ii, etc. | match_duration histogram | Untested |
| H6 | death_region is a reliable role proxy | All maps | life_segment_traffic_features.death_region | Untested |
| H7 | Snapped sequence sufficient for role inference | All maps | life_segment_traffic_features.snapped_sequence | Partially validated by diagnostics |

---

_This document is intended to be updated as hypotheses are tested and results accumulate._
