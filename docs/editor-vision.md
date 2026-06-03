# pgm-map-studio — Editor Vision

## Tool Identity

The tool is an **editor**, not a viewer. The current "map_viewer" name is a historical artefact from when the goal was read-only analysis. As editing capabilities were added the name was never updated. Going forward the tool is consistently called the **editor**.

The concept-first workflow (drawing a map from scratch) and the existing-map workflow share the same editor shell with different entry points. Region rules, filter logic, and symmetry behaviour are identical in both paths.

---

## User Workflow

```
Upload / download URL  (tool-external; user confirms)
        │
        ▼
   Auto-analyse
   (layout → symmetry → XML)
        │
        ▼
   ┌─ Configure ─┐   ← first mandatory stop
   │ layer, symmetry confirmation │
   └─────────────┘
        │
        ▼
   Edit (multi-step activities — see below)
```

1. The user provides a map folder, ZIP, or download URL. Map acquisition is external to the tool; the user explicitly triggers import.
2. The pipeline runs automatically (layout → symmetry → XML).
3. **Configure** opens first — the pipeline cannot reliably auto-select the correct scan layer, so the user must confirm it before results are trusted.
4. The user then works through the editing activities in order.

---

## Activity Structure

### Order

| # | Activity | Core purpose |
|---|---|---|
| 1 | **Configure** | Scan layer, island exclusions, symmetry axis confirmation |
| 2 | **Overview** | Map name, version, authors, game mode |
| 3 | **Teams** | Team definitions (name, color, min/max players) + spawn placement |
| 4 | **Build Regions** | Define traversable build areas per team |
| 5 | **Objectives** | Wool rooms, kits — requires teams |
| 6 | **Filters** | Full filter overview — catch anything missed in earlier steps |
| 7 | **Regions** | Complete region list with filter options; validation and overview |

### Teams includes spawn placement

Spawns are links from a region to a team (`{team, kit, yaw, region}`). They are logically inseparable from the team they belong to: deleting a team cascades to delete all its spawns. The Teams step therefore covers both team definition and assigning spawn regions per team.

### Build Regions before Objectives

If no block exists at y=0, movement between islands is impossible. Build Regions comes before Objectives so the editor can signal this at the earliest opportunity — "based on the current scan, players cannot move between islands" — before any objectives are placed. Fixing traversability first ensures the path from spawn A to spawn B, and onward to objectives, is valid. This is the natural prerequisite gate.

### Filters — inline during steps, overview at end

Filters are **not** a single step at the end. Relevant filter scenarios are surfaced inline during the step where they apply:

- **Teams step** → spawn protection filters (deny enemy team entry to own spawn)
- **Objectives step** → wool room access restrictions (deny own team entry to own wool room)
- **Build Regions step** → block editing rules (wool room protection, full lockdowns), resource renewal
- **Filters activity** → final overview of all applied rules; catch anything not covered; rare mechanics (jump pads, time-gated unlocks, anti-climb)

Region groupings (which regions belong together as a logical set) must be addressed in each step where regions are defined — not deferred to the end. Whether grouping is automatic (inferred from symmetry + team count) or guided (user assigns) requires deeper analysis of the 300+ map corpus. That analysis is out of scope here.

---

## Symmetry-Driven Suggestions

Symmetry suggestions are **configurable** — the user selects which region types the symmetry engine should propose counterparts for. Configuration is per-map and toggleable per region type.

Examples of region types that can be toggled on or off: spawn points (`point` / `cylinder`), wool monuments, wool room regions, build regions. The list is not exhaustive — the exact set of toggleable types is determined during implementation based on what the parser produces and what the corpus analysis shows is meaningful.

Each automatically generated suggestion requires **individual confirmation** by the user before it is applied. There is no batch-accept. This keeps the user in control and avoids silently creating incorrect counterparts.

### Symmetry as quality control

For existing maps, symmetry detection doubles as a **validation tool**. Given a confirmed `rot_180` or `mirror_*` axis and exactly 2 teams, the editor can check:

- Are exactly 2 team spawns present?
- Do their positions satisfy the detected symmetry within tolerance?
- Do wool room boundaries match their expected counterparts?

Violations are surfaced as Panel Validation Warnings in the relevant step. This is useful both for newly authored maps and for auditing community maps imported for analysis.

---

## Regions Activity

The Regions activity is a read-filtered overview of the complete region hierarchy — not an authoring surface. By the time the user reaches it, Teams, Objectives, Build Regions, and inline Filters have already structured the meaningful regions.

Regions provides:
- A flat list of all regions with their type, bounds, and assignments
- Filter/sort options (by type, by team, by assignment status, unassigned regions highlighted)
- No "expert mode" toggle — just practical list controls

The full hierarchy view remains available because it is still useful for map analysis and QA. It is not the primary authoring interface.

---

## Notification System

Four canonical types replace the current six fragmented mechanisms:

| Type | Location | Trigger | Duration |
|---|---|---|---|
| **System Error** | Top bar | HTTP 4xx/5xx — human-readable message, never raw status codes | Until dismissed |
| **Operation Toast** | Bottom-right | Successful save, export, pipeline run | 4 s auto-dismiss |
| **Canvas Drawing Hint** | MapCanvas overlay | User enters draw/select mode | Until mode exits |
| **Panel Validation Warning** | Inline in panel | Invalid field, missing required input, symmetry violation | Until resolved |

Exact trigger mapping per activity step is to be defined during implementation.

---

## Entry Points

### Existing-map workflow

1. User provides folder, ZIP, or download URL (tool-external action).
2. User explicitly confirms import — the editor does not silently fetch anything.
3. Pipeline runs → Configure opens.
4. User works through activities.

### Sketch (concept-first) workflow

Sketch is for **new maps only** — it is not a mode for editing existing maps.

In Sketch, Configure is unnecessary. Sketch defines everything from scratch. To produce a symmetric map the user must specify the **center point** and **symmetry type** upfront — without this, building a symmetric layout by hand is impractical. These two inputs are the entry screen for Sketch.

Once center and symmetry are set, the same region rules, filter templates, and suggestion engine apply as in the existing-map workflow.

---

## Activity Status

Every activity in the rail carries a **status indicator** with four states:

| State | Meaning |
|---|---|
| None | Not yet visited, or no data present |
| Yellow | Visited but required fields are incomplete |
| Green | All required fields present and valid |
| Red | Validation errors that must be resolved |

Activities are freely navigable at any time once a map is loaded. Status indicators communicate progress without blocking navigation.

The exact definition of what contributes to each state per activity — which fields are "required", what counts as a validation error — is to be specified per activity during implementation.

---

## Export

Export is the final activity. It is reached after all other activities have been completed.

**What the user does here:** Preview the generated `map.xml`, review any remaining warnings, and download the file.

Key behaviours:
- **XML preview** — the full generated `map.xml` is shown before download so the user can inspect it.
- **Download gated on Build Regions** — the download button is disabled until the Build Regions activity is valid (connectivity check passes).
- **Round-trip safety** — if the imported map contains XML elements the editor cannot parse and safely re-serialize, export is blocked entirely. Silently dropping original XML on save is not acceptable.
- The original `map.xml` is never modified. Export always generates a new file from the current editor state.

Panel layouts and the exact warning presentation are to be defined during implementation.

---

## Open Questions

1. **Filter grouping strategy**: Automatic inference from symmetry + team count, or user-guided grouping? Requires corpus analysis of the 300+ map dataset.
