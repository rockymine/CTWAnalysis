# PGM Map Studio — Port Requirements: XML, Symmetry & Pipeline Simplification

## 1. Overview

This document specifies requirements for the next development phase of `pgm_map_studio`. It is written in the context of a port from the legacy `CTWAnalysis` repository into the clean new codebase, with the map viewer as the primary access point.

The refactor produces four concrete outcomes:

1. A new `pgm_map_studio.pgm` package that parses `map.xml` and produces `xml_data.json`
2. A new `pgm_map_studio.symmetry` package that detects map symmetry and produces `symmetry.json`
3. A simplified 3-step pipeline (Layout → Symmetry → XML) with no assembly combinator
4. Updated map viewer that reads from `xml_data.json` and `islands.json` directly, with removed dependencies on all dropped data

---

## 2. Current State of the New Repository

The following packages are already implemented and are **not part of this refactor**:

### `pgm_map_studio.minecraft`
Low-level Minecraft file I/O. Reads Anvil `.mca` region files, extracts block data via layer and feature extractors. No PGM or game-rule knowledge.

### `pgm_map_studio.layout`
Island geometry extraction pipeline. Detects connected-component islands, constructs Shapely polygons, writes `islands.json` and parquet layer files.

**Output files already produced:**

| File | Contents |
|---|---|
| `layer.parquet` | Block scan used for island detection |
| `wools.parquet` | Wool positions and colours |
| `resources.parquet` | Iron/gold/diamond block positions |
| `chests.parquet` | Chest inventory |
| `spawners.parquet` | Mob spawner configuration |
| `islands.json` | Detected islands — GeoJSON polygons + metadata |

**`islands.json` island structure (already defined):**

```json
{
  "id": 1,
  "block_count": 7950,
  "bounds": [-70, -137, 70, -33],
  "polygon": {
    "type": "Polygon",
    "coordinates": [[[x, z], ...], [[hx, hz], ...]]
  }
}
```

`polygon` is Shapely's native GeoJSON mapping: index 0 is the exterior ring, subsequent entries are hole rings. Coordinates are `[x, z]` pairs.

---

## 3. Scope

### 3.1 In Scope

- `pgm_map_studio.pgm` — PGM `map.xml` parser producing `xml_data.json`
- `pgm_map_studio.symmetry` — symmetry detection producing `symmetry.json`
- Pipeline integration — 3-step pipeline with per-map config
- Map viewer updates — remove all dropped dependencies, wire to new data sources
- Test suite — comprehensive new tests following project conventions

### 3.2 Explicitly Out of Scope

The following features from the legacy repository are **not ported**:

| Feature | Reason |
|---|---|
| Skeleton analysis | Not needed by the map viewer |
| Build region extraction | Replaced by a future dedicated activity |
| Team assignment (geometric) | User configures teams in the editor UI |
| POI annotation (spawn/wool → skeleton node matching) | Depends on skeleton |
| Map assembly step | Entire step disappears; each pipeline step writes its own output |
| `map_context.json` | Superseded by `xml_data.json` + `islands.json` |
| `map_graph.json` | Skeleton output; not generated |
| Island profiling (Tier B skeleton metrics) | Skeleton-dependent |
| Intra-team symmetry | Additive extra that required team assignment; not displayed in viewer panel |
| Match analysis | Entirely out of scope |
| `kit_parser.py` (DataFrame output) | Only fed match DB, not the viewer |

---

## 4. Package: `pgm_map_studio.pgm`

### 4.1 Purpose

Parses a PGM `map.xml` file and produces a `MapXml` dataclass and `xml_data.json`. No knowledge of block geometry, islands, or symmetry.

> **Why `pgm` and not `xml`?** `xml` is a Python standard library module. `pgm` refers to the ProjectAres Game Manager server framework whose XML format is being parsed — unambiguous in this domain.

### 4.2 Module Structure

```
pgm_map_studio/pgm/
├── __init__.py          # Public API: MapXml, parse()
├── datatypes.py         # MapXml, Team, Kit, Spawn, Wool, WoolSpawner, Renewable,
│                        # BlockDropRule, ApplyRule, Author, KitItem, KitArmor
├── regions.py           # Region class hierarchy + Shapely geometry + coordinate parsing
├── parser.py            # Top-level orchestrator: teams, kits, spawns, wools,
│                        # spawners, renewables, block_drop_rules, apply_rules
├── region_parser.py     # All region type parsers; synthetic ID injection;
│                        # reference resolution
└── serializer.py        # MapXml → dict → xml_data.json
```

**Not included** (present in legacy repo, not ported):

| Legacy file | Reason excluded |
|---|---|
| `kit_parser.py` | DataFrame output for match DB only |
| `build_regions.py` | Build region extraction, out of scope |
| `symmetry.py` | Region-level mirror utility, not needed without skeleton |
| `pipeline.py` | Thin wrapper, inlined into CLI / viewer service |

### 4.3 Refactoring Changes from Legacy

The following changes are applied during the port. This is not a straight copy.

#### Split `builder.py` → `parser.py` + `region_parser.py`

`parser.py` handles: teams, kits, spawns, wools, spawners, renewables, block_drop_rules, apply_rules, observer_spawn detection.

`region_parser.py` handles: all individual region type parsers, `_parse_region_node` dispatch, synthetic ID injection, reference resolution. This makes region parsing independently testable.

#### Collapse composite region parsers

The four structurally identical parsers for union, negative, complement, and intersect are replaced by a single helper:

```python
def _parse_composite(self, elem, region_id: str, cls: type) -> Region:
    children = [r for c in elem if (r := self._parse_region_node(c))]
    return cls(id=region_id, children=children)
```

#### Consolidate coordinate parsing

Three competing implementations in the legacy codebase (`_safe_float()` in `builder.py`, `Region.parse_value()` in `regions.py`, `_parse_coords()` in `builder.py`) are replaced by a single module-level function in `regions.py` that handles all cases:

- Template variable syntax: `${variable_name}` → stored as `None`
- Infinity syntax: `"oo"` / `"-oo"` → `float('inf')` / `float('-inf')`
- Normal float and int values

#### Split `_parse_kits()`

The legacy method simultaneously parses kit items/armor and expands kits per team. These are two separate steps:

1. `_parse_kits()` — pure parsing, returns `list[Kit]`
2. `_expand_kits_per_team()` — post-processing, resolves team-color variants using spawn references

#### File naming

| Legacy name | New name |
|---|---|
| `builder.py` | `parser.py` |
| `exporter.py` | `serializer.py` |

#### Remove dead code

| Location | Item |
|---|---|
| `exporter.py` (legacy) | Unused `BlockDropItem` import |
| `regions.py` (legacy) | Unused `math` import |

### 4.4 Data Structures (`datatypes.py`)

The central dataclass is renamed from `MapData` to `MapXml` to reflect that it holds only XML-derived data. The field `region_categories` is **not** a stored field — it is computed on-the-fly by the viewer at load time.

```python
@dataclass
class MapXml:
    name: str = ""
    version: str = ""
    gamemode: str = "ctw"
    objective: str = ""
    max_build_height: Optional[int] = None
    authors: list[Author] = field(default_factory=list)
    kits: list[Kit] = field(default_factory=list)
    teams: list[Team] = field(default_factory=list)
    spawns: list[Spawn] = field(default_factory=list)
    observer_spawn: Optional[Spawn] = None
    wools: list[Wool] = field(default_factory=list)
    spawners: list[WoolSpawner] = field(default_factory=list)
    renewables: list[Renewable] = field(default_factory=list)
    block_drop_rules: list[BlockDropRule] = field(default_factory=list)
    regions: dict[str, Region] = field(default_factory=dict)
    apply_rules: list[ApplyRule] = field(default_factory=list)
```

All other dataclasses (`Team`, `Kit`, `KitItem`, `KitArmor`, `Spawn`, `Wool`, `WoolSpawner`, `SpawnerItem`, `Renewable`, `BlockDropRule`, `BlockDropItem`, `ApplyRule`, `Author`) are ported unchanged from `xml_analysis/datatypes.py`.

### 4.5 Region System (`regions.py`)

All 15+ region types from the legacy codebase are ported: Rectangle, Cuboid, Cylinder, Circle, Sphere, Block, Point, Union, Negative, Complement, Intersect, Mirror, Translate, Reference, Everywhere, Above, Half.

#### Flat registry — single source of truth

Every named or synthetic region exists exactly once in `MapXml.regions{}`. Composite regions reference their children by ID string only. Geometry is never duplicated.

```python
# Composite region: children are ID strings, not Region objects
@dataclass
class Union(Region):
    id: str = ""
    children: list[str] = field(default_factory=list)
```

A region that appears as a child of a composite is stored once in the flat dict. The composite stores its ID. This eliminates the two-place-edit problem and is the correct model for an editor.

#### Stable synthetic IDs

Anonymous child regions (those without an `id` attribute in XML) receive a deterministic synthetic ID. Requirements:

- **Deterministic:** same XML input → same IDs on every parse
- **Unique:** no two regions share an ID within the regions dict
- **Stable across unrelated edits:** adding or removing a sibling region does not change another region's synthetic ID

The exact algorithm is left to the implementer. Both content-hash-based (hash of type + coordinates) and parent-scoped positional approaches are acceptable if they satisfy the above. Positional suffixes scoped to the parent ID (e.g. `{parent_id}__{index}`) are acceptable only if the index is stable — i.e. a sibling's removal does not renumber remaining children.

The `(inline)` suffix currently produced by the legacy parser for anonymous regions is **not** carried over. IDs must be clean strings without implementation-detail markers.

#### Normalized `bounds_2d`

All regions carry a `bounds_2d` field representing the 2D bounding box in normalized form (min.x < max.x, min.z < max.z always). The raw XML axis convention (where PGM rectangles may have max < min) is corrected at parse time.

```python
bounds_2d = {
    "min": {"x": float, "z": float},
    "max": {"x": float, "z": float}
}
```

Rectangle regions do **not** carry `min_x`, `min_z`, `max_x`, `max_z` as separate top-level fields. Only `bounds_2d` is written.

### 4.6 Output Format: `xml_data.json`

The output file is named `xml_data.json` (replacing the legacy `map_data.json`).

#### Top-level structure

```json
{
  "name": "Outback: Outback Edition",
  "version": "1.0.0",
  "gamemode": "ctw",
  "objective": "Capture both wools!",
  "max_build_height": 32,
  "authors": [
    {"uuid": "fe3608b7-...", "role": "author"},
    {"uuid": "e2d2c2c6-...", "role": "contributor", "contribution": "xml"}
  ],
  "kits": [ ... ],
  "teams": [ ... ],
  "spawns": [ ... ],
  "observer_spawn": { ... },
  "wools": [ ... ],
  "spawners": [ ... ],
  "renewables": [ ... ],
  "block_drop_rules": [ ... ],
  "regions": { ... },
  "apply_rules": [ ... ]
}
```

**Not present:** `region_categories` (computed on-the-fly by the viewer).

#### Region entries

Primitive region — rectangle:
```json
"yellow-spawn": {
  "id": "yellow-spawn",
  "type": "rectangle",
  "bounds_2d": {
    "min": {"x": -11.0, "z": -121.0},
    "max": {"x": 11.0, "z": -94.0}
  }
}
```

Composite region — children are ID strings, not inline objects:
```json
"spawns": {
  "id": "spawns",
  "type": "union",
  "bounds_2d": {
    "min": {"x": -11.0, "z": -121.0},
    "max": {"x": 11.0, "z": 121.0}
  },
  "children": ["yellow-spawn", "purple-spawn"]
}
```

Synthetic child region — stored once in flat dict, referenced by ID above:
```json
"spawns__anon_0": {
  "id": "spawns__anon_0",
  "type": "complement",
  "bounds_2d": { ... },
  "children": ["spawns__anon_0__anon_0"]
}
```

#### Other entry examples

Spawner:
```json
{
  "spawn_region": "blue-wool-spawn",
  "player_region": "blue-woolroom",
  "delay": "1.5s",
  "max_entities": 10,
  "items": [
    {"material": "wool", "damage": 11, "amount": 1}
  ]
}
```

Renewable (optional fields omitted when default):
```json
{
  "region_id": "spawns",
  "rate": 2.0,
  "renew_filter": "only-iron",
  "replace_filter": "only-air"
}
```

Apply rule:
```json
{
  "region": "spawns",
  "block_place": "only-iron-cause-world",
  "block_break": "only-iron",
  "message": "You may not edit spawn!"
}
```

#### Serialization conventions (carried over from legacy)

Optional fields are omitted when they equal their default value:
- `rate` omitted when `1.0`
- `grow` omitted when `false`
- `wrong_tool` omitted when `false`
- `damage` omitted when `0`
- `amount` omitted when `1`
- `chance` omitted when `1.0`
- `delay`, `max_entities` omitted when absent

---

## 5. Package: `pgm_map_studio.symmetry`

### 5.1 Purpose

Detects global geometric symmetry from island polygon data and writes `symmetry.json`. No XML dependency. Reads `islands.json` produced by `pgm_map_studio.layout`.

### 5.2 Module Structure

```
pgm_map_studio/symmetry/
├── __init__.py          # Public API: detect(), SymmetryResult
├── detection.py         # Symmetry detection algorithms (IoU-based)
├── datatypes.py         # SymmetryResult dataclass
└── serializer.py        # SymmetryResult → symmetry.json
```

**Not ported from legacy:**

| Legacy file | Reason |
|---|---|
| Intra-team symmetry detection | Requires team assignment, which is out of scope |
| `report.py` | Diagnostic reporting, not needed |

### 5.3 What Is Detected

Four global symmetry types, fully unaffected by the removal of skeleton/assembly:

| Type | Description |
|---|---|
| `mirror_x` | Left-right mirror across the X axis |
| `mirror_z` | Front-back mirror across the Z axis |
| `rot_90` | 90-degree rotational symmetry |
| `rot_180` | 180-degree rotational symmetry |

Each carries a `confidence` score (0.0–1.0) and a `detected` boolean. All four are evaluated; the highest-confidence detected type becomes `primary`.

### 5.4 Output Format: `symmetry.json`

Format is unchanged from the legacy repo. The `intra_team_symmetry` field is not written.

```json
{
  "symmetry_status": "confirmed",
  "global_symmetry": [
    {
      "type": "rot_180",
      "detected": true,
      "confidence": 1.0,
      "description": "180-degree rotational symmetry"
    },
    {
      "type": "mirror_x",
      "detected": false,
      "confidence": 0.31,
      "description": "Mirror symmetry across X axis"
    }
  ],
  "center": {
    "center_x": 0.0,
    "center_z": 0.0
  },
  "primary": {
    "type": "rot_180",
    "confidence": 1.0,
    "description": "180-degree rotational symmetry"
  }
}
```

`symmetry_status` is set by the user in the editor UI (`"confirmed"`, `"none"`, `"skipped"`). The pipeline writes `"skipped"` as the initial value; the viewer allows the user to confirm or reject the detection result.

---

## 6. Pipeline

### 6.1 Steps and Dependency Order

```
Step 1: Layout     (minecraft + layout)   → layer.parquet, islands.json, wools.parquet, ...
Step 2: Symmetry   (symmetry)             → symmetry.json          [depends on Step 1]
Step 3: XML        (pgm)                  → xml_data.json           [independent]
```

Steps 1 and 3 are independent. Step 2 depends on Step 1. There is no assembly step — each step writes its own output directly.

**Default behaviour:** When a map is submitted for analysis (upload or local path), the full pipeline runs automatically. The viewer can then be opened immediately on the results.

**Browsing already-analysed maps** remains possible without re-running the pipeline. If all output files are present and up to date, the pipeline steps are skipped.

### 6.2 Per-Map Configuration File

Location: `{output_dir}/{map_slug}/map_config.json`

This file allows per-map overrides for pipeline behaviour, most importantly for symmetry detection when the user identifies a non-playable island (e.g. a central observer platform) that distorts the symmetry result.

**Schema:**

```json
{
  "exclude_islands": [],
  "scan_layer": "surface"
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `exclude_islands` | `list[int]` | `[]` | Island IDs excluded from symmetry detection |
| `scan_layer` | `string` | `"surface"` | Layer extractor: `"surface"`, `"y0"`, `"bedrock"`, `"base"` |

When `exclude_islands` is non-empty and the symmetry step runs, only the remaining islands are used for detection. The symmetry step must be individually re-runnable (i.e. `force=True` on step 2 only) so that the user can update this config and re-detect without re-running the full pipeline.

### 6.3 Cache Behaviour

Each step checks for its output file(s) before running. If outputs exist and `force=False`, the step is skipped. Steps are individually re-runnable via `force=True`.

---

## 7. Output File Structure

After a full pipeline run:

```
{output_dir}/{map_slug}/
├── layer.parquet          ← Layout step
├── wools.parquet          ← Layout step
├── resources.parquet      ← Layout step
├── chests.parquet         ← Layout step
├── spawners.parquet       ← Layout step
├── islands.json           ← Layout step
├── symmetry.json          ← Symmetry step
├── xml_data.json          ← XML step
└── map_config.json        ← Per-map config (user-editable)
```

**Not generated:** `map_context.json`, `map_graph.json`, `island_profiles.json`, any build region file.

The viewer reads `xml_data.json` for the editor and `islands.json` for the canvas. Map-level bounding box and center are computed at viewer load time from `islands.json` (union of island bounds) — not stored as separate fields.

---

## 8. Map Viewer Changes

### 8.1 File Rename

All viewer services that load `map_data.json` are updated to load `xml_data.json`. Internal variable names should be updated accordingly (`map_data` → `xml_data` where the distinction matters for clarity).

### 8.2 Removed Dependencies

| Removed | Action |
|---|---|
| `map_context.json` consumption | Remove all load paths and references |
| `poi_assignments` in `wools.py`, `wool_editor.py` | Replace with direct reads from `xml_data.json` |
| `node_id` references | Remove (no skeleton) |
| Duplicate `teams` / metadata from `map_context.json` | `xml_data.json` is the single source |
| `map_graph.json` — not generated | No viewer code referenced it |

### 8.3 POI Marker Coordinates

`map-canvas.js` and `objective-activity.js` currently read spawn and wool marker positions from `poi_assignments[].x/z`. These are replaced with direct reads from `xml_data.json`:

| Marker | Source field |
|---|---|
| Spawn markers | `spawns[].region.base.{x, z}` (point/cylinder), or `bounds_2d` centroid for rectangular regions |
| Wool markers | `wools[].location.{x, z}` |
| Monument markers | `wools[].monument.{x, z}` |

### 8.4 Region Categories: On-the-Fly Computation

`region_categories` is not stored in `xml_data.json`. The viewer computes it at load time using pattern-matching on region IDs (logic ported from `builder.py:identify_region_categories()`).

Categories: `spawn`, `wool`, `build`, `other`. The categorisation behaviour must match the legacy output exactly — existing tests that verify category membership can be used as a reference.

This computation should live in a small utility function, either in the viewer's Python service layer or in JavaScript, depending on where the categories are consumed first.

### 8.5 Canvas Simplification

| Layer | Change |
|---|---|
| Surface blocks toggle | **Retained** — shows/hides `layer.parquet` top-surface rendering |
| Build region overlay toggle | **Removed** — no pre-computed build region data exists |
| Island polygon outlines | **Retained** — rendered from `islands.json` |
| XML region overlays | **Retained** — rendered from `xml_data.json` regions |

### 8.6 Viewer Pipeline Service

The viewer's `services/pipeline.py` (currently creates an empty `xml_data.json` stub) is updated to invoke the actual pipeline steps:

- **New map upload:** triggers full pipeline (Layout → Symmetry → XML)
- **Existing map with cached outputs:** opens editor directly without re-running
- **Force re-run:** individual steps can be re-triggered from the editor (e.g. after modifying `map_config.json` to exclude an island)

---

## 9. Testing Requirements

### 9.1 Conventions

All tests follow the project conventions in `testing.md`:

- Framework: `pytest` with `pytest-cov`
- Location: `tests/`, mirroring `src/pgm_map_studio/`
- Naming: `test_<source_filename>.py`, functions named `test_<thing>_<condition>`
- Fixtures: synthetic minimum-structure inputs preferred; no real `.mca` files in unit tests
- Integration tests with real map data live in `tools/` and are not part of the `pytest` suite

The current test coverage across the codebase is insufficient. The new `pgm` and `symmetry` packages must have complete coverage of all parsing and serialization logic. Every public function must have at least one test.

### 9.2 `tests/pgm/test_parser.py`

- **Teams:** id, color, dye_color, max_players, min_players default
- **Kits:** items with all optional fields (slot, material, amount, damage, unbreakable, team_color); armor slots; enchantments in attribute form (`"arrow_infinite:1"`); enchantments as nested `<enchantment>` elements; kit parent inheritance
- **Kit team expansion:** team-colored items and armor correctly duplicated per team after `_expand_kits_per_team()`
- **Spawns:** team reference, kit reference, yaw, inline region, named region reference, observer spawn detected correctly
- **Wools:** team, color, location (x/y/z), monument (x/y/z/region_id), wool_room_region
- **Spawners:** spawn_region, player_region, delay, max_entities, items with damage/amount; spawner missing required attribute is skipped
- **Renewables:** region_id required; rate, renew_filter, replace_filter, grow optional; renewable without region skipped
- **Block-drop rules:** region_id, filter_id, replacement, wrong_tool, items with chance
- **Apply rules:** region-only entry; entry with block_place + block_break + region + message; entry with block (combined) filter
- **Missing/optional fields** default correctly throughout (min_players=0, rate=1.0, grow=False, damage=0, amount=1)

### 9.3 `tests/pgm/test_region_parser.py`

- **Primitive types:** rectangle (normalized bounds), cuboid (min/max 3D), cylinder (base, radius, height), circle (center, radius), sphere (center, radius), block (position, bounds expanded by +1), point (position, bounds expanded by +1)
- **Composite types:** union, negative, complement, intersect — each has `children` as list of ID strings, not Region objects
- **Transform types:** mirror (axis, origin), translate (offset)
- **Special types:** everywhere, above, reference (resolved to target region)
- **Flat registry:** a region appearing as a child of a composite is stored once in the flat dict; the composite's `children` field is a list of strings
- **Synthetic ID stability:** parsing the same XML twice produces identical IDs for all anonymous regions
- **Synthetic ID uniqueness:** no two entries in the regions dict share an ID
- **No `(inline)` suffix:** synthetic IDs are clean strings
- **Deep nesting:** anonymous children at three or more nesting levels receive stable unique IDs
- **Named vs. anonymous:** regions with `id` attribute use that ID; those without receive a synthetic one

### 9.4 `tests/pgm/test_regions.py`

- `bounds_2d` correctness for each region type
- Coordinate parsing: normal float, `"oo"` → `inf`, `"-oo"` → `-inf`, `${var}` → `None`
- Rectangle normalization: raw XML with max < min (PGM convention) produces bounds_2d with min < max

### 9.5 `tests/pgm/test_serializer.py`

- Full round-trip: parse real map XML → serialize → parse output JSON → field values preserved
- Children in composite regions are ID strings in JSON output, not inline objects
- `region_categories` key is absent from output
- `min_x`, `min_z`, `max_x`, `max_z` keys are absent from rectangle output
- Optional fields omitted at default: `rate=1.0`, `grow=false`, `wrong_tool=false`, `damage=0`, `amount=1`, `chance=1.0`
- `observer_spawn` is `null` in JSON when absent
- Empty lists (`kits`, `spawners`, etc.) serialized as `[]`, not omitted

### 9.6 `tests/symmetry/test_detection.py`

- `rot_180` detected with high confidence on a known symmetric island set
- `mirror_x` and `mirror_z` detected correctly on appropriate inputs
- No symmetry detected on a clearly asymmetric island set
- Observer island exclusion: result changes when a central asymmetric island is excluded via `exclude_islands`
- All confidence scores are in `[0.0, 1.0]`
- `primary` is the highest-confidence detected type

### 9.7 `tests/symmetry/test_serializer.py`

- Output contains `symmetry_status`, `global_symmetry`, `center`, `primary` keys
- `intra_team_symmetry` key is absent
- `symmetry_status` is `"skipped"` when no islands provided
- `primary` is `null` when no symmetry type is detected

### 9.8 Integration Tests (`tools/`)

Not part of the `pytest` suite; run manually:

- Full pipeline run on each of the three available test maps (tumbleweed, outback_outback_edition, annealing_iv)
- Verify `xml_data.json` schema: all expected top-level keys present, no `region_categories`, no raw rectangle coordinates, children are ID strings
- Verify `symmetry.json` primary type matches known ground truth for each map
- Verify `islands.json` GeoJSON polygon format is valid Shapely-loadable geometry

---

## 10. Design Decisions and Rationale

### The assembly step disappears entirely

The assembly step existed solely to combine skeleton results, POI annotations, and team assignments into `map_context.json`. With all three removed, each pipeline step writes its own output independently. The outputs produced by the new pipeline (`xml_data.json`, `islands.json`, `symmetry.json`) are each the direct responsibility of their generating step.

### `map_context.json` is removed rather than trimmed

After removing skeleton stats, `poi_assignments`, `build_region`, and the duplicate metadata fields copied from XML, the only remaining content in `map_context.json` would have been island data — which is already in `islands.json`. Retaining a near-empty file for compatibility is not worthwhile in a clean new repository.

### Build regions are dropped

The legacy build region computation fused two conceptually distinct things: (1) physical buildability from raw block data (a floor block exists at Y=0), and (2) rule-based restrictions from XML `<apply>` rules. The fusion was opaque and pre-computed. In the new tool:

- Physical buildability will be a future canvas overlay computed from `layer.parquet` on demand — derivable from the Y=0 layer scan that already exists
- Rule-based restrictions are already fully visible through `xml_data.json` → `apply_rules` and the region hierarchy in the editor

### `region_categories` is not stored

Categories are a derived view over region IDs, not source data. Storing them in `xml_data.json` means they must be regenerated whenever categorisation logic changes, creating stale-data risk. Computing them at viewer load time from the region IDs is trivial and always correct.

### Synthetic ID stability is a hard requirement

The viewer edits regions and saves back to `xml_data.json`. If a re-parse after an edit produces different synthetic IDs, references from spawners, apply rules, and `wool_room_region` to those IDs would silently break. Stable IDs ensure the editor's save/reload cycle is safe.

### Intra-team symmetry is dropped without loss

The viewer's symmetry panel reads only from `global_symmetry[]` in `symmetry.json`. The `intra_team_symmetry` field was appended by the assembly step and is not referenced anywhere in the viewer frontend. Its removal has no user-visible effect.

### Per-map config replaces automatic observer detection

The legacy pipeline attempted to auto-detect the observer island and re-run symmetry excluding it. This was heuristic-based and occasionally wrong. The new approach makes it explicit: the user identifies non-playable islands in `map_config.json`, and the symmetry step re-runs with those excluded. This gives the user control and makes the result transparent.
