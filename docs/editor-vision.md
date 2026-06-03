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
| 3 | **Teams** | Team definitions (name, color, min/max players) |
| 4 | **Objectives** | Wool rooms, spawns, kits — requires teams |
| 5 | **Build Regions** | Define traversable build areas per team |
| 6 | **Filters** | Full filter overview — catch anything missed in earlier steps |
| 7 | **Regions** | Complete region list with filter options; validation and overview |

### Why Teams before Objectives

Objectives (wool rooms, spawns, kits) require team assignments. Teams must exist first.

### Why Build Regions before Objectives (or directly after Teams)

Build Regions may belong immediately after Teams. The rationale: if no block exists at y=0, movement between islands is impossible. The editor can detect this and signal to the user at the earliest opportunity — "based on the current scan, players cannot move between islands" — before they place any objectives. Fixing traversability first ensures that the path from spawn A to spawn B, and onward to objectives, is possible. This is a natural prerequisite gate before Objectives.

This placement is still under consideration. Either directly after Teams or as step 5 (after Objectives) are both valid. Consensus needed.

### Filters — inline during steps, overview at end

Filters are **not** a single step at the end. Relevant filter scenarios are surfaced inline during the step where they apply:

- **Teams step** → spawn protection filters (deny enemy team entry to own spawn)
- **Objectives step** → wool room access restrictions (deny own team entry to own wool room)
- **Build Regions step** → block editing rules (wool room protection, full lockdowns), resource renewal
- **Filters activity** → final overview of all applied rules; catch anything not covered; rare mechanics (jump pads, time-gated unlocks, anti-climb)

Region groupings (which regions belong together as a logical set) must be addressed in each step where regions are defined — not deferred to the end. Whether grouping is automatic (inferred from symmetry + team count) or guided (user assigns) requires deeper analysis of the 300+ map corpus. That analysis is out of scope here.

---

## Symmetry-Driven Suggestions

Symmetry suggestions are **configurable** — the user selects which region types the symmetry engine should propose counterparts for. Configuration is per-map and toggleable.

### Configurable region types

| Region type | Example semantic | Suggestion behavior |
|---|---|---|
| Spawn points (`point` / `cylinder`) | Team A spawn → Team B spawn | Suggest rotated/mirrored counterpart |
| Wool monuments | Monument A → Monument B | Suggest mirrored position |
| Wool room regions | Wool room A → Wool room B | Suggest rotated boundary |
| Build regions | Build area A → Build area B | Suggest reflected boundary |

Each type can be switched on or off. The user may not want suggestions for certain region categories (e.g. a shared center region has no counterpart).

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

Exact trigger mapping per activity step requires further discussion.

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

## Open Questions

1. **Build Regions placement**: Directly after Teams (step 4) or after Objectives (step 5)?
2. **Filter grouping strategy**: Automatic inference from symmetry + team count, or user-guided grouping? Requires corpus analysis.
3. **Inline filter UI pattern**: Panel section within the step, or modal/sidebar triggered from a region selection?
4. **Symmetry suggestion acceptance**: Per-suggestion confirm, or batch accept all with single override?
5. **Notification trigger mapping**: Which specific events in each activity map to which notification type?
