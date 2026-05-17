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
- Draw multiple rectangles over lanes/bridge gaps.
- Combine into a union.
- Guided explanation of what a union is.
- Preview the allowed build area.

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

| Phase | Scope |
|-------|-------|
| 0 | Data model extension (authors, kits, game_mode, min_players, filter parsing) |
| 1 | App shell: vertical mode rail + workspace panel switching |
| 2 | Read-only CTW overview workspace |
| 3 | Region editor polish (Lucide icons, type-specific inspector) |
| 4 | Preprocessing UX improvements |
| 5 | Editable map info + teams + authors |
| 6 | Guided spatial setup (spawns, observer, wools) |
| 7 | Symmetry assistance |
| 8 | Apply rules and filters UI |
| 9 | Validation framework |
| 10 | Full XML export |

---

## Open Questions (Unresolved)

- **Q1**: Should authors be parsed into map_data.json from the original XML (simple, name-only, no Mojang lookup)? Or written directly into the generated map.xml during export?
- **Q2**: Filter parsing depth — only named block filters, full filter AST, or raw XML strings stored verbatim?
- **Q6**: Should the app remember the last opened map across sessions (via config.json)?
- **Q8**: Exact Lucide v4 icon names for region type icons — needs verification before implementation.
- **Q9**: Is a vertical slice/height tool needed in Phase 6, or are numeric Y inputs sufficient for first spatial editing?
- **Q10**: Single Flask app long-term, or eventual split into research app + authoring app?
