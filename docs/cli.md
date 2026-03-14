# CTW Analysis Toolkit — CLI Reference

## Quick Start

```bash
# Full pipeline for one map (layout + islands + XML + assembly)
python ctw.py run --map tumbleweed --no-matches

# Check what's been analyzed
python ctw.py info --map tumbleweed

# Run individual steps
python ctw.py layout --map tumbleweed
python ctw.py islands --map tumbleweed
python ctw.py xml --map tumbleweed

# Load map into the database, then process matches
python ctw.py maps load --map tumbleweed
python ctw.py maps spawns --map tumbleweed
python ctw.py matches index --match-dir match_logs/
python ctw.py matches process-all --map-name tumbleweed

# Visualize
python ctw.py matches trace --map tumbleweed --match 57 --player ALL --color-mode team
```

The `--map` flag accepts either a map name (resolved from `map_folders/`) or a
direct path to a map folder.

---

## Commands

### `ctw run` — Full Analysis Pipeline

Runs layout extraction, island analysis, XML parsing, and map assembly in sequence.

```
python ctw.py run (--map NAME | --all | --all-matches) [--force]
    [--no-layout] [--no-islands] [--no-xml] [--no-matches]
    [--island-layout bedrock|y0|top|density]
    [--canonical-triangulation] [--plots]
```

| Flag | Description |
|---|---|
| `--map NAME` | Map name to analyze |
| `--all` | Analyze all maps in `map_folders/` |
| `--all-matches` | Analyze only maps that have match data in the database |
| `--force` | Regenerate even if outputs exist |
| `--no-layout` | Skip layout extraction |
| `--no-islands` | Skip island/skeleton analysis |
| `--no-xml` | Skip XML parsing |
| `--no-matches` | Skip match analysis (use this for map-only runs) |
| `--island-layout` | Layout file for islands: `bedrock` (default), `y0`, `top`, `density`, `solid` |
| `--canonical-triangulation` | Identical islands share the same mesh |
| `--plots` | Generate debug plots |

---

### `ctw layout` — Layout Extraction

Extract block data from Minecraft region files into parquet files.

```
python ctw.py layout (--map NAME | --all | --all-matches) [--map-dir DIR] [--force]
    [--output DIR]
    [--threshold N] [--density-mode run,count]
    [--skip-y0] [--skip-surface] [--skip-density] [--skip-bedrock]
    [--skip-lowest-solid] [--skip-features] [--plots]
```

| Flag | Description |
|---|---|
| `--map NAME` | Single map name or path |
| `--all` | Process all maps found in `--map-dir` |
| `--all-matches` | Process only maps that have match data in the database |
| `--map-dir DIR` | Directory to scan with `--all` or `--all-matches` (default: `map_folders/`). Use this for external collections such as CommunityMaps or PublicMaps. |
| `--output DIR` | Output root directory (default: `output/`). Each map writes to `<DIR>/<map_name>/`. |
| `--threshold N` | Density threshold (default: 10) |
| `--density-mode` | Comma-separated modes: `run`, `count` |
| `--skip-y0` | Skip Y=0 layer |
| `--skip-surface` | Skip top surface |
| `--skip-density` | Skip vertical density |
| `--skip-bedrock` | Skip lowest bedrock |
| `--skip-lowest-solid` | Skip lowest-solid-layer extraction |
| `--skip-features` | Skip resource block and chest extraction |
| `--plots` | Generate visualization plots (single map only) |
| `--workers N` | Process N maps in parallel (default: 1) |

---

### `ctw islands` — Island & Skeleton Analysis

Detect islands, compute skeleton graphs, annotate POIs, and build connectivity.

```
python ctw.py islands --map NAME [--force]
    [--connectivity 4|8] [--min-size N] [--buffer F] [--simplify F]
    [--no-holes] [--layout bedrock|y0|top|density]
    [--canonical-triangulation] [--basic]
    [--output DIR] [--plots]
```

| Flag | Description |
|---|---|
| `--connectivity` | 4 or 8-connectivity for island detection (default: 8) |
| `--min-size N` | Minimum blocks per island (default: 10) |
| `--buffer F` | Buffer distance for polygon smoothing (default: 0.0) |
| `--simplify F` | Simplification tolerance (default: 1.0) |
| `--no-holes` | Disable internal hole detection |
| `--layout` | Which layout file to use: `bedrock` (default), `y0`, `top`, `density`, `solid` |
| `--canonical-triangulation` | D4-symmetric islands share mesh |
| `--basic` | Detection + triangulation only, no skeleton/POI/connectivity |
| `--output DIR` | Save to custom directory |
| `--plots` | Generate debug plots (per-island debug, POI, pathfinding) |

**Essential figures** (always generated):
`island_triangulation_detail.png`, `unique_islands.png`, `map_overview.png`,
`map_connectivity.png`

**Debug figures** (only with `--plots`):
`island_comparison.png`, `island_statistics.png`, `island_report.txt`,
`island_{id}_debug.png`, `skeleton_report.txt`, `island_{id}_poi.png`,
`island_{id}_paths.png`

---

### `ctw xml` — XML Configuration Parsing

Parse map XML and optionally generate region visualizations.

```
python ctw.py xml --map NAME [--force]
    [--visualize] [--category-plots] [--no-summary] [--no-json]
```

| Flag | Description |
|---|---|
| `--visualize` | Generate map layout visualization plots |
| `--category-plots` | Generate per-category region plots |
| `--no-summary` | Skip printing text summary |
| `--no-json` | Skip generating `map_data.json` |

---

### `ctw maps` — Map Metadata

Load map metadata and spawn data into the database. Must be run after `ctw run`
and before `ctw matches process-all`.

#### `maps load`

Populate the `maps` table from pipeline output (`map_context.json`, `symmetry.json`,
`layout_top_surface.parquet`).

```
python ctw.py maps load [--map NAME]
```

Omit `--map` to load all maps with pipeline output.

#### `maps spawns`

Populate the `map_spawns` table from POI assignments in `map_context.json`. Required
before processing matches, since team assignment reads spawn bounds from the database.

```
python ctw.py maps spawns [--map NAME]
```

#### `maps resources`

Classify resource blocks (iron/gold/diamond) and chest inventories by zone, and store
results in `map_resource_blocks`, `map_chests`, and `map_chest_contents`.

```
python ctw.py maps resources [--map NAME]
```

Reads `layout_resource_blocks.parquet` and `layout_chest_contents.parquet` produced
by `ctw layout`. Omit `--map` to process all maps.

#### `maps kits`

Parse starter kit definitions from `map.xml` and store results in `map_kit_items`
and `map_kit_armor`.

```
python ctw.py maps kits [--map NAME]
```

Reads `map.xml` directly — no prior pipeline step required beyond `maps load`.
Parses the `<kits>` section and resolves team association via `<spawn kit="...">`.
Only kits with at least one item or armor slot are stored; secondary utility kits
(e.g. `reset-resistance-kit`) are skipped. Omit `--map` to process all maps.

---

### `ctw matches` — Match Data Analysis

Index, process, and visualize match data. Uses a DuckDB database
(`match_analysis/metadata.db`) to track indexed matches.

#### `matches parse`

Parse a structured text log file mapping parquet filenames to map names.

```
python ctw.py matches parse --input FILE --match-dir DIR
```

Produces a `match_history.csv` with columns `parquet_file,map_name`.

#### `matches scan`

Scan a folder tree of per-map parquet directories into a history CSV.

```
python ctw.py matches scan --folder DIR [--output CSV_PATH]
```

| Flag | Description |
|---|---|
| `--folder DIR` | Root folder containing per-map subdirectories of parquet files |
| `--output CSV_PATH` | Output CSV path (default: `<folder>/match_history.csv`) |

#### `matches index`

Index match parquet files into the `matches` table.

```
python ctw.py matches index [--match-dir DIR] [--history CSV_PATH]
```

| Flag | Description |
|---|---|
| `--match-dir DIR` | Directory containing match parquet files (default: `match_logs`) |
| `--history CSV_PATH` | CSV produced by `parse` or `scan` to resolve map names |

Matches for maps not yet in the `maps` table are skipped with a warning.

#### `matches list`

List matches in the database.

```
python ctw.py matches list [--map-name NAME] [--processed] [--unprocessed]
```

#### `matches stats`

Show database statistics (total matches, processed counts, per-map breakdown).

```
python ctw.py matches stats
```

#### `matches process`

Process a specific match by ID.

```
python ctw.py matches process MATCH_ID [--force]
```

#### `matches process-all`

Process all unprocessed matches. **Always use `--map-name` to scope by map** —
running without it across 700+ matches is slow.

```
python ctw.py matches process-all [--map-name NAME] [--force]
```

#### `matches post-process`

Re-run post-processing (life features, region visits, wool carry chains) without
reprocessing raw events. Useful after code changes.

```
python ctw.py matches post-process (--match ID | --all)
```

#### `matches reset`

Reset processing state (clears extracted data, keeps indexed matches).

```
python ctw.py matches reset [--match-id ID]
```

#### `matches trace`

Visualize player movement traces on the map.

```
python ctw.py matches trace --map NAME --match (ID | ID,ID,... | ALL) --player (ID | ALL)
    [--output PATH] [--overlay]
    [--no-deaths] [--no-kills] [--no-wool] [--no-edges]
    [--no-legend] [--no-stats]
    [--color-mode life|team|location]
    [--map-base outline|blocks]
```

| Flag | Description |
|---|---|
| `--match ID` | Match ID, comma-separated IDs, or `ALL` |
| `--player ID` | Player ID to visualize, or `ALL` for every player |
| `--overlay` | Overlay all matches onto a single plot (use with `--match ALL`) |
| `--color-mode` | `life` (per-segment, default), `team` (by spawn team), `location` (by position type) |
| `--map-base` | `outline` (polygon outlines, default) or `blocks` (individual blocks) |

```bash
python ctw.py matches trace --map Ingwaz --match 57 --player ALL --color-mode team
python ctw.py matches trace --map Ingwaz --match ALL --player ALL --overlay
python ctw.py matches trace --map Ingwaz --match 57 --player 0 --no-edges --color-mode location
```

#### `matches kills`

Visualize kill-death pairs on the map.

```
python ctw.py matches kills --map NAME --match (ID | ALL)
    [--output PATH] [--overlay]
    [--no-legend] [--no-stats]
    [--color-mode team|distance]
    [--map-base outline|blocks]
```

| Flag | Description |
|---|---|
| `--color-mode` | `team` (by killer team) or `distance` (green→red by kill range) |
| `--overlay` | Overlay all matches onto a single plot |

#### `matches traffic-graph`

Build a data-driven navigation graph from aggregated player position traces.

```
python ctw.py matches traffic-graph (--map NAME | --all)
    [--grid-size N] [--min-occupation N] [--min-transitions N]
    [--log-interval 2|5] [--strategy grid|voronoi]
    [--compare] [--force]
```

| Flag | Default | Description |
|---|---|---|
| `--grid-size N` | auto | Grid cell side in blocks; auto = `max(2, round(sqrt(total_blocks/300)))` |
| `--min-occupation N` | 5 | Minimum position ticks to keep a node |
| `--min-transitions N` | 2 | Minimum crossings to keep an edge |
| `--log-interval` | 2 | Only use matches logged at this interval (2 or 5 seconds) |
| `--strategy` | grid | `grid` or `voronoi` (k-means cluster nodes) |
| `--compare` | off | Generate a strategy comparison plot instead of building the graph |
| `--force` | off | Rebuild even if `traffic_graph.json` already exists |

Outputs `output/<map>/traffic_graph.json` and `output/<map>/traffic_graph.png`.

---

### `ctw debug` — Diagnostic Tools

Cross-map diagnostic commands for inspecting pipeline outputs.

#### `debug layout`

Scan a layout parquet across all maps and list unique block IDs found.

```
python ctw.py debug layout --parquet PARQUET [--dir DIR] [--csv PATH] [--water]
```

| Flag | Description |
|---|---|
| `--parquet PARQUET` | Parquet filename without extension (e.g. `layout_y0`) |
| `--water` | Analyze water blocks and check overlap with XML build regions |

```bash
python ctw.py debug layout --parquet layout_y0
python ctw.py debug layout --parquet layout_y0 --water
```

#### `debug data`

Scan output JSON files across all maps and report empty or missing fields.

```
python ctw.py debug data --json JSON_FILE [--dir DIR]
```

```bash
python ctw.py debug data --json map_data.json
python ctw.py debug data --json map_context.json
```

#### `debug symmetry`

Analyze map symmetry from preprocessed geometry (`map_context.json`).

```
python ctw.py debug symmetry [--map MAP] [--dir DIR]
```

Omit `--map` to scan all maps.

#### `debug compare`

Compare layout layers side-by-side (Y0 vs bedrock vs difference).

```
python ctw.py debug compare (--map MAP | --all) [--dir DIR] [--summary] [--output-dir DIR]
```

| Flag | Description |
|---|---|
| `--summary` | Text-only summary table, no plots (useful with `--all`) |

```bash
python ctw.py debug compare --map acapulco
python ctw.py debug compare --all --summary
```

#### `debug audit`

Scan layout parquet files (y0, bedrock, top_surface) across maps and populate two
audit tables in the database: `layout_layer_stats` (block count and y-range per layer)
and `layout_block_inventory` (per-block-ID counts per layer). Idempotent — safe to
re-run; existing rows for the affected maps are replaced.

```
python ctw.py debug audit (--map MAP[,MAP,...] | --all) [--dir DIR]
```

| Flag | Description |
|---|---|
| `--dir DIR` | Root directory containing per-map output folders (default: `output`) |

```bash
python ctw.py debug audit --all
python ctw.py debug audit --map acapulco,arabia
```

Maps not yet registered in the `maps` table are skipped with a warning. Run
`ctw maps load` first if needed.

#### `debug resources`

Plot chest and resource block locations on the map layout. Runs the same
zone classification as `ctw maps resources` without writing to the database.
Saves `output/<map>/resources_overview.png`.

```
python ctw.py debug resources --map MAP[,MAP,...] [--output DIR]
    [--defense-buffer N] [--near-spawn-buffer N]
```

```bash
python ctw.py debug resources --map arabia
python ctw.py debug resources --map arabia,tumbleweed
```

#### `debug prepare-demo`

Build traffic graph assets for a map and copy them to `docs/demo/assets/`.

```
python ctw.py debug prepare-demo --map MAP [--force]
```

---

### `ctw purge` — Delete Output Folders

Delete per-map output folders under `output/`. The `output/` root is never
touched — only the per-map subdirectories are removed.

```
python ctw.py purge (--map NAME[,NAME,...] | --all | --no-matches)
    [--output DIR] [--yes]
```

| Flag | Description |
|---|---|
| `--map NAME` | Delete output for specific map slug(s) (comma-separated) |
| `--all` | Delete all per-map output folders |
| `--no-matches` | Delete output for every map with no match data in the database |
| `--output DIR` | Output root to scan (default: `output/`) |
| `--yes` / `-y` | Skip confirmation prompt |

Prints folder names and sizes before deleting. Without `--yes`, prompts
for confirmation.

```bash
python ctw.py purge --no-matches
python ctw.py purge --map some_old_map
python ctw.py purge --all --yes
```

---

### `ctw db` — SQL Query Runner

Run SQL queries against the analysis database (`match_analysis/metadata.db`).

```
python ctw.py db [SQL]
python ctw.py db --list
python ctw.py db --run QUERY_ID[,QUERY_ID,...]
python ctw.py db --section SECTION_NAME
python ctw.py db --all
python ctw.py db --file SQL_FILE --run QUERY_ID
```

| Mode | Description |
|---|---|
| `ctw db "SELECT ..."` | Run an ad-hoc SQL query |
| `--list` | List named queries available in `scripts/debug_queries.sql` |
| `--run 1a` | Run named query `1a` from the default SQL file |
| `--run 1a,2b` | Run multiple named queries |
| `--section NAME` | Run all queries in a named section |
| `--all` | Run all queries from the file |
| `--file PATH` | Use a custom SQL file instead of the default |

```bash
python ctw.py db "SELECT COUNT(*) FROM matches"
python ctw.py db --list
python ctw.py db --run 5d
python ctw.py db --section "data integrity"
```

---

### `ctw info` — Map Status Summary

Display analysis status and key metrics for a map.

```
python ctw.py info --map NAME [--json]
```

| Flag | Description |
|---|---|
| `--json` | Output raw `map_context.json` instead of formatted summary |

---

### `ctw docs` — API Documentation

Regenerate `docs/api_index.json` from source code.

```
python ctw.py docs
```
