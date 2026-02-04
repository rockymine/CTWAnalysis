# Layout Analysis Package

Extracts block data from Minecraft region files and builds a complete spatial
model of CTW maps: islands, skeleton graphs, POI annotations, pathfinding,
and inter-island connectivity.

## Pipeline Overview

The full pipeline is orchestrated by `services/islands_service.py` and runs
as step 2 of the CLI (`ctw islands` or `ctw run`). It builds on the layout
parquets produced by step 1 (`ctw layout`).

```
Region files (.mca)
  │
  ▼
Layout Extraction (extractors.py, region_reader.py)
  │  Produces: layout_bedrock.parquet, layout_y0.parquet, etc.
  │  Each row is a block at integer index (world_x, world_z).
  │
  ▼
Island Detection (islands/detection.py)
  │  Connected-component labeling (4 or 8-connectivity).
  │  Writes island_id back into the layout parquet.
  │
  ▼
Triangulation (islands/triangulation.py)
  │  Builds Shapely polygons from block unit-squares, simplifies,
  │  and triangulates via earcut. Two modes:
  │    - Per-island union (default)
  │    - Canonical grouping (--canonical-triangulation):
  │      groups D4-equivalent islands, but builds polygons
  │      from world-space blocks (not canonical space).
  │
  ▼
Skeleton Extraction (skeleton/)
  │  Per-island: rasterize → thin → extract nodes/edges →
  │  merge junction blobs → prune short branches.
  │  Canonicalization groups islands by D4 symmetry.
  │
  ▼
POI Annotation (skeleton/poi_annotation.py)
  │  Parses map.xml to find spawns and wools, assigns them
  │  to nearest skeleton nodes. Classifies island teams.
  │
  ▼
MapContext + Build Region (map_context.py, xml_analysis/build_regions.py)
  │  Aggregates all results into map_context.json.
  │  Extracts buildable void from XML build regions minus islands.
  │
  ▼
Pathfinding (skeleton/pathfinding.py)
  │  Computes shortest paths between POI nodes and endpoints
  │  within each island's skeleton graph.
  │
  ▼
Connectivity (connectivity/)
     Builds inter-island graph: intra-island edges from skeleton,
     void links between nearby island endpoints across buildable void.
     Produces map_graph.json and map_connectivity.png.
```

## Coordinate Convention

Block at integer index `(x, z)` occupies world space `[x, x+1] × [z, z+1]`
with center at `(x+0.5, z+0.5)`.

- **Parquet files** store block positions as integer `(world_x, world_z)` —
  these are block indices, not centers.
- **Island bounding boxes** use `(min_x, max_x, min_z, max_z)` where max
  values include +1 for world extent.
- **Island centers** are computed as `mean(block_indices) + 0.5`.
- **Polygons** are built with `box(x, z, x+1, z+1)` per block, then unioned
  and simplified.

## Package Structure

```
layout_analysis/
├── __init__.py              # Package exports
├── region_reader.py         # Anvil region file reader (MC 1.8.9)
├── extractors.py            # Block extraction modes (Y0, surface, density, bedrock)
├── utils.py                 # NBT decoding utilities (nibble, block ID)
├── plotting.py              # Layout-level visualization (density, surface plots)
├── map_context.py           # MapContext dataclass and builder
│
├── islands/                 # Island detection and geometry
│   ├── datatypes.py         # Island dataclass
│   ├── detection.py         # Connected-component island detection
│   ├── triangulation.py     # Polygon construction and triangulation
│   ├── statistics.py        # Island statistics and classification
│   └── visualization.py     # Island comparison, triangulation detail plots
│
├── skeleton/                # Skeleton graph extraction
│   ├── datatypes.py         # CanonicalTransform, IslandResult, SkeletonGraph
│   ├── pipeline.py          # Full skeleton pipeline orchestrator
│   ├── rasterize.py         # Island blocks → binary raster grid
│   ├── skeletonize.py       # Morphological thinning (Zhang-Suen)
│   ├── nodes.py             # Endpoint and junction extraction
│   ├── edges.py             # Edge path walking
│   ├── merge.py             # Junction blob merging
│   ├── prune.py             # Short branch pruning
│   ├── canonicalize.py      # D4 dihedral group canonicalization
│   ├── poi_annotation.py    # Spawn/wool POI assignment, map center
│   ├── pathfinding.py       # Intra-island shortest paths
│   └── visualize.py         # Skeleton debug, POI, path grid plots
│
├── connectivity/            # Inter-island connectivity
│   ├── map_graph.py         # Build connectivity graph (void links)
│   ├── serialize.py         # map_graph.json I/O
│   └── visualize.py         # Map connectivity visualization
│
├── services/                # CLI orchestration
│   ├── layout_service.py    # Layout extraction orchestrator
│   └── islands_service.py   # Island analysis orchestrator (8 stages)
│
└── tests/                   # Unit tests
```

## Key Data Flow

### Island → Skeleton → POI

1. `detect_islands()` returns `List[Island]` with `.blocks` (Nx2 int array)
2. `triangulate_island_union()` builds `.simplified_polygon` and `.triangles`
3. `process_all_islands()` computes skeleton graphs, returns `List[IslandResult]`
   and `canonical_groups` dict
4. `annotate_skeleton_pois()` marks skeleton nodes as spawn/wool POIs
5. `build_map_context()` aggregates everything into `MapContext`

### Canonical Triangulation

Islands related by D4 symmetry (rotation, reflection) are grouped by
`canonicalize.py`. The canonical transform maps block indices to a normalized
orientation. However, `to_original()` only correctly maps block INDEX
coordinates, not polygon boundary coordinates — the "+1" block extent
direction is axis-aligned in world space but rotates in canonical space.
Therefore, `triangulate_islands_canonical()` groups by canonical key but
builds polygons from world-space blocks.

## Output Files

| File | Description |
|------|-------------|
| `layout_bedrock.parquet` | Block positions with `island_id` column |
| `island_analysis/map_context.json` | Aggregated map context |
| `map_graph.json` | Inter-island connectivity graph |
| `island_analysis/island_triangulation_detail.png` | Triangulation overview (essential) |
| `island_analysis/skeleton/unique_islands.png` | Canonical shapes (essential) |
| `island_analysis/skeleton/world_overview.png` | World skeleton overlay (essential) |
| `island_analysis/map_connectivity.png` | Connectivity graph (essential) |

Debug outputs (with `--plots`): per-island skeleton/POI images, pathfinding
grids, island comparison/statistics, text reports.

## Minecraft 1.8.9 Format

The region reader handles Minecraft 1.8.9 Anvil format:
- Region files: `r.<rx>.<rz>.mca` containing 32x32 chunks
- Chunk sections: 16x16x16 block volumes
- NBT structure: `Level.Sections[]` with `Y`, `Blocks`, `Data`, `Add` fields
- Block IDs: `id = (Blocks[i] & 0xFF) | (nibble(Add, i) << 8)`
- Block array index: `(y * 16 + z) * 16 + x`

## Testing

```bash
python -m unittest discover layout_analysis/tests/
```
