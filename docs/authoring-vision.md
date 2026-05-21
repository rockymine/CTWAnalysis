# CTW Authoring Assistant — Product Vision

This document describes the intended product: what it is, who it is for, why it exists, and how each
part of the guided editor is designed to work. It is the authoritative reference for the tool's
user experience and should be consulted before planning any new feature work.

---

## What This Tool Is

The CTW Authoring Assistant is a local-first XML authoring tool for Capture the Wool maps on PGM
servers. It gives mapmakers a guided, visual way to configure all the moving parts of a CTW map —
teams, spawns, wool objectives, regions, and rules — and export a valid `map.xml` without writing
raw XML by hand.

**Launched with:**
```
python ctw.py viewer
```
Processing is orchestrated through the web UI. The same preprocessing pipeline is also available
via the CLI for batch or research workflows.

### Why it matters

Writing CTW map XML is tedious and error-prone. The main bottlenecks are:

- **Coordinate transcription**: mapmakers typically open F3 in-game, note X/Y/Z coordinates, and
  manually paste them into the XML. One digit wrong means the region is off by a block — and the
  error is invisible until the map is loaded in-game.
- **Region composition**: expressing "players can build everywhere except the void" requires
  understanding `<apply>`, `<complement>`, `<union>`, and named references before writing a single
  meaningful rule.
- **Catching omissions**: it is easy to define a wool without a monument, or a team without a
  spawn, and only find out when the server refuses to load the map.

The tool addresses all three: coordinates are captured by drawing on the map canvas rather than
transcribing from F3, region concepts are explained when they are needed, and the map's validity
state is visible at all times. Even a first-time mapmaker can complete a basic CTW configuration
and verify it before ever touching the XML.

### Technical background

Before authoring begins, the pipeline preprocesses the map folder and writes two files the editor
reads and writes:

- **`map_data.json`** — declarative metadata: name, version, gamemode, objective text, max build
  height, authors, teams, and phase.
- **`map_context.json`** — spatial data: regions, spawns, wools, build region polygon, symmetry
  axis.

The original `map.xml`, if present, is the source of truth for any existing configuration. It is
never modified. On export, the editor generates a new `map.xml` from the current editor state.

---

## The Complete User Journey

A mapmaker opens the tool and selects their map folder. The tool checks which preprocessing outputs
exist and, if needed, lets the user run the pipeline directly from the UI with a progress log.

Once the map is loaded, the editor opens at the **Overview** activity. Here the mapmaker sets the
map's name, version, and objective, reviews the author list, and confirms (or adjusts) the
symmetry axis the pipeline detected. With the axis confirmed, the tool can later offer to mirror a
spawn or wool to the other side of the map with a single click.

Next, the mapmaker moves to **Players & Teams**. They add their teams, then draw spawn regions on
the canvas for each team. After placing a spawn, the editor asks: should this spawn be protected
from other teams? A yaw direction control lets them orient players on entry. If symmetry is
confirmed, a prompt offers to mirror the spawn to the opposing side.

In **Objective**, they define wools. For each wool, they click the canvas to set the pickup
location — the editor immediately queries whether a wool block or item is actually present there —
then click to place the monument. They draw the wool room region, choose which team defends it,
and the editor auto-generates the entry rule. If they want a wool spawner, they set the delay
and count. Symmetry mirroring is available for the entire wool configuration at once.

The **Build Region** activity confirms the playable area. If the pipeline found block-36 piston
heads or a water layer at Y=0, it shows the detected build polygon and asks for confirmation.
Otherwise, the mapmaker draws rectangles over their lanes and the tool combines them into a union.
A side-view of the map (from the vertical segments data) lets the mapmaker click a block to set
the maximum build height. The editor then runs a connectivity check: can a player path from one
team's spawn to another's inside the build polygon? This check must pass before export is enabled.

In **Regions**, the mapmaker handles anything not covered by the guided flows: void restrictions,
decorative bounds, or advanced composites. The full region tree is available here, and regions
created in earlier activities also appear in this tree.

**Rules & Filters** shows every apply rule in the map — including those auto-generated in Players &
Teams and Objective — and lets the mapmaker review, edit, or add custom rules.

**Validation** shows a structured checklist. Any incomplete item links directly to the responsible
activity. The mapmaker can jump to exactly what needs fixing without hunting through the XML.

Finally, **Export** previews the generated XML, surfaces any remaining warnings, and offers a
download. The export is blocked if the map contains unparsed XML elements that the editor cannot
safely round-trip.

---

## App Shell

The editor is a **single-page app with a vertical activity rail** on the left edge (icon-based,
VS Code style). Clicking a rail icon switches the active workspace.

Each rail icon carries a small status dot in the bottom-right corner:

| Dot | Meaning |
|-----|---------|
| None | Not yet visited / no data |
| Yellow | Visited but required fields are incomplete |
| Green | All required fields present |
| Red | Validation errors in this activity |

All activities are freely navigable at any time once a map is loaded. The status dots communicate
progress without blocking navigation — except where a hard dependency is noted below.

The **map canvas** is embedded in activities that require spatial interaction. In Validation and
Export it is replaced by a static, non-editable SVG preview of the map (blocks layer only,
clipped to the map's bounding box).

---

## Activity Reference

**Rail order:** Overview → Players & Teams → Objective → Build Region → Regions → Rules & Filters → Validation → Export

---

### Overview

**What the user does here:** Establish the map's identity and confirm the symmetry axis before any
spatial work begins.

**Guiding questions:** What is this map called? Who made it? Is the detected symmetry axis correct?

| Panel | Contents |
|-------|----------|
| Left | Map identity form: name, version, gamemode (CTW), objective text; authors list (UUID, type, contribution) |
| Canvas | Map with symmetry center (purple dot) + symmetry axis line (purple) |
| Right | Symmetry axis configuration: axis type dropdown, center block/rectangle size (1×1, 1×2, 2×2), origin + normal coordinate inputs, "No symmetry" option |

The user can **Confirm**, **Adjust** (drag the axis on canvas or edit coordinates), or **Skip** the
symmetry axis:

- **Confirmed** → axis locked for the session; mirroring prompts and the "Create mirror region"
  context menu option are enabled throughout the editor.
- **Skipped** → no mirroring prompts appear anywhere; the user can return and confirm later.

**Status dot:** Green when name, version, and gamemode are set.

---

### Players & Teams

**What the user does here:** Define teams and place spawn regions. Teams are the prerequisite for
everything that follows — spawns, wools, and rules all require a team to be assigned.

**Guiding questions:** How many teams are there? What colors? Where does each team start? Should
the spawn be protected from enemy players?

| Panel | Contents |
|-------|----------|
| Left (top) | Teams list + "Add team" button |
| Left (bottom) | Region tree filtered to the `spawn` category; supports all tree operations (rename, group into union, delete); "+" creates a new spawn-category region |
| Canvas | Spawn regions highlighted at full opacity; all other regions dimmed |
| Right | Team config inspector (id, display name, color, dye color, max/min players) → Spawn config inspector (region, yaw direction, kit assignment) |

**Drawing tools:** Point, Cylinder.

**Hard lock:** Spawn drawing and the spawn-region tree are disabled until at least one team is
defined. Wools and rules also depend on teams existing.

**Guided flow after drawing a spawn:**
1. "Protect this spawn from other teams?" — if yes, an `enter="only-<team>"` apply rule is auto-generated.
2. Yaw direction control: drag the orientation arrow on canvas or enter a numeric value.
3. "Mirror spawn for [other team]?" — shown if symmetry is confirmed.

**Right-click on a region name** opens a context menu. "Create mirror region" is available when
the symmetry axis is confirmed. Additional options will be added over time.

When a new region is created and the symmetry axis is confirmed, a toast notification in the
top-right corner of the canvas reminds the user that mirroring is available via right-click.

**Status dot:** Yellow if teams are defined but any team lacks a spawn; green when all teams have
spawn regions.

---

### Objective

**What the user does here:** Define CTW wools — what color each team must capture, where each
wool is on the map, and where it must be delivered. The guided flow covers the full objective
setup including wool rooms, spawners, and auto-generated rules.

**Guiding questions:** What wool colors are needed? Where is each wool located? Where is the
monument? Who defends this wool?

| Panel | Contents |
|-------|----------|
| Left (top) | Wool list grouped by team + "Add wool" button |
| Left (bottom) | Region tree filtered to the `wool` category; full tree operations available |
| Canvas | Wool and monument regions highlighted; all other regions dimmed |
| Right | Wool config inspector (color, defending team, pickup X/Y/Z, monument X/Y/Z, spawner config) |

**Drawing tools:** Point, Rect, Cuboid, Cylinder.

**Hard lock:** Wool configuration requires at least one team to exist; wools must be assigned to a
defending team.

**Guided flow after adding a wool:**
1. "Set wool location" → click canvas → X/Y/Z recorded → editor queries whether a wool block or
   item is present in that location or in any chest within it → inline status shows ✓ (found,
   with color) or ✗ (nothing found).
2. "Set monument" → click canvas → monument X/Y/Z recorded.
3. "Define wool room?" → draw region on canvas → "Who defends this?" team picker → an
   `enter="only-<team>"` apply rule is auto-generated for the wool room.
4. "Add wool spawner?" → yes → the wool room region is used as the `player-region`; user sets
   respawn delay (default 3 s) and item count.
5. "Mirror this wool for [other team]?" (if symmetry confirmed) → mirrors the pickup location,
   monument, wool room region, apply rule, and spawner in one step.

**Status dot:** Yellow if any wool is missing a location or monument; green when all wools are
fully configured.

---

### Build Region

**What the user does here:** Confirm where players may place blocks and set the maximum build
height. These two settings determine whether the map is structurally playable — teams must be
reachable from each other through the build area.

**Guiding questions:** Where can players bridge and build? Can a player path from one team's
spawn to another's? What is the maximum height a player should be able to build to?

| Panel | Contents |
|-------|----------|
| Left | Build region status banner (source: "detected from block layout" / "from map XML" / "manual") + auto-detected polygon or manual drawing controls |
| Canvas | Build region polygon highlighted; pathfinding overlay showing the route from spawn A to spawn B |
| Right | Max build height control: cross-sectional side view of the map (from vertical segments data); click a block to set the Y threshold; a horizontal line marks the selected height |

**Auto-detect logic** (from `map_context.json` `build_region`):
- `source = "y0_blocks"` — blocks at Y=0 detected (extended piston heads or water layer); build
  polygon shown for user confirmation.
- `source = "xml"` — a build region was defined in the existing `map.xml`; loaded and shown for
  confirmation.
- Nothing detected — manual mode: user draws rectangles or cuboids over the playable area (lanes,
  bridge gaps); the tool combines them into a union and explains the concept inline.

**Connectivity check:** After the build region and at least two team spawns are defined, the editor
attempts to pathfind from team A's spawn to team B's spawn inside the build polygon. The result is
shown inline on the canvas and in the status banner.

**Valid when:**
- Max build height is set, AND
- Build region is confirmed (auto or manual), AND
- Connectivity check passes.

The export download is disabled until this activity is valid.

**Status dot:** Red if the connectivity check fails or either field is unset; green when all three
conditions are met.

---

### Regions

**What the user does here:** Manage all regions that were not produced by the guided flows in
Players & Teams, Objective, or Build Region. This is the general-purpose region editor for void
restrictions, decorative bounds, and advanced composites.

**Guiding questions:** Are there regions this map needs that weren't covered by guided steps?

| Panel | Contents |
|-------|----------|
| Left | Full region tree (all categories, all types) |
| Canvas | All regions at full opacity |
| Right | Region inspector: header (icon, id, type) → type-specific geometry fields → derived bounding box → composition / reference list → warnings → XML preview |

**Drawing tools:** All available tools.

Regions created in Players & Teams or Objective appear in this tree — the region tree is shared
across activities. Right-click on a region name opens the context menu; "Create mirror region" is
available when the symmetry axis is confirmed.

**Status dot:** Yellow if any region has unresolved references; green otherwise.

---

### Rules & Filters

**What the user does here:** Review every apply rule in the map — including those auto-generated
in Players & Teams and Objective — and add, edit, or remove rules as needed.

**Guiding questions:** Are the auto-generated rules correct? Are there additional restrictions that
weren't covered by the guided flows?

| Panel | Contents |
|-------|----------|
| Left | Apply rules list (all rules, including auto-generated) + named filters list |
| Canvas | Region referenced by the currently selected apply rule, highlighted; canvas is read-only in this activity |
| Right | Rule editor form: region picker (where), restriction type (block-place, enter, exit, etc.), team filter (who), message; raw XML view toggle for advanced cases |

**Drawing tools:** None.

Auto-generated rules from Players & Teams (spawn entry rules) and Objective (wool room entry
rules) appear here and are fully editable.

**Status dot:** Yellow if any rule references an unresolved region; green otherwise.

---

### Validation

**What the user does here:** Review the map's completeness before attempting an export. Every
failed check links directly to the activity responsible for fixing it.

**Guiding questions:** Is the map complete? Would PGM accept this configuration?

| Panel | Contents |
|-------|----------|
| Canvas | Static SVG map preview: blocks layer only, clipped to bounding box, not editable |
| Main | Checklist of required conditions (see below); each failure shows a "Go to [Activity]" link |

**Checklist items (non-exhaustive):**
- Name, version, and gamemode are set
- At least two teams are defined
- Each team has a spawn region
- Observer spawn is defined
- Each wool has a pickup location and monument
- Build region is valid (confirmed + max height set + connectivity passes)
- No unresolved region references

Validation runs continuously in the background. This activity shows the current state rather than
triggering a one-time check.

**Status dot:** Red if any blocking check fails; green when all checks pass.

---

### Export

**What the user does here:** Generate the final `map.xml` and download it.

**Guiding questions:** Is everything correct? Ready to export?

| Panel | Contents |
|-------|----------|
| Canvas | Static SVG map preview (same as Validation) |
| Main | Validation summary (with link to Validation for detail) → XML preview → warnings and errors list → Download / Copy / Save buttons |

The **download is disabled** if the Build Region activity is not yet valid.

The **export is blocked entirely** if the map contains XML elements that the editor cannot parse
and round-trip — this prevents silently dropping parts of the original XML on save.

Export generates a new `map.xml` from `map_data.json` and the current editor state. The original
`map.xml` is never modified.
