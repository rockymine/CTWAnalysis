# Layout Analysis Package

Extracts block data from Minecraft 1.8.9 Anvil region files and orchestrates
the first stage of the CTW map pipeline.  The package handles low-level region
I/O, block extraction, and the serialisation of the final `MapContext` that
aggregates all later analysis results.

Downstream packages that consume layout output:
- **`island_analysis/`** — island detection and polygon construction
- **`skeleton_analysis/`** — skeleton graphs, pathfinding, and POI annotation
- **`xml_analysis/`** — PGM `map.xml` parsing (teams, spawns, wools, regions)

---

## Package Structure

```
layout_analysis/
├── __init__.py              # Public API — re-exports extractors, reader, utils
├── region_reader.py         # Anvil region file reader (streaming, MC 1.8.9)
├── extractors.py            # Block extraction modes (Y0, surface, density, bedrock)
├── utils.py                 # NBT nibble/block-ID decoding helpers
├── datatypes.py             # MapContext dataclass (aggregated analysis result)
├── builder.py               # build_map_context() — populates MapContext
├── exporter.py              # to_dict() / save() — serialise MapContext to JSON
├── visualization.py         # 2-D scatter/pixel plots of extracted point sets
│
├── services/
│   └── layout_service.py    # analyze_layout() — CLI orchestration (Step 1/5)
│
└── tests/
    └── test_utils.py        # Unit tests for NBT decoding utilities
```

---

## Minecraft 1.8.9 Anvil Format

Region files (`r.<rx>.<rz>.mca`) contain a 32×32 grid of chunks.
Each chunk stores up to 16 vertical sections, each a 16×16×16 block volume.

### NBT structure per section

| Field | Type | Notes |
|-------|------|-------|
| `Y` | byte | Section index (0–15), covering world y = Y*16 … Y*16+15 |
| `Blocks` | byte[4096] | Low 8 bits of block ID |
| `Data` | byte[2048] | 4-bit metadata per block, two nibbles per byte |
| `Add` | byte[2048] | High 4 bits for block IDs > 255 (optional) |

### Block array indexing

```
index = (y * 16 + z) * 16 + x        # local x,y,z ∈ [0, 15]
block_id = Blocks[index] | (nibble(Add, index) << 8)
block_data = nibble(Data, index)
```

`get_block_index()`, `decode_block_id()`, and `decode_block_data()` in
`utils.py` implement these exactly.

---

## Module Reference

### `region_reader.py` — `RegionReader`

Streams chunks from all `.mca` files in a region directory without loading the
entire world into memory.

```python
reader = RegionReader("map_folders/my_map/region")

for chunk, chunk_x, chunk_z in reader.iter_chunks():
    # chunk_x, chunk_z are world chunk coordinates
    block = chunk.get_block(local_x, y, local_z)
```

| Method | Returns | Notes |
|--------|---------|-------|
| `get_region_files()` | `list[Path]` | Sorted `.mca` paths in region dir |
| `iter_chunks()` | `Iterator[(chunk, cx, cz)]` | All non-empty chunks across all regions |
| `get_section(chunk, section_y)` | `dict \| None` | Raw NBT section dict with `Blocks`/`Data`/`Add` bytes |

Corrupt or missing chunks are skipped silently; corrupt region files emit a
warning and are skipped.

---

### `extractors.py` — Block Extractors

Four extractor classes, each accepting a `RegionReader` and returning a
`pd.DataFrame`.  All iterate via `reader.iter_chunks()`.

#### `Y0LayerExtractor`

Finds every non-air block at world `y=0`.

```python
df = Y0LayerExtractor(reader).extract()
# Columns: world_x, world_z, block_id, block_data
```

Used to locate the bedrock floor pattern — a reliable proxy for island layout
on CTW maps where the floor is at y=0.

#### `TopSurfaceExtractor`

Finds the highest non-air block in each x/z column (scans y=255 down to y=0).

```python
df = TopSurfaceExtractor(reader).extract()
# Columns: world_x, world_z, y, block_id, block_data
```

#### `VerticalDensityExtractor`

Filters columns by a vertical density metric; columns below the threshold are
excluded.

```python
df = VerticalDensityExtractor(reader, threshold=10, mode='run').extract()
# Columns: world_x, world_z, metric
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `threshold` | `10` | Minimum metric value to include the column |
| `mode` | `'run'` | `'run'` — max consecutive non-air run length; `'count'` — total non-air count |

#### `LowestBedrockExtractor`

Finds the lowest bedrock block (`block_id=7`) in each column (scans y=0 upward).

```python
df = LowestBedrockExtractor(reader).extract()
# Columns: world_x, world_z, y, block_data
```

Primary source for island detection: bedrock at y=0 cleanly separates islands
from void on Capture the Wool maps.

---

### `utils.py` — NBT Decoding Utilities

Low-level helpers; called internally by `RegionReader.get_section()` and
available in the public `__init__` API.

| Function | Signature | Notes |
|----------|-----------|-------|
| `nibble(arr, i)` | `bytes, int → int` | Extract 4-bit value at index `i` from packed nibble array |
| `decode_block_id(blocks, add, index)` | `bytes, bytes\|None, int → int` | Combine `Blocks` + `Add` into full 12-bit block ID |
| `decode_block_data(data, index)` | `bytes, int → int` | Extract 4-bit metadata from `Data` array |
| `get_block_index(x, y, z)` | `int, int, int → int` | Compute section array index: `(y*16 + z)*16 + x` |

---

### `datatypes.py` — `MapContext`

Flat dataclass that accumulates all analysis results into one structure.
Populated by `builder.build_map_context()` and serialised by `exporter.save()`.

```python
@dataclass
class MapContext:
    # From XML
    map_name: str
    map_version: str
    objective: str
    teams: List[Dict]           # {id, color, name, max_players}

    # From layout extractor
    bounding_box: Tuple[float, float, float, float]  # (min_x, max_x, min_z, max_z) — extent convention (+1 applied)
    map_center: Tuple[float, float]
    total_blocks: int

    # From island detection
    island_count: int
    islands: List[Dict]         # per-island geometry dict (see below)

    # From skeleton analysis
    total_nodes: int
    total_edges: int
    total_endpoints: int
    total_junctions: int
    unique_canonical_shapes: int

    # From POI annotation
    poi_assignments: Dict

    # From XML build-region parsing
    build_region: Optional[Dict]
```

**Per-island dict keys:**

| Key | Type | Notes |
|-----|------|-------|
| `id` | int | Island index |
| `area` | int | Block count |
| `center` | `[float, float]` | Centroid `(x, z)` applying +0.5 to each block |
| `bounding_box` | `[float, float, float, float]` | `(min_x, max_x, min_z, max_z)` extent convention |
| `has_spawn` | bool | Island contains a spawn point |
| `has_wool` | bool | Island contains a wool location |
| `has_center` | bool | Island contains the map geometric center block(s) |
| `distance_to_center` | float | Euclidean distance from island centroid to map center |
| `team` | str \| None | Team ID if assigned |
| `hole_count` | int | Number of enclosed holes in the island polygon |
| `simplified_polygon` | list | Serialised Shapely polygon (list of coordinate pairs) |

**Coordinate convention:** `bounding_box` values follow the `+1` rule from
`common/geometry` — `max_x` and `max_z` are extent upper bounds (already `+1`
beyond the highest block index).  See `common/geometry/COORDINATE_SYSTEMS.md`.

---

### `builder.py` — `build_map_context()`

Assembles a `MapContext` from the outputs of all pipeline stages.

```python
ctx = build_map_context(
    islands,            # List[Island] from island_analysis.detection
    skeleton_results,   # List[IslandResult] from skeleton_analysis
    canonical_groups,   # Dict[str, List[int]] — canonical_key → island IDs
    layout_df,          # DataFrame with world_x/world_z columns
    map_data=None,      # Optional MapData from xml_analysis
    map_center=None,    # Optional pre-computed (cx, cz)
    poi_assignments=None,  # Optional POI dict from skeleton_analysis
)
```

Column names for `layout_df` are detected automatically: `world_x`/`world_z`
are preferred, falling back to `x`/`z`.  Bounding box is computed via
`common.geometry.get_grid_extent()` (applies the +1 extent rule once).

---

### `exporter.py` — JSON Serialisation

```python
from layout_analysis import exporter

d = exporter.to_dict(ctx)          # MapContext → plain dict
exporter.save(ctx, "path/to/map_context.json")  # writes via json_export.save_json
```

The `skeleton` key in the output dict groups all skeleton summary counts:

```json
{
  "map_name": "...",
  "bounding_box": [min_x, max_x, min_z, max_z],
  "island_count": 12,
  "islands": [...],
  "skeleton": {
    "total_nodes": 84,
    "total_edges": 96,
    "total_endpoints": 20,
    "total_junctions": 16,
    "unique_canonical_shapes": 3
  },
  "poi_assignments": {...},
  "build_region": {...}
}
```

---

### `visualization.py` — Layout Plots

```python
from layout_analysis.visualization import save_point_plot, save_all_plots

# Single plot — auto-selects scatter vs. binned pixel plot based on point count
save_point_plot(df, "output/y0_layer.png", title="Y0 Layer", use_binned=None, bin_size=1)

# Convenience wrapper for all four extractors
save_all_plots(y0_df, top_surface_df, density_dfs, bedrock_df, output_dir="output/")
```

`save_point_plot` switches to a 2D histogram (`imshow`) when `len(df) > 100_000`
(or when `use_binned=True`).  Both modes set `invert_yaxis()` so that `+z`
points south, matching the world orientation convention.

---

### `services/layout_service.py` — `analyze_layout()`

CLI orchestration entry point for pipeline Stage 1.  Called by
`ctw/commands/layout.py`.

```python
parquet_files = analyze_layout(
    map_folder=Path("map_folders/my_map"),
    force_rerun=False,
    output_dir=None,          # defaults to map_folder
    skip_y0=False,
    skip_surface=False,
    skip_density=False,
    skip_bedrock=False,
    threshold=10,
    density_mode='run',
)
# Returns dict: {'y0_layer': Path, 'top_surface': Path, ...}
# Returns None if region folder is missing
```

Skips extraction for any output file that already exists (unless
`force_rerun=True`).  Prints `[OK]` / `[X]` progress lines to stdout.

---

## Data Flow

```
map_folders/<name>/region/*.mca
          │
          ▼ RegionReader.iter_chunks()
          │
          ├─▶ Y0LayerExtractor        → layout_y0.parquet
          ├─▶ TopSurfaceExtractor     → layout_top_surface.parquet
          ├─▶ VerticalDensityExtractor→ layout_vertical_density.parquet
          └─▶ LowestBedrockExtractor  → layout_bedrock.parquet  ← primary for islands
                    │
                    ▼ (consumed by island_analysis, skeleton_analysis, xml_analysis)
                    │
          build_map_context(islands, skeleton_results, canonical_groups,
                            layout_df, map_data, map_center, poi_assignments)
                    │
                    ▼ exporter.save()
          map_context.json
```

---

## Output Files

| File | Written by | Description |
|------|-----------|-------------|
| `layout_y0.parquet` | `analyze_layout()` | Non-air blocks at y=0; columns: `world_x, world_z, block_id, block_data` |
| `layout_top_surface.parquet` | `analyze_layout()` | Highest non-air block per column; adds `y` column |
| `layout_vertical_density.parquet` | `analyze_layout()` | Columns meeting density threshold; adds `metric` column |
| `layout_bedrock.parquet` | `analyze_layout()` | Lowest bedrock per column; columns: `world_x, world_z, y, block_data` |
| `map_context.json` | `exporter.save()` | Aggregated analysis results (map metadata, islands, skeleton, POIs) |

---

## Public API (`__init__.py`)

```python
from layout_analysis import (
    # Extractors
    Y0LayerExtractor,
    TopSurfaceExtractor,
    VerticalDensityExtractor,
    LowestBedrockExtractor,
    # Reader
    RegionReader,
    # Visualization
    save_point_plot,
    # NBT utilities
    nibble,
    decode_block_id,
    decode_block_data,
    get_block_index,
    # Modules (access builder/exporter directly)
    builder,
    exporter,
)
```

---

## Testing

```bash
python -m unittest discover layout_analysis/tests/
```

`tests/test_utils.py` covers `nibble`, `decode_block_id`, `decode_block_data`,
and `get_block_index` with boundary and round-trip cases.

---

## Monolithic File Warnings

The following files across the project exceed 500 lines and may benefit from
splitting as the codebase grows:

| File | Lines | Notes |
|------|------:|-------|
| `symmetry_analysis/builder.py` | 947 | All four detection stages in one file |
| `ctw/commands/debug.py` | 863 | Mixes symmetry, skeleton, and DB debug commands |
| `symmetry_analysis/tests/test_detector.py` | 701 | Single test class for all detector scenarios |
| `ctw/commands/matches.py` | 692 | Many subcommands (index, list, stats, process, trace) in one module |
| `match_analysis/visualization.py` | 610 | Multiple distinct rendering modes |
| `xml_analysis/builder.py` | 564 | Region type dispatch and region tree walking |
| `island_analysis/services/islands_service.py` | 547 | Full 8-stage island pipeline in one function |
| `island_analysis/visualization.py` | 542 | Many figure types combined |
| `skeleton_analysis/visualization.py` | 518 | Skeleton, POI, and pathfinding renders |

None of these are in `layout_analysis/` — the layout package itself is
well-sized with no file exceeding 340 lines.
