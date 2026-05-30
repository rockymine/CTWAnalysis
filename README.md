# CTW Analysis Toolkit

A modular analysis toolkit for Capture the Wool (CTW) Minecraft maps and match data. Built with [Claude Code](https://claude.com/claude-code).

## Features

- **Layout Analysis**: Extract and analyze map block layouts from Minecraft region files
- **XML Analysis**: Parse PGM map.xml files to extract spawns, wools, regions, and teams
- **Island Detection**: Identify disconnected landmasses with skeleton graph extraction, D4 canonicalization, and POI annotation
- **Symmetry Detection**: Detect global and intra-team geometric symmetry from island geometry
- **Map Assembly**: Combine island geometry, symmetry, and XML into a complete map model
- **Match Analysis**: Index match logs, extract trajectories, and classify player positions
- **Visualization**: Player trace plotting with multiple color modes, event filtering, and block-level map rendering

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Populate Map Folders

Each map needs its own folder inside `map_folders/` containing the Minecraft world data:

```
map_folders/
  your_map_name/
    region/           # Minecraft region files (.mca)
    map.xml           # PGM map XML file
```

### 3. Populate Match Logs

Place match event parquet files into `match_logs/`:

```
match_logs/
  2026-01-24_09-26-48_3.parquet
  2026-01-24_10-42-00_15.parquet
  ...
```

Each parquet file contains event data for a single match. See [docs/analysis_overview.md](docs/analysis_overview.md) for a full description of the raw data format.

## Running the Analysis

All commands go through the `ctw.py` CLI. See [docs/cli.md](docs/cli.md) for the full reference.

### Map Pipeline

```bash
# Analyze a single map (layout + islands + symmetry + XML + assembly)
python ctw.py run --map your_map_name --no-matches

# Analyze all maps
python ctw.py run --all --no-matches

# With debug plots enabled
python ctw.py run --map your_map_name --no-matches --plots

# Check analysis status
python ctw.py info --map your_map_name
```

### Map Resources (optional)

```bash
# Classify and store resource blocks and chests for a map
python ctw.py maps resources --map your_map_name

# Visualize resource and chest locations without writing to DB
python ctw.py debug resources --map your_map_name
```

### Match Analysis

```bash
# Load map into the database (run after ctw run)
python ctw.py maps load --map your_map_name
python ctw.py maps spawns --map your_map_name

# Index match files, then process
python ctw.py matches index --match-dir match_logs/
python ctw.py matches process-all --map-name your_map_name

# Visualize player traces
python ctw.py matches trace --map your_map_name --match 57 --player ALL --color-mode team

# Visualize kill locations
python ctw.py matches kills --map your_map_name --match ALL --overlay
```

## Analysis Pipeline

The map pipeline runs five sequential steps:

```
[1/5] Layout     ctw layout      Extract block data from region files → layout_*.parquet
[2/5] Islands    ctw islands     Detect landmasses, skeleton graphs, POIs → islands.json
[3/5] Symmetry   (ctw run)       Detect global geometric symmetry → symmetry.json
[4/5] XML        ctw xml         Parse map.xml for teams/spawns/wools → map_data.json
[5/5] Assembly   (ctw run)       Combine everything → map_context.json, map_graph.json
```

Steps 1, 2, and 4 can be run individually. Steps 3 and 5 are only run as part of `ctw run`.

For a detailed explanation of each step, the data produced, and the match processing pipeline, see [docs/analysis_overview.md](docs/analysis_overview.md).

## Output Structure

After running the full pipeline, outputs are written to `output/<map>/`:

```
output/your_map_name/
  layout_bedrock.parquet           # extracted block coordinates
  layout_y0.parquet                # Y=0 layer
  layout_top_surface.parquet       # top surface layer
  layout_vertical_density.parquet  # vertical density
  layout_resource_blocks.parquet   # iron/gold/diamond block positions
  layout_chest_contents.parquet    # chest inventories
  map_data.json                    # parsed XML data
  map_context.json                 # complete aggregated map model
  map_graph.json                   # inter-island connectivity graph
  symmetry.json                    # detected symmetry axes
  island_analysis/
    islands.json                   # island geometry data
    island_triangulation_detail.png
    unique_islands.png
    map_overview.png
    map_connectivity.png
    skeleton/
      world_overview.png
      (per-island debug images with --plots)
  traffic_graph.json               # data-driven navigation graph (after matches)
  traffic_graph.png
```

Input files in `map_folders/<map>/` are never modified.

## Project Structure

```
CTWAnalysisWithClaudeCode/
├── ctw.py                           # CLI entry point
├── ctw/
│   ├── common.py                    # Shared CLI utilities
│   └── commands/                    # CLI command modules
│       ├── run.py                   # Full pipeline orchestration
│       ├── layout.py                # Layout extraction
│       ├── islands.py               # Island geometry (standalone)
│       ├── xml.py                   # XML parsing
│       ├── matches.py               # Match analysis
│       ├── maps.py                  # Map metadata (load/spawns/resources)
│       ├── debug.py                 # Diagnostic tools
│       ├── info.py                  # Map status
│       └── docs.py                  # API docs generation
├── layout_analysis/                 # Layout extraction from region files
├── island_analysis/                 # Island detection and polygon construction
├── skeleton_analysis/               # Skeleton extraction, POI annotation, pathfinding
├── symmetry_analysis/               # Symmetry detection
├── xml_analysis/                    # PGM XML parsing
├── match_analysis/                  # Match event processing and database
├── visualization/                   # Shared visualization utilities
├── common/                          # Geometry types, coordinate utilities
├── notebooks/                       # Jupyter analysis notebooks
├── docs/                            # Documentation
│   ├── cli.md                       # CLI reference
│   ├── analysis_overview.md         # Match data pipeline and feature definitions
│   ├── contributing.md              # Developer guidelines
│   └── demo/                        # Visual walkthroughs
├── map_folders/                     # Map data (not tracked in git)
├── output/                          # Pipeline outputs (not tracked in git)
├── match_logs/                      # Match parquet files (not tracked in git)
└── requirements.txt                 # Python dependencies
```

## Documentation

| Document | Contents |
|---|---|
| [docs/cli.md](docs/cli.md) | Full CLI reference for all commands and flags |
| [docs/analysis_overview.md](docs/analysis_overview.md) | Raw data format, match pipeline, feature definitions, clustering |
| [docs/contributing.md](docs/contributing.md) | Logging conventions, type annotations, domain types |
| [docs/demo/README.md](docs/demo/README.md) | Visual walkthroughs of pipeline output |
| [xml_analysis/README.md](xml_analysis/README.md) | PGM XML schema, region types, build region extraction |
| [layout_analysis/README.md](layout_analysis/README.md) | Region file format, extractors, feature classifiers |
| [match_analysis/README.md](match_analysis/README.md) | Database schema, setup workflow, clustering notebook |
| [symmetry_analysis/README.md](symmetry_analysis/README.md) | Symmetry detection stages and confidence scoring |
| [common/geometry/COORDINATE_SYSTEMS.md](common/geometry/COORDINATE_SYSTEMS.md) | Coordinate spaces, the +1 rule, plotting recipes |

## License

This project is for educational and analysis purposes.
