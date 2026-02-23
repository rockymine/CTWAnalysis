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
# Analyze a single map (layout + islands + symmetry + XML + assembly)
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
python ctw.py matches process-all --map-name your_map_name

# Visualize player traces
python ctw.py matches trace --map Ingwaz --match 57 --player 0
python ctw.py matches trace --map Ingwaz --match 57 --player ALL --color-mode team
```

## Analysis Pipeline

The full pipeline runs six sequential steps. Each step produces a typed in-memory result object that is passed directly to the next step — JSON files are written only as debug artifacts for human inspection and are never read back as pipeline inputs.

```
[1/6] Layout        ctw layout          analyze_layout()         layout_*.parquet
[2/6] Islands       ctw islands         run_island_geometry()    IslandGeometryResult
[3/6] Symmetry      (part of ctw run)   run_symmetry()           SymmetryResult
[4/6] XML           ctw xml             analyze_xml()            MapXmlContext
[5/6] Assembly      (part of ctw run)   assemble_map()           MapContext
[6/6] Matches       ctw matches         (not yet implemented)
```

### Step 1 — Layout (`analyze_layout`)

**Module**: `ctw/commands/layout.py`

Reads Minecraft region files (`region/*.mca`) and extracts block coordinates into parquet files. Multiple layout variants capture different cross-sections of the map.

**Outputs** (in `output/<map>/`):
- `layout_bedrock.parquet` — bedrock-anchored block layer (default for island detection)
- `layout_y0.parquet` — Y=0 layer (used for build region detection via block 36)
- `layout_top_surface.parquet` — topmost non-air block per column
- `layout_vertical_density.parquet` — density-weighted column summary

**Return value**: none (writes files only).

---

### Step 2 — Island Geometry (`run_island_geometry`)

**Module**: `map_analysis/pipeline.py`
**Public function**: `run_island_geometry(map_folder, ...) -> Optional[IslandGeometryResult]`

Pure geometry pipeline — no XML knowledge. Reads a layout parquet, detects disconnected landmasses, builds simplified polygons, computes skeleton graphs (morphological thinning), canonicalizes island shapes under the D4 dihedral group, and classifies island centers relative to the map center.

**Returns** `None` only on failure (missing layout file or no islands detected).

**`write_outputs` behaviour**: computation always runs in full. File writes (visualizations, `islands.json`) are skipped when `islands.json` already exists and `force_rerun=False`. This means the returned `IslandGeometryResult` always contains fresh in-memory objects even on a cache hit.

**Outputs** (in `output/<map>/island_analysis/`):
- `islands.json` — island geometry data (debug artifact; also read by `run_symmetry`)
- `island_detail.png` — island layout overview (always generated)
- `skeleton/unique_islands.png` — canonical shape comparison (always generated)
- `skeleton/map_overview.png` — skeleton graph with polygons + build regions (written by `assemble_map`)
- `skeleton/island_N_debug.png` — per-canonical-shape debug (requires `--plots`)
- `skeleton/skeleton_report.txt` — skeleton text report (requires `--plots`)

#### `IslandGeometryResult` fields

```python
@dataclass
class IslandGeometryResult:
    islands: List[Island]                          # Island objects with .blocks, .center, .simplified_polygon, etc.
    skeleton_results: List[IslandResult]           # One IslandResult per island (graph, nodes, edges)
    canonical_groups: Dict[str, List[int]]         # canonical_key -> [island_id, ...]
    df: pd.DataFrame                               # Full layout dataframe (world_x, world_z, island_id, ...)
    island_output_dir: Path                        # Resolved path to island_analysis/ subdir
    map_center_pt: Optional[Tuple[float, float]]   # Map centroid (world coords)
```

---

### Step 3 — Symmetry (`run_symmetry`)

**Module**: `map_analysis/pipeline.py`
**Public function**: `run_symmetry(map_output_dir: Path) -> Optional[SymmetryResult]`

Detects global geometric symmetry of the map from island geometry. Currently reads `island_analysis/islands.json` from disk (written by step 2). A future improvement would accept an `IslandGeometryResult` directly to avoid the file round-trip.

**Returns** `None` when `islands.json` is missing (step 2 was skipped or failed).

**Output** (in `output/<map>/`):
- `symmetry.json` — detected symmetry axes, confidence scores, center point

#### `SymmetryResult` fields

```python
@dataclass
class SymmetryResult:
    map_name: str
    center: Dict[str, Any]                     # center_x, center_z, type, description, blocks
    pair_analysis: Dict[str, Any]              # total_pairs, transform_counts, pairs
    global_symmetry: List[Dict[str, Any]]      # per-candidate: type, detected, confidence, description

    # Convenience properties:
    center_x: float                            # symmetry center X
    center_z: float                            # symmetry center Z
    primary: Optional[Dict[str, Any]]          # highest-confidence detected entry, or None
```

`symmetry.json` is also updated in step 5 (assembly) to add an `intra_team_symmetry` field once team assignments are known.

---

### Step 4 — XML Analysis (`analyze_xml`)

**Module**: `ctw/commands/xml.py`
**Public function**: `analyze_xml(map_folder, ...) -> Optional[MapXmlContext]`

Parses `map.xml` using the PGM XML schema — extracts teams, spawns, wools, and region definitions. Returns a typed `MapXmlContext` so downstream steps receive live `MapData` / `Region` objects without re-parsing the XML.

**Returns** `None` when `map.xml` is absent.

**Output** (in `output/<map>/`):
- `map_data.json` — declarative metadata export (debug artifact for human inspection)

#### `MapXmlContext` fields

```python
@dataclass
class MapXmlContext:
    map_data: MapData                          # Full parsed map data (teams, spawns, wools, regions)
    region_categories: Dict[str, List[str]]   # region_id -> [category, ...]
```

`MapData` contains:

```python
@dataclass
class MapData:
    name: str; version: str; objective: str
    teams: List[Team]                          # id, color, name, max_players, dye_color
    spawns: List[Spawn]                        # team, kit, yaw, region
    wools: List[Wool]                          # team, color, location, monument
    regions: Dict[str, Region]                 # named regions (cuboids, polygons, mirrors, etc.)
    apply_rules: List[ApplyRule]               # <apply> elements (block filters, regions)
    max_build_height: Optional[int]
```

---

### Step 5 — Map Assembly (`assemble_map`)

**Module**: `map_analysis/pipeline.py`
**Public function**: `assemble_map(map_folder, geometry, map_output_dir, symmetry=None, xml_context=None, plots=False) -> MapContext`

Combines all previous results into the complete map model. Requires `IslandGeometryResult` from step 2. Accepts `SymmetryResult` and `MapXmlContext` as optional in-memory objects; falls back to reading `symmetry.json` / re-parsing `map.xml` when they are absent (supporting partial runs and `--no-symmetry` / `--no-xml` flags).

Assembly sub-steps:
1. **POI annotation** — maps XML spawn/wool locations to nearest skeleton nodes
2. **Team assignment** — assigns islands to teams using symmetry + POI data
3. **Intra-team symmetry** — detects per-team internal symmetry, appends to `symmetry.json`
4. **MapContext construction** — aggregates all data into `MapContext`
5. **Build region extraction** — derives buildable void area from XML regions + Y0 layer
6. **File writes** — `map_context.json`, `map_graph.json`, `skeleton/map_overview.png`

**Always returns** `MapContext` (never `None`).

**Outputs** (in `output/<map>/`):
- `map_context.json` — complete aggregated map model
- `map_graph.json` — inter-island connectivity graph (skeleton nodes as graph)
- `island_analysis/skeleton/map_overview.png` — map overview visualization
- `symmetry.json` updated with `intra_team_symmetry` (if applicable)
- `island_analysis/skeleton/island_N_poi.png` — per-island POI debug (requires `--plots`)

#### `MapContext` fields

```python
@dataclass
class MapContext:
    # Map metadata (from XML)
    map_name: str; map_version: str; objective: str
    teams: List[Dict]                          # id, color, name, max_players

    # Layout
    bounding_box: Optional[Tuple[float, float, float, float]]  # min_x, max_x, min_z, max_z
    map_center: Optional[Tuple[float, float]]
    total_blocks: int

    # Islands
    island_count: int
    islands: List[Dict]                        # per-island: id, area, center, bounding_box,
                                               #   has_center, team, has_spawn, has_wool,
                                               #   hole_count, simplified_polygon, distance_to_center

    # Skeleton summary
    total_nodes: int; total_edges: int
    total_endpoints: int; total_junctions: int
    unique_canonical_shapes: int

    # POI
    poi_assignments: Dict                      # spawns: [...], wools: [...]

    # Build region
    build_region: Optional[Dict]               # source, buildable_void_area, polygon
```

---

## Output Structure

After running the full pipeline, outputs are written to `output/<map>/`:

```
output/your_map_name/
  layout_bedrock.parquet           # extracted block coordinates
  layout_y0.parquet                # Y=0 layer
  layout_top_surface.parquet       # top surface layer
  layout_vertical_density.parquet  # vertical density layer
  map_data.json                    # parsed XML data (debug artifact)
  map_context.json                 # complete aggregated map model
  map_graph.json                   # inter-island connectivity graph
  symmetry.json                    # detected symmetry axes + intra-team symmetry
  island_analysis/
    islands.json                   # island geometry data (debug artifact)
    island_detail.png              # island layout overview
    skeleton/
      unique_islands.png           # canonical shape comparison
      map_overview.png             # skeleton graph with polygons + build regions
      island_N_debug.png           # per-canonical-shape skeleton debug (--plots)
      skeleton_report.txt          # skeleton text report (--plots)
    pathfinding/
      island_N_paths.png           # pathfinding grids (--plots)
  match_analysis/
    trace_player0_match57.png      # player trace visualizations
```

Input files remain in `map_folders/<map>/` (read-only, never modified).

## Design Principles

### JSON Files Are Debug Artifacts

Pipeline steps communicate exclusively through typed in-memory objects. JSON files (`islands.json`, `symmetry.json`, `map_data.json`, `map_context.json`) are written as side effects for human inspection and are **never read back as pipeline inputs** within a single run.

The one current exception is `run_symmetry`, which reads `island_analysis/islands.json` by path. This is a known limitation and will be resolved when `detect_symmetry` is updated to accept an `IslandGeometryResult` directly.

### Cache Hit Behaviour

When a debug artifact already exists on disk and `--force` is not set, computation still runs in full — only file writes are skipped. This ensures the pipeline always returns correct typed objects regardless of cache state.

### Single Responsibility

Each helper function does exactly one thing:
- `_log_y0_diagnostics` — prints Y0 layer stats
- `_attach_build_region` — attaches build region to MapContext in-place
- `_assign_teams` — mutates `island.team` from symmetry + XML data
- `_update_intra_team_symmetry` — detects per-team symmetry and appends to `symmetry.json`
- `_build_island_dicts` — converts Island objects to plain attribute dicts

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
│       ├── run.py                   # Full pipeline orchestration
│       ├── layout.py                # Layout extraction
│       ├── islands.py               # Island geometry (standalone)
│       ├── xml.py                   # XML parsing
│       ├── matches.py               # Match analysis
│       ├── info.py                  # Map status
│       └── docs.py                  # API docs generation
├── map_analysis/                    # Pipeline orchestration
│   ├── pipeline.py                  # Public API: run_island_geometry, run_symmetry, assemble_map
│   ├── datatypes.py                 # IslandGeometryResult, MapContext
│   ├── builder.py                   # MapContext construction
│   ├── exporter.py                  # map_context.json serialization
│   ├── poi_annotation.py            # Map center computation, island center classification
│   └── team_assignment.py           # Team / intra-team symmetry assignment
├── island_analysis/                 # Island detection, polygon construction, visualization
│   ├── detection.py                 # Island labeling (connected components)
│   ├── triangulation.py             # Polygon triangulation
│   └── visualization.py            # Island layout plots
├── skeleton_analysis/               # Skeleton extraction, POI annotation, pathfinding
│   ├── canonicalize.py              # D4 dihedral group canonicalization
│   ├── skeletonize.py               # Morphological thinning
│   ├── poi_annotation.py            # Spawn/wool POI classification
│   ├── pathfinding.py               # Intra-island path analysis
│   ├── visualize.py                 # Skeleton and POI visualization
│   ├── builder.py                   # Skeleton dict construction
│   ├── exporter.py                  # map_graph.json serialization
│   └── connectivity/                # Inter-island connectivity graph
├── symmetry_analysis/               # Symmetry detection
│   ├── datatypes.py                 # SymmetryResult
│   └── exporter.py                  # symmetry.json serialization
├── xml_analysis/                    # PGM XML parsing
│   ├── datatypes.py                 # MapXmlContext, MapData, Team, Spawn, Wool
│   ├── parser.py                    # Map XML parser
│   ├── regions.py                   # Region type hierarchy
│   ├── build_regions.py             # Build region extraction
│   └── exporter.py                  # map_data.json serialization
├── layout_analysis/                 # Layout extraction from region files
├── match_analysis/                  # Match event processing
│   ├── match_indexer.py             # Match file indexing (DuckDB)
│   ├── match_processor.py           # Per-match processing orchestrator
│   ├── extractors.py                # Event extraction (life segments, combat, etc.)
│   ├── position_classifier.py       # Position classification
│   └── visualization.py            # Player trace plotting
├── visualization/                   # Shared visualization utilities
│   ├── map_primitives.py            # Map base layer rendering
│   └── colors.py                    # Team/POI color definitions
├── docs/                            # Documentation
│   ├── cli.md                       # CLI reference
│   └── api_index.json               # Auto-generated API docs
├── map_folders/                     # Map data (not tracked in git)
├── output/                          # Pipeline outputs (not tracked in git)
├── match_logs/                      # Match parquet files (not tracked in git)
└── requirements.txt                 # Python dependencies
```

## License

This project is for educational and analysis purposes.
