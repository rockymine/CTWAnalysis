# XML Analysis

Parses Minecraft CTW map XML configuration files (`map.xml`) and extracts structured data about teams, spawns, wool objectives, regions, apply rules, and build restrictions.

## Module Structure

```
xml_analysis/
├── __init__.py              # Public API: MapXMLParser, MapVisualizer, MapDataEncoder
├── parser.py                # XML parsing and data extraction
├── regions.py               # Region class hierarchy with Shapely integration
├── build_regions.py         # Build region / void area extraction
├── exporter.py              # JSON serialization (MapDataEncoder)
├── visualizer.py            # Matplotlib region plots
├── services/
│   └── xml_service.py       # Pipeline step 3 orchestration
└── tests/
    ├── test_parser.py       # Parser and region tests
    └── test_exporter.py     # JSON encoding tests
```

## CLI Usage

The module is used via `ctw xml`:

```bash
# Simple mode — parse XML and write map_data.json to output dir
ctw xml --map tumbleweed

# With visualization plots
ctw xml --map tumbleweed --visualize

# Per-category region plots (spawn, wool, build, other)
ctw xml --map tumbleweed --visualize --category-plots

# Skip text summary or JSON output
ctw xml --map tumbleweed --visualize --no-summary
ctw xml --map tumbleweed --visualize --no-json
```

Output is written to `output/<map_name>/` by default. The map folder itself is read-only.

## Data Model

The parser produces a `MapData` dataclass containing:

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Map display name |
| `version` | `str` | Map version string |
| `objective` | `str` | Game objective text |
| `max_build_height` | `int` | Y-level build ceiling |
| `teams` | `List[Team]` | Team definitions (id, color, max_players) |
| `spawns` | `List[Spawn]` | Spawn points with team, kit, yaw, region |
| `wools` | `List[Wool]` | Wool objectives with location and monument coords |
| `regions` | `Dict[str, Region]` | Named regions by ID |
| `apply_rules` | `List[ApplyRule]` | Block filter rules referencing regions |

## Region Types

### Primitives

| Class | Geometry | Key Attributes |
|-------|----------|----------------|
| `RectangleRegion` | 2D axis-aligned box | `min_x`, `min_z`, `max_x`, `max_z` |
| `CuboidRegion` | 3D axis-aligned box | `min_x/y/z`, `max_x/y/z` |
| `CircleRegion` | 2D circle | `center_x`, `center_z`, `radius` |
| `CylinderRegion` | 3D cylinder | `base_x/y/z`, `radius`, `height` |
| `SphereRegion` | 3D sphere | `origin_x/y/z`, `radius` |
| `BlockRegion` | Single block (unit square) | `x`, `y`, `z` |
| `PointRegion` | Single point | `x`, `y`, `z` |

### Composites

| Class | Semantics |
|-------|-----------|
| `UnionRegion` | Union of all children |
| `IntersectRegion` | Intersection of all children |
| `NegativeRegion` | Universe minus all children |
| `ComplementRegion` | First child minus subsequent children |

### Special

| Class | Purpose |
|-------|---------|
| `RegionReference` | Named reference resolved through registry |
| `EverywhereRegion` | Represents the entire map |
| `AboveRegion` | Everything above a Y level |

All regions support `get_bounds_2d()` and `to_shapely_2d()` for geometric operations.

### Coordinate Conventions

- Rectangle/cuboid coords are corner coordinates (world-space boundaries) — **not** expanded
- Block regions use block indices and are expanded by `+1` on max via `_expand_block_bounds()` to form unit squares
- Special values: `oo` / `-oo` for infinity, `$var` placeholders treated as `0.0`

## Build Regions

`build_regions.py` extracts buildable void areas by analyzing `<apply>` rules:

1. Finds `deny(void)` rules — regions where building over void is blocked
2. Computes buildable area = map bounds minus denied regions
3. Subtracts island polygons to get buildable void area
4. Falls back to block 36 detection from `layout_y0.parquet` if no XML rules found

Returns a dict with `source` (`'xml'` or `'block_36'`), `polygons`, `buildable_void`, and `buildable_void_area`.

## Region Categorization

Regions are automatically categorized by ID pattern matching:

| Category | Pattern |
|----------|---------|
| `spawn` | IDs containing "spawn" |
| `wool` | IDs containing "wool" |
| `build` | IDs containing "build", "height", or "limit" |
| `other` | Everything else |

## JSON Output

`map_data.json` contains the full structured export:

```json
{
  "name": "Tumbleweed",
  "version": "1.1.5",
  "objective": "Capture the enemy's two wools!",
  "max_build_height": 29,
  "teams": [
    { "id": "red", "name": "Red", "color": "dark red", "max_players": 35 }
  ],
  "spawns": [
    { "team": "blue", "kit": "spawn-kit", "yaw": 0.0, "region": { "type": "cuboid", ... } }
  ],
  "wools": [
    { "team": "blue", "color": "lime", "location": [x, y, z], "monument": [x, y, z] }
  ],
  "regions": { "region-id": { "type": "rectangle", "bounds_2d": [...], ... } },
  "region_categories": { "spawn": ["spawns"], "wool": ["wool-rooms"] }
}
```

## Python API

```python
from xml_analysis import MapXMLParser, MapVisualizer, MapDataEncoder

# Parse
parser = MapXMLParser('map_folders/tumbleweed/map.xml')
data = parser.parse()
categories = parser.identify_region_categories(data)

# Export JSON
MapDataEncoder.save_json(data, 'output/map_data.json', categories)

# Visualize
viz = MapVisualizer(data)
viz.plot_all('output/layout.png')
viz.plot_by_category('output/', categories)
viz.print_summary()
```

## Testing

```bash
python -m unittest discover xml_analysis/tests/ -v
```

Tests cover region value parsing, team/spawn/wool/region extraction, composite region handling, block coordinate expansion, region categorization, JSON encoding structure, and full Tumbleweed map integration.
