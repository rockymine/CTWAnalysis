# CTW Analysis Toolkit — CLI Reference

## Quick Start

```bash
# Full pipeline for one map
python ctw.py run --map tumbleweed

# Full pipeline for all maps
python ctw.py run --all --force

# Check what's been analyzed
python ctw.py info --map tumbleweed

# Run individual steps
python ctw.py layout --map tumbleweed
python ctw.py islands --map tumbleweed
python ctw.py xml --map tumbleweed

# Match analysis
python ctw.py matches index
python ctw.py matches trace --map Ingwaz --match 57 --player 0
```

The `--map` flag accepts either a map name (resolved from `map_folders/`) or a
direct path to a map folder.

---

## Commands

### `ctw run` — Full Analysis Pipeline

Runs layout extraction, island analysis, XML parsing, and match analysis in
sequence.

```
python ctw.py run (--map NAME | --all) [--force]
    [--no-layout] [--no-islands] [--no-xml] [--no-matches]
    [--match-history PATH] [--island-layout bedrock|y0|top|density]
    [--canonical-triangulation] [--plots]
```

| Flag | Description |
|---|---|
| `--map NAME` | Map name to analyze |
| `--all` | Analyze all maps in `map_folders/` |
| `--force` | Regenerate even if outputs exist |
| `--no-layout` | Skip layout extraction (step 1) |
| `--no-islands` | Skip island/skeleton analysis (step 2) |
| `--no-xml` | Skip XML parsing (step 3) |
| `--no-matches` | Skip match analysis (step 4) |
| `--match-history PATH` | Match history file (default: `match_logs/match_history.txt`) |
| `--island-layout` | Layout file for islands: `bedrock`, `y0`, `top`, `density` |
| `--canonical-triangulation` | Identical islands share the same mesh |
| `--plots` | Generate debug plots for layout and island analysis |

---

### `ctw layout` — Layout Extraction

Extract block data from Minecraft region files into parquet files.

```
python ctw.py layout --map NAME [--force]
    [--threshold N] [--density-mode run,count]
    [--skip-y0] [--skip-surface] [--skip-density] [--skip-bedrock]
    [--output DIR] [--plots]
```

| Flag | Description |
|---|---|
| `--threshold N` | Density threshold (default: 10) |
| `--density-mode` | Comma-separated modes: `run`, `count` |
| `--skip-y0` | Skip Y=0 layer |
| `--skip-surface` | Skip top surface |
| `--skip-density` | Skip vertical density |
| `--skip-bedrock` | Skip lowest bedrock |
| `--output DIR` | Save to custom directory instead of map folder |
| `--plots` | Generate visualization plots alongside data |

Default behavior saves parquets into the map folder. Adding `--plots` or
`--output` uses the extended extraction pipeline with plot generation.

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
| `--layout` | Which layout file to use (default: `bedrock`) |
| `--canonical-triangulation` | D4-symmetric islands share mesh |
| `--basic` | Basic mode: detection + triangulation only, no skeleton/POI/connectivity |
| `--output DIR` | Save to custom directory instead of `island_analysis/` |
| `--plots` | Generate debug plots (per-island debug, POI, pathfinding) |

Default runs the full pipeline (detection, triangulation, skeleton extraction,
POI annotation, pathfinding, connectivity graph) and generates essential figures
only. Add `--plots` to also generate per-island debug images, POI annotations,
pathfinding grids, and the full island report. Use `--basic` for quick detection
without the full analysis stack.

**Essential figures** (always generated):
`island_triangulation_detail.png`, `unique_islands.png`, `world_overview.png`,
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

Default behavior parses XML and saves `map_data.json`. Add `--visualize` for
region layout plots.

---

### `ctw matches` — Match Data Analysis

Index, process, and visualize match data. Uses a DuckDB database
(`match_analysis/metadata.db`) to track indexed matches.

#### `matches index`

Scan match parquet files and index them into the database.

```
python ctw.py matches index [--match-dir DIR]
```

| Flag | Description |
|---|---|
| `--match-dir DIR` | Directory containing match parquet files (default: `match_logs`) |

#### `matches list`

List matches in the database.

```
python ctw.py matches list [--map-name NAME] [--processed] [--unprocessed]
```

| Flag | Description |
|---|---|
| `--map-name NAME` | Filter by map name |
| `--processed` | Show only processed matches |
| `--unprocessed` | Show only unprocessed matches |

#### `matches process`

Process a specific match by ID (extracts trajectories).

```
python ctw.py matches process MATCH_ID [--force]
```

#### `matches process-all`

Process all unprocessed matches.

```
python ctw.py matches process-all [--map-name NAME] [--force]
```

| Flag | Description |
|---|---|
| `--map-name NAME` | Only process matches for this map |
| `--force` | Reprocess all matches, not just unprocessed ones |

#### `matches reset`

Reset processing state and delete trajectory files.

```
python ctw.py matches reset [--match-id ID]
```

| Flag | Description |
|---|---|
| `--match-id ID` | Reset only a specific match (default: reset all) |

#### `matches stats`

Show database statistics (total matches, processed counts, per-map breakdown).

```
python ctw.py matches stats
```

#### `matches trace`

Visualize player movement traces on the map.

```
python ctw.py matches trace --map NAME --match ID --player (ID | ALL)
    [--output PATH]
    [--no-deaths] [--no-kills] [--no-wool] [--no-edges]
    [--no-legend] [--no-stats]
    [--color-mode life|team|location]
    [--map-base outline|blocks]
```

| Flag | Description |
|---|---|
| `--map NAME` | Map name or path to map folder |
| `--match ID` | Match ID (from database) |
| `--player ID` | Player ID to visualize, or `ALL` for every player |
| `--output PATH` | Output PNG path (default: auto-generated in `match_analysis/`) |
| `--no-deaths` | Hide death markers |
| `--no-kills` | Hide kill markers |
| `--no-wool` | Hide wool event markers |
| `--no-edges` | Show position dots instead of trace lines |
| `--no-legend` | Hide the legend |
| `--no-stats` | Hide the stats box |
| `--color-mode` | Color scheme: `life` (per-segment, default), `team` (by spawn team), `location` (by position type) |
| `--map-base` | Map base layer: `outline` (polygon outlines, default) or `blocks` (individual blocks) |

Examples:
```bash
# Single player trace
python ctw.py matches trace --map Ingwaz --match 57 --player 0

# All players, colored by team
python ctw.py matches trace --map Ingwaz --match 57 --player ALL --color-mode team

# Dots only (no trace lines), colored by location type
python ctw.py matches trace --map Ingwaz --match 57 --player 0 --no-edges --color-mode location

# Block-level map base
python ctw.py matches trace --map Ingwaz --match 57 --player 0 --map-base blocks
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

Example output:
```
Map: segment
Path: /path/to/map_folders/segment

Output files:
  [OK] Layout Y0
  [OK] Layout Bedrock
  [OK] Map Context
  ...

Map name:    Segment
Version:     1.1.0
Islands:     5
Build region: source=xml, void_area=3551.9
```

---

### `ctw docs` — API Documentation

Regenerate `docs/api_index.json` from source code.

```
python ctw.py docs
```
