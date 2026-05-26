# CTW Analysis — Codebase Navigation Reference

> This file exists so Claude Code can orient quickly at the start of a new session
> without extensive grepping. It documents patterns, entry points, and structural
> conventions. It is NOT a user guide — see `docs/cli.md` for that.

---

## Project Layout at a Glance

```
CTWAnalysisWithClaudeCode/
├── ctw.py                            CLI entry point (registers commands, delegates)
├── ctw/
│   ├── common.py                     Shared helpers: resolve_map_folder, collect_map_folders,
│   │                                 resolve_output_dir, ensure_match_db, _slugs_with_matches
│   └── commands/                     One module per top-level CLI command
│       ├── run.py                    Full pipeline orchestration (5-step)
│       ├── layout.py                 Layout extraction (calls extractors.py)
│       ├── islands.py                Standalone island geometry
│       ├── xml.py                    PGM XML parsing
│       ├── maps.py                   Map metadata subcommands (load/spawns/resources/…)
│       ├── matches.py                Match data subcommands (process/trace/traffic-graph/…)
│       ├── debug.py                  Diagnostic subcommands (layout-blocks/layout-grid/compare/terrain-height/symmetry/…)
│       ├── info.py                   Map status summary
│       └── docs.py                   API index regeneration
│
├── layout_analysis/
│   ├── extractors.py                 Y0, TopSurface, Density, LowestBedrock, LowestSolid extractors
│   ├── map_layout_config.py          MapLayoutConfig dataclass + get_map_layout()
│   ├── map_context.py                assemble_map() — builds map_context.json
│   ├── features/
│   │   └── zone_classifier.py        ZoneClassifier (runtime zone labeling) + public detection fns:
│   │                                   detect_wool_room_region_id(x, z, regions) → str|None
│   │                                   assign_wool_room_regions(wools, regions, spawners, output_dir)
│   └── services/                     Orchestration services called by run.py
│
├── island_analysis/
│   ├── detection.py                  detect_islands(), find_island_holes()
│   ├── datatypes.py                  Island dataclass
│   ├── profile.py                    IslandFeatures/IslandProfile/IslandRasterStrategy; profile_islands(), classify_island(), save/load_profiles(); override helpers; cross-map plots
│   ├── profile_review.py             Interactive web review server; run via `ctw islands profile-review`
│   └── triangulation.py             triangulate_islands_canonical()
│
├── skeleton_analysis/
│   ├── pipeline.py                   run_island_geometry() — main entry for islands+skeleton
│   ├── canonicalize.py               CanonicalTransform
│   ├── datatypes.py                  IslandResult dataclass
│   ├── poi_annotation.py             POI assignment to skeleton nodes
│   └── connectivity/                 Graph connectivity and pathfinding
│
├── xml_analysis/
│   ├── regions.py                    Region types: Rectangle, Cuboid, Union, Mirror, Translate…
│   ├── build_regions.py              Build region extraction (void decomposition)
│   └── datatypes.py                  MapData, MapXmlContext
│
├── map_analysis/
│   ├── pipeline.py                   run_island_geometry() + assemble_map() — produces map_context.json
│   ├── datatypes.py                  IslandAnalysis, MapContext dataclasses
│   ├── builder.py                    Island construction from geometry + XML
│   ├── exporter.py                   JSON serialisation helpers
│   ├── poi_annotation.py             POI (spawn/wool/monument) assignment to islands
│   ├── team_assignment.py            Team color/slug resolution
│   ├── grid_base.py                  GridBase + rasterize_map_polygons() + _adaptive_grid_size()
│   │                                 Converts map_context polygons to grid cells (no DB required)
│   │                                 apply_profile_grid_sizes() + load_grid_base_profiled() — per-island grid hints
│   └── geometry_graph.py             build_geometry_graph() — 4-connected adjacency graph from GridBase
│
├── match_analysis/
│   ├── metadata.db                   DuckDB database (READ-ONLY for analysis; write for processing)
│   ├── database/
│   │   ├── schema.py                 initialize_database(), all CREATE TABLE statements, migrations
│   │   └── terrain_height.py         populate_terrain_height(map_id, output_dir, conn)
│   ├── processing/
│   │   ├── processor.py              process_match(), extract_match_data(), insert_match_data()
│   │   ├── extractors.py             extract_life_segments/combat/position/wool_events()
│   │   ├── position_classifier.py    PositionClassifier (STRtree bulk classification)
│   │   └── post_processor.py         Life features, carry chains, spatial features
│   └── visualization.py              Match trace plots
│
├── common/
│   ├── geometry/
│   │   ├── __init__.py               BoundingBox, Point2D, block_centers(), blocks_to_unit_squares(),
│   │   │                             raster_imshow_extent(), world_blocks_to_shapely()
│   │   └── COORDINATE_SYSTEMS.md     THE reference for coordinate space rules
│   └── visualization/
│       └── map_primitives.py         draw_build_region(), draw_island_outlines(),
│                                     draw_poi_markers(), draw_map_base(), draw_block_base()
│
├── visualization/
│   └── map_primitives.py             (re-export from common/visualization — prefer common/)
│
├── map_folders/<map>/                RAW INPUT (never modified)
│   ├── region/                       Minecraft .mca region files
│   └── map.xml                       PGM map definition
│
├── output/<map>/                     PIPELINE OUTPUT (all files flat)
│   ├── layout_*.parquet              Extracted block layers
│   ├── map_data.json                 Parsed XML metadata
│   ├── map_context.json              Complete assembled map model (primary reference)
│   ├── map_graph.json                Inter-island connectivity graph
│   ├── symmetry.json                 Detected symmetry
│   ├── traffic_graph.json            Data-driven navigation graph (player movement)
│   ├── geometry_graph.json          Geometry-derived adjacency graph (no match data needed)
│   ├── island_profiles.json         Island spatial profiles (one per canonical shape; written by Stage 8 of assemble_map)
│   └── island_analysis/             Island geometry + debug images
│
├── output/_debug/
│   └── island_profile_overrides.json  Manual classification overrides: canonical_key → {profile, note}
│
├── match_logs/                       Raw match parquet files (not in git)
├── map_layouts.yaml                  Per-map extraction config (layer, exclude, playable_bbox)
├── ctw_config.yaml                   Global CLI defaults
└── docs/
    ├── cli.md                        Full CLI reference
    ├── analysis_overview.md          Data format and pipeline details
    ├── contributing.md               Logging/typing/domain type conventions
    └── analysis_roadmap.md           Research hypotheses and analysis plan (keep updated)
```

---

## Adding a New `maps` Subcommand — Exact Pattern

```python
# In ctw/commands/maps.py

# 1. Add to the epilog string in register():
#    "  new-thing    One-line description\n"

# 2. Register the subcommand in register() after existing add_parser blocks:
p = maps_sub.add_parser(
    'new-thing',
    help='One-line description',
)
p.add_argument('--map', default=None,
               help='Map name (omit to process all maps in DB)')
p.add_argument('--output', default='output',
               help='Output root directory (default: output)')
p.set_defaults(func=handle_new_thing)

# 3. Write the handler — standard shape:
def handle_new_thing(args: object) -> None:
    """One-line description."""
    import duckdb
    from match_analysis.database.schema import migrate_new_thing  # if migration needed

    ensure_match_db()
    db_path = Path('match_analysis/metadata.db')
    output_root = Path(args.output)

    # Resolve which maps to process
    if args.map:
        map_slugs = [s.strip() for s in args.map.split(',')]
    else:
        map_slugs = _slugs_with_matches()  # all maps in DB

    conn = duckdb.connect(str(db_path))
    total = 0

    for slug in map_slugs:
        map_dir = output_root / slug
        if not map_dir.exists():
            print(f"  [{slug}] output dir not found, skipping")
            continue

        row = conn.execute(
            "SELECT map_id FROM maps WHERE map_slug = ?", [slug]
        ).fetchone()
        if row is None:
            print(f"  [{slug}] not in DB, run 'ctw maps load' first")
            continue
        map_id = row[0]

        # --- call business logic ---
        n = do_the_work(map_id, map_dir, conn)
        print(f"  [{slug}] {n} rows")
        total += n

    conn.close()
    print(f"\nDone: {total} total across {len(map_slugs)} map(s)")
```

---

## Adding a New `debug` Subcommand — Exact Pattern

Each subcommand has its own `description=`, `formatter_class=_RAW`, and `epilog=` with examples.
All logic lives in a dedicated module; `debug.py` holds only the CLI wiring and a thin handler.

```python
# In ctw/commands/debug.py

_RAW = argparse.RawDescriptionHelpFormatter

# 1. Register (no epilog on the parent debug parser):
p = debug_sub.add_parser(
    'new-diagnostic',
    help='One-line summary shown in ctw debug -h',
    description=(
        'Detailed paragraph shown in ctw debug new-diagnostic -h. '
        'Describe what the command does, what files it reads/writes, and notable flags.'
    ),
    formatter_class=_RAW,
    epilog="""\
Examples:
  python ctw.py debug new-diagnostic --map arabia
  python ctw.py debug new-diagnostic --map arabia --save /tmp/out.png
""",
)
p.add_argument('--map', required=True,
               help='Map name')
p.add_argument('--output', default='output',
               help='Output root directory (default: output)')
p.add_argument('--save', default=None, dest='save_path',
               help='Output PNG path (default: output/<map>/images/<name>.png)')
p.set_defaults(func=handle_new_diagnostic)

# 2. Handler — thin wrapper only:
def handle_new_diagnostic(args: object) -> None:
    from some_module.new_diagnostic import run
    run(args)
```

All real logic goes in `some_module/new_diagnostic.py` with a `run(args: object) -> None` entry point.

```python
# In some_module/new_diagnostic.py — full handler shape (read-only DB access):
def run(args: object) -> None:
    import duckdb

    map_name = args.map
    map_dir = Path(args.output) / map_name

    # Load map_context.json for spatial reference
    context_path = map_dir / 'map_context.json'
    if not context_path.exists():
        print(f"map_context.json not found for '{map_name}'. Run 'ctw run' first.")
        return
    import json
    with open(context_path) as f:
        map_context = json.load(f)

    save_path = (
        Path(args.save_path) if args.save_path
        else map_dir / 'images' / 'new_diagnostic.png'
    )
    save_path.parent.mkdir(parents=True, exist_ok=True)

    db_path = Path('match_analysis/metadata.db')
    conn = duckdb.connect(str(db_path), read_only=True)

    map_id = conn.execute(
        "SELECT map_id FROM maps WHERE map_slug = ?", [map_name]
    ).fetchone()
    if map_id is None:
        conn.close()
        print(f"Map '{map_name}' not in DB.")
        return
    map_id = map_id[0]

    df = conn.execute("SELECT ... FROM ... WHERE map_id = ?", [map_id]).df()
    conn.close()

    _plot_new_diagnostic(map_name, map_context, df, save_path)
    print(f"Saved: {save_path}")
```

---

## Terrain Height Pattern (compute at query time)

```sql
-- height_above_terrain = player_y − (surface_y + 1)
-- NULL when player is in void/build_region (no terrain entry)
SELECT
    pe.x, pe.y, pe.z,
    th.surface_y,
    pe.y - (th.surface_y + 1) AS height_above_terrain
FROM position_events pe
JOIN matches mat ON mat.match_id = pe.match_id
LEFT JOIN map_terrain_height th
    ON  th.map_id  = mat.map_id
    AND th.world_x = CAST(pe.x AS INT)
    AND th.world_z = CAST(pe.z AS INT)
WHERE mat.map_id = ?
  AND pe.y >= 0        -- exclude void-fall deaths (y < 0)
```

Skybridge threshold (map-relative, replaces global SKYBRIDGE_Y_THRESHOLD = 22):
```sql
pe.y - (th.surface_y + 1) >= 8   -- 8+ blocks above terrain = skybridge activity
```

---

## Database Schema

All tables in `match_analysis/metadata.db` (DuckDB).

### Core Tables

| Table | Key Columns |
|---|---|
| `maps` | map_id PK, map_slug UNIQUE, map_name, max_build_height, min_x/max_x/min_z/max_z, center_x/center_z, island_count, team_count, wools_per_team, max_players_per_team, size_tier, symmetry_type, symmetry_confidence, stub (BOOLEAN, TRUE = auto-created placeholder for unregistered slug; cleared to FALSE by `maps load`) |
| `map_spawns` | spawn_id PK, map_id FK, x, z, min_x/min_z/max_x/max_z, team, team_color |
| `matches` | match_id PK, match_file UNIQUE, map_id FK, match_start, match_duration, player_count, processed, spatial_classified, log_interval |
| `life_segments` | segment_id PK, match_id FK, player_id, segment_idx, start_timestamp, end_timestamp, duration, outcome, spawn_x/z, kill_count, wool_touches, wool_captures |
| `position_events` | position_id PK, match_id FK, timestamp, player_id, x, y, z, segment_idx, location_type (island/build_region/void), island_id |
| `combat_events` | combat_id PK, match_id FK, timestamp, event_type, player_id, victim_id, x, y, z, segment_idx |
| `wool_events` | wool_event_id PK, match_id FK, timestamp, event_type (6=touch,7=capture), player_id, wool_id, x, y, z, segment_idx |
| `player_team_segments` | team_segment_id PK, match_id FK, player_id, team, start_timestamp, end_timestamp |
| `map_terrain_height` | map_id FK, world_x, world_z, surface_y, lowest_y — PRIMARY KEY (map_id, world_x, world_z) |
| `island_profiles` | profile_id PK, map_id FK, canonical_key, island_type (square\|rectangle\|circle\|donut\|shard\|L_shape\|Z_shape\|plus\|fork\|rugged\|linear\|blob), area, perimeter, bbox_fill_ratio, rugosity, aspect_ratio, compactness, convexity, pca_elongation, pca_angle_deg, hole_count, hole_ratio, skeleton_topology, skeleton_path_bends, skeleton_available — UNIQUE (map_id, canonical_key) |

### Feature / Derived Tables

| Table | Key Columns |
|---|---|
| `life_segment_traffic_features` | segment_id FK, snapped_sequence (JSON array of node IDs), max_attack_depth, death_region (home_island/enemy_island/bridge/void) |
| `life_segment_summary` | Aggregated spatial, movement, and engagement metrics per segment |
| `wool_carry_chains` | Grouped carry attempts: carrier list, handoff count, outcome |
| `wool_spawn_baselines` | Distance from spawn to wool, per map/team/wool |

### Spatial / Map Feature Tables

| Table | Key Columns |
|---|---|
| `map_wool_locations` | Corrected wool positions from capture events |
| `map_wool_objectives` | Many-to-many: wool_id → teams |
| `map_wool_attack_relations` | attacking_team, wool_id, relative_side (left/right/on_axis), attack_angle_deg |
| `map_team_spatial` | Inter-team spatial relations (center distance, axis angle) |
| `map_resource_blocks` | block_type, x, y, z, zone (defense/near_spawn/mid_map/enemy_territory) |
| `map_chests` | Chest positions with zone classification and `content_category` (wool/combat/weapon/supply/defense/empty) |
| `map_kit_items` / `map_kit_armor` | Spawn kit contents from map.xml |
| `layout_layer_stats` | Block counts and y-range per layer per map |
| `layout_block_inventory` | Per-block-ID counts per layer per map |

### Views
- `map_size_buckets` — quintile size classification (tiny/small/medium/large/huge)
- `life_segment_features` — backward-compat union of summary + skeleton_features

### Connection Pattern
```python
import duckdb
conn = duckdb.connect('match_analysis/metadata.db', read_only=True)  # analysis
conn = duckdb.connect('match_analysis/metadata.db')                   # processing
df = conn.execute("SELECT ...", [param]).df()       # → DataFrame
rows = conn.execute("SELECT ...", [param]).fetchall()
conn.close()
```

---

## Map Context JSON Structure (`output/<map>/map_context.json`)

```jsonc
{
  "map_name": "Display Name",
  "map_version": "X.Y.Z",
  "bounding_box": [min_x, max_x, min_z, max_z],   // world extent (max already +1)
  "map_center": [center_x, center_z],
  "total_blocks": N,
  "island_count": N,
  "islands": [
    {
      "id": N,
      "area": N,                                   // block count
      "center": [x, z],
      "bounding_box": [min_x, max_x, min_z, max_z],
      "team": "team-slug",                         // null for neutral/bridge islands
      "has_spawn": true,
      "has_wool": true,
      "simplified_polygon": {
        "exterior": [[x, z], ...],                 // world-extent coords
        "holes": [[[x, z], ...], ...]
      }
    }
  ],
  "build_region": {
    "buildable_void": [                            // list of polygons
      { "exterior": [[x, z], ...], "holes": [...] }
    ]
  },
  "poi_assignments": {
    "spawns": [{ "x", "z", "team", "team_color", "bounds_2d": {"min": {x,z}, "max": {x,z}} }],
    "wools": [{ "x", "z", "color", "wool_id" }],
    "monuments": [{ "x", "z", "team", "wool_ids": [N, ...] }]
  },
  "max_build_height": N,
  "symmetry": {
    "global_symmetry": [{ "type": "rotation_2|mirror_v|mirror_h|none", "confidence": f }],
    "intra_team_symmetry": [{ "team", "symmetry_detected", "type", "confidence" }]
  }
}
```

---

## Map Data JSON Structure (`output/<map>/map_data.json`)

Written by `xml_analysis/pipeline.py:analyze_xml()`. Raw XML export with wool room
detection already applied. All fields present — no optional fallbacks.

```jsonc
{
  "name": "Display Name",
  "version": "X.Y.Z",
  "gamemode": "ctw",
  "objective": "...",
  "max_build_height": N,
  "authors": [{ "uuid": "...", "role": "author|contributor", "contribution": "..." }],
  "kits": [{ "id": "...", "items": [...], "armor": [...] }],
  "teams": [{ "id": "...", "name": "...", "color": "...", "dye_color": "...", "max_players": N, "min_players": N }],
  "spawns": [{ "team": "...", "kit": "...", "yaw": N, "region": {...} }],
  "observer_spawn": { ... } | null,
  "wools": [
    {
      "team": "team-slug",
      "color": "red",                          // wool color string
      "location": { "x": N, "y": N, "z": N }, // chest/spawner location
      "monument": { "x": N, "y": N, "z": N, "region_id": "blue-monument" | null },
      "wool_room_region": "red-wool-room"      // detected region ID; null if unresolved (~7%)
    }
  ],
  "spawners": [                                // PGM <spawner> elements (may be empty list)
    {
      "spawn_region": "red-wool-spawn",
      "player_region": "red-wool-room",        // the wool room — most reliable source
      "delay": "1.5s",
      "max_entities": N | null,
      "items": [{ "material": "wool", "damage": 14, "amount": 1 }]
                                               // damage = Minecraft 1.8.9 wool color ID (0–15)
    }
  ],
  "regions": {
    "region-id": {
      "id": "region-id",
      "type": "rectangle|cuboid|cylinder|union|...",
      "bounds_2d": { "min": {"x": N, "z": N}, "max": {"x": N, "z": N} },
      // type-specific fields (min_x/max_x/min_z/max_z for rectangles, etc.)
    }
  },
  "region_categories": {
    "spawn": ["blue-spawn", ...],
    "wool": ["red-wool-room", ...],
    "build": ["blue-build", ...],
    "other": [...]
  },
  "apply_rules": [...]
}
```

**Wool room detection priority chain** (in `assign_wool_room_regions()` in
`layout_analysis/features/zone_classifier.py`):
1. XML `<spawner>` `player-region` matched by wool color (damage value)
2. Chest spatial search (`layout_chest_contents.parquet` — wool items inside region)
3. Wool `location` spatial search (smallest containing named region)

~92–93 % of wools resolve; ~7–8 % (mirror/translate regions) remain `null` and
can be assigned manually in the map viewer Objective activity.

**Wool damage → color mapping** (Minecraft 1.8.9):
`0`=white, `1`=orange, `2`=magenta, `3`=light_blue, `4`=yellow, `5`=lime,
`6`=pink, `7`=gray, `8`=silver, `9`=cyan, `10`=purple, `11`=blue,
`12`=brown, `13`=green, `14`=red, `15`=black

---

## Key Coordinate Rules

Full reference: `common/geometry/COORDINATE_SYSTEMS.md`

- **Block index** `(x, z)` is the lower-left corner of a 1×1 block
- Block occupies `[x, x+1] × [z, z+1]` in world space
- Block centre: `(x + 0.5, z + 0.5)` — use `block_centers(arr)` helper
- `BoundingBox(min_x, max_x, min_z, max_z)` has `+1` already applied on max
- Polygon edges in `simplified_polygon` run along integer grid lines → test containment with `Point(x+0.5, z+0.5)`, NOT `Point(x, z)`
- `PositionClassifier.classify_bulk()` already applies `+0.5` internally (fixed 2026-03-19)

### Plotting

**World-space** (`ax.invert_yaxis()` + `ax.set_aspect('equal')`):
- Polygons: use as-is (already extent coords)
- Scatter/lines: `block_centers(block_indices)` — adds 0.5

**Raster-space** (`origin='upper'`):
- `imshow`: always `extent=raster_imshow_extent(mask.shape)`
- Scatter/lines: `block_centers([col, row])`

Both rules are inseparable — either alone causes a 0.5-block shift.

---

## CLI Command Cross-Reference

| CLI command | Handler | Business logic |
|---|---|---|
| `ctw layout` | `ctw/commands/layout.py` | `layout_analysis/extractors.py` (5 extractor classes) |
| `ctw islands` | `ctw/commands/islands.py` | `skeleton_analysis/pipeline.py:run_island_geometry()` |
| `ctw xml` | `ctw/commands/xml.py` | `xml_analysis/` |
| `ctw run` | `ctw/commands/run.py` | Calls layout → islands → symmetry → xml → assemble in sequence |
| `ctw maps load` | `handle_load()` | Reads `map_context.json` → inserts into `maps` table |
| `ctw maps spawns` | `handle_spawns()` | Reads `poi_assignments.spawns` → `map_spawns` |
| `ctw maps resources` | `handle_resources()` | Reads layout parquets → `map_resource_blocks`, `map_chests` |
| `ctw maps chest-classify` | `handle_chest_classify()` | Reads `map_chest_contents` → updates `map_chests.content_category` |
| `ctw maps kits` | `handle_kits()` | Reads `map.xml` → `map_kit_items`, `map_kit_armor` |
| `ctw maps spatial-relations` | `handle_spatial_relations()` | Reads `map_wool_locations`, `map_spawns` → `map_wool_attack_relations`, `map_team_spatial` |
| `ctw maps terrain-height` | `handle_terrain_height()` | `match_analysis/database/terrain_height.py:populate_terrain_height()` |
| `ctw maps geometry-graph` | `handle_geometry_graph()` | `map_analysis/grid_base.py:rasterize_map_polygons()` + `map_analysis/geometry_graph.py:build_geometry_graph()` |
| `ctw maps profile-summary` | `handle_profile_summary()` | Cross-map island type count table (console only); reads `island_profiles.json` from all maps |
| `ctw maps profile-landscape` | `handle_profile_landscape()` | `island_analysis/profile.py:plot_profile_landscape()` → `output/images/island_landscape.png` |
| `ctw maps profile-mosaic` | `handle_profile_mosaic()` | `island_analysis/profile.py:plot_profile_mosaic()` → `output/images/island_mosaic_<type>.png`; `--type` filters |
| `ctw maps profile-distributions` | `handle_profile_distributions()` | `island_analysis/profile.py:plot_feature_distributions()` → `output/images/island_feature_distributions.png` |
| `ctw islands profile` | `handle_profile()` in `ctw/commands/islands.py` | Re-run profiling from cached JSON; loads overrides from `output/_debug/island_profile_overrides.json`; `--map` optional (all maps); `--plot` emits `island_profiles.png` |
| `ctw islands profile-inspect` | `handle_profile_inspect()` | Console feature table per canonical island; shows both `island_type` (effective) and `auto_profile` (algorithm); `--map` required |
| `ctw islands profile-canonical` | `handle_profile_canonical()` | Show canonical groupings (unique shapes + instance counts) from `map_context.json` |
| `ctw islands profile-review` | `handle_profile_review()` → `island_analysis/profile_review.py:run_review_server()` | Local HTTP review page; SVG thumbnails + reclassify dropdown + notes; saves to `island_profile_overrides.json`; `--map`, `--type`, `--port` |
| `ctw matches index` | `handle_index()` | `match_analysis/database/indexer.py:index_match_files()` — recurse logs dir, create stub maps as needed |
| `ctw matches extract` | `handle_extract()` | `match_analysis/processing/processor.py:extract_match_data()` + `insert_match_data()` |
| `ctw matches classify` | `handle_classify()` | `match_analysis/processing/processor.py:classify_match()` — spatial annotation + traffic features |
| `ctw db` | `ctw/commands/db.py:handler()` | Run named queries from `scripts/debug_queries.sql` or ad-hoc SQL against `metadata.db` |
| `ctw debug layout-blocks` | `handle_layout()` → `layout_analysis/layout_scan.py:run_layout()` | List unique block IDs across maps; `--water` checks water footprint vs XML build region |
| `ctw debug data` | `handle_data()` → `layout_analysis/layout_scan.py:run_data()` | Scan output JSON files and report null/empty fields |
| `ctw debug compare` | `handle_compare()` → `layout_analysis/layout_compare.py:run()` | 3-panel y0 vs bedrock diff figure; `--summary` for text-only table |
| `ctw debug layout-grid` | `handle_layout_grid()` → `layout_analysis/layout_grid.py:run()` | 2×2 grid of all four layout layers → `output/<map>/images/layout_case_study.png` |
| `ctw debug symmetry` | `handle_symmetry()` → `symmetry_analysis/report.py:run()` | `--map`: text report + 2-panel image at `output/<map>/images/symmetry_debug.png`; no `--map`: one-line-per-map table with optional `--threshold PCT` |
| `ctw debug terrain-height` | `handle_terrain_height()` → `match_analysis/terrain_height_plot.py:run()` | SQL queries + 4×2 grid PNG at `output/<map>/images/terrain_height_debug.png` |
| `ctw debug layout-audit` | `handle_audit()` → `layout_analysis/audit.py:run()` | Layout parquet scan → upserts `layout_layer_stats`, `layout_block_inventory` |
| `ctw debug resources` | `handle_resources()` → `layout_analysis/resources_plot.py:run()` | Zone-classified chest/resource block plot → `output/<map>/images/resources_overview.png` |
| `ctw debug prepare-demo` | `handle_prepare_demo()` → `layout_analysis/demo.py:run()` | Build traffic graph assets and copy to `docs/demo/assets/<slug>/` |
| `ctw debug activity-grid` | `handle_activity_grid()` → `match_analysis/activity_grid.py:generate()` | Match activity heatmap (24h × day grouped by ISO week) |

### `ctw db` — Named Query Runner

Queries live in `scripts/debug_queries.sql`. Each query has a short ID (e.g. `1a`, `7a`) and a one-line description comment that doubles as the `--list` display name. The ID scheme is `<section_number><letter>` where letters increment within a section.

```
ctw db --list                  # show all query IDs and descriptions
ctw db --run 7a                # run a single query
ctw db --run 1a,5c             # run multiple
ctw db --section inventory     # run all queries in a section
ctw db "SELECT COUNT(*) FROM matches"   # ad-hoc SQL
```

**Convention**: whenever a SQL query is written for debugging or validation and may be reused in future sessions, add it to `scripts/debug_queries.sql` with an appropriate section, ID, and description comment. This builds a shared library of verified queries that both the user and Claude can run by ID.

---

## Layout Extractors

```python
# layout_analysis/extractors.py

NON_SOLID_BLOCK_IDS = frozenset({31, 32, 37, 38, 55, 77, 143})
# Decorative blocks excluded from top-surface when --skip-non-solid:
# 31=tall_grass, 32=dead_bush, 37=dandelion, 38=rose, 55=redstone_wire,
# 77=stone_button, 143=wooden_button
# Water (8, 9) is NEVER in this set — water is a walkable surface in CTW

class TopSurfaceExtractor:
    def __init__(self, region_reader, exclude_ids=None, skip_non_solid=False,
                 max_build_height=None)
    # skip_non_solid=True unions NON_SOLID_BLOCK_IDS into exclude_ids
    # max_build_height=N skips blocks at y >= N (read from map.xml via
    #   _read_max_build_height() in layout.py — applied automatically in analyze_layout)

class Y0LayerExtractor:
    def __init__(self, region_reader)

class VerticalDensityExtractor:
    def __init__(self, region_reader, threshold=10, mode='run'|'count')

class LowestBedrockExtractor:
    def __init__(self, region_reader)

class LowestSolidLayerExtractor:
    def __init__(self, region_reader, exclude_ids=None)
```

---

## Match Processing Pipeline

```
[1] Extract (parallel workers):
    process_match(match_id)
      → extract_match_data()  reads parquet, produces DataFrames
          extract_life_segments()      type 2 (spawn) → type 4 (death)
          extract_combat_events()      type 3 (kill)
          extract_position_events()    type 5 (position sample)
          extract_wool_events()        type 6 (touch), type 7 (capture)

[2] Insert (serial):
    insert_match_data(conn, data)
      → bulk-insert all tables
      → matches.processed = TRUE, spatial_classified = FALSE

[3] Classify (serial):
    classify_match(conn, match_id)
      → PositionClassifier.classify_bulk() — sets location_type, island_id
      → Traffic graph snap — sets snapped_sequence, max_attack_depth
      → matches.spatial_classified = TRUE
```

Raw event types: 0=MATCH_START, 1=MATCH_END, 2=SPAWN, 3=KILL, 4=DEATH, 5=POSITION, 6=WOOL_TOUCH, 7=WOOL_CAPTURE

---

## Map Layout Config (`map_layouts.yaml`)

```yaml
maps:
  arabia:
    layer: bedrock      # which parquet has island_id written back after island detection
    exclude: []         # block IDs filtered AFTER extraction
    exclude_observer_island: false
    exclude_islands: []
    playable_bbox: null
```

`get_map_layout(map_slug)` returns `MapLayoutConfig` or `None` (unconfigured maps fall back to bedrock).

`_find_clustering_parquet()` in `terrain_height.py` priority:
1. `layout_decided.parquet` (most configured maps)
2. Layer-specific file from config (e.g. `layout_bedrock.parquet`)
3. `layout_bedrock.parquet` (unconfigured fallback)
4. `layout_y0.parquet` (last resort)

---

## Visualization Primitives

```python
# common/visualization/map_primitives.py — preferred import location

from common.visualization.map_primitives import (
    draw_build_region,        # fills build-region polygon with semi-transparent color
    draw_island_outlines,     # draws simplified_polygon exteriors + holes
    draw_poi_markers,         # spawns, wools, monuments as markers
    draw_map_base,            # convenience: outlines + pois + build region
    BuildRegionStyle,         # fill_alpha, linewidth, color
    IslandOutlineStyle,       # exterior_linewidth/alpha, hole_linewidth/alpha
    POIStyle,                 # markersize, zorder, alpha
)
```

All draw_* functions take `(ax, map_context: dict, style=None)`.
`draw_map_base` takes `(ax, map_context, island_style, poi_style)` — no build region.

For PolyCollection block rendering:
```python
from common.geometry import blocks_to_unit_squares
from matplotlib.collections import PolyCollection
squares = blocks_to_unit_squares(xs, zs)   # (N, 4, 2) array
col = PolyCollection(squares, facecolors=..., edgecolors='none', antialiased=False)
ax.add_collection(col)
```

---

## Common Workflow Reminders

- **NEVER** `matches process-all` without `--map-name` — too slow across 700+ matches
- Always `read_only=True` when opening DB for analysis to avoid lock conflicts
- `player_id` is re-assigned 0…n **per match** — not stable across matches
- Use `SUM(player_count)` from `matches` for total participations, not `COUNT(DISTINCT player_id)`
- `CanonicalTransform.to_original()` only maps block INDEX coords — do NOT use it on polygon boundary coords
- Run `ctw maps terrain-height --map NAME` after any `ctw layout --skip-non-solid` regen
- Position events at y < 0 are void-fall deaths — filter with `AND pe.y >= 0` for terrain analysis
- After the 2026-03-19 classifier fix: existing `position_events` rows still need `ctw matches classify` reclassification (edges previously misclassified as void)

---

## Schema Initialization / Migration

```python
# match_analysis/database/schema.py

def initialize_database(db_path=None) -> None:
    # Creates all tables if not exists; calls _create_views(); _migrate_*() for backfill

def migrate_terrain_height_table(db_path=None) -> None:
    # Safe no-op if map_terrain_height already exists; otherwise creates it
```

Migrations are idempotent — safe to call multiple times.

---

## Debug Plot Conventions (terrain-height diagnostic)

The `ctw debug terrain-height` command produces a **4×2 grid** at `output/<map>/images/terrain_height_debug.png`:

| Panel | Content | Colormap |
|---|---|---|
| [0,0] | Above terrain — max HAT > 0 per cell | YlOrRd |
| [0,1] | Below terrain — deepest HAT < 0 per cell | Blues |
| [1,0] | Data coverage — event count (log scale); gray = absent cells | plasma + #d1d5db |
| [1,1] | Vertical extremes — diverging, furthest from terrain | RdBu_r, TwoSlopeNorm |
| [2,0] | Location type — dominant classification per cell | #2ecc71/island #f39c12/build_region #e74c3c/void |
| [2,1] | Reference map — island outlines + POIs | draw_map_base() |
| [3,0] | Terrain elevation — surface_y per island cell | terrain |
| [3,1] | (empty) | — |

All panels: `invert_yaxis()`, `set_aspect('equal')`, thin island outlines + build region overlay.
95th-percentile clipping for above/below panels. `y >= 0` filter applied in SQL.
