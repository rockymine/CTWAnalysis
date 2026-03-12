# Layout Analysis Package

Extracts block data from Minecraft region files. This package handles
the low-level region I/O, block extraction, and orchestration services.

Island detection and geometry live in `island_analysis/`.
Skeleton extraction, pathfinding, and connectivity live in `skeleton_analysis/`.

## Package Structure

```
layout_analysis/
├── __init__.py              # Package exports (extractors, reader, utils, features)
├── region_reader.py         # Anvil region file reader (MC 1.8.9)
├── extractors.py            # Block extraction modes (Y0, surface, density, bedrock)
├── utils.py                 # NBT decoding utilities (nibble, block ID)
├── visualization.py         # Layout-level visualization (density, surface plots)
├── map_context.py           # MapContext dataclass and builder
│
├── features/                # Map feature extractors
│   ├── __init__.py          # Exports ResourceBlockExtractor, ChestExtractor
│   ├── resource_blocks.py   # Scan all Y levels for iron/gold/diamond blocks
│   └── chests.py            # Read chest tile entities and inventory contents
│
├── services/                # CLI orchestration
│   ├── layout_service.py    # Layout extraction orchestrator
│   └── islands_service.py   # Full analysis orchestrator (8 stages)
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
| `layout_bedrock.parquet` | Lowest bedrock per column (`world_x, world_z, y, block_data`) |
| `layout_resource_blocks.parquet` | All iron/gold/diamond blocks (`world_x, world_z, y, resource_type`) |
| `layout_chest_contents.parquet` | Chest inventories (`world_x, world_z, y, chest_type, slot, item_id, item_damage, count`) |
| `map_context.json` | Aggregated map context |
| `map_graph.json` | Inter-island connectivity graph |
| `island_analysis/island_triangulation_detail.png` | Triangulation overview (essential) |
| `island_analysis/skeleton/unique_islands.png` | Canonical shapes (essential) |
| `island_analysis/skeleton/map_overview.png` | Skeleton with polygons + build regions (essential) |
| `island_analysis/map_connectivity.png` | Connectivity graph (essential) |

### Feature Extractor Details

**`ResourceBlockExtractor`** (`features/resource_blocks.py`)

Scans all chunk sections using direct Blocks-array access (one pass per 16³
section) for full resource blocks. Default targets: iron_block (ID 42),
gold_block (ID 41), diamond_block (ID 57). Additional block types can be
passed via `target_blocks={id: label, ...}`.

**`ChestExtractor`** (`features/chests.py`)

Reads `TileEntities` from each chunk's NBT data to locate chests and
trapped chests. Extracts the full inventory (slot, item_id, item_damage,
count) per chest. Empty chests produce no rows; maps without chests produce
an empty DataFrame with the correct schema.

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
