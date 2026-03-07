# Analysis Overview

This document explains, in plain language, what the post-processing pipeline computes,
why each variable is defined the way it is, and what the downstream analysis notebooks
make possible. It is a companion to the schema reference in `match_analysis/README.md`.

---

## The raw data

A match log (parquet file) records discrete events: player positions sampled every few
ticks, deaths, wool touches, wool captures, and team changes. After indexing and
processing a match, the pipeline populates the event tables — `position_events`,
`combat_events`, `wool_events`, `player_team_segments` — and segments each player's
continuous play into **life segments**: one row per life, from spawn to death or match
end.

Post-processing then builds three layers on top of those raw events:

1. Baseline distances — a reference scale for spatial normalisation
2. Region visits — a compact, structured summary of where each life was spent
3. Life segment features — one summary row per life, ready for analysis and clustering

---

## Post-processing: what happens and why

### 1. Wool spawn baselines

The first thing post-processing computes for each match is the set of **wool spawn
baselines**. For every `(team, wool)` pair, this is the Euclidean distance from that
team's spawn center (averaged over all spawn positions in the `map_spawns` table) to
the enemy wool's location in the map graph.

This distance becomes the denominator for **attack depth**: the idea is that a player
sitting at their own spawn is at distance ≈ baseline from the enemy wool, so they get
a depth score of 0. A player standing at the wool room gets a depth score close to 1.
The baseline makes this measure comparable across maps of different physical sizes and
layouts.

### 2. Region visits

The raw position event stream is a dense sequence of `(x, y, z, timestamp)` ticks.
Rather than work with individual ticks, post-processing **run-length-encodes** each
player's trajectory within a life into a sequence of contiguous *region visits*. A
region visit is a maximal span of consecutive ticks in the same spatial region:
`home_island`, `enemy_island`, `neutral_island`, or `build_region` (the bridge and
void corridors between islands).

Each visit record captures:

- Which region was visited (and whether it is home or enemy territory)
- When it started and ended (giving visit duration)
- The **entry node** and **exit node** — the nearest skeleton graph nodes at the start
  and end of the visit. These are not where the player stepped in and out at the
  island boundary, but which interior navigation landmark they were closest to at
  those moments.
- The **node path** — a deduplicated, run-length-encoded sequence of skeleton node IDs
  seen during the visit. If a player moves through nodes 4 → 7 → 7 → 12 → 7, the
  stored path is `[4, 7, 12, 7]`, capturing direction changes without redundant repeats.

For build-region visits (bridge crossings), the visit is annotated with the exit node
of the preceding island visit and the entry node of the following island visit. This
pair — `bridge_node_1` and `bridge_node_2` — identifies exactly which corridor was
used, independently of which island was the origin and which the destination.

The skeleton graph itself (`map_graph.json`) classifies each node by degree:
- **Endpoint nodes** (degree 1) are leaf nodes at the outer edge of an island — the
  easiest parts to reach from the bridge entrance.
- **Junction nodes** (degree ≥ 3) are interior branching points — reaching one means
  the player has committed deep into the island, past the chokepoint at the entrance.

### 3. Life segment features

Once all visits for a life are computed, the feature extraction step aggregates them
into a single summary row in `life_segment_features`. These features are the inputs to
the clustering notebook.

---

## Feature definitions

### Time-fraction features

The four `frac_time_*` columns divide the life's duration into mutually exclusive
buckets based on where each tick was spent:

| Feature | What it counts |
|---|---|
| `frac_time_home_island` | Time on the player's own team island |
| `frac_time_enemy_island` | Time on the opposing team's island |
| `frac_time_neutral_island` | Time on unowned mid-map islands |
| `frac_time_build` | Time in bridge or void regions between islands |

These sum to approximately 1 (small residuals arise from ticks not assigned to any
region). Together they describe how a player *distributes* their life across the map —
a defender will have `frac_time_home_island` near 1, an aggressive attacker will have
high `frac_time_enemy_island`, and a bridge-fighter will have high `frac_time_build`.

### Attack depth

For every position tick, the pipeline computes:

```
depth(W) = clip(1 − dist(player, wool_W) / baseline_distance_W, 0, 1)
```

for every enemy wool `W` that the player's team must capture. The result is clipped to
`[0, 1]`: a player far from all enemy wools gets 0, a player at the wool room gets
close to 1.

The **per-life `max_attack_depth`** is then the maximum of this value across all ticks
and all enemy wools during the life. It answers: "how far toward any enemy objective
did this player push at their deepest point?"

Note that `max_attack_depth` is a peak measure, not a mean — one brief rush to the
wool room will give a high score even if the rest of the life was spent at home. The
node-path features introduced later address this limitation.

### Time to first departure

`time_to_first_departure_s` records how many seconds elapsed from spawn before the
player left their home island for the first time. If they never left, it is `NULL`.

In the clustering notebook this is **imputed** with `duration_s` (the full life
length) so that players who never departed read as having "departed at the very end"
— a value of 1.0 in the derived `departure_frac` feature. This keeps the feature
continuous and avoids special-casing nulls in the clustering algorithm.

### Derived features (computed in the clustering notebook)

Four additional features are computed from the stored columns at clustering time rather
than in post-processing, because they depend on imputation and normalisation choices
that may change between experiments:

| Feature | Formula | Interpretation |
|---|---|---|
| `kill_rate` | `kills / duration_s` | Killing efficiency, independent of life length |
| `departure_frac` | `time_to_first_departure_s / duration_s`, clipped to [0,1] | 0 = left immediately; 1 = never left home |
| `aggression` | `kill_on_enemy_island / kills` (0 when kills=0) | Whether kills happen on offense vs. defense |
| `mobility_rate` | `n_transitions / duration_s` | How frequently the player crossed regional boundaries |

### Node-path features

These nine metrics are derived from the `node_path`, `entry_node`, `exit_node`, and
`bridge_node_1/2` columns in the region visit table. They require `map_graph.json` to
be available so that each global node ID can be looked up for its degree and type.

| Feature | What it measures |
|---|---|
| `visited_junction` | Did the player reach any junction node (degree ≥ 3) at all during the life? A boolean proxy for interior island penetration. |
| `frac_island_visits_with_junction` | Of all island visits in this life, what fraction contained at least one junction node? Captures *consistency* of deep play — a player who reaches the interior every time scores higher than one who got lucky once. |
| `max_node_degree_visited` | The highest skeleton-node degree seen during the life. Higher degree → deeper interior access. |
| `traversal_rate` | Fraction of island visits where the entry node and exit node differ — the player moved through the island rather than sitting still. Static campers score 0; active movers score near 1. |
| `avg_nodes_per_island_visit` | Average count of unique skeleton nodes visited per island visit. Complements traversal rate with an absolute coverage measure. |
| `died_at_endpoint` | For lives that ended in a death on an island: `True` if the death happened at a leaf (endpoint) node, `False` if at a junction. `NULL` if the player did not die on an island. This distinguishes defenders killed at the island edge from those killed deep inside. |
| `n_unique_corridors` | Number of distinct `(bridge_node_1, bridge_node_2)` corridor pairs used during the life. More granular than `n_build_regions_visited` — two bridge crossings using different entry points count separately. |
| `position_entropy` | Shannon entropy (in bits) of the frequency distribution of skeleton node visits across the life. High entropy = spatial variety (roamer); low entropy = concentrated at one node (camper). |
| `dominant_node_frac` | The fraction of all node appearances accounted for by the single most-visited node. This is the direct inverse of entropy: a value close to 1.0 identifies a player who barely moved from one spot. |

---

## What the features enable: life segment clustering

With 11 features per life — 8 region-level and 3 node-path — the clustering notebook
runs K-Means to discover **behavioural archetypes**: recurring patterns of play that
appear across different maps and matches.

The clustering pipeline:

1. **Standardises** all features to zero mean and unit variance (StandardScaler), so
   that features with large absolute ranges don't dominate the distance metric.
2. **Runs PCA** to visualise the variance structure and choose a sensible number of
   principal components for the HDBSCAN fallback.
3. **Scans k from 2 to 9** (elbow and silhouette criteria) to identify the optimal
   number of clusters for K-Means.
4. **Fits the final model** and assigns a `cluster_id` to every life segment.
5. **Writes labels back** to `life_segment_features`, so downstream SQL queries can
   filter by archetype.

### What archetypes look like at k=5

Across 2,318 life segments from three maps, k=5 produces the following profiles:

**Defender** (~44% of lives) — almost all time on home island; `departure_frac` near
1.0; low `max_attack_depth`; low traversal and entropy. This player rarely leaves the
base and is either holding the monument or camping the wool entrance. The most common
archetype by a large margin.

**Attacker** (~34%) — meaningful time on enemy island; pushes reasonably deep
(`max_attack_depth` ~0.7); moderate junction penetration and traversal. This is the
standard forward player who travels to the enemy base but may not always reach the
wool room interior.

**Deep-attacker** (~11%) — high `max_attack_depth` (~0.76), high `frac_time_enemy_island`
(~0.60), high `kill_rate`, and consistently high junction penetration and traversal
rate. This player not only reaches the enemy island frequently but commits into the
interior every time, fights there, and accounts for the majority of kills on offense.

**Bridge-fighter** (~10%) — most of the life spent in `frac_time_build` (~0.55);
moderate attack depth reached from the bridge without sustained island presence; low
junction visits. This player contests the mid-map corridor rather than pushing through
to the island. Distinct from attackers because they don't dwell on enemy ground.

**Outlier** (<1%) — near-zero presence in all region types; likely neutral-island
traversal or edge cases where team assignment failed. Treated as unclassified.

### What the archetypes enable

Once cluster labels are written back to the database, they can be joined against any
event table to ask questions like:

- What fraction of wool captures were preceded by a `deep-attacker` life from the same
  team in the same time window?
- How does the archetype distribution shift over match time — do teams move toward
  defender-heavy play as they approach a win?
- Which maps produce a higher proportion of bridge-fighter lives, suggesting mid-map
  control is the dominant strategic axis?
- Does a team that loses a `deep-attacker` to death see a measurable dip in attack
  depth in the following minutes?

---

## Match time series analysis

The `match_time_series.ipynb` notebook takes a different perspective from clustering:
instead of summarising individual lives, it looks at the **continuous evolution of a
match over time**.

### Attack depth over time

The match is divided into 60-second buckets. For every tick in a bucket, attack depth
is computed exactly as above (using `wool_spawn_baselines` for normalisation). The
bucket value is the **mean attack depth** across all ticks by all players of that team
in that window, plus a ±1-standard-deviation shading band.

This turns the match into a time series: "how much pressure did this team sustain on
the enemy objective each minute?" Wool touch and capture events are overlaid as markers
so that objective plays can be correlated with pressure spikes.

### Aggregate view across multiple matches

When multiple matches on the same map are available, the notebook normalises time to
`[0, 1]` and overlays all matches simultaneously. Individual match traces appear as
faint lines; the bold line is the median; the band is the 25th–75th percentile. This
shows the *typical* pressure trajectory for each team on that map — some maps settle
into a mid-game standoff before one team breaks through; others see immediate
escalation; others are consistently lopsided.

### Push-pull score

For each match, the notebook computes the **Pearson correlation** between Team A's and
Team B's mean attack-depth series over normalised time. This single number summarises
the macro dynamics of the match:

- **Negative** — the teams are anti-correlated: one team surges exactly when the other
  retreats. Classic back-and-forth play. Higher absolute negative values indicate more
  structured alternating pushes.
- **Near zero** — the teams move independently: one may dominate while the other is
  stagnant, or both are camped at home.
- **Positive** — both teams press simultaneously. This either means simultaneous
  escalation (chaotic, high-intensity) or both sides mounting pressure in parallel.

The push-pull score is a lightweight map-quality heuristic: a map with a consistently
negative push-pull score across its matches is producing dynamic, interactive gameplay;
a map with scores near zero may have a structural problem that encourages passive play.

---

## Wool dynamics analysis

The `wool_dynamics.ipynb` notebook focuses on the objective layer specifically, going
beyond the unified attack-depth metric to understand *which* wool is under pressure,
*how* carry attempts unfold, and *whether* the map's vertical structure changes how
teams move.

### Per-wool node coverage

In Capture the Wool, defenders cannot enter their own wool rooms — they must hold the
entrance corridor. The node coverage plot counts, per 60-second bucket, how many ticks
the defending and attacking teams each spent at the wool room's skeleton node. Gaps in
the defender's coverage are moments of vulnerability; sustained attacker presence at
that node signals an active push. Wool touch and capture markers show whether those
pressure moments converted into objective events.

### Y-level phase detection

Many CTW maps have a skybridge — a platform or network of paths built at or above
`max_build_height` — that offers a faster, higher-risk route to the enemy base. Once
teams discover the skybridge route, the distribution of player Y coordinates shifts
upward and becomes bimodal: a ground-level cluster and a skybridge-level cluster.

The notebook plots a rolling 5-minute median Y for each team across match time. An
upward shift marks the start of the skybridge phase. The right-hand panel shows the Y
histogram for the early game versus the final ten minutes, confirming (or disconfirming)
the bimodal structure. This matters because skybridge approaches produce different carry
chain patterns from ground approaches — they are faster but require more coordination
and are more exposed to fall-kills.

### Per-wool attack depth

The `max_attack_depth` in `life_segment_features` takes the maximum over *all* enemy
wools. This is correct for characterising how far a player pushed, but it obscures
*which* wool was under pressure. The wool dynamics notebook computes independent depth
series for each wool objective:

```
depth_W(t) = clip(1 − dist(player, wool_W) / baseline_W, 0, 1)
```

averaged over all players of the attacking team in each 60-second bucket. When the two
depth series for the same attacking team diverge — one high, one flat — it reveals the
"forced single defence" dynamic: defenders have committed entirely to protecting one
wool, leaving the other structurally exposed. The timing of this divergence and whether
it correlates with captures is a key signal of strategic decision-making.

### Carry chain timeline

Each wool carry attempt (a "wave") is reconstructed from the raw touch event stream.
Touches on the same wool within `CARRY_WAVE_GAP_S` seconds of each other (default:
120 s) are grouped into a single wave. For each wave the notebook records:

- **Start and end time** (first touch to capture, death, or match end)
- **Outcome** — captured, dropped on land, dropped into void, or incomplete
- **Number of handoffs** — how many different players touched the wool during the wave
- **Approach type** — whether the first carrier's Y coordinate in the 60 seconds before
  the touch was at or above the skybridge threshold (classified as `skybridge`) or below
  it (`ground`)

These waves are drawn as a Gantt-style timeline, one row per wool, coloured by the
attacking team. A captured wave gets a gold star; a void drop gets a cross. Hatch
patterns distinguish outcomes. This makes it visually immediate which wools were
contested, when, and with what result — and whether skybridge approaches were more
effective than ground approaches on this map.
