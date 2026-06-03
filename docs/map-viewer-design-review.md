# Map Viewer — Design Review & Component Inventory

## 1. Overview

This document is a critical design review of the map viewer frontend. It captures what currently exists, where the implementation is inconsistent or duplicated, and establishes clear definitions for the component vocabulary going forward. It is intended as the reference document for a design consolidation pass.

**Sources:** Full static analysis of `map_viewer/static/` and `map_viewer/templates/` (83 files, ~15,000 LOC), combined with direct user feedback.

**Reference implementations (what "correct" looks like in the current codebase):**
- **Best:** Overview activity + Regions activity — clearest separation of concerns, cleanest layout
- **Good but overloaded:** Objective activity — right panel carries too many responsibilities
- **Problems:** Teams activity repeats patterns from Objective without a shared base

---

## 2. Terminology Definitions

These definitions are the authoritative vocabulary for the codebase. Every component, file, and class name should align with them.

### Page
A full-screen HTML document served by Flask. Each page has its own template, entry-point JavaScript file, and CSS scope. Pages do not share DOM.

| Name | Route | Entry JS | Purpose |
|---|---|---|---|
| **Dashboard** | `/` | `dashboard.js` | Map discovery, config, pipeline trigger |
| **Editor** | `/editor?map=<name>` | `main.js` | Main map authoring tool |
| **Configure** | `/configure?map=<name>` | `configure.js` | Per-map pipeline setup: layer selection, island exclusion, symmetry config |
| **Concept** | `/concept` | `concept.js` | Experimental shape/island exploration tool |

### Activity
A named workspace mode within a page. Activities are mutually exclusive — only one is active at a time. Each activity owns a canvas region, a left panel (list), and a right panel (inspector). Activities expose a consistent interface: `activate({ mapName })`, `deactivate()`, `resize()`.

Activities exist in the **Editor** page only. Configure and Concept have similar switching but should not use the Activity pattern — they are steps, not authoring modes.

| Activity | ID | Left panel | Right panel | Canvas |
|---|---|---|---|---|
| **Overview** | `activity-overview` | — | Map identity, authors | Block layer preview |
| **Teams** | `activity-teams` | Teams list + Spawn list | Team inspector OR Spawn inspector | Spawn regions |
| **Objective** | `activity-objective` | Wools list + Region list | Wool inspector | Wool + monument POI markers |
| **Regions** | `activity-regions` | Region tree | Region detail inspector | All regions (editable, with draw tools) |

> **Pending move:** Symmetry configuration currently lives in the Overview activity. It belongs on the Configure page — it is a pipeline setup concern, not a map metadata concern. The Overview activity should show only map identity and authors.

### Panel
A vertically scrollable area anchored to the left or right of the canvas. Panels are subdivided into **sections**.

- **Left panel** — always a list of items (teams, wools, regions). Supports single selection, which drives the right panel.
- **Right panel** — a detail inspector for the currently selected item. Shows editable fields. When nothing is selected it shows an empty state.

A panel consists of one or more `section` units (see §4 Component Library).

### List
An ordered, scrollable set of rows inside a left panel section. Every row uses the `.list-row` component. Lists support single selection. An empty list shows a `.list-empty` placeholder.

### MapCanvas
The SVG drawing surface that occupies the center column of an activity. A single `MapCanvas` instance is created per activity. Responsibilities:

- Renders regions as SVG shapes with color coding by category
- Renders POI markers (spawns, wools, monuments)
- Supports zoom/pan via mouse wheel and drag
- Hosts draw tools (rectangle, cylinder, polygon, etc.) for the Regions activity
- Fires events: `onCanvasClick(node)`, `onPoiClick(type, coords)`, `onRegionDrawn(type, geometry)`

The MapCanvas does not own data. It receives regions and markers from its activity and renders them. All mutations go back through callbacks to the activity.

### Navigation

**Activity rail** — the 56px-wide vertical sidebar on the left edge of the Editor. Contains one button per activity plus the app logo. Buttons have a `data-status` attribute (`green` / `yellow` / `red`) rendered as a colored dot via CSS `::after`.

**Top bar** — the horizontal strip at the top of every page. Contains: breadcrumb (Home › Map name › Version), page-specific action buttons (Export, Run Pipeline), and the system notification zone (right-aligned). The top bar is not an activity.

**Sub-bar** — an optional horizontal strip directly below the top bar, specific to the Regions activity. Contains draw tool buttons and the zoom/coordinate readout.

---

## 3. Notification & Feedback System

Currently there are six separate feedback mechanisms with no shared implementation. This section defines four canonical types that replace all of them.

### Type 1 — System Error (top bar)

**What it is:** A non-dismissable error state in the top bar triggered by a failed page-level operation — map not found, API unreachable, HTTP 4xx/5xx on initial load.

**Current state:** `#status` element with plain `textContent` assignment. Displays raw HTTP codes like `"200"`, `"400"`, `"401"` with no context message.

**Correct behavior:**
- Human-readable message: `"Map not found"`, `"Could not connect to server"`, not raw status codes
- Displayed in the top bar notification zone (right-aligned)
- Persists until the condition is resolved or the user navigates away
- Styled with `--color-error` background tint, not plain text

### Type 2 — Operation Toast

**What it is:** A brief, auto-dismissing confirmation that a user-initiated operation succeeded or failed. Appears after actions like: region saved, wool added, team deleted, name changed.

**Current state:** Only implemented in the Concept tool (`concept-activity.js`, inline DOM creation). Not available in Teams, Objective, or Regions activities. Operations in those activities either update `#status` (error path) or give no feedback at all.

**Correct behavior:**
- Fixed position: bottom center of the viewport
- Auto-dismisses after ~3 seconds
- Two variants: success (green) and error (red)
- One shared implementation, called from any activity or panel via `showToast(message, type)`
- CSS: `.toast`, `.toast--success`, `.toast--error`, `.toast--visible`

### Type 3 — Canvas Drawing Hint

**What it is:** A contextual instruction rendered inside the canvas area while a draw tool is active. Tells the user what to do next.

**Current state:** Only in the Concept tool (`.concept-hint`, static text below toolbar). Not present in MapCanvas at all. Users get no guidance while drawing regions.

**Correct behavior:**
- Rendered as a text overlay inside the canvas, bottom-left or bottom-center
- Updates as tool state changes:
  - Rectangle: `"Click and drag to draw"`
  - Polygon: `"Click to add points · Double-click to close"`
  - Polygon (≥3 points): `"Double-click or click first point to close"`
  - Cylinder: `"Click center, then drag to set radius"`
- Disappears when no tool is active
- CSS: `.canvas-hint` — muted text, no background, unobtrusive

### Type 4 — Panel Validation Warning

**What it is:** A persistent inline warning inside a right panel, shown when the selected item has a fixable problem. Stays visible until the problem is resolved.

**Current state:** Not systematically implemented. Some fields show red borders (`input.author-name--error`), but there is no unified inline warning component.

**Examples of needed warnings:**
- Wool: "No wool room region assigned"
- Wool: "Monument block location not set"
- Spawn: "No team assigned"
- Region: "This region has no named parent — it will not appear in the XML"

**Correct behavior:**
- Rendered at the top of the relevant panel section, above the affected fields
- Uses a `.panel-warning` component: left border in `--color-warning`, muted background, icon + text
- Does not block interaction — the user can still edit other fields

### Summary table

| Type | Location | Trigger | Duration | Current implementation |
|---|---|---|---|---|
| **System Error** | Top bar (right) | Map load failure, API error | Persistent | `#status` plain text, shows raw HTTP codes |
| **Operation Toast** | Bottom center | CRUD operation result | ~3s auto-dismiss | Concept only; not in Editor |
| **Canvas Hint** | Canvas overlay | Draw tool active | While tool active | Concept only; absent in MapCanvas |
| **Panel Warning** | Right panel, inline | Validation failure | Until resolved | Not systematically implemented |

---

## 4. Component Library — Current State

### What exists and is correct (`components.css`)

**Section** — the structural unit of a panel:
```css
.panel-section        /* padded container */
.section-header       /* label row at top of section */
.section-header--ruled  /* with top border rule */
.section-header--list   /* flush, for list-section headers */
.section-title        /* text within header */
```

**Form fields:**
```css
.field              /* wrapper row */
.field-row          /* label + input in one row */
.field-label        /* left label */
.field-input        /* right input (text, select, number) */
.field-pick-row     /* label + color picker row */
.field-swatch       /* colored square for team/wool color */
```

**List:**
```css
.list-row             /* base: flex, 34px min-height, 12px horizontal padding */
.list-row--compact    /* 28px height variant */
.list-row--selected   /* bg-selected state */
.list-label           /* primary text within a row */
.list-label--mono     /* monospace variant (region IDs) */
.list-tag             /* small inline badge within a row */
.list-empty           /* empty state placeholder text */
```

**Buttons:**
```css
.action-btn           /* block-level button */
.action-btn--primary  /* blue accent */
.action-btn--danger   /* red */
.btn-remove           /* inline ✕ button */
.btn-remove--hover-only  /* only visible on parent hover */
```

**Canvas sub-components:**
```css
.canvas-subbar        /* draw tool strip below top bar */
.canvas-toolbar       /* floating tool selector */
.canvas-cursor        /* coordinates readout */
.canvas-zoom          /* zoom level readout */
```

**Panel utilities:**
```css
.panel-empty          /* full-panel empty state */
.panel-empty-msg      /* message within empty state */
.panel-actions        /* bottom button row */
.panel-save-status    /* save confirmation text (underused) */
```

### What is missing from `components.css`

| Missing component | Current workaround | Should be |
|---|---|---|
| `.toast` | Inline DOM in concept-activity.js | `components.css` + `showToast()` utility |
| `.canvas-hint` | `.concept-hint` (concept only) | `components.css` |
| `.panel-warning` | Red input borders, ad-hoc `<p>` tags | `components.css` |
| `.status-badge` | 6 separate badge systems | Unified in `components.css` |
| Spacing scale | Ad-hoc px values throughout | CSS variables: `--space-1` through `--space-6` |

### Badge / status indicator fragmentation

Currently there are six separate badge/indicator systems. They should be unified into one `.status-badge` component with semantic modifier classes:

| Current class | Used for | Should become |
|---|---|---|
| `.ov-sym-badge` | Symmetry status | `.status-badge .status-badge--confirmed` etc. |
| `.obj-respawn-badge` | Wool respawn type | `.status-badge .status-badge--spawner` etc. |
| `.detail-type-badge` | Region type label | `.status-badge .status-badge--neutral` |
| `.tag` (with `--ok/--error/--warn`) | Inline semantic tags | Merge with `.status-badge` |
| `.map-status-dot` | Dashboard map state | `.status-dot` (dot-only variant) |
| `activity-btn::after` (data-status) | Activity rail dot | Keep as-is (pseudo-element, CSS-only) |

---

## 5. Duplication Inventory

### Three coordinate input builders

Three independent implementations exist for what is conceptually one component — displaying and editing 2D/3D coordinates:

| File | Pattern | Used in |
|---|---|---|
| `coord-group.js` | X/Y/Z label + input rows | Spawn inspector, wool location |
| `bounds-table.js` | Table layout: axis / value / size | Regions detail, concept inspector |
| `region-detail.js` | Full geometry schema map | Regions activity detail panel |

These should consolidate into a single `CoordInput` component with layout variants.

### No base Activity or Panel class

`TeamsActivity`, `ObjectiveActivity`, `RegionsActivity` each repeat:
```javascript
this.#mapName = null;
this.#panel = new XPanel({ onStatusChange: ..., onBoundsSave: ..., ... });
this.#registry = new RegionRegistry({ ... });
```

`TeamsPanel` and `ObjectivePanel` each repeat:
```javascript
this._mapName = null;
this._selectedId = null;
this._dirty = false;
// ... identical listener setup
```

A base `Activity` class and base `Panel` class would eliminate this duplication and enforce the interface.

### Dashboard list vs. `.list-row`

The dashboard map list uses a custom `map-list-item` class structure instead of the shared `.list-row` component. Similarly, the configure island list and concept shape list use custom structures. All three should use `.list-row` to keep visual consistency.

### Activity boot duplicated in three page entry points

`main.js`, `configure.js`, and `concept.js` all independently parse `?map=` from the URL:
```javascript
const urlParams = new URLSearchParams(window.location.search);
const mapParam = urlParams.get("map");
```
Should be a shared one-liner utility.

### Color swatch updates

`teams-panel.js` and `objective-panel.js` both execute:
```javascript
swatch.style.backgroundColor = chatColorHex(teamColor);
```
Should be a `updateSwatch(el, color)` helper in `ui-helpers.js`.

---

## 6. Known Issues by Component

### Overview Activity
- ✅ Best reference implementation — clean three-column layout
- ❌ Symmetry panel belongs on the Configure page, not here. The Overview activity should show only: map name, version, objective, gamemode, max build height, authors
- ❌ SVG canvas loading placeholder uses hardcoded `fill="#334155"` — should use `var(--text-muted)`

### Teams Activity
- ⚠️ Right panel is dual-purpose (team inspector / spawn inspector) with no clear visual distinction between the two modes
- ❌ No operation feedback when team or spawn is added/deleted (missing Toast)
- ⚠️ Spawn region deletion here does not notify the Regions activity — state desync workaround via `#reloadRegions()` on re-activation

### Objective Activity
- ✅ Good overall structure
- ❌ Right panel is severely overloaded. Currently contains in one scrollable pane:
  1. Wool color selector
  2. Defending team selector
  3. Wool room region selector
  4. Respawn mechanism badge + full respawn detail (varies by type: pgm_spawner / mob_spawner / renewable / chest — each with 4–6 fields)
  5. Location coordinates (x/y/z)
  6. Monument capture cards (one per attacking team, with coordinates)
  
  The respawn detail section alone has four completely different layouts. This needs either collapsible sections or a sub-panel navigation pattern.
- ❌ Respawn badge colors are hardcoded hex values, not design tokens

### Regions Activity
- ✅ Best reference for the left panel (region tree with visibility toggles, context menu)
- ✅ RegionRegistry correctly models the tree with stable parent/child tracking
- ⚠️ Keyboard shortcuts (delete, ctrl+Z/Y, tool keys) work but are undiscoverable — no visible shortcut reference
- ⚠️ Multi-select (Ctrl+Click) is registered but not fully implemented

### MapCanvas
- ✅ Core SVG rendering, zoom/pan, draw tools well implemented
- ❌ No drawing hints while tools are active (Type 3 notification absent)
- ❌ Canvas loading state uses hardcoded SVG `<text>` in two places in editor.html — not a component

### Top Bar / Status
- ❌ Displays raw HTTP codes (`"200"`, `"400"`, `"401"`) instead of human-readable messages
- ❌ `#status` is plain `textContent`, no error styling

### Configure Page
- ⚠️ "Activities" here (Layer Selection + Exclusions) are pipeline steps, not authoring modes — they should not use the activity rail pattern from the Editor. A simple step indicator or tab pattern is more appropriate.
- 🆕 Symmetry configuration should move here from the Editor's Overview activity

---

## 7. Current Feature Inventory

### Editor — implemented and working

**Overview activity:**
- Edit map name, version, objective, gamemode, max build height
- Edit authors (name/UUID lookup, role, contribution field)
- View and confirm symmetry detection (to be moved to Configure)
- Block layer preview canvas

**Teams activity:**
- Add / edit / delete teams (id, color, dye color, display name, max/min players)
- Link spawn regions to teams (with yaw and kit references)
- View spawn region bounds on canvas

**Objective activity:**
- Add / edit / delete wools (color, defending team, location, monument block)
- Assign wool room region
- Wool respawn type detection (pgm_spawner / mob_spawner / renewable / chest / unknown)
- Respawn detail display (delay, max entities, items for PGM spawner; mob spawner config; renewable rules; block drop rules)
- Monument capture cards per attacking team

**Regions activity:**
- Region tree view with hierarchy, visibility toggles, context menu
- Draw tools: rectangle, cylinder, polygon, circle, sphere, block, point
- Region type change in-place
- Group / ungroup regions
- Coordinate / bounds editing in detail panel
- XML preview per region
- Delete with undo history (Ctrl+Z / Ctrl+Y)
- Resolved composite view (E key)

**MapCanvas (shared across activities):**
- SVG-based rendering with zoom/pan
- Region shapes with category color coding (spawn/wool/build/other)
- POI markers: spawns (team-colored), wools (◆), monuments (⊕)
- Draw mode with tool-specific interaction
- Transform matrix for zoom/pan

### Configure page — implemented and working
- Layer extractor selection (surface, bedrock, y0, base)
- Block exclusion list
- Island inspector with exclude toggle
- Pipeline trigger with SSE progress bar and console output

### Dashboard — implemented and working
- Config: maps folder + output folder paths
- Map list with status dots (preprocessed / not preprocessed)
- URL import (paste WorldEdit download link)
- Pipeline progress (SSE-based step visualization with console)
- Map detail panel: team count, wool count, version

### Export
- XML export from current `xml_data.json` state via `/api/map/{name}/export/xml`

---

## 8. What Needs to Be Built or Fixed

### Priority 1 — Correctness / UX clarity

1. **Fix top bar error messages** — replace raw HTTP codes with human-readable strings; add error styling to `#status`
2. **Implement unified Toast** — one `showToast(message, type)` function in `ui-helpers.js`, CSS in `components.css`, used by all activities for operation feedback
3. **Add canvas drawing hints** — `.canvas-hint` overlay in MapCanvas, driven by active tool state
4. **Move symmetry to Configure page** — remove from Overview activity; add to Configure as a third step after island exclusion

### Priority 2 — Design consistency

5. **Unify badge system** — replace 6 badge/dot systems with `.status-badge` + modifier classes in `components.css`
6. **Add `.panel-warning`** — inline validation warning component for right panels
7. **Apply `.list-row`** to dashboard map list, configure island list, concept shape list
8. **Fix hardcoded colors** — `fill="#334155"` in SVG templates, hex values in respawn badges and concept canvas

### Priority 3 — Architecture

9. **Base Activity class** — shared constructor logic: `#mapName`, `#panel`, `#registry` initialization, `activate()` / `deactivate()` lifecycle
10. **Base Panel class** — shared `_dirty`, `_selectedId`, listener setup, `_setDirty()` pattern
11. **Single CoordInput component** — replace `coord-group.js`, `bounds-table.js`, and the geometry schema renderer with one component accepting a layout variant
12. **Objective right panel refactor** — split into collapsible sections or introduce a sub-panel tab pattern for the respawn detail section
13. **Add spacing scale** — CSS variables `--space-1` (4px) through `--space-6` (24px) in `viewer.css` root

### Priority 4 — Minor cleanup

14. **URL param utility** — `getMapParam()` shared function, remove duplication in `main.js` / `configure.js` / `concept.js`
15. **`updateSwatch()` helper** — move to `ui-helpers.js`
16. **`panel-save-status`** — either wire it up consistently or replace with Toast
17. **Add `concept.css` tokens** — make concept page use `viewer.css` design tokens instead of isolated styles

---

## 9. CSS Design Tokens — Current State

Defined in `viewer.css :root`:

```css
/* Backgrounds */
--bg-deep, --bg-base, --bg-panel, --bg-multi
--bg-selected, --bg-selected-hover, --bg-selected-child
--bg-vis-hover, --bg-base-glass, --bg-panel-glass

/* Text */
--text-muted, --text-dim, --text-secondary, --text-primary, --text-bright, --text-white

/* Borders */
--border

/* Accent */
--accent, --accent-light, --accent-lighter, --accent-bg-hover

/* Semantic status */
--color-success, --color-success-bg
--color-error, --color-error-bg, --color-error-light
--color-warning
--code-color
```

**Missing:**
- Spacing scale (`--space-*`)
- Typography scale (`--font-size-*` or `--text-sm/md/lg`)
- Border radius (`--radius-sm`, `--radius-md`)
- Transition duration (`--transition-fast`)

---

## 10. Vision Gap Analysis

Cross-referencing the current implementation against `docs/editor-vision.md` reveals gaps that go beyond component-level issues. These are structural absences — activities, flows, and mechanisms that the vision requires but that do not exist at all in the current codebase.

### Missing activities

**Build Regions activity** — completely absent. The vision places this as step 4 (between Teams and Objectives) to enforce the traversability gate: if no block exists at y=0, players cannot reach each other, and the editor should surface this before any objectives are placed. Currently, build region logic is referenced only in `map_context.json` from the old pipeline. There is no dedicated editor activity, no MapCanvas integration, and no connectivity check in the frontend.

**Export activity** — the backend endpoint `/api/map/{name}/export/xml` exists, but there is no Export activity in the editor rail. The vision requires: an XML preview pane before download, the download button gated on Build Regions validity, and a round-trip safety block (export disabled if the XML contains elements the editor cannot re-serialize). None of these are implemented. Export is currently an invisible button action with no preview and no safety gate.

### Missing flows

**Inline filter prompts** — the vision calls for filter scenarios to be surfaced contextually within each step: spawn protection prompt after placing a spawn in Teams; wool room access rule prompt after assigning a defending team in Objectives; block-editing rules in Build Regions. Currently no guided prompts exist anywhere. The user must know to navigate to Rules & Filters manually and construct rules from scratch. The Teams and Objective activities do not ask any filter-related questions.

**Cross-activity dependencies** — the vision defines clear prerequisites: Teams must exist before Objectives; Build Regions validity gates Export. The current editor enforces none of this. All activities are independently accessible with no dependency signaling. A user can define wools before any team exists, or attempt export with an invalid build region.

**Configure → Editor handoff** — Configure is currently a standalone page separate from the editor. The vision makes Configure the mandatory first activity when opening a map (scan layer confirmation, symmetry axis). The current separation means a user can open the editor without having confirmed the scan layer at all. There is no formal handoff: no redirect, no status indicator on the editor rail that Configure is incomplete.

### Framing shifts with architectural consequences

**Regions is now an overview, not the primary authoring surface** — the vision places Regions last as a validation/QA view with filter and sort controls. Currently Regions is the most feature-complete activity and the primary place to create and edit geometry. Once Build Regions and the guided Objectives flow exist, most region creation will happen inline in those steps. The Regions activity will need to shift from "authoring surface" to "all regions in one filterable list." The draw tools currently in Regions would move to the steps where regions are created.

**Symmetry as quality control** — the vision calls for symmetry to validate existing maps: given `rot_180` or `mirror_*` and exactly 2 teams, the editor should check whether 2 spawn regions exist at symmetric positions, whether wool room boundaries match their counterparts, etc. Currently symmetry is display-only (a confirmed/unconfirmed axis in Overview). There is no validation logic connecting symmetry data to the regions or spawns.

**Activity status semantics undefined** — the rail `data-status` attribute (green/yellow/red) exists in the CSS and HTML, but the logic that sets it is not systematically defined per activity. What makes Teams yellow vs. green (is it "at least one team defined" or "all teams have spawns"? is an empty kit acceptable?) is not specified anywhere in the codebase. The vision identifies this as requiring per-activity definition before implementation.

**Sketch entry point** — the current Concept page is an exploratory shape tool with no guided workflow. The vision defines Sketch as a full entry point for new maps: center point and symmetry type are mandatory inputs before drawing begins, and the same region rules, filter prompts, and suggestion engine as the existing-map workflow apply. The current Concept page cannot serve this role without significant redesign.

### Summary

| Gap | Current state | Required by vision |
|---|---|---|
| Build Regions activity | Absent | Step 4 in editor rail |
| Export activity | API endpoint only | Full activity with XML preview + safety gate |
| Inline filter prompts | Absent | Contextual per step (Teams, Objectives, Build Regions) |
| Cross-activity dependencies | Not enforced | Teams before Objectives; Build Regions gates Export |
| Configure → Editor handoff | Separate page, no handoff | Configure is activity 1 in the same flow |
| Symmetry as validator | Display only | Checks spawn/region positions against axis |
| Activity status semantics | CSS exists; logic undefined | Specified per-activity during implementation |
| Sketch as guided entry | Exploratory tool | Guided flow with mandatory center + symmetry inputs |

---

## Appendix: File Size Reference

| File | LOC | Notes |
|---|---|---|
| `map-canvas.js` | 1293 | Core canvas — consider splitting draw tools into separate module |
| `objective-panel.js` | 856 | Largest panel — split candidate |
| `concept-canvas.js` | 970 | Concept tool canvas |
| `configure.js` | 836 | Dense; mixes pipeline logic with UI |
| `teams-panel.js` | 662 | Two inspectors in one file |
| `regions-activity.js` | 675 | Activity + keyboard shortcuts + history |
| `region-detail.js` | 724 | Geometry schema + coordinate editing |
| `region-tree.py` | 540 | Backend tree — separate from frontend RegionRegistry |
| `viewer.css` | 1020 | Primary stylesheet |
