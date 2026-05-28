# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## What This Project Is

A modular analysis toolkit for **Capture the Wool (CTW)** Minecraft maps and match data. It processes raw Minecraft region files and PGM map XMLs through a staged pipeline to produce spatial models, then loads match event parquet files into a DuckDB database for player behaviour analysis.

The primary reference for the codebase's structure, patterns, and schema is **`CODEBASE.md`** — read it at the start of any session that involves adding features, writing queries, or touching the pipeline.

---

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Full map pipeline (layout → islands → symmetry → XML → assembly)
python ctw.py run --map <map_name> --no-matches

# Individual pipeline steps
python ctw.py layout --map <map_name>
python ctw.py islands --map <map_name>
python ctw.py xml --map <map_name>

# Load map into DB and process matches
python ctw.py maps load --map <map_name>
python ctw.py maps spawns --map <map_name>
python ctw.py matches index --match-dir match_logs/
python ctw.py matches process-all --map-name <map_name>   # always use --map-name

# Map viewer (Flask, opens browser at http://localhost:7891)
python ctw.py viewer

# Run all tests
python -m pytest

# Run a single test file
python -m pytest island_analysis/tests/test_cutout_classifier.py

# Run a specific test class or method
python -m pytest island_analysis/test_profile_classify.py::TestSquareAndRectangle

# Run named debug queries against metadata.db
python ctw.py db --list
python ctw.py db --run 7a
python ctw.py db "SELECT COUNT(*) FROM matches"
```

`ctw_config.yaml` in the working directory sets defaults for all flags — CLI arguments override it.

---

## Architecture

### Pipeline Overview

```
map_folders/<map>/region/*.mca   map_folders/<map>/map.xml
          │                                │
    [1] layout_analysis/          [4] xml_analysis/
          │                                │
    output/<map>/layout_*.parquet   output/<map>/map_data.json
          │                                │
    [2] island_analysis/           [5] map_analysis/
    skeleton_analysis/                     │
          │                      output/<map>/map_context.json
    output/<map>/island_analysis/  output/<map>/map_graph.json
          │
    [3] symmetry_analysis/
          │
    output/<map>/symmetry.json
```

Steps 3 and 5 only run as part of `ctw run`. The five steps are orchestrated by `ctw/commands/run.py`.

After the map pipeline, match data flows into DuckDB (`match_analysis/metadata.db`):

```
match_logs/*.parquet
  → ctw matches index        (stub map rows, match index)
  → ctw matches extract      (life segments, positions, combat, wool events)
  → ctw matches classify     (spatial annotation via PositionClassifier, traffic snapping)
```

### Key Modules

| Module | Role |
|---|---|
| `ctw.py` | Thin entry point — bootstraps `ctw/cli.py` |
| `ctw/commands/` | One file per top-level CLI command; handlers are thin wrappers over business logic |
| `ctw/common.py` | `resolve_map_folder`, `collect_map_folders`, `resolve_output_dir`, `ensure_match_db`, `_slugs_with_matches` |
| `layout_analysis/extractors.py` | Six extractor classes: `Y0Layer`, `TopSurface`, `VerticalDensity`, `LowestBedrock`, `LowestSolid`, `VerticalSegments` |
| `layout_analysis/pipeline.py` | `analyze_layout()` — orchestrates all extractors; the actual entry point for layout extraction |
| `island_analysis/` | Island detection, polygon construction, canonical classification, interactive profile review |
| `skeleton_analysis/pipeline.py` | `run_island_geometry()` — skeleton graphs + POI annotation per island |
| `xml_analysis/` | PGM `map.xml` parser; produces `MapData` / `MapXmlContext` |
| `map_analysis/pipeline.py` | `assemble_map()` — merges island geometry + XML into `map_context.json` |
| `map_analysis/grid_base.py` | `rasterize_map_polygons()` — converts island polygons to grid cells (no DB required) |
| `match_analysis/processing/processor.py` | `process_match()`, `extract_match_data()`, `insert_match_data()`, `classify_match()` |
| `match_analysis/processing/position_classifier.py` | `PositionClassifier` — STRtree-based bulk spatial classification of position events |
| `match_analysis/database/schema.py` | `initialize_database()` and all migrations (idempotent) |
| `common/geometry/` | `BoundingBox`, `Point2D`, `block_centers()`, `blocks_to_unit_squares()`, `raster_imshow_extent()` |
| `common/visualization/map_primitives.py` | `draw_build_region`, `draw_island_outlines`, `draw_poi_markers`, `draw_map_base` — preferred import location |
| `map_viewer/` | **Primary user-facing tool** — Flask app (port 7891) for inspecting and editing map data. Three pages: dashboard (`/`), editor (`/editor`), configure (`/configure`). Ten route blueprints over `routes/`; all business logic in `services/`. Edits write to `map_data.json` in-place; pipeline runs via SSE streaming. Full architecture in `CODEBASE.md § Map Viewer Architecture`. |

### Primary Output Files

- **`output/<map>/map_context.json`** — the assembled map model; the primary spatial reference for all downstream analysis. Contains islands (with polygons, team, POIs), build regions, symmetry, and poi_assignments.
- **`output/<map>/map_data.json`** — parsed XML; teams, spawns, wools, regions, kits, spawners.
- **`match_analysis/metadata.db`** — DuckDB; all match tables. Open `read_only=True` for analysis to avoid lock conflicts.
- **`map_layouts.json`** — per-map extraction config (`layer`, `exclude`, `playable_bbox`).

### The Database

Full schema in `CODEBASE.md`. Core tables: `maps`, `matches`, `life_segments`, `position_events`, `combat_events`, `wool_events`, `map_terrain_height`, `island_profiles`.

```python
import duckdb
conn = duckdb.connect('match_analysis/metadata.db', read_only=True)  # analysis
conn = duckdb.connect('match_analysis/metadata.db')                   # processing
df = conn.execute("SELECT ...", [param]).df()
conn.close()
```

`player_id` is reassigned 0…n **per match** — never treat it as a stable identity across matches.

---

## Conventions

### Adding CLI Subcommands

Follow the exact patterns in `CODEBASE.md`:
- `maps` subcommands: see "Adding a New `maps` Subcommand — Exact Pattern"
- `debug` subcommands: see "Adding a New `debug` Subcommand — Exact Pattern"
- All real logic lives in a dedicated module; the CLI handler file holds only wiring and a thin `run(args)` delegator.

### Logging

Use the `ctw` named logger everywhere in pipeline code:

```python
import logging
logger = logging.getLogger('ctw')
```

- `logger.info()` — one-line human summary per major step (shows on console)
- `logger.debug()` — file paths, counts, intermediate metrics
- `logger.warning()` — unexpected but recoverable situation
- Raise exceptions for hard failures; never use `logger.error/critical` in pipeline code.

When a function emits more than ~3 consecutive log lines, extract them into a `_log_*` helper placed directly above its only caller.

### Type Annotations

Every function must have a fully annotated signature. Use:
- `Point2D` (from `common.geometry`) for world-space (x, z) positions — construct explicitly, not as a bare tuple
- `BoundingBox` (from `common.geometry`) for spatial extents — `max` values already carry the +1 block-extent adjustment; do not add +1 again
- Concrete dataclasses (`Island`, `IslandResult`, `MapData`, `MapXmlContext`, `MapContext`) in signatures rather than `Any` or `dict`
- `Any` for Shapely geometry objects where importing the type is impractical
- `pd.DataFrame` for DataFrames (no row/column-level typing expected)

### Coordinate System

Full reference: `common/geometry/COORDINATE_SYSTEMS.md`

- Block index `(x, z)` is the **lower-left corner**; the block occupies `[x, x+1] × [z, z+1]`
- Test polygon containment with `Point(x+0.5, z+0.5)`, not `Point(x, z)`
- `BoundingBox.max` values already have +1 applied — do not add it again
- Plotting: always pair `ax.invert_yaxis()` + `ax.set_aspect('equal')` for world-space; use `extent=raster_imshow_extent(mask.shape)` for raster imshow

### Debug Queries

When writing a SQL query useful for validation or debugging, add it to `scripts/debug_queries.sql` with a section, ID (e.g. `7b`), and one-line description comment. This builds a shared library runnable by ID via `ctw db --run <id>`.

### Terrain Height SQL Pattern

```sql
-- height_above_terrain = player_y − (surface_y + 1)
SELECT pe.x, pe.y, pe.z, pe.y - (th.surface_y + 1) AS height_above_terrain
FROM position_events pe
JOIN matches mat ON mat.match_id = pe.match_id
LEFT JOIN map_terrain_height th
    ON th.map_id = mat.map_id AND th.world_x = CAST(pe.x AS INT) AND th.world_z = CAST(pe.z AS INT)
WHERE mat.map_id = ? AND pe.y >= 0   -- exclude void-fall deaths
```

Skybridge threshold: `pe.y - (th.surface_y + 1) >= 8` (8+ blocks above terrain).

### Visualization Primitives

Always import from `common/visualization/map_primitives.py` (not `visualization/map_primitives.py`):

```python
from common.visualization.map_primitives import draw_map_base, draw_island_outlines, draw_poi_markers
```

For block rendering use `blocks_to_unit_squares()` + `PolyCollection` (see `CODEBASE.md`).

---

## Important Gotchas

- **Never** run `ctw matches process-all` without `--map-name` — it processes all 700+ matches.
- `CanonicalTransform.to_original()` maps block INDEX coords only — do not use it on polygon boundary coordinates.
- After running `ctw layout --skip-non-solid` for a map, always re-run `ctw maps terrain-height --map <name>`.
- After the 2026-03-19 classifier fix, existing `position_events` rows need reclassification via `ctw matches classify`.
- `stub = TRUE` in `maps` table means the row was auto-created by `matches index` for an unregistered map slug; cleared to `FALSE` by `maps load`.
