# CTW Authoring Assistant — Deep Architecture Research Report

*Researched May 2026. Consult this before starting any new phase of work.*

---

## 1. Executive Summary

The current project is **further along than expected** in several architectural dimensions, but still has significant gaps in data model coverage and UI structure for the authoring vision.

**What already works well:**
- The pipeline already follows the ideal layered architecture: Flask endpoints call shared Python functions directly (not CLI subprocesses). The `run_pipeline` SSE endpoint imports `run_island_geometry`, `run_symmetry`, `assemble_map`, `analyze_layout`, `analyze_xml` — exactly the right pattern.
- Two-page shell already exists: `index.html` (dashboard + preprocessing) and `editor.html` (region editor). Phase 1 of the plan is largely pre-built.
- The pipeline streaming/SSE pattern for showing live logs already works.
- Region types are comprehensive (all 14+ types parsed and rendered).
- Symmetry analysis already runs and writes `symmetry.json`, but is not surfaced in the editor.
- The top-surface parquet layer already contains `surface_y`, giving per-column height data.
- `map_data.json` is the right shared artifact between pipeline and viewer.

**Critical gaps:**
- **Authors/contributors** are not in MapData or map_data.json — parsed only into DuckDB via a separate CLI command.
- **Kits** are not in MapData — a kit_parser.py produces DataFrames for analysis but the data never reaches the viewer.
- **Filter definitions** are stored as string IDs only in ApplyRule — actual filter bodies (which blocks are allowed) are not parsed.
- **Game mode** is not represented in MapData — implied by wools' presence.
- **min_players** is absent from the Team dataclass (only max_players).
- **Full XML round-trip**: the export endpoint only serializes the `<regions>` block, not the full PGM map.xml.
- **No CTW validation framework** exists beyond folder/file structure checks.
- **No guided authoring UI** — current editor is region-centric, not concept-first.

---

## 2. Current Architecture Map

### Backend Python Modules

| Module | Path | Purpose |
|--------|------|---------|
| Flask app | `map_viewer/app.py` | All HTTP routes; calls pipeline functions directly |
| Region encoder | `map_viewer/region_encoder.py` | Converts map_data.json regions → browser tree; `regions_to_xml()` for partial export |
| XML parser | `xml_analysis/builder.py` | `MapXMLParser.parse()` → MapData; handles variants, constants, all region types |
| Region types | `xml_analysis/regions.py` | All 14 region dataclasses with `get_bounds_2d()` / `to_shapely_2d()` |
| XML exporter | `xml_analysis/exporter.py` | `to_dict()` / `to_json()` / `save()` — MapData → JSON |
| XML datatypes | `xml_analysis/datatypes.py` | `MapData`, `Team`, `Spawn`, `Wool`, `ApplyRule`, `MapXmlContext` |
| Kit parser | `xml_analysis/kit_parser.py` | `parse_kits()` → DataFrames (kit items + armor); NOT wired into MapData |
| Assembly pipeline | `map_analysis/pipeline.py` | `run_island_geometry()`, `run_symmetry()`, `assemble_map()` |
| Layout extraction | `layout_analysis/extractors.py` | Parquet extractors: top surface, bedrock, density, y0, resource blocks, chests |
| Symmetry | `symmetry_analysis/builder.py` | Detects rot_90/rot_180/mirror_x/mirror_z symmetry → `symmetry.json` |
| Authors (DB only) | `ctw/commands/maps.py` | `handle_authors()` parses `<authors>` XML → DuckDB, not MapData |
| CLI entry | `ctw/cli.py` + `ctw.py` | CLI commands; `viewer` command starts Flask |

### Frontend Files

| File | Path | Purpose |
|------|------|---------|
| Dashboard | `map_viewer/templates/index.html` | Map selection, config, pipeline status, pipeline run |
| Editor | `map_viewer/templates/editor.html` | 3-panel SVG editor shell |
| Dashboard JS | `map_viewer/static/dashboard.js` | Config, map list, pipeline SSE, validation display |
| Editor bootstrap | `map_viewer/static/main.js` | Wires all editor components; keyboard shortcuts; tool modes |
| SVG canvas | `map_viewer/static/map-canvas.js` | Rendering, zoom/pan, region shapes, handles, draw tools |
| Sidebar | `map_viewer/static/region-sidebar.js` | Region tree: categories, chevrons, type badges, visibility |
| Inspector | `map_viewer/static/region-detail.js` | Selected region: fields, bounds table, children, XML preview |
| Registry | `map_viewer/static/region-registry.js` | Selection state, ancestor bounds recomputation, rename tracking |
| API | `map_viewer/static/api.js` | All fetch calls to Flask routes |
| Transform | `map_viewer/static/transform.js` | World ↔ SVG coordinate math |
| CSS | `map_viewer/static/viewer.css` | Dark theme; 3-panel layout; region row styles |

### Key Flask Routes (existing)

```
GET  /                                 → Dashboard
GET  /editor                           → Editor (3-panel region editor)
GET/POST /api/config                   → maps_folder + output_folder
GET  /api/source-maps                  → Discover source map folders
GET  /api/source-map/<n>/validate      → Check map.xml + region/ exist
GET  /api/source-map/<n>/pipeline-status → 5-step pipeline file existence check
GET  /api/source-map/<n>/pipeline/run  → SSE: run full pipeline
GET  /api/maps                         → List maps with map_context.json
GET  /api/map/<name>/context           → map_context.json payload
GET  /api/map/<name>/regions           → Region tree grouped by category
POST /api/map/<name>/regions           → Create rectangle region
POST /api/map/<name>/regions/group     → Group regions into union
PATCH /api/map/<name>/region/<id>      → Update region bounds or id
DELETE /api/map/<name>/region/<id>     → Delete region (cascading); returns snapshot for undo
POST /api/map/<name>/regions/restore  → Restore a deleted region from snapshot
GET  /api/map/<name>/export/xml        → Export <regions> block only
GET  /api/map/<name>/layers/top-surface → PNG-encoded top surface layer
```

### Output Artifacts (per map, under `output/<map_name>/`)

```
map_data.json          → Parsed XML: name, version, teams, spawns, wools, regions, apply_rules
map_context.json       → Assembly output: islands, POIs, build region, bounding box, symmetry ref
symmetry.json          → Detected symmetry type, center, confidence scores
layout_top_surface.parquet  → world_x, world_z, block_id, block_data, surface_y
layout_bedrock.parquet      → world_x, world_z, block_id, block_data
layout_lowest_solid.parquet → world_x, world_z, block_id, block_data
layout_vertical_density*.parquet → world_x, world_z, density metrics
layout_resource_blocks.parquet  → world_x, world_y, world_z, block_id
layout_chest_contents.parquet   → world_x, world_y, world_z, slot, item_id, count, damage
islands.json           → Island polygons, skeletons, canonical groups
```

---

## 3. Data Model Coverage

### What map_data.json Currently Contains (from MapData)

| Field | Parsed | In JSON | In Viewer | Notes |
|-------|--------|---------|-----------|-------|
| name | ✅ | ✅ | ✅ (header) | |
| version | ✅ | ✅ | ✅ (header) | |
| objective | ✅ | ✅ | ❌ | Not shown in editor |
| max_build_height | ✅ | ✅ | ❌ | Not shown |
| teams (id, name, color, dye_color, max_players) | ✅ | ✅ | ❌ (only used for coloring) | Not shown as editable |
| teams.min_players | ❌ | ❌ | ❌ | Not in Team dataclass |
| spawns (team, kit, yaw, region) | ✅ | ✅ | ✅ (POI layer) | Kit stored as string ID only |
| observer_spawn | ✅ | ✅ | ✅ (POI layer) | |
| wools (team, color, location, monument) | ✅ | ✅ | ✅ (POI layer) | |
| regions (all 14 types) | ✅ | ✅ | ✅ | |
| apply_rules (filter IDs, region ref) | ✅ | ✅ | ❌ | Not shown or editable |
| authors/contributors | ❌ | ❌ | ❌ | Goes to DuckDB only via separate CLI |
| kits (full definitions) | ❌ | ❌ | ❌ | kit_parser.py gives DataFrames, not MapData |
| filter definitions | ❌ | ❌ | ❌ | Only stored as string IDs in ApplyRule |
| game mode | ❌ | ❌ | ❌ | Not parsed; implied by wools |
| enter/leave/use filters (non-block) | ❌ | ❌ | ❌ | use_filter exists but enter/leave absent |

### Symmetry Data (available but not surfaced)

`symmetry.json` contains:
- Center type and coordinates (single_block, 2×2, etc.)
- Detected symmetry type(s): rot_90, rot_180, mirror_x, mirror_z
- Confidence scores per candidate
- Island pair assignments

The editor does not read or display any of this.

### Vertical Height Data (partial)

- `layout_top_surface.parquet` has `surface_y` per column — sufficient for a 2D slice approximation
- `layout_lowest_bedrock.parquet` and `layout_lowest_solid.parquet` give floor Y per column
- No vertical segment intervals (occupied Y ranges per column) — would need a new extractor
- A future `layout_vertical_segments.parquet` with `[(y_start, y_end)]` lists is feasible using existing extractor infrastructure

---

## 4. Frontend/Backend Coverage

### What the Editor Already Supports

- ✅ Display map top-surface texture layer (PNG encoded from parquet)
- ✅ Display island polygons
- ✅ Display spawn and wool POIs (team-colored arrows/icons)
- ✅ Display build region polygon overlay
- ✅ Display all regions in categorized sidebar tree with collapse/expand
- ✅ Select regions (click sidebar or canvas; shows descendants)
- ✅ Inspect region bounds (bounds table, live edit, XML preview)
- ✅ Rename regions
- ✅ Resize rectangle regions via drag handles
- ✅ Create new rectangle regions (draw tool)
- ✅ Group regions into union
- ✅ Delete regions (with cascading children)
- ✅ Undo / redo region deletion (Ctrl+Z / Ctrl+Y, 20-entry history per map session)
- ✅ Layer toggles (blocks, POIs, build region)
- ✅ Zoom / pan canvas
- ✅ Export `<regions>` XML block
- ✅ Lucide icons for tool buttons
- ✅ Region type icons in sidebar (left-aligned Lucide icons replacing text badges)
- ✅ Type-specific inspector fields (editable geometry for all region types: radius, height, base, coords, etc.)
- ✅ Editable geometry fields for all region types via the inspector panel

### What Is Missing for Authoring Vision

- ❌ Map identity section (name, version, objective, max_build_height are read-only in header only)
- ❌ Authors/contributors section (no data model, no UI)
- ❌ Teams section (no editable UI for teams)
- ❌ Kits section (no data, no UI)
- ❌ Spawns section (shown as POIs but not editable)
- ❌ Observer spawn editing
- ❌ Wool definitions editing (shown as POIs but not editable)
- ❌ Apply rules display or editing
- ❌ Filter definitions (what blocks are allowed/denied)
- ❌ Symmetry display or mirror-assist tools
- ❌ Full PGM map.xml export (only regions block exported)
- ❌ CTW validation framework
- ❌ Guided authoring flow / concept-first UX
- ❌ App-level navigation (workspace switcher / section nav)
- ❌ Draw tools for non-rectangle region types (only rectangle currently; need circle, cylinder, sphere, cuboid, point)
- ❌ Vertical / height slice view for cuboid Y editing
- ❌ Placing point/cylinder regions by clicking canvas

---

## 5. Pipeline/API Integration Assessment

### Current Pattern (Already Correct)

The Flask `run_pipeline` SSE endpoint (`app.py` around line 281) imports pipeline functions directly:

```python
from map_analysis.pipeline import run_island_geometry, run_symmetry, assemble_map
from ctw.commands.layout import analyze_layout
from ctw.commands.xml import analyze_xml
```

This is the exact shared-function pattern described in the vision. The web UI already triggers the same code that CLI `ctw run` calls. No shell-out occurs.

### Concern: CLI Command Wrappers as Reusable Functions

`analyze_layout()` and `analyze_xml()` live in `ctw/commands/layout.py` and `ctw/commands/xml.py` — inside the CLI commands package. This is slightly awkward: command modules should be thin wrappers, not the source of reusable functions. The actual logic should eventually live in domain modules (`layout_analysis/`, `xml_analysis/`), with CLI commands and Flask endpoints both importing from there.

This is not blocking but is worth addressing as a refactor: move `analyze_layout()` to `layout_analysis/pipeline.py` and `analyze_xml()` to `xml_analysis/pipeline.py`.

### Single-map vs. Bulk Processing

The pipeline already supports both:
- `GET /api/source-map/<name>/pipeline/run` — single map via web UI
- `python ctw.py run --all` — all maps via CLI

These concerns are cleanly separated: the web UI passes a single `map_name`; the CLI iterates all. No architectural conflict.

---

## 6. Risks and Design Concerns

### R1: map_data.json is incomplete
The authoring UI needs authors, kits, filter bodies, and game mode — none currently in `map_data.json`. Adding them requires extending `MapData`, updating `builder.py` parsing, and updating `exporter.py` serialization before any authoring UI can read them.

### R2: Full XML round-trip does not exist
The current export only produces a `<regions>` block. A full PGM map.xml round-trip requires building serializers for all sections: `<name>`, `<version>`, `<authors>`, `<teams>`, `<spawns>`, `<kits>`, `<wools>`, `<regions>`, `<apply>`, `<filters>`. This is the largest single gap for the export phase.

### R3: Apply rules reference filters by string ID only
`ApplyRule.block_filter` stores a name like `"only-sand"`. The filter body (`<filter name="only-sand"><block>sand</block></filter>`) is not parsed. A guided rules UI cannot explain what a filter does without parsing filter definitions.

### R4: Authors live in DuckDB, not map_data.json
`handle_authors()` in `maps.py` stores UUIDs + roles in DuckDB after a Mojang API lookup. For authoring, authors should be stored directly in map_data.json (name + role + optional UUID, no Mojang lookup).

### R5: Type-specific inspector is not schema-driven
The inspector shows a generic bounds table for all region types. Extending it requires a schema map keyed by region type.

### R6: Sidebar type badges are text (not icons)
Text badges truncate long region names. Replacing with compact Lucide icons on the left requires verifying exact icon names against the installed Lucide v4 set.

### R7: No CTW validation framework
Beyond checking that `map.xml` and `region/` exist, there is no CTW-semantic validation.

### R8: App navigation is minimal
The two-page structure exists but there is no workspace navigation within the editor.

### R9: Symmetry data available but unused
`symmetry.json` exists after pipeline runs but the editor never reads it. Low-hanging fruit once the UI has a place to surface it.

---

## 7. Recommended App / Navigation Structure

### Single-page editor shell with vertical mode rail

Add a left **mode rail** (icon-based vertical navigation, VS Code style) to `editor.html`. Rail switches visible workspace panels. The current 3-panel layout stays as the "Regions" workspace; other sections appear in its place.

```
┌────┬─────────────────────────────────────────────────┐
│    │ [Back] CTW Map Editor     Map Name        [Save] │ ← Topbar
│ ★  ├──────────────────────────────────────────────────┤
│ ℹ  │                                                  │
│ ✎  │  [Active workspace panel]                        │
│ 👥 │                                                  │
│ ⚔  │  (region editor, teams form, spawns, etc.)       │
│ 🏹 │                                                  │
│ 🧶 │                                                  │
│ □  │                                                  │
│ ⚙  │                                                  │
│ ✓  │                                                  │
│ ↓  │                                                  │
└────┴──────────────────────────────────────────────────┘
Rail  Workspace
```

Rail sections (proposed order):
1. **Overview** — CTW checklist/status dashboard
2. **Map Info** — name, version, objective, max_build_height, game mode
3. **Authors** — author + contributor list
4. **Teams** — team definitions
5. **Kits** — kit/loadout (preset selector)
6. **Spawns** — team spawns + observer spawn (with map canvas)
7. **Wools** — wool objectives (with map canvas)
8. **Regions** — current region editor (existing 3-panel layout)
9. **Rules** — apply rules + filters
10. **Validation** — CTW validation report
11. **Export** — XML preview + download

The map canvas is embedded only in sections needing spatial interaction (Spawns, Wools, Regions).

### Dashboard (index.html) — Already correct
The dashboard already handles map discovery, pipeline status, and pipeline execution. No major restructuring needed.

---

## 8. Recommended Phased Implementation Plan

### Phase 0: Data model extension ← CURRENT PHASE
*Prerequisite for all authoring phases.*

- Add `Author(name: str, role: str, uuid: str = "")` dataclass to `xml_analysis/datatypes.py`
- Add `authors: list[Author]` to `MapData`; parse from `<authors>` XML element
- Add `gamemode: str = "ctw"` to `MapData`; parse from `<gamemode>` or infer from wools
- Add `min_players: int = 0` to `Team` dataclass; parse from `min` XML attribute
- Add basic filter parsing: `filters: dict[str, FilterDef]` (name → raw XML string initially)
- Wire `kit_parser.py` into `MapData` as `kits: list[Kit]` (structured, not DataFrames)
- Update `exporter.py` to serialize all new fields
- Update `builder.py` to parse all new fields

**Critical files:**
- `xml_analysis/datatypes.py`
- `xml_analysis/builder.py`
- `xml_analysis/exporter.py`
- `xml_analysis/kit_parser.py`

### Phase 1: App shell / navigation structure
- Dashboard (index.html) is already the start page ✅
- Editor (editor.html) already exists ✅
- Add mode rail to `editor.html` with section switching in `main.js`
- Create empty placeholder panels for each section
- Keep existing region editor as the "Regions" workspace

**Critical files:** `map_viewer/templates/editor.html`, `map_viewer/static/main.js`, `map_viewer/static/viewer.css`

### Phase 2: Read-only CTW overview
- Add Overview workspace: name, version, teams, spawns, wools, region count, apply_rules count
- CTW completeness checklist (all green = probably exportable)
- Show symmetry detection result from `symmetry.json`
- No editing yet

**New files:** `map_viewer/static/workspace-overview.js`
**New routes:** `GET /api/map/<name>/summary`

### Phase 3: Region editor polish
- Replace text type badges with Lucide icons (left-aligned, compact)
- Schema-driven inspector: `REGION_FIELD_SCHEMA` map from type → field descriptors
- Show type-specific geometry fields (radius, height, base_y, etc.)

**Critical files:** `map_viewer/static/region-sidebar.js`, `map_viewer/static/region-detail.js`

### Phase 4: Editable map info + teams + authors
- Map Info workspace: editable name, version, objective, max_build_height, gamemode
- Teams workspace: add/remove/edit teams
- Authors workspace: add/remove authors and contributors
- PATCH endpoints write back to map_data.json

**New routes:** `PATCH /api/map/<name>/info`, `POST/PATCH/DELETE /api/map/<name>/teams`, `POST/PATCH/DELETE /api/map/<name>/authors`

### Phase 5: Preprocessing UX improvements
- Single-map preprocessing already works via SSE ✅
- Expose individual pipeline step execution
- Move `analyze_layout()` to `layout_analysis/pipeline.py`
- Move `analyze_xml()` to `xml_analysis/pipeline.py`

### Phase 6: Guided spatial CTW setup
- Spawns workspace: list by team, click-to-select spawn region on canvas, edit yaw
- Observer spawn workspace: similar
- Wools workspace: list by team, show pickup + monument on canvas, click to relocate
- Canvas interaction: place point region by clicking, cylinder by click+drag

### Phase 7: Symmetry assistance
- Read `symmetry.json` in editor, draw symmetry axis on canvas
- Accept/override symmetry axis
- "Mirror spawn" / "Mirror wool" buttons

### Phase 8: Apply rules and filters UI
- Rules workspace: list apply rules with filter references
- Show filter names with resolved block types (after Phase 0 filter parsing)
- Guided intent-based creation

### Phase 9: Validation framework
- New module: `xml_analysis/validation.py` with `validate_ctw(map_data) -> list[ValidationIssue]`
- Wire into `GET /api/map/<name>/validate-ctw`
- Validation workspace: grouped issues, click to navigate
- Validation badge count in rail icons

### Phase 10: Full XML export
- Full PGM map.xml serializer from MapData
- Export gated on: no unknown unparsed elements, no validation errors
- XML preview pane + download + copy

---

## 9. Concrete First Implementation Tasks (Phase 0)

These tasks are in dependency order and are immediately actionable:

**Task A** — Extend `Team` dataclass: add `min_players: int = 0`, parse from `min` XML attribute
File: `xml_analysis/datatypes.py`, `xml_analysis/builder.py`

**Task B** — Add `Author` dataclass; add `authors: list[Author]` to `MapData`; parse `<authors>/<author>` and `<authors>/<contributor>` from XML
Files: `xml_analysis/datatypes.py`, `xml_analysis/builder.py`, `xml_analysis/exporter.py`

**Task C** — Add `gamemode: str = "ctw"` to `MapData`; parse from `<gamemode>` element or infer from wools
Files: `xml_analysis/datatypes.py`, `xml_analysis/builder.py`, `xml_analysis/exporter.py`

**Task D** — Add filter parsing: store `<filters>` block as `filters: dict[str, str]` (name → raw XML string) for now
Files: `xml_analysis/datatypes.py`, `xml_analysis/builder.py`, `xml_analysis/exporter.py`

**Task E** — Define `Kit` and `KitItem` dataclasses; wire `kit_parser.py` into `MapData.kits`
Files: `xml_analysis/datatypes.py`, `xml_analysis/kit_parser.py`, `xml_analysis/builder.py`, `xml_analysis/exporter.py`

**Task F** — Add mode rail skeleton to `editor.html` (vertical icon bar, 10–11 entries, placeholder panels)
Files: `map_viewer/templates/editor.html`, `map_viewer/static/viewer.css`

**Task G** — Add workspace panel switching in `main.js`
File: `map_viewer/static/main.js`

**Task H** — Replace sidebar type text badges with Lucide icons (verify exact v4 icon names first)
File: `map_viewer/static/region-sidebar.js`

**Task I** — Make the inspector type-specific via `REGION_FIELD_SCHEMA`
File: `map_viewer/static/region-detail.js`

**Task J** — Add `GET /api/map/<name>/summary` endpoint
File: `map_viewer/app.py`

**Task K** — Add Overview workspace showing checklist + symmetry result
New file: `map_viewer/static/workspace-overview.js`

---

## 10. Open Questions (Unresolved)

**Q1: Authors in map_data.json vs. original XML round-trip**
DECIDED: Parse from `<authors>` XML into map_data.json as name + role + optional UUID. No Mojang lookup. Fits the pipeline pattern and makes authors editable via the authoring UI.

**Q2: Filter parsing depth for Phase 0**
DECIDED: Defer entirely — full filter AST will be built in the Rules/Apply phase (Phase 8). Phase 0 leaves `ApplyRule.block_filter` etc. as string IDs. No filter model added to MapData yet.

**Q6: Remember last opened map across sessions**
Should config.json remember the last selected map, or keep the stateless pick-every-time approach?

**Q8: Exact Lucide v4 icon names for region type icons**
Must be verified against the installed icon set before implementing Task H. Some proposed names (`cylinder`, `cuboid`, `squares-unite`) may not exist in v4.

**Q9: Vertical slice tool priority**
Is a visual Y-range slice tool needed in Phase 6, or are numeric min_y/max_y inputs sufficient for the first spatial editing pass?

**Q10: Single Flask app long-term**
Should the research tool and the authoring tool eventually split into two Flask apps, or remain one?

---

## Verification Plan

When implementing each phase, verify:

1. `python ctw.py run --map <test_map>` → map_data.json contains new fields (authors, gamemode, min_players, filters)
2. `python ctw.py viewer` → dashboard loads, pipeline runs, editor opens
3. Mode rail switches workspace panels; existing region editor is unaffected
4. Overview workspace renders checklist from map_data.json + symmetry.json
5. Lucide icons render correctly in sidebar (no text badges)
6. Cylinder region selected → inspector shows radius + height, not generic bounds table
7. Validation endpoint returns issues list
8. Export produces full PGM map.xml (not just regions block)
9. `python ctw.py run --all` still works (bulk CLI unaffected)
