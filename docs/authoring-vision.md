# CTW Authoring Assistant — Product Vision

This document captures the long-term product direction for the CTW Map Viewer tool.
It was written in May 2026 and should be consulted before planning any new feature work.

---

## What This Is (and Is Not)

**Not** a generic Minecraft 3D editor.
**Not** a hosted SaaS web app.

**Is:** a local-first CTW XML authoring assistant with a visual map editor. It helps mapmakers create or inspect valid CTW map XML without having to manually write complex XML from scratch.

---

## Core Framing: CTW-First

The first guided experience focuses on **Capture the Wool** because CTW maps have a repeatable authoring structure and are complex enough to benefit strongly from guidance. Other PGM game modes may be supported later.

The tool guides mapmakers through concepts they already understand from building the map:
- What is the map called?
- Who made it?
- What teams exist?
- Where do teams spawn?
- What kits/loadouts do players get?
- Where do observers spawn?
- Where are the wools?
- Where are the wool monuments/capture locations?
- Which regions are protected?
- Where are players allowed to build?
- Which rules apply to which regions?
- Is the map valid?
- Can we export a playable XML?

---

## UI Philosophy: Concept-First, XML-Second

Users should **not** have to begin by understanding raw `<apply>` rules, filters, region references, unions, complements, or inline regions. The tool should progressively teach these concepts only when needed.

Example: when defining build areas across multiple lanes or void gaps, the user can learn that a "union" combines several regions into one build region.

---

## App Structure

The current viewer/editor should become one part of a larger guided workflow. The region editor remains important, but it is not the entire app. The app needs multiple sections/workspaces:

1. Start / map selection / preprocessing
2. Overview / CTW setup checklist
3. Map info (name, version, objective, max build height)
4. Authors / contributors
5. Teams
6. Kits / loadouts
7. Spawns (team spawns + observer)
8. Wools / objectives
9. Regions
10. Rules / apply rules
11. Validation
12. Export

These are implemented as a **single editor shell with a vertical mode rail** (icon-based, left edge, VS Code style), not as separate HTML pages. The map canvas is embedded in sections that need spatial interaction (Spawns, Wools, Regions).

---

## Intended Workflow

1. User launches the local tool.
2. User opens/selects a local CTW map folder.
3. Tool checks which source files and generated files exist.
4. Tool shows a status/checklist.
5. If preprocessing is missing, user can run it from the UI.
6. UI shows logs/progress from the pipeline.
7. User opens the CTW setup/editor.
8. User follows guided setup sections.
9. User validates the map.
10. User exports XML.

---

## Architecture Principles

- CLI commands call shared Python pipeline/service functions.
- Flask API endpoints call the same shared Python pipeline/service functions.
- The frontend triggers API endpoints.
- The pipeline writes/updates generated files (map_data.json, etc.).
- The viewer/editor reads and edits those generated artifacts.

---

## Local-First Deployment

The browser UI communicates with a local Flask backend that reads/writes local files. The backend is a trusted local process. A hosted read-only demo may be useful later, but the main authoring workflow remains local-first.

Requirements for public usability:
- Simplified install/run command
- Ability to choose/open a map folder from the UI
- Ability to run single-map preprocessing from the UI
- Clear output/workspace separation
- Visible logs/progress
- Export XML

---

## Research vs. Authoring Separation

The existing pipeline supports **bulk processing of many maps** (researcher workflow: `--all` flag).
The authoring UI supports **guided processing of one map at a time**.
These concerns should remain cleanly separated — the web UI always operates on a single selected map; the CLI handles bulk research.

---

## Guided CTW User Journey

### 1. Map Identity
- Map name, version, game mode (CTW), objective text, max build height.

### 2. Authors and Contributors
- Add/remove authors and contributors.
- Distinctions: author, XML author, tester, etc. (per what PGM XML supports).

### 3. Teams
- Team ID, display name, color, dye color, max players, min players.
- Teams must be defined before spawns, wools, or rules.

### 4. Kits / Loadouts
- First version: preset selector (e.g., "iron sword + leather armor").
- Full structured kit editor is a later phase.

### 5. Team Spawns
- Define spawn region per team, kit assignment, yaw direction.
- Map canvas: click to place, drag for cylinder/rectangle, arrow for yaw.

### 6. Symmetry Assistance
- Tool detects symmetry axis from `symmetry.json`.
- User can accept or adjust.
- "Mirror spawn" / "Mirror wool" from one side to the other.
- Mirroring is explicit/previewed, not hidden.

### 7. Observer Spawn
- Same as team spawn but without team association.
- Click/select region, set Y height, set yaw.

### 8. CTW Objective / Wools
- Wool color, defending team, pickup location, capture/monument location.
- Visual: click to set pickup, click to set monument.
- Mirror counterpart wool if symmetry is configured.

### 9. Protected Regions
- Guided by intent: "protect this wool room", "prevent block placement here".
- Tool translates intent into `<apply>` + filter XML.

### 10. Build Regions
This is the entry step for the Regions activity and is required for every map. Three scenarios:

1. **Block 36 detected** — the pipeline finds extended piston heads in `layout_y0.parquet`.
   The tool auto-generates the build region from these blocks and asks the user to confirm.
2. **Water at Y=0 detected** — water layer marks the playable area; auto-generate + confirm.
3. **Manual** — no auto-detection. User draws rectangles/cuboids over lanes and bridge gaps on
   the canvas. The tool explains what a union is and combines the drawn regions automatically.

Without a build region, players cannot bridge across the void. This must be resolved before export.

### 11. Rules / Apply Rules
- Intent-based: where, what restriction, who, what message.
- Advanced/raw view preserved for complex cases.

### 12. Validation
- Continuous guidance, not just end-of-flow.
- Checks: name/version/authors present, teams exist, each team has spawn, observer spawn exists, each wool has pickup + monument, no unresolved references, build region exists, etc.

### 13. Export
- Validation status shown first.
- XML preview.
- Warnings/errors listed.
- Download / copy / save options.
- Export is **blocked** if unknown/unparsed XML elements exist (prevents data loss).

---

## Activity Canvas & Tool Behavior

Each activity in the rail has a defined layout: which panels are visible, whether the map canvas
is shown, which drawing tools are active, and what region categories are highlighted.

### Layout per activity

| Activity | Canvas | Left panel | Right panel | Drawing tools |
|----------|--------|------------|-------------|---------------|
| Overview | None (static thumbnail optional) | — | — | None |
| Players & Teams | Yes — spawn regions highlighted | **Split:** team list (top) + spawn region tree (bottom) | Team + spawn config | Point, Cylinder only |
| Objective | Yes — wool/monument regions highlighted | **Split:** wool list (top) + wool region tree (bottom) | Wool + spawner config | Point, Rect, Cuboid, Cylinder |
| Regions | Yes — all regions | **Build region banner** (top) + full region tree (below) | Region inspector | All |
| Rules & Filters | Yes — selected rule's region (read-only) | Apply rules + named filters | Rule editor form | None |
| Validation | None | — | — | None |
| Export | None | — | — | None |

### Split sidebar pattern (spatial activities)

The left panel in Players & Teams and Objective is divided into two sections:

**Top section — activity config:**
- Teams list with "Add team" / Wools list grouped by team with "Add wool"
- This is the primary list the user works from; clicking an item loads it into the inspector

**Bottom section — contextual region tree:**
- Filtered region tree showing only regions relevant to this activity (spawn or wool category)
- Supports all region tree operations: select, rename, group into union, delete
- Unions and other composites can be created here without switching to the Regions activity
- A "+" button creates a new region scoped to this activity's category
- Selecting a region here highlights it on the canvas and loads its geometry into the inspector

This means region grouping (unions, nested structures) is fully available within each spatial
activity, not just in the Regions activity. A mapmaker can group blue-spawn and red-spawn into
a spawns union directly in Players & Teams.

### Canvas region filtering

In spatial activities, only the relevant region category is highlighted. Other regions are dimmed
but not hidden — they remain visible as low-opacity context. This avoids visual noise without
concealing map geometry.

- **Players & Teams** → `spawn` category regions only highlighted
- **Objective** → `wool` category regions only highlighted
- **Rules & Filters** → only the region referenced by the currently selected apply rule is highlighted
- **Regions** → all regions at full opacity (current editor behavior)

### Guided post-draw prompts

After the user draws a region in a spatial activity, the inspector immediately presents the next
logical configuration step. No manual filter writing is required.

**Players & Teams — after drawing a spawn:**
1. Spawn region placed on canvas.
2. Inspector: "Protect this spawn from other teams?" (checkbox)
   - If yes → `enter="only-<team>"` apply rule auto-generated.
3. Inspector: yaw direction control (drag arrow on canvas or numeric input).
4. Inspector: "Mirror spawn for [other team]?" (if symmetry axis confirmed).

**Objective — after adding a wool:**
1. "Set wool location" → click on canvas → X,Y,Z recorded.
   - `api_query_wool_in_region` called immediately → inline status: Wool found ✓ / ✗.
2. "Set monument" → click on canvas → monument block X,Y,Z recorded.
3. "Define wool room?" → draw region → inspector: "Who defends this?" (team picker)
   → `enter="only-<team>"` apply rule auto-generated for the wool room.
4. "Add wool spawner?" → yes → wool room region auto-used as `player-region`; user sets delay
   (default 3s) and item count.
5. "Mirror this wool for [other team]?" (if symmetry axis confirmed)
   → mirrors location, monument, wool room region, apply rule, and spawner.

### Regions activity — build region entry step

The Regions activity opens with a **Build Region** banner at the top of the left panel. This
is the first required step before the general region tree is used.

**Auto-detect logic (from pipeline outputs):**
1. Block 36 (extended piston head) found in `layout_y0.parquet` → region auto-generated from
   those block positions → user confirms or adjusts on canvas.
2. Water at Y=0 found in layout → same auto-generate + confirm flow.
3. Nothing detected → user draws rectangles/cuboids over the playable area (void gaps, bridges,
   lanes); the tool combines them into a union and explains the concept inline.

Once confirmed, the banner collapses to a small "Build region: ✓ confirmed" status line and the
full region tree appears below. The Regions activity then serves as the general-purpose editor
for all other regions: void restrictions, decorative bounds, advanced composites, and any region
not produced by the guided flows in Players & Teams or Objective.

### Progress indicators on rail icons

Each rail icon carries a small status dot (bottom-right corner):
- No dot — not yet visited / no data loaded
- Yellow — visited but required fields are incomplete
- Green — all required fields present
- Red — validation errors in this activity

This communicates workflow progress without locking navigation. All activities remain clickable
at any time once a map is loaded.

---

## Symmetry Axis Verification

The pipeline already detects the map symmetry axis and stores it in `symmetry.json`. Before any
spatial configuration begins, the user should confirm or correct this axis.

**Placement:** Surfaced as a banner/card at the top of the **Players & Teams** activity on first
visit. The canvas shows the detected axis as a dotted line overlaid on the map. The user can:

- **Confirm** → axis locked for the session; mirroring enabled everywhere.
- **Adjust** → drag the axis line on canvas, or enter exact origin + normal coordinates.
- **Skip** → mirroring prompts will not appear in any activity.

**Where mirroring appears once confirmed:**

| Activity | Trigger |
|----------|---------|
| Players & Teams | After placing any team spawn → "Mirror for [other team]" |
| Objective | After configuring one team's wools → "Mirror all for [other team]" |
| Regions | Manual via the existing `<mirror>` region type (advanced) |

Mirrored regions are shown as a canvas preview before being committed. The generated XML uses
`<mirror>` elements where appropriate, keeping the file concise rather than duplicating raw
coordinates.

---

## Region Editor Improvements

### Type Icons (replace text badges)
Current sidebar shows region type as a right-aligned text badge. Replace with compact Lucide icons on the left:

| Type | Icon (proposed) |
|------|----------------|
| point | `circle-dot` |
| block | `square` |
| rectangle | `rectangle-horizontal` |
| cuboid | `box` |
| circle | `circle` |
| cylinder | `cylinder` |
| sphere | `globe` |
| union | `unite` (or `layers`) |
| intersect | `intersect` |
| negative / complement | `minus-square` |
| mirror | `flip-horizontal-2` |
| translate | `move` |
| reference | `link-2` |
| everywhere | `expand` |
| above | `arrow-up` |

Exact icon names must be verified against the installed Lucide v4 icon set.

Design principle: type icon is compact and neutral; team/semantic color is shown separately.

### Type-Specific Inspector Fields

The inspector should show type-specific fields:

| Type | Fields |
|------|--------|
| rectangle | min_x, min_z, max_x, max_z |
| cuboid | min_x/y/z, max_x/y/z |
| cylinder | base x/y/z, radius, height |
| circle | center x/z, radius |
| sphere | origin x/y/z, radius |
| block / point | x, y, z |
| union/negative/complement/intersect | children list |
| mirror | source region, origin x/y/z, normal x/y/z |
| translate | source region, offset x/y/z |
| reference | ref_id, resolved/unresolved status |
| everywhere | semantic note only |
| above | y threshold |

Inspector grouping: header (icon, id, type) → geometry → derived bounds → composition/reference → warnings → XML preview.

### Vertical / Height Slice Tool (future)
A constrained vertical cross-section showing occupied Y intervals per x/z column. Lets users set min_y/max_y visually for cuboids/cylinders/spheres. Not an immediate priority but should be kept in mind for architecture.

---

## Phased Implementation Plan

See `docs/architecture-research-report.md` for the full research findings and detailed phase breakdown.

### Summary Order

| Phase | Scope | Status |
|-------|-------|--------|
| 0 | Data model extension (authors, kits, gamemode, min_players, filter parsing) | — |
| 1 | App shell: vertical activity rail (Overview, Players, Objective, Regions, Rules, Validation, Export) | **Done** (2026-05-19) |
| 2 | Read-only Overview workspace (map info form, authors, read from map_data.json) | — |
| 2.5 | Symmetry axis verification UI (confirm/adjust detected axis; enable mirroring) | — |
| 3 | Region editor polish (Lucide type icons, type-specific inspector fields) | — |
| 4 | Preprocessing UX improvements | — |
| 5 | Players & Teams: split sidebar (team config top / spawn region tree bottom); guided spawn placement (Point/Cylinder, yaw, protection prompt, mirroring) | — |
| 5.5 | Objective: split sidebar (wool config top / wool region tree bottom); guided wool flow (location, monument, wool room, spawner, apply rule, mirroring; `api_query_wool_in_region` integration) | — |
| 6 | Regions — build region entry step (auto-detect block 36 / water, or manual draw + union); split sidebar with build region banner above full region tree | — |
| 7 | Rules & Filters: apply rule list + named filter list; canvas highlight on rule selection | — |
| 8 | Validation framework (checklist, batch wool world check, jump-to-activity on failure) | — |
| 9 | Full XML export (preview, download, error blocking) | — |

---

## Open Questions (Unresolved)

- **Q1**: Should authors be parsed into map_data.json from the original XML (simple, name-only, no Mojang lookup)? Or written directly into the generated map.xml during export?
- **Q2**: Filter parsing depth — only named block filters, full filter AST, or raw XML strings stored verbatim?
- **Q1**: Should authors be parsed into map_data.json from the original XML (simple, name-only, no Mojang lookup)? Or written directly into the generated map.xml during export?
- **Q2**: Filter parsing depth — only named block filters, full filter AST, or raw XML strings stored verbatim?
- **Q6**: Should the app remember the last opened map across sessions (via config.json)?
- **Q8**: Exact Lucide v4 icon names for region type icons — needs verification before implementation.
- **Q9**: ~~Is a vertical slice/height tool needed in Phase 6?~~ **Resolved:** Numeric Y inputs are sufficient for first spatial editing. Vertical slice tool deferred.
- **Q10**: Single Flask app long-term, or eventual split into research app + authoring app?
