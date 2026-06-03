# pgm-map-studio — Editor Vision

## Tool Identity

The tool is an **editor**, not a viewer. The current "map_viewer" name is a historical artefact from when the goal was read-only analysis. As editing capabilities were added the name was never updated. Going forward the tool is consistently called the **editor**.

The concept-first workflow (drawing a map from scratch) and the existing-map workflow share the same editor shell with different entry points. Region rules, filter logic, and symmetry behaviour are identical in both paths.

---

## User Workflow

```
Upload / download URL
        │
        ▼
   Auto-analyse
   (layout → symmetry → XML)
        │
        ▼
   ┌─ Configure ─┐   ← first mandatory stop
   │ layer, symmetry confirmation, teams │
   └─────────────┘
        │
        ▼
   Edit XML  (multi-step activities)
```

1. The user provides a map folder, ZIP, or download URL.
2. The pipeline runs automatically (layout → symmetry → XML).
3. The **Configure** step opens first — the pipeline cannot yet reliably auto-select the correct scan layer, so the user must confirm it before results are trusted.
4. After configuration the user works through the editing activities.

---

## Activity Structure (revised)

### Current problems
- Symmetry sits inside Overview, which is wrong — it has no connection to map metadata.
- The Regions activity is overwhelming for end users (designed for analysis, not authoring).
- Build regions and filters have no dedicated home.

### Proposed activity order

| # | Activity | Description |
|---|---|---|
| 1 | **Configure** | Scan layer selection, island exclusions, symmetry axis confirmation, team definitions |
| 2 | **Overview** | Map name, version, authors, game mode — read-only summary |
| 3 | **Objectives** | Wool rooms, spawns, kits — the core CTW elements |
| 4 | **Regions** | Full region hierarchy (simplified view for authoring; expert toggle for full tree) |
| 5 | **Build Regions** | Define and adjust build region boundaries per team |
| 6 | **Filters** | Apply rules, region groupings, access control, block editing rules |
| 7 | **Export** | Preview and export `map.xml` |

### Configure as Activity, not Page

Configuration does not justify a separate top-level page. It is an Activity — the user completes it once but can return at any time (e.g. to change the scan layer or re-run symmetry). It lives in the same activity navigation as the other steps.

---

## Symmetry-Driven Region Suggestions

This is a key differentiator of the tool.

Once the user has:
- Confirmed the symmetry axis (in Configure), and
- Defined the teams (also in Configure),

the editor can automatically suggest mirrored/rotated counterparts for any region the user creates. For example:

- 2 teams + `rot_180` symmetry → placing one wool room automatically suggests the rotated position for the second.
- 2 teams + `mirror_z` → build regions are reflected across the Z-axis centerline.

The suggestion is **interactive**, not silent background inference: the editor shows the proposed counterpart and the user accepts or adjusts it. This keeps the user in control while eliminating repetitive manual placement.

Implementation note: the symmetry axis and team count are already available in `symmetry.json` and `xml_data.json` respectively after the pipeline runs. The editor frontend can derive suggestions without additional backend calls.

---

## Regions Activity (simplified)

The full region hierarchy is essential for power users and map analysis, but it is the wrong first view for an author creating a new map.

Proposal:
- **Default view**: flat list of named regions with their type and bounds — no tree.
- **Expert mode toggle**: expands into the full reference-based hierarchy (composite → children by ID).
- Region groupings (which regions belong to which team's wool room, build area, etc.) are managed in the Filters activity, not here.

---

## Filters Activity

Filters is where region groupings become meaningful. The `filter-use-cases.md` analysis identified six recurring cluster patterns across 345 CTW maps:

1. Access control (wool room restrictions, spawn protection)
2. Block editing (wool room protection, full lockdowns)
3. Kit assignment
4. Movement mechanics (jump pads)
5. Resources (iron/gold renewal)
6. Advanced (time-gated unlocks, anti-climb)

The Filters activity should present these as **authoring templates** the user can instantiate, rather than requiring them to construct apply rules from scratch. Each template pre-fills the relevant regions and filter references based on the current team and region configuration.

---

## Notification System (confirmed)

Three canonical types replace the current six fragmented mechanisms:

| Type | Location | Trigger | Duration |
|---|---|---|---|
| **System Error** | Top bar | HTTP 4xx/5xx — shown as human-readable message, not status code | Until dismissed |
| **Operation Toast** | Bottom-right | Successful save, export, pipeline run | 4 s auto-dismiss |
| **Canvas Drawing Hint** | MapCanvas overlay | User enters a draw/select mode | Until mode exits |
| **Panel Validation Warning** | Inline in panel | Invalid field value, missing required input | Until resolved |

Raw HTTP status codes (200, 400, 401, etc.) are never shown to the user.

---

## Open Questions

1. **Configure activity placement**: Should Configure always be the landing activity for a freshly imported map, or should the editor remember the last-visited activity on re-open?
2. **Symmetry suggestions — scope**: Are suggestions shown only during region placement, or also retroactively for existing regions that lack a counterpart?
3. **Concept-first entry point**: In the scratch workflow, does Configure still come first (to set scan layer / teams before drawing), or does drawing come first and Configure follows?
4. **Expert mode persistence**: Is the expert region tree toggle per-session or persisted to `map_config.json`?
