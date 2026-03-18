# Match Analysis Database

## Overview

All match and map metadata lives in a single DuckDB database at `match_analysis/metadata.db`. The database is populated through a series of CLI commands that must be run in a specific order due to foreign key dependencies.

## Setup Workflow

```
0. Initialize database      python match_analysis/database/schema.py
1. Preprocess maps          ctw run --map <name>
2. Load map metadata        ctw maps load
3. Load spawn data          ctw maps spawns
4. Load resource data       ctw maps resources --map <name>   (optional)
5. Parse match logs         ctw matches parse ...   (or: ctw matches scan ...)
6. Index matches            ctw matches index ...
7. Process matches          ctw matches process-all --map-name <name>
8. Post-process features    runs automatically inside step 7; re-run with:
                            ctw matches post-process --all
9. Build traffic graph      ctw matches traffic-graph --map <name>
                            (also populates life_segment_traffic_features)
9a. Update wool data        ctw matches update-wool-locations --map <name>
                            (populates map_wool_locations, map_wool_monuments,
                            map_wool_objectives; runs automatically in step 9)
9b. Spatial relations       ctw maps spatial-relations --map <name>
                            (populates map_wool_attack_relations, map_team_spatial;
                            requires steps 3 and 9a)
10. Cluster archetypes      notebooks/life_segment_clustering.ipynb
```

### Step 0: Initialize the database

If starting fresh or after schema changes, create the empty tables:

```bash
python match_analysis/database/schema.py
```

This is idempotent — existing tables are not recreated.

#### Migrating an existing database

If you have an existing database that predates a schema addition, use the migration helpers in `match_analysis/database/schema.py`. Each is safe to run on an already-migrated database.

| Migration function | What it adds |
|-------------------|-------------|
| `migrate_map_classification_columns()` | `wools_per_team`, `max_players_per_team`, `total_blocks`, `size_tier`, `symmetry_type`, `has_intra_team_symmetry` to `maps` |
| `migrate_traffic_graph_tables()` | Splits old `life_segment_features` TABLE into `life_segment_summary` + `life_segment_skeleton_features` + `life_segment_traffic_features`; recreates `life_segment_features` as a backward-compat VIEW; adds `traffic_graph_match_hash` / `traffic_graph_built_at` to `maps`. **Drops old data — re-run post-processing afterwards.** |
| `migrate_log_interval_column()` | `log_interval` to `matches` (2 or 5 — position sampling interval in seconds) |
| `migrate_wool_location_tables()` | `map_wool_locations` (first-touch-confirmed wool chest positions) and `map_wool_monuments` (capture-event-confirmed monument positions) |
| `migrate_wool_objectives_table()` | `map_wool_objectives` (many-to-many: which teams must capture each wool, with `source` column) |
| `migrate_spatial_relations_tables()` | `map_wool_attack_relations` (vector-based wool attack geometry per team) and `map_team_spatial` (spawn-to-spawn geometry per team pair) |
| `migrate_views()` | Creates or replaces all derived views (e.g. `map_size_buckets`, `life_segment_features`) |

Run any migration directly:

```python
from match_analysis.database.schema import (
    migrate_map_classification_columns,
    migrate_traffic_graph_tables,
    migrate_views,
)
migrate_map_classification_columns()   # safe if columns already exist
migrate_traffic_graph_tables()         # drops old life_segment_features table
migrate_views()                        # recreates all views
```

After adding classification columns, reload map metadata to populate them:

```bash
ctw maps load       # repopulates all classification columns for every map
```

### Step 1: Preprocess maps

Each map must be run through the analysis pipeline first to generate `map_context.json`
and `map_graph.json`:

```bash
ctw run --map ingwaz
ctw run --all          # all maps at once
```

### Step 2: Load map metadata

Populate the `maps` table from pipeline output. This must happen **before** indexing
matches, since `matches.map_id` is a foreign key to `maps`.

```bash
ctw maps load                       # all maps with output data
ctw maps load --map ingwaz          # single map
```

### Step 3: Load spawn data

Populate the `map_spawns` table from `map_context.json` POI assignments. This must
happen **before** processing matches, since team assignment reads spawns from the
database.

```bash
ctw maps spawns                     # all maps
ctw maps spawns --map ingwaz        # single map
```

### Step 4: Load resource data (optional)

Classify and store resource blocks (iron/gold/diamond) and chest locations for each map.
Reads `layout_resource_blocks.parquet` and `layout_chest_contents.parquet` produced by
`ctw layout`, applies zone classification using XML regions, detects double chests, and
writes to the `map_resource_blocks`, `map_chests`, and `map_chest_contents` tables.

```bash
ctw maps resources --map ingwaz     # single map
ctw maps resources                  # all maps with layout parquets
```

To visualise the output without writing to the database:

```bash
python ctw.py debug resources --map ingwaz   # saves output/<map>/resources_overview.png
```

### Step 5: Parse or scan match logs (optional)

If you have a structured text log file mapping parquet filenames to map names:

```bash
ctw matches parse --input match_logs/logs.txt --match-dir match_logs/
```

If your parquet files are organised in a `<map>/` folder tree:

```bash
ctw matches scan --folder data/ --output data/match_history.csv
```

Both produce a CSV with columns `parquet_file,map_name`.

### Step 6: Index match files

Index parquet files into the `matches` table. Each match is linked to a map via
`map_id`. Pass `--history` to resolve map names from the CSV produced by `parse`:

```bash
ctw matches index --match-dir match_logs/ --history match_logs/match_history.csv
```

- `match_id` is an internal sequential integer (1, 2, 3, ...), not the ID from the log file.
- Duplicate files are skipped (UNIQUE constraint on `match_file`).
- Matches for maps not yet in the `maps` table are skipped with a warning.

### Step 7: Process matches

Extract life segments, combat events, position events, and team assignments:

```bash
ctw matches process <match_id>              # single match
ctw matches process-all                     # all unprocessed
ctw matches process-all --map-name ingwaz   # filter by map
ctw matches process-all --force             # reprocess everything
```

Processing populates: `life_segments`, `combat_events`, `position_events`,
`player_team_segments`.

### Step 8: Post-processing (automatic)

Post-processing runs at the end of every `ctw matches process` call and produces
derived tables: `wool_spawn_baselines`, `life_segment_region_visits`,
`life_segment_summary`, and `life_segment_skeleton_features`. The
`life_segment_features` name remains available as a backward-compat VIEW over
`life_segment_summary LEFT JOIN life_segment_skeleton_features`. It can also be
triggered manually, for example to recompute features after a code change without
reprocessing raw events:

```python
import duckdb
from match_analysis.processing.pipeline import run_post_processing

conn = duckdb.connect('match_analysis/metadata.db')
run_post_processing(conn, match_id=1)  # safe to call repeatedly — idempotent
conn.close()
```

The function runs five internal steps in order:

1. **Ensure schema** — calls `migrate_traffic_graph_tables()` to ensure all three
   life-segment tables exist (idempotent).
2. **Wool spawn baselines** — for each team/wool pair, computes the Euclidean distance
   from that team's spawn center to the enemy wool location. Used to normalise
   `max_attack_depth` to [0, 1].
3. **Region visits** — run-length-encodes each player's position sequence into
   contiguous visits (`island`, `build_region`). Annotates each island visit with
   `entry_node` / `exit_node` (nearest skeleton nodes) and `node_path` (the
   deduplicated sequence of `nearest_graph_node` values observed during the visit).
   For build-region visits, infers `bridge_node_1` / `bridge_node_2` from the
   adjacent island visits.
4. **Life features** — aggregates all visits for a life into one row of
   `life_segment_summary` (core facts) and one row of `life_segment_skeleton_features`
   (the nine node-path skeleton metrics).
5. **Wool carry chains** — groups wool touch events into coordinated carry waves,
   determines the outcome (captured / dropped in void / dropped on land / incomplete),
   and populates `wool_carry_chains`.

### Step 9: Build traffic graph

Build a data-driven navigation graph from aggregated player position traces.
This is used as the default graph for Section 4 of `match_time_series.ipynb`
and produces a standalone visualisation. It also populates
`life_segment_traffic_features` with snapped sequences and movement metrics:

```bash
ctw matches traffic-graph --map tumbleweed
ctw matches traffic-graph --map tumbleweed --force    # rebuild if exists
ctw matches traffic-graph --map tumbleweed --grid-size 3   # finer grid
ctw matches traffic-graph --all --min-matches 10      # all maps with ≥10 matches
```

The command automatically refreshes `map_wool_locations` and `map_wool_monuments`
from wool event data before building, so wool node positions are always derived
from first-touch events rather than (potentially incorrect) XML coordinates.

The command skips maps with fewer than `--min-matches` processed matches (default
`10`), and uses a hash of the current processed-match set to skip rebuilding if
nothing has changed since the last run.

Output files:
- `output/<map_slug>/traffic_graph.json` — nodes, edges, aggregate statistics
- `output/<map_slug>/images/traffic_graph.png` — visualisation with island fills and edge heatmap

The graph is built from all processed matches for the map. See
`docs/analysis_overview.md` § *The skeleton graph and the traffic graph* for a
full description of the construction process and how it differs from the
geometric skeleton graph.

Parameters:

| Flag | Default | Meaning |
|------|---------|---------|
| `--grid-size` | auto | Grid cell side length in blocks; auto = `max(2, round(sqrt(total_blocks/300)))` |
| `--min-occupation` | 5 | Minimum position samples to keep a node |
| `--min-transitions` | 2 | Minimum crossings to keep an edge |
| `--min-matches` | 10 | Skip maps with fewer processed matches than this threshold |
| `--log-interval` | 2 | Only use matches logged at this interval (2 or 5 seconds) |
| `--strategy` | grid | Graph construction strategy: `grid` or `voronoi` (k-means cluster nodes) |
| `--compare` | off | Generate a 6-panel strategy comparison plot instead of building the graph |
| `--force` | off | Rebuild even if `traffic_graph.json` already exists |

The comparison plot is saved to `output/<map_slug>/images/traffic_strategy_comparison.png` and shows raw position density, grid-5, grid-3, adaptive-grid, and Voronoi strategies side-by-side.

### Step 9a: Update wool data (standalone)

Wool data is refreshed automatically by `traffic-graph`, but can also be
updated independently — useful after processing new matches without rebuilding
the full graph:

```bash
ctw matches update-wool-locations --map tumbleweed
ctw matches update-wool-locations --all
```

This command writes to three tables:

- **`map_wool_locations`** — verified wool chest positions from first-touch events
  (the first touch per wool per match always happens in the wool room). Falls back to
  `map_context.json` coordinates for maps with no touch data.
- **`map_wool_monuments`** — monument positions from capture events (exact coords).
- **`map_wool_objectives`** — which teams must capture each wool (many-to-many).
  Primary source: capture events joined against `map_spawns` for team-name
  normalisation. Fallback: `map_context.json` wool definitions.

`wool_id` values in the event log are Minecraft wool damage values (0–15), which
map directly to color names (`4` = yellow, `11` = blue, `13` = green, `14` = red,
etc.), so no fuzzy matching is needed.

### Step 9b: Compute spatial relations

After wool data is populated, compute vector-based spatial geometry for each map:

```bash
ctw maps spatial-relations --map tumbleweed
ctw maps spatial-relations           # all maps
```

For each (attacking_team, wool) pair, the signed angle of the wool from the team's
spawn-to-center attack axis is computed using Minecraft's left-handed XZ convention.
Results are stored in `map_wool_attack_relations` (one row per attacking_team/wool)
and `map_team_spatial` (one row per from_team/to_team pair).

**Prerequisites:** `maps spawns` (step 3) and `matches update-wool-locations` (step 9a).

### Step 10: Cluster archetypes

Open and run the Jupyter notebook (see [Clustering Notebook](#clustering-notebook) below).

---

## Querying

```bash
ctw matches list                            # all matches
ctw matches list --map-name ingwaz          # filter by map
ctw matches list --processed                # only processed
ctw matches stats                           # aggregate statistics
```

---

## Database Schema

```
maps                        Map metadata (bbox, island count, teams)
 └─ map_spawns              Spawn locations per map (team, center, bounds)
 └─ map_resource_blocks     Iron/gold/diamond block positions with zone classification
 └─ map_chests              Chest positions with zone classification and double-chest detection
 └─ map_chest_contents      Full inventory of each chest (one row per slot)
 └─ map_wool_locations      Verified wool chest positions (from first-touch events)
 └─ map_wool_monuments      Verified monument positions (from capture events; one row per team per wool on multi-team maps)
 └─ map_wool_objectives     Which teams must capture each wool (many-to-many; source = db or map_context)
 └─ map_wool_attack_relations  Vector-based spatial geometry: wool relative to each attacking team's spawn axis
 └─ map_team_spatial        Vector-based spatial geometry: spawn-to-spawn relations per team pair
 └─ wool_spawn_baselines    Spawn-to-wool baseline distances per team/wool
 └─ matches                 One row per indexed parquet file
     ├─ life_segments            Player life segments (spawn → death)
     │   ├─ combat_events        Kill and death events with positions
     │   ├─ position_events      Type-5 events with spatial annotation
     │   ├─ wool_events          Wool touch (6) and capture (7) events with positions
     │   ├─ player_team_segments Team membership over time
     │   ├─ processing_log       Audit trail for processing steps
     │   ├─ life_segment_region_visits    Per-visit breakdown of each life
     │   ├─ life_segment_summary          Core facts per life
     │   ├─ life_segment_skeleton_features  Skeleton-graph node-path metrics
     │   └─ life_segment_traffic_features   Traffic-graph snapped sequence + metrics
```

`life_segment_features` is available as a backward-compat VIEW over
`life_segment_summary LEFT JOIN life_segment_skeleton_features`.

### Processing tables

| Table | Key Columns | Populated By |
|-------|-------------|-------------|
| `maps` | `map_id`, `map_slug`, `map_name`, bbox, `island_count`, classification columns | `ctw maps load` |
| `map_spawns` | `map_id` (FK), `x`, `z`, bounds, `team`, `team_color` | `ctw maps spawns` |
| `map_resource_blocks` | `map_id` (FK), `world_x`, `world_z`, `y`, `resource_type`, `zone`, `team` | `ctw maps resources` |
| `map_chests` | `map_id` (FK), `world_x`, `world_z`, `y`, `chest_type`, `zone`, `team`, `is_double`, `chest_group_id` | `ctw maps resources` |
| `map_chest_contents` | `map_id` (FK), `world_x`, `world_z`, `y`, `slot`, `item_id`, `item_damage`, `count` | `ctw maps resources` |
| `map_wool_locations` | `map_id` (FK), `wool_id`, `wool_color`, `team`, `x`, `z`, `source`, `first_touch_count`, `x_std`, `z_std` | `ctw matches update-wool-locations` (also runs automatically inside `traffic-graph`) |
| `map_wool_monuments` | `map_id` (FK), `wool_id`, `wool_color`, `monument_x`, `monument_z`, `capture_count`, `source` | `ctw matches update-wool-locations` (also runs automatically inside `traffic-graph`) |
| `map_wool_objectives` | `map_id` (FK), `wool_id`, `wool_color`, `team`, `source` | `ctw matches update-wool-locations` (primary: capture events; fallback: `map_context.json`) |
| `map_wool_attack_relations` | `map_id` (FK), `attacking_team`, `wool_id`, `defending_team`, `relative_side`, `relative_depth`, `angle_deg`, `distance`, `defending_side`, `defending_angle_deg` | `ctw maps spatial-relations` |
| `map_team_spatial` | `map_id` (FK), `from_team`, `to_team`, `relative_side`, `relative_depth`, `angle_deg`, `distance` | `ctw maps spatial-relations` |
| `matches` | `match_id`, `match_file`, `map_id` (FK), `processed`, `log_interval` | `ctw matches index` |
| `life_segments` | `match_id` (FK), `player_id`, `segment_idx`, outcome, kills | `ctw matches process` |
| `combat_events` | `match_id` (FK), `player_id`, `event_type`, position | `ctw matches process` |
| `position_events` | `match_id` (FK), `player_id`, position, `location_type`, `island_id` | `ctw matches process` |
| `wool_events` | `match_id` (FK), `player_id`, `event_type` (6=touch, 7=capture), `wool_id`, position | `ctw matches process` |
| `player_team_segments` | `match_id` (FK), `player_id`, `team`, time range | `ctw matches process` |
| `processing_log` | `match_id` (FK), `step`, `status`, `duration` | `ctw matches process` |

### Post-processing tables

| Table | Key Columns | Populated By |
|-------|-------------|-------------|
| `wool_spawn_baselines` | `map_id` (FK), `team`, `wool_id`, `baseline_distance` | `run_post_processing` |
| `life_segment_region_visits` | `segment_id` (FK), `visit_idx`, `location_type`, `entry_node`, `exit_node`, `node_path` | `run_post_processing` |
| `life_segment_summary` | `segment_id` (FK), movement fractions, `cluster_label` | `run_post_processing` |
| `life_segment_skeleton_features` | `segment_id` (FK), nine node-path metrics | `run_post_processing` |
| `life_segment_traffic_features` | `segment_id` (FK), `snapped_sequence`, `unique_nodes`, `min_enemy_wool_dist`, `avg_home_wool_dist`, `span_m`, `tortuosity` | `ctw matches traffic-graph` |
| `wool_carry_chains` | `match_id` (FK), `wool_id`, `wave_idx`, `attacking_team`, `n_carriers`, `n_handoffs`, `outcome`, `approach_type` | `run_post_processing` |

`life_segment_features` is a VIEW over `life_segment_summary LEFT JOIN life_segment_skeleton_features` kept for backward compatibility.

### `maps` classification columns

These columns are populated by `ctw maps load` from pipeline output files (`map_data.json`, `symmetry.json`, `layout_top_surface.parquet`):

| Column | Type | Source | Description |
|--------|------|---------|-------------|
| `wools_per_team` | INTEGER | `map_data.json` wools/teams | Wool objectives per team; 0 = non-CTW |
| `max_players_per_team` | INTEGER | `map_data.json` teams | Max players per team (avg across teams) |
| `total_blocks` | INTEGER | `layout_top_surface.parquet` | Buildable surface blocks, **excluding block ID 36** (void marker) |
| `size_tier` | VARCHAR | derived from `max_players_per_team` | Server tier: `pico`/`nano`/`micro`/`milli`/`centi`/`hecto`/`mega`/`giga` |
| `symmetry_type` | VARCHAR | `symmetry.json` global_symmetry | Highest-confidence detected global symmetry type, or `none` |
| `has_intra_team_symmetry` | BOOLEAN | `symmetry.json` intra_team_symmetry | True if any team's island cluster has intra-team symmetry |
| `traffic_graph_match_hash` | TEXT | computed by `ctw matches traffic-graph` | MD5 of the sorted processed-match IDs used for staleness detection |
| `traffic_graph_built_at` | TIMESTAMP | set by `ctw matches traffic-graph` | UTC timestamp of the last successful traffic graph build |

Size tier thresholds (players per team, lower-bound inclusive):

| Tier | Threshold |
|------|----------:|
| `giga` | 80+ |
| `mega` | 64 |
| `hecto` | 48 |
| `centi` | 32 |
| `milli` | 22 |
| `micro` | 14 |
| `nano` | 6 |
| `pico` | 1 |

### `map_size_buckets` view

A derived view assigning each map to one of five area buckets via NTILE(5) percentile ranking on `total_blocks`. Only maps with `wools_per_team > 0` and a valid `total_blocks` are included. Bucket boundaries shift automatically as new maps are loaded.

```sql
SELECT map_slug, map_size_bucket FROM map_size_buckets;
-- Buckets: tiny, small, medium, large, huge (~59 maps each)
```

#### `life_segment_region_visits` — notable columns

Each row is one contiguous spell in a region (island or build/void area) within a life.

| Column | Type | Description |
|--------|------|-------------|
| `visit_idx` | INTEGER | Ordinal position within the life (0-based) |
| `location_type` | TEXT | `'island'`, `'build_region'` |
| `island_id` | INTEGER | Populated for island visits |
| `is_home_island` | BOOLEAN | Whether this island is the player's own spawn island |
| `is_enemy_island` | BOOLEAN | Whether this island belongs to the opposing team |
| `entry_node` | INTEGER | Global skeleton node ID nearest to the player's first position in this visit |
| `exit_node` | INTEGER | Global skeleton node ID nearest to the player's last position in this visit |
| `bridge_node_1` | INTEGER | For build-region visits: `exit_node` of the preceding island visit |
| `bridge_node_2` | INTEGER | For build-region visits: `entry_node` of the following island visit |
| `node_path` | TEXT (JSON) | Run-length-deduplicated sequence of `nearest_graph_node` values observed during this visit |
| `kill_count` | INTEGER | Kills scored during this visit's time window |
| `was_death` | BOOLEAN | True only for the final visit of a life that ended in death |

#### `life_segment_features` — region-level metrics

`life_segment_features` is now a VIEW over `life_segment_summary LEFT JOIN life_segment_skeleton_features`. It exposes the same columns as before for backward compatibility.

| Column | Description |
|--------|-------------|
| `n_islands_visited` | Count of distinct islands touched |
| `n_build_regions_visited` | Count of distinct island-pair bridge corridors used |
| `n_transitions` | Total number of region visits |
| `frac_time_home_island` | Fraction of active time on own spawn island |
| `frac_time_enemy_island` | Fraction of active time on opponent's island |
| `frac_time_neutral_island` | Fraction of active time on unowned neutral islands |
| `frac_time_build` | Fraction of active time in build/void bridge regions |
| `max_attack_depth` | Normalised 0–1 progress toward nearest enemy wool objective |
| `time_to_first_departure_s` | Seconds before leaving home island (`NULL` = never left) |
| `ended_on_enemy_island` | Whether the life ended (death or match-end) while on an enemy island |

The following four are derived in the clustering notebook rather than stored directly,
since they depend on imputation choices:

| Derived | Formula |
|---------|---------|
| `kill_rate` | `kills / duration_s` |
| `departure_frac` | `time_to_first_departure_s / duration_s`, clipped to [0, 1]; 1.0 = never left home |
| `aggression` | `kill_on_enemy_island / kills` (0 when no kills) |
| `mobility_rate` | `n_transitions / duration_s` |

#### `life_segment_features` — node-path metrics

Nine columns from `life_segment_skeleton_features`, surfaced in the `life_segment_features`
view. They are derived from `node_path`, `entry_node`, `exit_node`, and `bridge_node_1/2`
in `life_segment_region_visits`. They require `map_graph.json` at post-processing time
to resolve each global node ID's degree and type.

| Column | Type | Description |
|--------|------|-------------|
| `visited_junction` | BOOLEAN | True if the player reached any junction node (skeleton degree ≥ 3); proxy for interior island penetration |
| `frac_island_visits_with_junction` | FLOAT | Fraction of island visits containing ≥1 junction in `node_path`; captures *consistency* of deep play vs. a single lucky run |
| `max_node_degree_visited` | INTEGER | Maximum skeleton node degree seen across the whole life; higher degree = deeper interior access |
| `traversal_rate` | FLOAT | Fraction of island visits where `entry_node ≠ exit_node`; active mover → high, static camper → 0 |
| `avg_nodes_per_island_visit` | FLOAT | Mean count of unique skeleton nodes per island visit |
| `died_at_endpoint` | BOOLEAN | For lives ending in death on an island: True if at an endpoint node, False if at a junction; `NULL` if not killed on an island |
| `n_unique_corridors` | INTEGER | Distinct `(bridge_node_1, bridge_node_2)` pairs used; 8× more granular than `n_build_regions_visited` |
| `position_entropy` | FLOAT | Shannon entropy (bits) of the node-visit frequency distribution; high = roamer, low = camper |
| `dominant_node_frac` | FLOAT | Fraction of all node appearances at the single most-visited node |

**Node types** (from `map_graph.json`):
- **Endpoint** — skeleton leaf (degree 1). The outermost reachable edge of an island.
- **Junction** — branching node (degree ≥ 3). Interior of the island skeleton; requires committing into the island to reach.

---

## Resetting

Reset processing state (keeps indexed matches, clears extracted data):

```bash
ctw matches reset                   # all matches
ctw matches reset --match-id 5      # single match
```

To fully rebuild, delete the database file and start from Step 0:

```bash
rm match_analysis/metadata.db
python match_analysis/database/schema.py
```

---

## Clustering Notebook

`notebooks/life_segment_clustering.ipynb` performs unsupervised discovery of player
role archetypes from `life_segment_features`. Run it after all matches have been
post-processed.

### Prerequisites

```bash
pip install jupyter scikit-learn hdbscan seaborn matplotlib
cd notebooks
jupyter notebook life_segment_clustering.ipynb
```

The notebook connects to `../match_analysis/metadata.db` (relative to `notebooks/`).
Run all cells in order from top to bottom; the final cell writes `cluster_id` and
`cluster_label` back to `life_segment_summary`.

### Notebook structure

| Section | What it does |
|---------|-------------|
| **1. Setup** | Imports, DB path, plot theme |
| **2. Load features** | Reads all `life_segment_features` rows with map and team joins; includes 9 node-path columns |
| **3. Feature engineering** | Imputes nulls; derives `kill_rate`, `departure_frac`, `aggression`, `mobility_rate` from stored columns |
| **4. Feature matrix** | Documents which features are used for clustering and why |
| **5. PCA overview** | Scree plot + PC1/PC2 scatter coloured by `max_attack_depth`; identifies how many components explain 80% of variance |
| **6. KMeans elbow/silhouette scan** | Tries k = 2–9; plots inertia and silhouette score to identify the elbow |
| **7. HDBSCAN** | Density-based alternative using first 4 PCs; useful for non-spherical clusters |
| **8. Choose final clustering** | Set `BEST_K` and `USE` (`'kmeans'` or `'hdbscan'`) |
| **9. Cluster characterisation** | Mean profile table across all `PROFILE_COLS` including node-path metrics |
| **10. Assign archetype labels** | Edit `CLUSTER_LABELS` dict to map cluster IDs to human names |
| **11. Write labels to database** | Batch `UPDATE life_segment_summary` via a registered DataFrame |
| **12. Cross-map distribution** | Bar chart: archetype % of lives per map; checks cross-map consistency |
| **13. Node-path deep dive** | Bar charts and scatter plot of junction penetration, traversal rate, and position entropy per archetype |

### Feature matrix (11 features, as of current version)

**Region-level (original 8):**

| Feature | Cluster signal |
|---------|---------------|
| `max_attack_depth` | Pushes deep toward objective vs. stays back |
| `frac_time_home_island` | Defensive anchor |
| `frac_time_enemy_island` | Offensive time investment |
| `frac_time_build` | Bridge/void mid-map combat |
| `departure_frac` | How late (or never) the player left home |
| `kill_rate` | Killing efficiency, life-length-normalised |
| `aggression` | Whether kills happen on offense vs. defense |
| `mobility_rate` | How actively the player moves between regions |

**Node-path (new 3):**

| Feature | Cluster signal |
|---------|---------------|
| `frac_island_visits_with_junction` | Consistent deep penetration vs. edge skimming |
| `traversal_rate` | Active movement within islands vs. static positioning |
| `position_entropy` | Spatial diversity (roamer) vs. concentration (camper) |

### Archetype profiles (reference, k=5)

These are the profiles produced from 2,318 life segments across three maps
(annealing_iv, tumbleweed, outback_outback_edition). Re-run will produce similar but
not identical numbers.

| Archetype | n | depth | home | enemy | build | junction_visits | traversal | entropy |
|-----------|---|-------|------|-------|-------|----------------|-----------|---------|
| `deep-attacker` | ~250 | 0.76 | 0.30 | 0.60 | 0.04 | high | high | high |
| `attacker` | ~790 | 0.69 | 0.40 | 0.33 | 0.05 | moderate | moderate | moderate |
| `defender` | ~1020 | 0.26 | 0.93 | 0.01 | 0.02 | low | low | low |
| `bridge-fighter` | ~240 | 0.53 | 0.32 | 0.05 | 0.55 | low | low | low |
| `outlier` | ~12 | 0.02 | 0.00 | 0.00 | 0.00 | — | — | — |

### Output files

| File | Content |
|------|---------|
| `output/clustering_corr.png` | Feature correlation heatmap (11×11) |
| `output/clustering_pca.png` | Scree plot + PC1/PC2 scatter |
| `output/clustering_kmeans_scan.png` | Elbow and silhouette vs. k |
| `output/clustering_radar.png` | 9-axis radar chart per cluster |
| `output/clustering_pca_clusters.png` | PC1/PC2 and PC3/PC4 scatter coloured by cluster |
| `output/clustering_boxplots.png` | Box plots of 8 features by cluster |
| `output/clustering_map_distribution.png` | Archetype % per map |
| `output/clustering_node_metrics.png` | Junction penetration, traversal rate, entropy bars by archetype |
| `output/clustering_traversal_vs_junction.png` | Traversal rate vs. junction penetration scatter |

---

## Analysis notebooks

After all matches are processed and post-processed, two time-series notebooks
are available for match-level and aggregate analysis.

### `notebooks/match_time_series.ipynb`

| Section | Description |
|---------|-------------|
| **1 — Single Match Inspector** | Per-team pusher count (players above `PUSH_DEPTH_THRESHOLD` graph depth) per enemy wool over absolute match time. Death rate on right axis. Touch/capture markers. |
| **2 — Aggregate Per-Map View** | All matches on a map overlaid on normalised time `[0, 1]`. Median and 25–75th percentile band. Wool-capture rug marks. Match duration histogram. |
| **3 — Push-Pull Summary** | Pearson correlation between Team A's and Team B's total pusher-count series over normalised time. Negative = back-and-forth; near zero = stagnant; positive = simultaneous escalation. |
| **4 — Coordinated Push Analysis** | Push window timeline with shaded coordinated windows; attack flow map using the traffic graph (falls back to skeleton graph if not built) with island polygon fills, node size ∝ attacker ticks during push windows, directed flow arrows ∝ transitions, dashed inter-island crossing edges; push efficiency table. |

Key tunables in the setup cell: `BUCKET_SIZE_S`, `PUSH_DEPTH_THRESHOLD`,
`PUSH_MIN_PLAYERS`.

### `notebooks/wool_dynamics.ipynb`

| Section | Description |
|---------|-------------|
| **1 — Per-Wool Node Coverage** | Defender vs. attacker ticks at each wool room skeleton node per 60s bucket. Exposes coverage gaps. |
| **2 — Y-Level Phase Detection** | Rolling 5-minute median Y per team; detects skybridge phase transition. Early vs. late Y histogram. |
| **3 — Per-Wool Attack Depth** | Per-wool graph-based pusher count (same metric as Section 1 above). Divergence between two wools reveals forced single-defence. |
| **4 — Carry Chain Timeline** | Gantt-style wool carry waves from touch to capture/drop. Handoffs, approach type (ground vs. skybridge), outcome. |

**Prerequisites**: `map_graph.json` with `poi_type`/`poi_color`/`team` fields
on global nodes (generated by `ctw run --map <slug>` with current pipeline).
Older `map_graph.json` files from before this field was added are handled
gracefully — wool nodes will be absent for those maps.

---

## Visualization

After processing, generate player trace and kill plots:

```bash
# Player movement traces
ctw matches trace --map Ingwaz --match 5 --player ALL --color-mode team
ctw matches trace --map Ingwaz --match ALL --player ALL --overlay

# Kill-death pair locations
ctw matches kills --map Ingwaz --match 5
ctw matches kills --map Ingwaz --match ALL --overlay --color-mode distance
```
