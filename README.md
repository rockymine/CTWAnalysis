# CTW Analysis Toolkit

A modular analysis toolkit for Capture the Wool (CTW) Minecraft maps and match data.
Built with [Claude Code](https://claude.com/claude-code).

## Features

- **Layout Analysis**: Extract block layouts from Minecraft region files into parquet files
- **Island Detection**: Identify disconnected landmasses with skeleton graph extraction and D4 canonicalization
- **Symmetry Analysis**: Detect global and intra-team geometric symmetry (rotational, mirror)
- **XML Analysis**: Parse PGM `map.xml` files to extract spawns, wools, regions, and teams
- **Match Analysis**: Index match logs, visualize player traces with event filtering and block-level map rendering

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Populate Map Folders

Each map needs its own folder inside `map_folders/` containing:

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

Each parquet file contains event data for a single match. Columns: `timestamp`,
`event_type`, `player_id`, `x`, `y`, `z`, `held_item`, `inventory_count`,
`wool_id`, `victim_id`.

### 4. Configuration (optional)

Create `ctw_config.yaml` in the project root to set persistent defaults:

```yaml
global:
  plots: false

islands:
  simplify: 1.0
  buffer: 0.0
  connectivity: 8
  min_size: 10

layout:
  skip_y0: true
  skip_surface: true
  skip_density: true
```

CLI arguments always override config file values.

---

## Running the Analysis

All commands go through `ctw.py`. See [docs/cli.md](docs/cli.md) for the full reference.

### Full Pipeline

```bash
# Analyze a single map (stages 1-4)
python ctw.py run --map your_map_name

# Analyze all maps in map_folders/ in parallel
python ctw.py run --all --workers 4

# Skip maps that already have output
python ctw.py run --all --skip-existing

# Force regeneration even if outputs exist
python ctw.py run --map your_map_name --force

# With debug plots enabled
python ctw.py run --map your_map_name --plots

# Write outputs to a custom directory
python ctw.py run --map your_map_name --output /path/to/output
```

Note: Stage 5 (match analysis integration) is not yet wired into `run` —
use the `matches` subcommands directly.

### Individual Stages

```bash
# Stage 1: Layout extraction (region files → parquet)
python ctw.py layout --map your_map_name

# Stage 2: Island detection, skeleton, POI annotation
python ctw.py islands --map your_map_name

# Stage 4: XML parsing
python ctw.py xml --map your_map_name

# Inspect output status for a map
python ctw.py info --map your_map_name
```

Note: Stage 3 (symmetry analysis) has no standalone subcommand — it runs
automatically inside `ctw run` after Stage 2.

### Match Analysis

```bash
# Index match files into DuckDB
python ctw.py matches index

# List and inspect matches
python ctw.py matches list
python ctw.py matches stats

# Process match trajectories
python ctw.py matches process-all

# Visualize player traces
python ctw.py matches trace --map Ingwaz --match 57 --player 0
python ctw.py matches trace --map Ingwaz --match 57 --player ALL --color-mode team
```

---

## Output Structure

All pipeline outputs are written to `output/` (separate from the read-only
`map_folders/` inputs).

```
output/
  your_map_name/
    layout_bedrock.parquet            # Stage 1 — lowest bedrock per column (primary for islands)
    layout_y0.parquet                 # Stage 1 — non-air blocks at y=0
    layout_top_surface.parquet        # Stage 1 — highest non-air block per column
    layout_vertical_density.parquet   # Stage 1 — columns meeting density threshold
    map_context.json                  # Stage 2 — aggregated map context (islands, skeleton, POIs)
    map_graph.json                    # Stage 2 — island skeleton graph
    symmetry.json                     # Stage 3 — symmetry detection results
    map_data.json                     # Stage 4 — parsed XML data
    island_analysis/
      island_detail.png               # Triangulation overview (always produced)
      skeleton/
        unique_islands.png            # Canonical shape comparison (always produced)
        map_overview.png              # Skeleton graph with polygons + build regions (always produced)
        island_N_debug.png            # Per-island skeleton debug (--plots only)
        island_N_poi.png              # Per-island POI annotation (--plots only)
        skeleton_report.txt           # Skeleton text report (--plots only)
      island_comparison.png           # Island overview (--plots only)
      island_statistics.png           # Size/shape statistics (--plots only)
      island_report.txt               # Text report (--plots only)
    match_analysis/
      trace_*.png                     # Player trace visualizations

match_analysis/
  metadata.db                         # DuckDB match index (created on first use)
  trajectories/
    <match_id>.parquet                # Processed life-segment trajectories
```

---

## Data Formats

### Match Event Parquet

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

Block at integer index `(x, z)` occupies world space `[x, x+1] × [z, z+1]` with
center at `(x+0.5, z+0.5)`. Parquet files store block positions as integer indices.
XML regions use corner coordinates (world-space boundaries). See
[`common/geometry/COORDINATE_SYSTEMS.md`](common/geometry/COORDINATE_SYSTEMS.md)
for the full coordinate system documentation.

---

## Pipeline Architecture

```
map_folders/<name>/region/*.mca
map_folders/<name>/map.xml
         │
         ▼
[Stage 1]  layout_analysis/
           RegionReader → Extractors (Y0, surface, density, bedrock)
           → output/<name>/layout_*.parquet
         │
         ▼
[Stage 2]  island_analysis/ + skeleton_analysis/
           detect_islands() → build polygons → skeletonize → annotate POIs
           → output/<name>/map_context.json
           → output/<name>/map_graph.json
           → output/<name>/island_analysis/
         │
         ▼
[Stage 3]  symmetry_analysis/
           detect_symmetry(map_context.json)
           → output/<name>/symmetry.json
         │
         ▼
[Stage 4]  xml_analysis/
           MapXMLParser(map.xml)
           → output/<name>/map_data.json
         │
         ▼
[Stage 5]  match_analysis/  (standalone — not wired into `run`)
           match indexing → match_analysis/metadata.db
           trajectory processing → match_analysis/trajectories/
           trace visualization → output/<name>/match_analysis/
```

---

## Project Structure

```
CTWAnalysis/
├── ctw.py                               # CLI entry point (thin wrapper)
├── ctw/                                 # CLI package
│   ├── cli.py                           # Argument parser + main()
│   ├── common.py                        # Shared helpers: resolve_map_folder,
│   │                                    #   resolve_output_dir, ensure_match_db
│   ├── config.py                        # YAML config loader (ctw_config.yaml)
│   └── commands/                        # One module per subcommand
│       ├── run.py                       # Full pipeline (stages 1–4)
│       ├── layout.py                    # Stage 1 only
│       ├── islands.py                   # Stage 2 only
│       ├── xml.py                       # Stage 4 only
│       ├── matches.py                   # Match indexing, processing, trace plots
│       ├── maps.py                      # Map management utilities
│       ├── debug.py                     # Diagnostics and debug commands
│       ├── db.py                        # Database management
│       ├── info.py                      # Map status display
│       └── docs.py                      # API doc generation
│
├── layout_analysis/                     # Stage 1: region I/O → parquet
│   ├── region_reader.py                 # Anvil .mca reader (streaming)
│   ├── extractors.py                    # Y0 / surface / density / bedrock extractors
│   ├── utils.py                         # NBT nibble/block-ID decoding
│   ├── datatypes.py                     # MapContext dataclass  [⚠ see Structural Notes]
│   ├── builder.py                       # build_map_context()   [⚠ see Structural Notes]
│   ├── exporter.py                      # MapContext → JSON     [⚠ see Structural Notes]
│   ├── visualization.py                 # Layout scatter plots
│   └── services/layout_service.py      # analyze_layout() orchestrator
│
├── island_analysis/                     # Stage 2a: island detection + polygons
│   ├── datatypes.py                     # Island dataclass
│   ├── detection.py                     # Connected-component flood fill
│   ├── polygon.py                       # Shapely polygon construction
│   ├── statistics.py                    # Island statistics + classification
│   ├── visualization.py                 # Island plots
│   └── services/islands_service.py     # analyze_islands_step() (8-stage orchestrator)
│
├── skeleton_analysis/                   # Stage 2b: skeleton graphs + POI annotation
│   ├── datatypes.py                     # GraphNode, GraphEdge, SkeletonGraph, IslandResult
│   ├── canonicalize.py                  # D4 canonicalization
│   ├── rasterize.py                     # World → raster space
│   ├── skeletonize.py                   # Morphological thinning
│   ├── nodes.py / edges.py             # Graph node + edge extraction
│   ├── merge.py / prune.py             # Graph cleanup
│   ├── pipeline.py                      # process_all_islands()
│   ├── poi_annotation.py                # Spawn/wool POI classification
│   ├── builder.py                       # Map graph construction
│   ├── exporter.py                      # map_graph.json export
│   └── visualization.py                 # Skeleton + POI plots
│
├── symmetry_analysis/                   # Stage 3: geometric symmetry detection
│   ├── builder.py                       # detect_symmetry() — all four detection stages
│   ├── exporter.py                      # symmetry.json export
│   └── report.py                        # Text report generation
│
├── xml_analysis/                        # Stage 4: PGM map.xml parsing
│   ├── datatypes.py                     # MapData, Team, Spawn, Wool, ApplyRule
│   ├── builder.py                       # MapXMLParser
│   ├── regions.py                       # Region type hierarchy
│   ├── build_regions.py                 # Build region extraction
│   ├── exporter.py                      # map_data.json export
│   ├── visualization.py                 # XML region plots
│   └── services/xml_service.py         # analyze_xml() orchestrator
│
├── match_analysis/                      # Stage 5: match event processing
│   ├── match_indexer.py                 # DuckDB match file indexer
│   ├── match_log_parser.py              # Parquet event log parser
│   ├── match_processor.py              # Per-match processing orchestrator
│   ├── extractors.py                    # Life segment / combat / wool extraction
│   ├── position_classifier.py          # Position classification
│   ├── team_extractor.py               # Team membership extraction
│   ├── visualization.py                 # Player trace plotting
│   └── services/match_service.py       # Match service layer
│
├── common/                              # Shared libraries
│   └── geometry/                        # Coordinate math and spatial types
│       ├── coordinates.py               # get_grid_extent, block_centers, etc.
│       ├── transforms.py                # CanonicalTransform, RasterMask
│       └── COORDINATE_SYSTEMS.md        # Authoritative coordinate documentation
│
├── visualization/                       # Shared map rendering primitives [⚠ see Structural Notes]
│   ├── colors.py                        # Team and POI color constants
│   └── map_primitives.py               # draw_island_outlines, draw_pois,
│                                        #   draw_build_region, draw_map_base
│
├── scripts/                             # DB setup utilities             [⚠ see Structural Notes]
│   ├── initialize_analysis_db.py        # DuckDB schema creation
│   └── test_database_setup.py          # Integration test script
│
├── json_export.py                       # Shared numpy-aware JSON serializer [⚠ see Structural Notes]
├── overview.py                          # Generates docs/api_index.json (AST scraper)
│
├── map_folders/                         # Input: map data (not tracked in git)
├── match_logs/                          # Input: match parquet files (not tracked)
├── output/                             # Generated outputs (not tracked in git)
└── docs/
    ├── cli.md                           # CLI reference
    ├── api_index.json                   # Auto-generated (via overview.py)
    └── demo/                            # Demo assets and generation script
```

---

## Structural Notes

The items below are known placement or naming issues. They work correctly today
but are inconsistent with the project's conventions.

### `visualization/` — belongs in `common/`

The top-level `visualization/` package is a **shared rendering primitive
library** (`draw_island_outlines`, `draw_pois`, `draw_build_region`, team
color constants). It is consumed by `match_analysis/visualization.py`,
`skeleton_analysis/visualization.py`, `island_analysis/visualization.py`, and
`docs/demo/generate_demo.py` — making it shared infrastructure on par with
`common/geometry/`.

The name directly conflicts with five per-package `visualization.py` modules
(one in each analysis package). A reader cannot easily distinguish the shared
library from the per-package rendering helpers without opening both.

It should move to `common/visualization/`.

### `scripts/` — belongs in `match_analysis/`

`scripts/` is not a Python package (no `__init__.py`) but is imported as one.
Both files are exclusively coupled to `match_analysis/`:

- `initialize_analysis_db.py` hardcodes `match_analysis/metadata.db` and creates
  the DuckDB schema used only by match analysis.
- `test_database_setup.py` is an integration smoke-test, not a proper unittest.

`ctw/common.py::ensure_match_db()` imports from `scripts/`, creating a reversed
dependency: the CLI layer depends on a loose root-level `scripts/` directory.
`initialize_analysis_db.py` should move to `match_analysis/db_setup.py`.

### `json_export.py` — belongs in `common/`

A shared numpy-aware JSON serializer used by `layout_analysis`, `skeleton_analysis`,
`xml_analysis`, and `symmetry_analysis`. It lives at the project root as a
standalone module instead of in `common/`.

### `layout_analysis/{datatypes,builder,exporter}.py` — belong in `common/`

`MapContext` is a pipeline-wide result aggregate. `builder.build_map_context()`
imports from `island_analysis`, `skeleton_analysis`, `xml_analysis`, and
`layout_analysis` simultaneously. Placing it inside `layout_analysis` inverts
the dependency hierarchy — the Stage 1 I/O package ends up knowing about all
downstream analytical types. See the open GitHub issue for the full analysis
and migration plan to `common/map_context/`.

### Monolithic files (>500 lines)

| File | Lines | Notes |
|------|------:|-------|
| `symmetry_analysis/builder.py` | 947 | All four detection stages in one file |
| `ctw/commands/debug.py` | 863 | Mixes symmetry, skeleton, and DB debug commands |
| `symmetry_analysis/tests/test_detector.py` | 701 | Single test class for all scenarios |
| `ctw/commands/matches.py` | 692 | Many subcommands in one module |
| `match_analysis/visualization.py` | 610 | Multiple distinct rendering modes |
| `xml_analysis/builder.py` | 564 | Region type dispatch and XML tree walking |
| `island_analysis/services/islands_service.py` | 547 | Full 8-stage pipeline in one function |
| `island_analysis/visualization.py` | 542 | Many figure types combined |
| `skeleton_analysis/visualization.py` | 518 | Skeleton, POI, and pathfinding renders |

---

## License

This project is for educational and analysis purposes.
