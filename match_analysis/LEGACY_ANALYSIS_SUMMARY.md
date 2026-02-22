# Legacy Match Analysis — Summary & Requirements Reference

This document captures everything the deprecated match analysis system
(`match_analysis_DEPRECATED/` and its caller scripts) implemented or
intended to implement.  Use it as a reference when building the
replacement inside `match_analysis/`.

---

## 1  Data Model

### 1.1  Event types

| Code | Name           | Populated columns                                      |
|------|----------------|--------------------------------------------------------|
| 0    | MATCH_START    | timestamp (always 0)                                   |
| 1    | MATCH_END      | timestamp                                              |
| 2    | SPAWN          | timestamp, player_id, x, y, z                          |
| 3    | KILL           | timestamp, player_id, x, y, z, held_item, inventory_count, victim_id |
| 4    | DEATH          | timestamp, player_id, x, y, z                          |
| 5    | POSITION       | timestamp, player_id, x, y, z, held_item, inventory_count |
| 6    | WOOL_TOUCH     | timestamp, player_id, x, y, z, wool_id                 |
| 7    | WOOL_CAPTURE   | timestamp, player_id, x, y, z, wool_id                 |

Position events are sampled every ~5 seconds by the server plugin.
The `victim_id` column was added after the deprecated code was written;
it is populated only for KILL events.

### 1.2  Life segments

A **life segment** represents one contiguous "life" of a player:

    spawn → (positions, kills, wool events, …) → death | match_end | team_switch

Fields stored per segment:

- `player_id`, `segment_id` (auto-incremented per player)
- `spawn_time`, `end_time`, `spawn_coords` (x, y, z)
- `end_reason`: one of `death`, `match_end`, `team_switch`, `incomplete`
- `team`: `red` | `blue` | `unknown`
- `events`: full DataFrame slice of all events in `[spawn_time, end_time]`

Derived counts: `kills`, `deaths`, `wool_touches`, `wool_captures`.

### 1.3  Team assignment

Teams were assigned by clustering spawn points with DBSCAN:

- `eps = 5.0` blocks, `min_samples = 2`
- Only the (x, z) coordinates of spawn events are used (Y ignored).
- The two largest clusters become red and blue.
- **Red** is assigned to whichever cluster has the **lower X coordinate**
  (or lower Z if X values are close).

> **Known limitation:** The axis heuristic (lower X = red) was a guess
> that worked for Tumbleweed.  With XML data now available, team spawn
> locations are known exactly and don't need to be inferred.

---

## 2  Map Characteristics (auto-detected)

The old system derived map geometry from position data at runtime:

| Property             | How it was computed                                           |
|----------------------|---------------------------------------------------------------|
| **Split axis**       | X or Z — whichever axis has the larger gap between red/blue spawn centers |
| **Midpoint**         | Average of red and blue spawn center along the split axis     |
| **Red side**         | Whether red is on the positive or negative side of the midpoint |
| **Skybridge height** | Mode of the top 5 % of Y values across all POSITION events    |
| **Ground level**     | 25th percentile of Y values                                  |
| **Tunnel threshold** | 5th percentile of Y values                                   |

> **Known limitation:** These thresholds are match-specific and fragile.
> With the map context now available (bounding box, island polygons,
> build region, XML spawns/wools), most of these can be replaced with
> deterministic values.

---

## 3  Role Classification

### 3.1  Decision tree (priority order)

The classifier runs through this cascade and picks the first match.
Every branch also stores a confidence score (shown in parentheses).

| Priority | Role                   | Condition                                                         | Confidence |
|----------|------------------------|-------------------------------------------------------------------|------------|
| 1        | WOOL_RUNNER            | `wool_touches > 0` or `wool_captures > 0`                        | 100        |
| 2        | SKYBRIDGE_CONTROLLER   | `skybridge_ratio > 0.7` and `kills >= 2`                         | 90         |
| 3        | ATTACKER_STEALTH       | `tunnel_ratio > 0.5` and `territory_ratio > 0.6`                 | 85         |
| 4        | RUSHER                 | `avg_speed > 3.0` and `territory_ratio > 0.7` and `duration < 120s` | 90      |
| 5        | ATTACKER_AGGRESSIVE    | `territory_ratio > 0.6` and `kills >= 2`                         | 85         |
| 6        | ATTACKER_PASSIVE       | `territory_ratio > 0.6`                                          | 75         |
| 7        | CAMPER                 | `avg_speed < 0.5` and `kills >= 2`                               | 80         |
| 8        | MID_CONTROLLER         | `abs(territory_ratio - 0.5) < 0.2` and `kills >= 1`              | 75         |
| 9        | BASE_DEFENDER          | `own_side_ratio > 0.8` and `max_penetration < 30`                | 80         |
| 10       | DEFENDER               | `own_side_ratio > 0.6`                                           | 70         |
| 11       | FLANKER                | `total_distance > 200` and `0.3 < territory_ratio < 0.7`         | 65         |
| 12       | ROAMER                 | *(fallback)*                                                      | 50         |

### 3.2  Secondary roles (additive, not mutually exclusive)

| Tag              | Condition                                              |
|------------------|--------------------------------------------------------|
| `skybridge_user` | `skybridge_ratio > 0.3` (and primary ≠ SKYBRIDGE_CONTROLLER) |
| `tunneler`       | `tunnel_ratio > 0.2` (and primary ≠ ATTACKER_STEALTH)        |
| `high_kills`     | `kills >= 3` and `kill_rate > 1.0 kills/min`                 |
| `mobile`         | `avg_speed > 2.5 blocks/s`                                   |

### 3.3  Metrics computed per segment

| Metric                  | Definition                                                             |
|-------------------------|------------------------------------------------------------------------|
| `territory_ratio`       | `time_on_enemy_side / duration`                                        |
| `own_side_ratio`        | `time_on_own_side / duration`                                          |
| `skybridge_ratio`       | `time_at_skybridge / duration`                                         |
| `tunnel_ratio`          | `time_tunneling / duration`                                            |
| `total_distance`        | Sum of 3D Euclidean distances between consecutive POSITION events      |
| `avg_speed`             | `total_distance / duration` (blocks/s)                                 |
| `max_penetration_depth` | Greatest distance past midpoint on the enemy side                      |
| `kill_rate`             | `kills / (duration / 60)` (kills/min)                                  |

Position-by-position accumulation:

- **Own side vs enemy side**: uses `MapCharacteristics.is_on_own_side(team, coord)`
  with the auto-detected split axis and midpoint.
- **Skybridge**: `y >= skybridge_height − 1`
- **Tunnel**: `y <= tunnel_threshold`
- **Stationary**: entire segment flagged if `avg_speed < 0.5`

> **Known limitation:** The 5-second position sampling makes speed and
> distance calculations coarse.  A player could sprint 30 blocks and
> return, appearing stationary.

---

## 4  Path Network Analysis

Four complementary techniques were implemented to visualize "highway
networks" of player movement.

### 4.1  Density heatmap

- Collects all (x, z) from POSITION events.
- 2D histogram with configurable `resolution` (default 1.0 block/cell).
- 10-block padding around data extents.
- Output: raw 2D array + world-coordinate bounds.

### 4.2  Skeleton network (morphological centerlines)

1. Gaussian-smooth the density heatmap (`sigma = 2.0`).
2. Binary threshold at the 75th percentile of nonzero values.
3. Morphological skeletonization (`skimage.morphology.skeletonize`).
4. Convert skeleton pixels back to world coordinates.

### 4.3  Waypoint graph (DBSCAN + path edges)

1. Pool all (x, z) positions across all segments.
2. DBSCAN clustering: `eps = 5.0`, `min_samples = 5`.
3. Cluster centers become **waypoints** (graph nodes).
   Node attribute: `visits` = number of positions in that cluster.
4. For each segment's path, assign each position to its nearest
   waypoint (if within `cluster_radius`).
5. Add an edge between consecutive *different* waypoints along a path.
   Edge attribute: `weight` / `traffic` = traversal count.
6. Output: `networkx.Graph`.

### 4.4  High-traffic corridors

1. Density heatmap at `resolution = 2.0`.
2. Gaussian smooth with `sigma = 3.0`.
3. Mask cells above `min_corridor_density = 10.0`.
4. Label connected components (`scipy.ndimage.label`).
5. Discard components smaller than 5 cells.
6. Record `avg_density`, `max_density`, `size` per corridor.
7. Sort by `avg_density` descending.

### 4.5  Major route extraction (incomplete)

- Finds segments whose first 5 positions fall in a `start_region` and
  last 5 positions fall in an `end_region` (bounding-box check).
- Resamples qualifying paths to 20 points (linear index interpolation).
- Returns an evenly-spaced sample of `num_routes` paths.
- **TODO left in code:** proper path clustering with k-medoids and DTW
  distance was planned but never implemented.

### 4.6  Visualization

Six-panel combined plot (20 × 15 inches, 150 DPI):

1. Movement density heatmap (`imshow`, `hot` colormap)
2. Skeleton centerlines (red scatter, size 2)
3. Waypoint graph (nodes sized by visits, edges by weight)
4. High-traffic corridors (colored by density, top 10)
5. Density + skeleton overlay
6. Traffic-weighted network graph

Team-specific plots: 3-panel (density, skeleton, graph) per team,
18 × 6 inches.

---

## 5  Outputs & Reports

### 5.1  Text reports

- **match_summary.txt**: match/map name, player count, segment count,
  team distribution.
- **classification_report.txt**: role distribution table, per-player
  breakdown, example segments per role.  Formatted to 70–80 chars wide.
- **path_network_stats.txt**: total paths, total/avg/median/max
  distance.

### 5.2  CSV exports

- **segment_classifications.csv**: one row per life segment with all
  classification metrics (player_id, segment_id, team, primary_role,
  secondary_roles, time metrics, movement metrics, combat stats).
- **life_segments.csv** (via `export_segments_to_csv`): raw segment
  data without classification.

### 5.3  PDF reports (ReportLab)

- **match_summary.pdf**: match info, overall stats, top 20 player
  table, per-team stats with K/D ratios.
- **classification_report.pdf**: map characteristics table, role
  distribution, role definitions, team role distributions, top players
  per role (top 5 for 6 major roles), example segment details.

### 5.4  Plots (matplotlib, 150 DPI PNG)

| File                              | Content                                 |
|-----------------------------------|-----------------------------------------|
| `all_teams.png`                   | All segments on bedrock map             |
| `red_team.png`                    | Red team segments only                  |
| `blue_team.png`                   | Blue team segments only                 |
| `path_network_combined.png`       | 6-panel network analysis                |
| `path_network_red_team.png`       | 3-panel red team network                |
| `path_network_blue_team.png`      | 3-panel blue team network               |
| Per-role PNGs (12 possible)       | One plot per role (configurable)        |

### 5.5  Interactive visualization

`MatchVisualizer.create_interactive_view()`:

- CheckButtons to toggle kills, deaths, wool events.
- RadioButtons for team filter (All / Red / Blue).
- Redraws on every toggle via matplotlib callbacks.

---

## 6  Configuration (config.json)

The old system used a central `config.json` to drive `generate_plots.py`
and `classify_segments.py`:

```json
{
  "data_files": {
    "map_name": "Tumbleweed",
    "match_file": "2026-01-24_22-24-17_75.parquet"
  },
  "output": {
    "folder": "output",
    "dpi": 150,
    "generate_pdf": true
  },
  "map_settings": { "show_map": true },
  "data_settings": {
    "kills": false,
    "deaths": true,
    "wool_touches": true,
    "wool_captures": true
  },
  "team_settings": {
    "all_teams": true,
    "red_team": true,
    "blue_team": true
  },
  "role_settings": {
    "wool_runner": true,
    "skybridge_controller": true,
    "attacker_stealth": true,
    "rusher": true,
    "attacker_aggressive": true,
    "attacker_passive": true,
    "camper": true,
    "mid_controller": true,
    "base_defender": true,
    "defender": true,
    "flanker": true,
    "roamer": true
  }
}
```

---

## 7  Visual Constants

| Constant              | Value                              |
|-----------------------|------------------------------------|
| Team red              | `#E74C3C`                          |
| Team blue             | `#3498DB`                          |
| Team unknown          | `#95A5A6`                          |
| Spawn marker          | `^` (triangle), green, size 100    |
| Death marker          | `x`, red, size 100                 |
| Kill marker           | `+`, dark red `#8B0000`, size 120  |
| Wool touch marker     | `*`, yellow, size 150              |
| Wool capture marker   | `*`, gold, size 200                |
| Map tile size         | 1.0 block                          |
| Map tile color        | gray, alpha 0.3                    |
| Map tile edge         | black, width 0.3                   |
| Spawn cluster radius  | 5.0 blocks (DBSCAN eps)            |
| Min cluster size      | 2 (DBSCAN min_samples)             |

---

## 8  Dependencies Used

| Library          | Purpose                                          |
|------------------|--------------------------------------------------|
| pandas           | DataFrames, parquet I/O                          |
| numpy            | Distance calculations, histograms                |
| matplotlib       | All plotting, interactive views                  |
| scipy.ndimage    | Gaussian smoothing, connected component labeling |
| skimage          | Morphological skeletonization                    |
| sklearn (DBSCAN) | Spawn clustering, waypoint clustering            |
| networkx         | Waypoint graph representation                   |
| reportlab        | PDF report generation                            |

---

## 9  What We Now Know (and didn't then)

When the deprecated analysis was written, we had only raw parquet
event logs and a bedrock layout.  Since then the pipeline has added:

| New capability               | Implication for match analysis                           |
|------------------------------|----------------------------------------------------------|
| Island polygons & IDs        | Can classify each position as "on island N" or "in void" |
| Skeleton graphs per island   | Can map positions to skeleton edges/nodes                |
| POI annotations (spawns, wools) | Exact spawn/wool locations, no need to infer from data |
| Inter-island connectivity    | Know which islands are adjacent and via which void gaps  |
| Build region / void area     | Know exactly where players can/cannot build              |
| Map bounding box             | Deterministic bounds, no padding heuristics              |
| Team data from XML           | Exact team colors and spawn regions, no DBSCAN needed    |
| DuckDB metadata DB           | Structured match indexing and processing log             |
| `victim_id` on KILL events   | Can reconstruct kill graphs (who killed whom)            |

---

## 10  Ideas & TODOs Found in the Old Code

1. **DTW-based path clustering** (`path_network.py:344`): "Implement
   proper path clustering (e.g., k-medoids with DTW)" for major route
   extraction.

2. **Island-aware positioning**: every position could be tagged with
   `island_id` using the island polygons, enabling "time on island N"
   breakdowns.

3. **Void crossing detection**: using the connectivity graph, detect
   when a player's consecutive positions are on different islands
   (implies a void crossing — bridge, TNT cannon, etc.).

4. **Role classification v2**: replace Y-percentile thresholds with
   island-derived heights; replace midpoint heuristic with XML team
   spawn regions; add wool-carrying state tracking using wool_touch →
   wool_capture sequences.

5. **Kill graph analysis**: with `victim_id`, build a directed
   kill graph to find dominant players, team-fight patterns, and
   revenge kills.

6. **Phase segmentation**: break a match into temporal phases
   (early game, mid game, late game) based on wool capture timing
   or kill rate changes.

---

## 11  Files to Delete

### Root-level caller scripts (import from match_analysis_DEPRECATED)

| File                           | What it did                                     |
|--------------------------------|-------------------------------------------------|
| `analyze_match.py`             | Hardcoded single-match analysis + interactive view |
| `classify_segments.py`         | Role classification pipeline + CSV/PDF export   |
| `explore_map_characteristics.py` | Exploratory Y-distribution and team territory analysis |
| `generate_path_networks.py`    | 6-panel path network visualization              |
| `generate_plots.py`            | config.json-driven team/role plot generation     |

### Package

| Directory                      | Contents                                        |
|--------------------------------|-------------------------------------------------|
| `match_analysis_DEPRECATED/`   | `__init__.py`, `constants.py`, `data_loader.py`, `preprocessing.py`, `utils.py`, `map_renderer.py`, `match_visualizer.py`, `segment_classifier.py`, `pdf_report.py`, `path_network.py`, `path_network_viz.py` |

After deletion, the `ctw match` command handler (`ctw/commands/match.py`)
will also need to be updated — it currently imports from both
`match_analysis.match_queries` and `generate_path_networks` (which itself
imports from `match_analysis_DEPRECATED`).
