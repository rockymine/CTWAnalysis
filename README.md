# CTW Analysis Toolkit

A modular analysis toolkit for Capture the Wool (CTW) Minecraft maps and match data. Built with [Claude Code](https://claude.com/claude-code).

## Features

- **Layout Analysis**: Extract and analyze map block layouts from Minecraft region files
- **XML Analysis**: Parse PGM map.xml files to extract spawns, wools, regions, and teams
- **Island Detection**: Identify disconnected landmasses with skeleton graph extraction, D4 canonicalization, and POI annotation
- **Connectivity**: Build inter-island connectivity graphs with pathfinding analysis
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

The `region/` directory should contain the Minecraft world region files (e.g., `r.0.0.mca`). The `map.xml` is the PGM map definition with spawns, wools, and regions.

### 3. Populate Match Logs

Place match event parquet files into `match_logs/`:

```
match_logs/
  2026-01-24_09-26-48_3.parquet
  2026-01-24_10-42-00_15.parquet
  ...
```

Each parquet file contains event data for a single match with columns: `timestamp`, `event_type`, `player_id`, `x`, `y`, `z`, `held_item`, `inventory_count`, `wool_id`, `victim_id`.

## Running the Analysis

All commands go through the `ctw.py` CLI. See [docs/cli.md](docs/cli.md) for the full reference.

### Full Pipeline

```bash
# Analyze a single map (layout + islands + XML)
python ctw.py run --map your_map_name

# Analyze all maps
python ctw.py run --all --force

# With debug plots enabled
python ctw.py run --map your_map_name --plots
```

### Individual Steps

```bash
# Layout extraction (region files -> parquet)
python ctw.py layout --map your_map_name

# Island detection, skeleton, POI, connectivity
python ctw.py islands --map your_map_name

# XML parsing
python ctw.py xml --map your_map_name

# Check analysis status
python ctw.py info --map your_map_name
```

### Match Analysis

```bash
# Index match files into database
python ctw.py matches index

# List and inspect matches
python ctw.py matches list
python ctw.py matches stats

# Process trajectories
python ctw.py matches process-all

# Visualize player traces
python ctw.py matches trace --map Ingwaz --match 57 --player 0
python ctw.py matches trace --map Ingwaz --match 57 --player ALL --color-mode team
```

## Output Structure

After running the pipeline, each map folder will contain:

```
map_folders/your_map_name/
  region/                          # (input) Minecraft region files
  map.xml                          # (input) PGM map definition
  layout_bedrock.parquet           # extracted block coordinates with island_id
  layout_y0.parquet                # Y=0 layer
  layout_top_surface.parquet       # top surface layer
  map_data.json                    # parsed XML data
  map_graph.json                   # inter-island connectivity graph
  island_analysis/
    map_context.json               # aggregated map context (islands, POIs, build region)
    island_triangulation_detail.png  # triangulation overview (essential)
    map_connectivity.png             # connectivity graph visualization (essential)
    skeleton/
      unique_islands.png           # canonical shape comparison (essential)
      map_overview.png             # skeleton graph with polygons + build regions (essential)
      island_N_debug.png           # per-island skeleton debug (--plots)
      island_N_poi.png             # per-island POI annotation (--plots)
      skeleton_report.txt          # skeleton text report (--plots)
    pathfinding/
      island_N_paths.png           # pathfinding grids (--plots)
    island_comparison.png          # island overview (--plots)
    island_statistics.png          # size/shape statistics (--plots)
    island_report.txt              # text report (--plots)
  match_analysis/
    trace_player0_match57.png      # player trace visualizations
```

## Data Format

### Match Data (Parquet)

| Column | Description |
|--------|-------------|
| `timestamp` | Event time |
| `event_type` | 0=MATCH_START, 1=MATCH_END, 2=SPAWN, 3=KILL, 4=DEATH, 5=POSITION, 6=WOOL_TOUCH, 7=WOOL_CAPTURE |
| `player_id` | Player identifier |
| `x`, `y`, `z` | World coordinates |
| `held_item` | Currently held item |
| `inventory_count` | Inventory item count |
| `wool_id` | Wool identifier (for wool events) |

### Coordinate Convention

Block at integer index `(x, z)` occupies world space `[x, x+1] x [z, z+1]` with center at `(x+0.5, z+0.5)`. Parquet files store block positions as integer indices. XML regions use corner coordinates (world-space boundaries).

## Project Structure

```
CTWAnalysisWithClaudeCode/
├── ctw.py                           # CLI entry point
├── ctw/
│   ├── common.py                    # Shared CLI utilities
│   └── commands/                    # CLI command modules
│       ├── run.py                   # Full pipeline
│       ├── layout.py                # Layout extraction
│       ├── islands.py               # Island analysis
│       ├── xml.py                   # XML parsing
│       ├── matches.py               # Match analysis
│       ├── info.py                  # Map status
│       └── docs.py                  # API docs generation
├── layout_analysis/                 # Layout extraction and orchestration
│   ├── services/                    # Orchestration (layout_service, islands_service)
│   └── map_context.py               # MapContext aggregation
├── island_analysis/                 # Island detection, triangulation, visualization
├── skeleton_analysis/               # Skeleton extraction, POI annotation, pathfinding
│   ├── canonicalize.py              # D4 dihedral group canonicalization
│   ├── skeletonize.py               # Morphological thinning
│   ├── poi_annotation.py            # Spawn/wool POI classification
│   ├── pathfinding.py               # Intra-island path analysis
│   ├── visualize.py                 # Skeleton and POI visualization
│   └── connectivity/               # Inter-island connectivity graph
├── xml_analysis/                    # PGM XML parsing
│   ├── parser.py                    # Map XML parser
│   ├── regions.py                   # Region type hierarchy
│   ├── build_regions.py             # Build region extraction
│   └── exporter.py                  # JSON export
├── match_analysis/                  # Match event processing
│   ├── match_indexer.py             # Match file indexing (DuckDB)
│   ├── match_processor.py           # Per-match processing orchestrator
│   ├── extractors.py                # Event extraction (life segments, combat, etc.)
│   ├── position_classifier.py       # Position classification
│   ├── visualization.py             # Player trace plotting
│   └── services/                    # Match service layer
├── visualization/                   # Shared visualization utilities
│   ├── map_primitives.py            # Map base layer rendering
│   └── colors.py                    # Team/POI color definitions
├── docs/                            # Documentation
│   ├── cli.md                       # CLI reference
│   └── api_index.json               # Auto-generated API docs
├── map_folders/                     # Map data (not tracked in git)
├── match_logs/                      # Match parquet files (not tracked in git)
└── requirements.txt                 # Python dependencies
```

## License

This project is for educational and analysis purposes.
