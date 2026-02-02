# CTW Analysis Toolkit — CLI Reference

## Quick Start

```bash
# Full pipeline for one map
python ctw.py run --map tumbleweed --no-matches

# Full pipeline for all maps
python ctw.py run --all --force --no-matches

# Check what's been analyzed
python ctw.py info --map tumbleweed

# Run individual steps
python ctw.py layout --map tumbleweed
python ctw.py islands --map tumbleweed
python ctw.py xml --map tumbleweed
```

The `--map` flag accepts either a map name (resolved from `map_folders/`) or a
direct path to a map folder.

---

## Commands

### `ctw run` — Full Analysis Pipeline

Runs layout extraction, island analysis, XML parsing, and match analysis in
sequence. Delegates to the same functions as `run_analysis_workflow.py`.

```
python ctw.py run (--map NAME | --all) [--force]
    [--no-layout] [--no-islands] [--no-xml] [--no-matches]
    [--match-history PATH] [--island-layout bedrock|y0|top|density]
    [--canonical-triangulation]
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

Default runs the full pipeline (detection, triangulation, skeleton extraction,
POI annotation, pathfinding, connectivity graph). Use `--basic` for quick
detection without the full analysis stack.

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

### `ctw match` — Single Match Analysis

Analyze a match replay with team visualization, classification, and path
network extraction.

```
python ctw.py match --map NAME --match FILE [--output DIR]
    [--no-team-networks] [--no-pdf] [--no-classification]
    [--resolution F] [--cluster-radius F]
```

| Flag | Description |
|---|---|
| `--match FILE` | Match parquet filename (from `match_logs/`) |
| `--output DIR` | Override output directory |
| `--no-team-networks` | Skip team-specific path network plots |
| `--no-pdf` | Skip PDF report generation |
| `--no-classification` | Skip segment classification |
| `--resolution F` | Grid resolution for path networks (default: 1.0) |
| `--cluster-radius F` | Waypoint clustering radius (default: 5.0) |

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

---

## Legacy Scripts

The following standalone scripts remain available. They are not deprecated but
`ctw.py` is the recommended entry point for new usage.

| Legacy Script | CLI Equivalent |
|---|---|
| `run_analysis_workflow.py --map X` | `ctw.py run --map X` |
| `run_layout_analysis.py --world X/region` | `ctw.py layout --map X --plots` |
| `run_xml_analysis.py --xml X/map.xml` | `ctw.py xml --map X --visualize` |
| `analyze_islands.py --bedrock X/layout_bedrock.parquet` | `ctw.py islands --map X --basic` |
| `generate_path_networks.py --match F` | `ctw.py match --map X --match F` |

Scripts with no CLI equivalent (config.json-driven or interactive):
- `classify_segments.py` — detailed role classification with config.json
- `generate_plots.py` — team/role-filtered static plots with config.json
- `analyze_match.py` — interactive matplotlib visualization
- `explore_map_characteristics.py` — exploratory analysis
