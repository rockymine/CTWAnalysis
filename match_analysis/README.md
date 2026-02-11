# Match Analysis Database

## Overview

All match and map metadata lives in a single DuckDB database at `match_analysis/metadata.db`. The database is populated through a series of CLI commands that must be run in a specific order due to foreign key dependencies.

## Setup Workflow

```
1. Preprocess maps          ctw run --map <name>
2. Load map metadata        ctw maps load
3. Load spawn data          ctw maps spawns
4. Parse match logs         ctw matches parse ...
5. Index matches            ctw matches index ...
6. Process matches          ctw matches process-all
```

### Step 0: Initialize the database

If starting fresh or after schema changes, create the empty tables:

```bash
python scripts/initialize_analysis_db.py
```

This is idempotent — existing tables are not recreated.

### Step 1: Preprocess maps

Each map must be run through the analysis pipeline first to generate `map_data.json` and `map_context.json`:

```bash
ctw run --map ingwaz --no-matches
ctw run --all --no-matches          # all maps at once
```

### Step 2: Load map metadata

Populate the `maps` table from pipeline output. This must happen **before** indexing matches, since `matches.map_id` is a foreign key to `maps`.

```bash
ctw maps load                       # all maps with output data
ctw maps load --map ingwaz          # single map
```

### Step 3: Load spawn data

Populate the `map_spawns` table from `map_context.json` POI assignments. This must happen **before** processing matches, since team assignment reads spawns from the database.

```bash
ctw maps spawns                     # all maps
ctw maps spawns --map ingwaz        # single map
```

### Step 4: Parse match logs (optional)

If you have a structured text log file mapping parquet filenames to map names:

```bash
ctw matches parse --input match_logs/logs.txt --match-dir match_logs/
```

Produces `match_history.csv` with columns `parquet_file,map_name`.

### Step 5: Index match files

Index parquet files into the `matches` table. Each match is linked to a map via `map_id`. Pass `--history` to resolve map names from the CSV produced by `parse`:

```bash
ctw matches index --match-dir match_logs/ --history match_logs/match_history.csv
```

- `match_id` is an internal sequential integer (1, 2, 3, ...), not the ID from the log file.
- Duplicate files are skipped (UNIQUE constraint on `match_file`).
- Matches for maps not yet in the `maps` table are skipped with a warning.

### Step 6: Process matches

Extract life segments, combat events, position events, and team assignments:

```bash
ctw matches process <match_id>              # single match
ctw matches process-all                     # all unprocessed
ctw matches process-all --map-name ingwaz   # filter by map
ctw matches process-all --force             # reprocess everything
```

Processing populates: `life_segments`, `combat_events`, `position_events`, `player_team_segments`.

## Querying

```bash
ctw matches list                            # all matches
ctw matches list --map-name ingwaz          # filter by map
ctw matches list --processed                # only processed
ctw matches stats                           # aggregate statistics
```

## Database Schema

```
maps                    Map metadata (bbox, island count, teams)
 └─ map_spawns          Spawn locations per map (team, center, bounds)
 └─ matches             One row per indexed parquet file
     ├─ life_segments       Player life segments (spawn → death)
     ├─ combat_events       Kill and death events with positions
     ├─ position_events     Type-5 position events with spatial annotation
     ├─ player_team_segments  Team membership over time
     └─ processing_log      Audit trail for processing steps
```

| Table | Key Columns | Populated By |
|-------|-------------|-------------|
| `maps` | `map_id`, `map_slug`, `map_name`, bbox, `island_count` | `ctw maps load` |
| `map_spawns` | `map_id` (FK), `x`, `z`, bounds, `team`, `team_color` | `ctw maps spawns` |
| `matches` | `match_id`, `match_file`, `map_id` (FK), `processed` | `ctw matches index` |
| `life_segments` | `match_id` (FK), `player_id`, `segment_idx`, outcome, kills | `ctw matches process` |
| `combat_events` | `match_id` (FK), `player_id`, `event_type`, position | `ctw matches process` |
| `position_events` | `match_id` (FK), `player_id`, position, `location_type`, `island_id` | `ctw matches process` |
| `player_team_segments` | `match_id` (FK), `player_id`, `team`, time range | `ctw matches process` |
| `processing_log` | `match_id` (FK), `step`, `status`, `duration` | `ctw matches process` |

## Resetting

Reset processing state (keeps indexed matches, clears extracted data):

```bash
ctw matches reset                   # all matches
ctw matches reset --match-id 5      # single match
```

To fully rebuild, delete the database file and start from Step 0:

```bash
rm match_analysis/metadata.db
python scripts/initialize_analysis_db.py
```

## Visualization

After processing, generate player trace plots:

```bash
ctw matches trace --map Ingwaz --match 5 --player ALL --color-mode team
ctw matches trace --map Ingwaz --match ALL --player 0
```
