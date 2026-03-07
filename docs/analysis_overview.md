# Analysis Overview

This document explains, in plain language, what the raw match data looks like,
how the processing pipeline transforms it into structured events, what the
post-processing layer computes on top of that, and what the downstream analysis
notebooks make possible. It is a companion to the schema reference in
`match_analysis/README.md`.

---

## The raw parquet files

Each match produces a single parquet file, written in real time by the
[pgmlogger](https://github.com/rockymine/pgmlogger) Bukkit plugin as the match
plays out on the server. The file contains **one row per event** with exactly
ten columns:

| column | type | notes |
|---|---|---|
| `timestamp` | INT32 | Seconds elapsed since match start (integer, not milliseconds) |
| `event_type` | INT32 | Ordinal code — see table below |
| `player_id` | INT32 | Per-match player identifier (see player IDs below) |
| `x` | INT32 | Block X — floor-cast from the player's floating-point location |
| `y` | INT32 | Block Y |
| `z` | INT32 | Block Z |
| `held_item` | INT32 | Bukkit `Material.ordinal()` of the item in hand |
| `inventory_count` | INT32 | Total item stack count in the player's inventory |
| `victim_id` | INT32 | Only set on KILL rows — refers to the killed player's `player_id` |
| `wool_id` | INT32 | Bukkit `DyeColor.ordinal()` of the wool colour (touch and capture rows only) |

All optional columns are `null` when not applicable to that event type.
There is no yaw, pitch, velocity, health, or team field in the raw file.
`nearest_graph_node`, `location_type`, and `island_id` — visible in the
database — are added by our own processing pipeline, not by the plugin.

### Event types

The `event_type` column stores the zero-based ordinal of a Java enum. The
order is fixed and must never be changed in the plugin source, since the
integer values are what ends up in the parquet file.

| code | name | fired when | notable fields |
|---|---|---|---|
| 0 | MATCH_START | Match begins; always `timestamp = 0` | no position or player |
| 1 | MATCH_END | Match concludes; `timestamp` = total duration in seconds | no position or player |
| 2 | SPAWN | A player spawns or respawns | `player_id`, `x/y/z` of spawn point |
| 3 | KILL | A player lands a kill | `player_id` = killer, `victim_id` = killed, killer's `x/y/z`, `held_item`, `inventory_count` |
| 4 | DEATH | A player dies | `player_id` = victim, victim's `x/y/z`; no held item |
| 5 | POSITION | Periodic position sample | `player_id`, `x/y/z`, `held_item`, `inventory_count` |
| 6 | WOOL_TOUCH | A player picks up a wool block | `player_id`, `wool_id`, `x/y/z` of wool location |
| 7 | WOOL_CAPTURE | A player places wool on their monument | `player_id`, `wool_id`, `x/y/z` of monument |

A death always produces **two rows at the same timestamp**: a DEATH row for the
victim and a KILL row for the killer. If the cause of death is environmental
(fall, void, fire) with no player killer, only the DEATH row is written.

### Position sampling

Position events (type 5) are the densest data in the file and the foundation
of all spatial analysis. The plugin fires them on a Bukkit scheduler task
running every `sampling.interval-ticks` ticks (configurable; default 100 ticks
= 5 seconds; **currently configured at 40 ticks = 2 seconds** on the live
server).

Critically, the plugin **deduplicates by block**: if a player has not moved to
a different block since the last sample tick, their position is silently
skipped. This means quiet periods — a defender camping in one spot — produce
far fewer rows than active play. The position count per life segment is
therefore a weak proxy for activity: it reflects how much a player moved,
not just how long they lived.

### Player IDs

Player IDs are assigned per-match by the plugin, not globally. Two kinds of
ID exist:

- **Permitted players** — those listed in the plugin's `permitted-players.yml`
  consent list — receive **negative IDs**: the first permitted player is `-1`,
  the second `-2`, and so on. These IDs are stable across matches for the same
  physical player.
- **Anonymous players** receive **non-negative sequential IDs** (0, 1, 2, ...)
  assigned in encounter order within the match. The same person playing two
  matches will have different anonymous IDs each time.

This means join operations across matches on `player_id` alone are only valid
for permitted (negative-ID) players.

---

## From raw events to the database

When you run `ctw matches process <match_id>`, the pipeline reads the parquet
file once and runs five extraction steps in sequence, each sharing the same
in-memory DataFrame.

### Life segment extraction

Every SPAWN event starts a life. The nth spawn for a given player is paired
with the nth DEATH event for that player. If a player's final life ends at
match conclusion rather than death, the life is closed at their last recorded
timestamp. The result is one row per life in `life_segments` with:

- `start_timestamp` / `end_timestamp` in seconds
- `outcome`: `'death'` or `'match_end'`
- Summary counts (kills, wool touches, wool captures, position samples) for
  quick aggregate queries without joining child tables

### Combat, wool, and position event extraction

Each event type is filtered from the raw DataFrame and inserted into its own
table with the addition of a `segment_idx` column — the ordinal index of the
life the event falls within, computed via a backward merge-asof on the spawn
table. This lets any event be traced back to the exact life it occurred during.

### Team assignment

The plugin does not log team information directly. Instead, the pipeline infers
team membership from spawn locations: each SPAWN event's `(x, z)` is compared
against the bounding boxes of each team's spawn region (loaded from
`map_spawns`), and the player is assigned to the team whose spawn they appeared
in. This produces `player_team_segments` — time intervals during which a player
belonged to a particular team — which every subsequent query joins against to
label events by team.

### Spatial annotation

After position events are extracted, each position tick is **spatially
classified** using the `PositionClassifier`, which has the full map geometry
loaded from `map_context.json` and `map_graph.json`. For every `(x, z)` pair
the classifier determines:

- **`location_type`** — whether the position falls on `'island'`, `'build_region'`
  (bridge or void corridor), or `'void'` (open air with no region assignment)
- **`island_id`** — which specific island the player is on (when applicable)
- **`nearest_graph_node`** — the ID of the closest skeleton node in the map
  graph, regardless of location type

This annotation step is what makes all of the spatial analysis possible. The
raw parquet knows only `(x, y, z)` integers; the classifier maps those into the
semantic geography of the map.

---

## Post-processing: building derived features

After a match is processed, `run_post_processing` runs automatically (and can
be re-run manually after code changes). It produces three additional tables.

### 1. Wool spawn baselines

For every `(team, wool)` pair, the pipeline computes the Euclidean distance
from that team's spawn center — the geometric mean of all spawn positions —
to the wool's location in the map graph. This distance is stored as
`baseline_distance` in `wool_spawn_baselines`.

It is used as the denominator for **attack depth**: the intuition is that a
player at their own spawn is approximately one baseline distance away from the
enemy wool, so depth normalised by this value gives 0 at spawn and 1 at the
wool room, regardless of how large or small the map is.

### 2. Region visits

The sequence of annotated position ticks for a life is **run-length-encoded**
into contiguous visits to the same region. If a player spends 30 seconds on
their home island, crosses the bridge, and then spends 45 seconds on the enemy
island, that becomes three visits: home → build → enemy.

Each visit record in `life_segment_region_visits` stores:

- **Which region** — `location_type` and `island_id`, plus flags `is_home_island`
  and `is_enemy_island` so queries don't need to cross-reference map metadata
- **Duration** — derived from the timestamps of the first and last ticks in the
  visit
- **Entry and exit nodes** — the `nearest_graph_node` of the first and last
  position ticks of an island visit. These are not the island boundary itself
  but the interior skeleton landmarks nearest to where the player entered and
  left from
- **Node path** — a run-length-deduplicated sequence of all `nearest_graph_node`
  values seen during the visit, stored as JSON. If the raw sequence is
  `[4, 4, 7, 7, 12, 7]`, the stored path is `[4, 7, 12, 7]`. This strips
  repeated dwell at the same node while preserving the direction of movement
  and any backtracking.
- **Bridge corridor annotation** — for build-region visits, `bridge_node_1` is
  the exit node of the preceding island visit and `bridge_node_2` is the entry
  node of the following island visit. This pair uniquely identifies which
  corridor was used.

The reason for this intermediate structure — rather than going directly to
aggregate features — is that it preserves the *sequence* of a life. Individual
visit records can be queried to answer questions like "how did players move
through the island over the course of the match?" or "which corridors were used
before a successful capture?" without re-running the full position stream.

### 3. Life segment features

The final step aggregates all region visits for a life into a single summary
row in `life_segment_features`. This is the table that feeds the clustering
notebook.

---

## Feature definitions

### The skeleton graph and node types

Before explaining individual features, it helps to understand the map graph
that underpins the node-path metrics. Each CTW map has a skeleton graph derived
from the map's block geometry and saved to `map_graph.json`. Nodes in this
graph represent significant navigational landmarks on each island, and edges
represent corridors between them.

Nodes are classified by their **degree** — the number of edges connecting them:

- **Endpoint nodes** (degree 1) are leaf nodes sitting at the outermost
  reachable edge of an island. They are the first things a player encounters
  when stepping off a bridge, and the last position a defender can occupy
  before being pushed deeper.
- **Junction nodes** (degree ≥ 3) are interior branching points. Reaching one
  means the player has moved past the island entrance and committed to the
  interior — past whatever chokepoint guards the wool room.

This distinction is important because many interactions in CTW happen at
endpoints: attackers and defenders meet at the island entrance. A player who
only ever visits endpoint nodes is skirting the perimeter; one who consistently
reaches junction nodes is penetrating the interior.

### Time-fraction features

The four `frac_time_*` columns divide a life into mutually exclusive geographic
buckets based on where each position sample was taken:

| feature | what it counts |
|---|---|
| `frac_time_home_island` | Time on the player's own spawn island |
| `frac_time_enemy_island` | Time on the opposing team's island |
| `frac_time_neutral_island` | Time on unowned mid-map islands |
| `frac_time_build` | Time in bridge or void corridors between islands |

Because position samples are deduplicated by block (a stationary player
produces no samples), these fractions reflect *movement* as well as presence.
A player who stands still the entire life in one region will register zero
position samples for other regions, but their single region will also
accumulate fewer samples per unit time than an actively moving player.
Interpreting these features requires keeping that in mind: they are not
wall-clock fractions, they are sampling-weighted fractions.

### Attack depth

For every position sample, the pipeline computes how close the player was to
each enemy wool they must capture:

```
depth(W) = clip(1 − dist(player, wool_W) / baseline_distance_W, 0, 1)
```

A player at their own spawn scores ≈ 0 (they are roughly one baseline distance
away). A player standing at the wool scores ≈ 1. The clip prevents negative
values for players who somehow end up farther from the wool than their spawn
(e.g. on a neutral island beyond the enemy base).

For matches with two enemy wools, the depth at each sample is the **maximum
across both wools** — the measure captures "how deep toward any objective" the
player pushed, not a specific one. The per-wool depth is computed separately in
the wool dynamics notebook when needed.

**`max_attack_depth`** in `life_segment_features` is the peak of this value
across all samples in the life. It answers "how far did this player push at
their furthest point?" It is a ceiling measure, not an average: one lucky rush
to the wool room gives a high score even if the rest of the life was spent at
home. The node-path consistency features below address this.

### Time to first departure

`time_to_first_departure_s` is the number of seconds between a player's spawn
and the first position sample that falls outside their home island. A player
who never left gets `NULL`.

In the clustering notebook this null is **imputed with `duration_s`** (the
life's full length), making it read as "departed at the very last moment." The
derived `departure_frac = time_to_first_departure_s / duration_s` then runs
from 0 (left home immediately) to 1 (never left or left only at the end). This
keeps the feature continuous without a special null class.

### Derived features (computed in the clustering notebook)

Four features are computed at analysis time rather than stored in the database.
This is intentional: imputation choices and normalisation denominators may
evolve, and recomputing from the stored primitives is fast.

| feature | formula | what it captures |
|---|---|---|
| `kill_rate` | `kills / duration_s` | Combat output per second of life, comparable across lives of different lengths |
| `departure_frac` | `time_to_first_departure_s / duration_s`, clipped [0,1] | How quickly the player left home; 1 = never left |
| `aggression` | `kill_on_enemy_island / kills` (0 when no kills) | Whether fighting happens on offense (deep) or defense (home) |
| `mobility_rate` | `n_transitions / duration_s` | How frequently the player crossed regional boundaries per second |

### Node-path features

These nine metrics require the skeleton graph to interpret the `node_path`,
`entry_node`, and `exit_node` fields in the region visit table.

**`visited_junction`** — A boolean: did the player reach any junction node
(degree ≥ 3) at any point during the life? This is the coarsest measure of
interior penetration. A player who never reached a junction was always at or
near the island perimeter — fighting at the entrance corridor, never pushing
through to the wool room.

**`frac_island_visits_with_junction`** — Of all island visits in the life,
what fraction contained at least one junction node in the node path? This
refines `visited_junction` by capturing *consistency*. A player who reached
the interior on 9 out of 10 visits is genuinely dominant deep; a player who
managed it once in ten visits happened upon a lucky gap. This feature is also
less susceptible to `max_attack_depth`'s ceiling effect.

**`max_node_degree_visited`** — The highest skeleton node degree encountered
across the whole life. High degree signals access to heavily connected interior
nodes that typically only occur deep inside the island.

**`traversal_rate`** — Fraction of island visits where the entry node and the
exit node differ. A player who lands on the island, stands still, gets killed,
and respawns has `entry_node == exit_node` for every visit — traversal rate 0.
A player who moves through the island before dying or leaving scores near 1.
This distinguishes campers from movers independently of how deep they went.

**`avg_nodes_per_island_visit`** — Mean count of unique skeleton nodes
encountered per island visit. Complements traversal rate by measuring spatial
coverage rather than just "did they move at all?"

**`died_at_endpoint`** — For lives that ended in a death while on an island:
`True` if the fatal position was nearest an endpoint node (island perimeter),
`False` if nearest a junction (island interior). `NULL` if the player did not
die on an island. This distinguishes defenders killed holding the island edge
from attackers killed after reaching the wool room.

**`n_unique_corridors`** — The number of distinct `(bridge_node_1,
bridge_node_2)` bridge-corridor pairs used across all build-region visits in
the life. A player who always uses the same bridge approach scores 1; a player
who explores multiple routes scores higher. This is more granular than
`n_build_regions_visited`, which groups all approaches between the same island
pair together regardless of which entry point was used.

**`position_entropy`** — Shannon entropy (in bits) of the node-visit frequency
distribution across the life. Every time the player is nearest a given skeleton
node, that node's count increments. Entropy over the resulting distribution
quantifies spatial diversity. High entropy means the player spread their time
across many nodes (roamer). Low entropy means most time was spent at a single
node (camper). A defender sitting at the monument will have entropy near zero;
a carrier sprinting through the enemy island to the wool room will have higher
entropy.

**`dominant_node_frac`** — The fraction of all node appearances accounted for
by the single most-visited node. This is the direct inverse of entropy and is
stored alongside it as a more interpretable version of the same signal: a value
near 1 identifies a player who barely moved from one spot, regardless of whether
that spot was home base or the enemy wool room.

---

## What the features enable: life segment clustering

The eleven features per life — 8 region-level and 3 node-path — serve as input
to the clustering notebook, which uses K-Means to discover **behavioural
archetypes**: recurring patterns of play that generalise across maps and matches.

The clustering pipeline:

1. **Imputes nulls** — `time_to_first_departure_s` and node-path fields that are
   null for lives with no island visits are filled with meaningful defaults
   before any modelling.
2. **Standardises** all features to zero mean and unit variance, so that features
   with large absolute ranges don't dominate the Euclidean distance metric.
3. **Runs PCA** for visualisation and as dimensionality reduction for the HDBSCAN
   variant. Inspecting the scree plot shows how many independent dimensions of
   variation the data actually has.
4. **Scans k from 2 to 9** using elbow (inertia) and silhouette score plots to
   identify the natural number of clusters.
5. **Fits the final K-Means model** and assigns a `cluster_id` to every life.
6. **Writes cluster labels back** to `life_segment_features` in the database, so
   downstream SQL can filter and join by archetype.

### What archetypes emerge at k=5

Across 2,318 life segments from three maps (annealing_iv, tumbleweed,
outback_outback_edition), five stable archetypes appear:

**Defender** (~44% of lives) — `frac_time_home_island` near 0.93; `departure_frac`
near 1.0; low `max_attack_depth` (~0.26); very low traversal and entropy. This
player almost never leaves their home island. They are guarding the monument
or holding the wool entrance corridor. The archetype's dominance by count
reflects the reality that in most CTW matches, most players spend most lives
on defense.

**Attacker** (~34%) — meaningful `frac_time_enemy_island` (~0.33); pushes
reasonably deep (`max_attack_depth` ~0.69); moderate junction penetration and
traversal. This is the standard forward player who makes the journey to the
enemy base but does not necessarily reach or contest the wool room interior.
They account for most wool touches but fewer captures than the deep-attacker.

**Deep-attacker** (~11%) — high `max_attack_depth` (~0.76) *and* consistently
high `frac_island_visits_with_junction`, meaning the depth is not incidental.
High `frac_time_enemy_island` (~0.60), high `kill_rate`, high traversal rate.
This player commits into the enemy island every time they visit, fights in the
interior, and is the primary engine of objective play. They represent the
attacking role in its most effective form.

**Bridge-fighter** (~10%) — most of the life spent in `frac_time_build`
(~0.55); moderate `max_attack_depth` reached from the bridge without dwelling
on enemy ground; low junction visits. This player contests the mid-map
corridors and the space between islands rather than pushing through to the
objective. Distinct from the attacker archetype precisely because they do not
spend time on the enemy island. They may be denying bridge access, escorting
carriers across, or simply fighting in the void.

**Outlier** (<1%) — near-zero presence in all region types. Likely neutral-
island traversal, team-change edge cases, or very short lives with no
interpretable trajectory. Treated as unclassified.

### What the archetypes enable

Once labels are in the database they can be joined against any event table:

- What fraction of wool captures were preceded by a `deep-attacker` life from
  the same team in the preceding two minutes?
- Do teams shift toward defender-heavy play as the match approaches a scoring
  event (a capture that brings them close to winning)?
- Which maps produce a higher proportion of `bridge-fighter` lives, suggesting
  mid-map control is the dominant strategic axis on that layout?
- Does losing a `deep-attacker` to death correlate with a measurable dip in
  team attack depth in the following minute?

---

## Match time series analysis (`match_time_series.ipynb`)

Where clustering characterises individual lives, the time series notebook looks
at the **continuous evolution of the match as a whole**.

### Attack depth over time

The match is divided into 60-second time buckets. For every position sample in
a bucket, attack depth is computed as above (maximum over enemy wools,
normalised by baseline distance). The bucket value is the **mean attack depth
across all samples from all players of that team in that minute**, with a
±1-standard-deviation band showing spread.

The resulting series answers: "how much collective pressure did this team
sustain on the enemy objective each minute?" Rising depth signals a push;
falling depth signals retreat or attrition. Wool touch and capture events are
overlaid as markers so that objective plays can be correlated with pressure
spikes.

Because positions are only sampled every 2 seconds and deduplicated by block,
each bucket typically contains on the order of one sample per active player per
~2–3 seconds. The mean smooths over individual player variation; the shading
band captures team-level disagreement (some players pushing, others hanging
back).

### Aggregate view across multiple matches

When multiple matches on the same map are available, the notebook normalises
time to `[0, 1]` and overlays all matches simultaneously. Individual match
traces appear as faint lines; the bold line is the per-bucket median; the band
is the 25th–75th percentile. This shows the *typical* pressure trajectory for
each team on a given map — whether pressure tends to build monotonically,
whether there is a characteristic mid-match dip, or whether one team
consistently dominates throughout.

### Push-pull score

For each match the notebook computes the **Pearson correlation** between Team
A's and Team B's mean attack-depth series over normalised time. This single
number summarises the macro dynamic of the match:

- **Negative** — the teams are anti-correlated: one surges when the other
  retreats. Classic alternating push-and-defend. Higher absolute negative
  values indicate more structured back-and-forth.
- **Near zero** — the teams move independently. One may dominate while the
  other is passive, or both may be stagnant.
- **Positive** — both teams attack simultaneously. This can mean a chaotic
  high-intensity match where neither team defends properly, or a structured
  mid-map clash where both teams push at the same time.

The push-pull score is a lightweight map-quality heuristic: a map with
consistently negative scores is generating dynamic, interactive matches.
A map with scores near zero may have a structural issue encouraging passive play
— perhaps defense is too easy, or the path to the enemy is too long.

---

## Wool dynamics analysis (`wool_dynamics.ipynb`)

The wool dynamics notebook focuses on the objective layer specifically: which
wool is under pressure when, how carry attempts unfold, and how the map's
vertical geometry influences movement.

### Per-wool node coverage

In CTW, defenders cannot enter their own wool rooms. They must hold the
entrance corridor — the skeleton edge leading to the wool room's node — from
outside. The node coverage chart counts, per 60-second bucket, how many
position samples the defending and attacking teams each accumulated at the
wool room's skeleton node.

A sustained defender presence suppresses captures; a gap in coverage
is a vulnerability window. Overlaid wool touch and capture markers show
whether those vulnerability windows were exploited. A touch that occurs
immediately after the defender leaves is visible as a marker following a
coverage drop.

### Y-level phase detection

Many CTW maps have a **skybridge** — a platform or network of paths built at or
near `max_build_height` that offers a faster, higher-risk route to the enemy
base. Once teams build and start using the skybridge, the distribution of player
Y coordinates becomes bimodal: a ground-level cluster and a skybridge-level
cluster.

The notebook plots the **rolling 5-minute median Y** per team across match time.
An upward step in the median marks the moment the skybridge became the dominant
route. The right-hand panel compares the Y histogram for the first and last ten
minutes of the match, confirming (or disconfirming) the bimodal structure and
estimating when the transition happened.

This matters because skybridge approaches to the wool produce fundamentally
different carry chain profiles from ground approaches. Skybridge routes are
faster end-to-end but require crossing an exposed elevated path with no cover
from fall-kills, making the carrier vulnerable to a single well-timed punch.
Ground approaches are slower but more sheltered. Detecting which phase a match
is in provides context for interpreting the carry chain timeline.

### Per-wool attack depth

The `max_attack_depth` in `life_segment_features` takes the maximum over *all*
enemy wools. When a team faces two wools they must capture, this feature
obscures *which* one is under pressure. The wool dynamics notebook computes
independent depth series for each objective:

```
depth_W(t) = clip(1 − dist(player, wool_W) / baseline_W, 0, 1)
```

averaged over all position samples from all players of the attacking team in
each 60-second bucket.

When the two depth series for the same attacking team diverge — one high and
sustained, one near zero — it reveals the **forced single defence** dynamic:
the defending team has concentrated all their players on one wool entrance,
leaving the other structurally exposed. Defenders face a genuine dilemma when
they do not have enough players to hold both wool rooms simultaneously. Seeing
this divergence emerge and then watching whether it correlates with a capture
on the neglected wool is one of the more revealing patterns the notebook
exposes.

### Carry chain timeline

Each wool carry "wave" is reconstructed from the touch event stream. Touches on
the same wool within `CARRY_WAVE_GAP_S` seconds of each other (default 120 s)
are grouped into a single wave — a coordinated carry attempt. A gap longer than
120 seconds indicates the wool was dropped and the attacking team reorganised
before the next attempt.

For each wave the notebook records:

- **Outcome** — `captured` (wool placed on monument), `dropped_land` (carrier
  died on solid ground and wool returned to its room), `dropped_void` (carrier
  fell to their death and the wool returned), or `incomplete` (wave still
  ongoing at match end or could not be resolved)
- **Number of handoffs** — how many different players touched the wool during
  the wave; multiple handoffs indicate the carrier died and a teammate
  immediately re-touched before the wool respawned
- **Approach type** — whether the first carrier's Y in the 60 seconds before
  the touch was at or above the skybridge threshold (`skybridge`) or below it
  (`ground`)

Waves are drawn as a Gantt-style timeline with one row per wool, coloured by
the attacking team. Capture waves get a gold star at their endpoint; void drops
get a cross; hatch patterns distinguish the other outcomes. This makes it
immediately visible how many attempts each wool took, whether captures came
from skybridge or ground approaches, and how long individual attempts lasted.
