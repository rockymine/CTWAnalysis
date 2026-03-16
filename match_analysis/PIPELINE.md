# Match Analysis Pipeline

## Overview

Processing is split into two independent commands so that the slow spatial work
does not block fast event extraction, and so that the two steps can be run
independently (e.g., re-classify after rebuilding the traffic graph without
re-extracting all data).

```
match_logs/*.parquet
    │
    ▼
matches extract          ← fast, CPU-bound, no spatial work
    │  Sets processed = TRUE, spatial_classified = FALSE
    │  Writes: life_segments, combat_events, wool_events,
    │          position_events (location_type/island_id = NULL),
    │          player_team_segments
    │
    ▼
matches classify         ← spatial annotation + traffic features
       Sets spatial_classified = TRUE
       Updates: position_events.location_type, position_events.island_id
       Writes: life_segment_traffic_features
```

---

## Command Reference

### `matches extract`

Reads raw parquet files, extracts all events into the database.
Does **not** run spatial classification — `location_type` and `island_id`
in `position_events` are inserted as NULL.

```bash
python ctw.py matches extract --map-name <slug> [--workers N] [--force]
```

- `--map-name`: scope to one map (recommended; running without a map filter
  is very slow for 700+ matches)
- `--workers N`: parallel extraction workers (DB writes remain serial)
- `--force`: re-extract already-processed matches

Sets `matches.processed = TRUE`, `spatial_classified = FALSE`.

### `matches classify`

Loads `position_events` from the database, runs spatial classification
(island/build_region/void), writes back `location_type` and `island_id`,
then computes `life_segment_traffic_features` if a `traffic_graph.json`
exists for the map.

```bash
python ctw.py matches classify --map-name <slug> [--force]
```

- `--map-name`: scope to one map
- `--force`: re-classify already-classified matches

Prerequisites:
- `matches extract` must have run for the matches in question
- `output/<map>/map_context.json` must exist (run `ctw run --map <name>` first)
- For traffic features: `output/<map>/traffic_graph.json` must exist
  (run `matches traffic-graph --map <slug>` first)

Sets `matches.spatial_classified = TRUE`.

### Typical workflow

```bash
# 1. Index parquet files
python ctw.py matches index --match-dir match_logs/

# 2. Run the full spatial pipeline (map_context.json must exist)
python ctw.py matches extract --map-name arabia --workers 4
python ctw.py matches classify --map-name arabia

# 3. Build traffic graph, then re-classify to compute traffic features
python ctw.py matches traffic-graph --map arabia
python ctw.py matches classify --map-name arabia --force
```

---

## Database Tables

### Core tables (populated by `extract`)

| Table | Description |
|-------|-------------|
| `life_segments` | One row per player life (spawn→death). Counts of kills, wools, positions. |
| `combat_events` | Kill and death events with positions. |
| `wool_events` | Wool touch and capture events. |
| `position_events` | Type-5 tracking events at 2s or 5s intervals. `location_type`/`island_id` start as NULL. |
| `player_team_segments` | Team membership over time, inferred from spawn locations. |

### Spatial / traffic tables (populated by `classify`)

| Table | Description |
|-------|-------------|
| `position_events.location_type` | `'island'`, `'build_region'`, or `'void'` |
| `position_events.island_id` | Integer island ID (NULL if not on an island) |
| `life_segment_traffic_features` | Per-life-segment traffic graph metrics (see below) |

### `life_segment_traffic_features` schema

| Column | Type | Description |
|--------|------|-------------|
| `segment_id` | INTEGER | FK to `life_segments.segment_id` |
| `snapped_sequence` | TEXT | JSON array of traffic node IDs visited (ordered) |
| `max_attack_depth` | FLOAT | Min Dijkstra distance to nearest enemy wool node; lower = deeper attack |
| `death_region` | TEXT | `'home_island'`, `'enemy_island'`, `'bridge'`, or `'void'` |

### Other tables

| Table | Description |
|-------|-------------|
| `wool_carry_chains` | Consecutive wool-carry attempts grouped into waves (from `post-process`) |
| `wool_spawn_baselines` | Baseline spawn→wool distances per map/team (from `post-process`) |

---

## Status Flags

`matches` table has two boolean flags:

| Column | Meaning |
|--------|---------|
| `processed` | `extract` (or `process`) has run successfully |
| `spatial_classified` | `classify` has run successfully |

Query to check status:
```sql
SELECT processed, spatial_classified, COUNT(*)
FROM matches
GROUP BY ALL
ORDER BY 1, 2;
```

---

## Removed Features (skeleton graph era)

The following tables were dropped in the skeleton-removal migration
(see `scripts/migrate_skeleton_removal.py`):

- `life_segment_skeleton_features` — node-path metrics (junction visits, entropy, etc.)
- `life_segment_region_visits` — RLE-compressed region visit sequences
- `life_segment_summary` — aggregate life metrics (time fractions, attack depth, etc.)

The `life_segment_features` view (which joined summary + skeleton) was also removed.

The following columns were dropped from `position_events`:
`nearest_node_1`, `nearest_node_2`, `nearest_island_1`, `nearest_island_2`,
`nearest_graph_node`.

---

## Key Source Files

| File | Role |
|------|------|
| `match_analysis/processing/processor.py` | `extract_match_data`, `insert_match_data`, `classify_match` |
| `match_analysis/processing/extractors.py` | Event extraction from raw parquet |
| `match_analysis/processing/position_classifier.py` | Spatial classification (STRtree-based) |
| `match_analysis/traffic/segment_features.py` | `build_traffic_features_for_match` |
| `match_analysis/processing/pipeline.py` | `run_post_processing` (wool carry chains only) |
| `ctw/commands/matches.py` | CLI commands |
