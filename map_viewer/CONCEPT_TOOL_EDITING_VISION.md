# Concept Tool — Editing Vision

## Core mental model

An **island** is a single connected polygon — a union of added shapes with holes carved by subtracted shapes. This matches the pipeline's definition of an island (a connected block mass). Islands are never manually created; they emerge automatically from the topology of what the user draws.

The editing surface has one flat pool of **primitive shapes** (rectangles, circles, polygons, lasso outlines). Each shape is tagged as either **add** or **subtract**. The system continuously recomputes a set of islands from those shapes using boolean operations:

```
island polygons = connected_components(union(all add shapes) − union(all subtract shapes))
```

If the result has two disconnected masses, those are two islands — automatically.

---

## Drawing workflow

Operations are **purely geometry-driven** — there is no notion of a "selected island" that an operation targets. A shape interacts with whatever it overlaps. This keeps the model simple and predictable.

### Add mode
- Draw a shape that overlaps **one** existing island → shape is unioned into that island.
- Draw a shape that overlaps **two or more** islands → all overlapping islands are **merged into one**.
- Draw a shape that overlaps **no** island → a new island is created; a warning toast is shown.

**Key use case:** two disconnected islands can be connected into one by drawing an add shape that bridges them. This is the primary way to merge islands.

### Subtract mode
- Draw a shape that overlaps **one** island → a hole is carved out of that island.
- Draw a shape that overlaps **two or more** islands → holes are carved out of **all** overlapping islands simultaneously.
- If subtraction splits an island into two disconnected masses → those become two separate islands automatically (split-off gets a new auto-name).
- A subtract shape that overlaps **no** island is rejected (red preview, not committed).
- Subtract wins over add when shapes occupy the same area.

### Feedback on completion
- While drawing, the tool shows only the **primitive outline being drawn** (rectangle drag preview, polygon vertex chain, lasso trace). No boolean computation happens during the drag.
- Once the shape is **completed** (mouseup for rect/circle, double-click or close for polygon, release for lasso), the boolean computation runs and the canvas immediately updates to show the new computed island polygon(s).
- Only the **computed polygon** is shown on the canvas by default. An optional **"Show primitives"** toggle (off by default) overlays the individual primitive shapes for inspection/debugging.

---

## Sidebar structure

### Left sidebar — island tree

The Islands header contains a **Primitives** toggle (off by default) that overlays the raw primitive shapes on the canvas for inspection. The tree below it is a **2-level hierarchy**:

```
Islands                          [☐ Primitives]
▼ Island 1          ← computed island, user-renameable
    ▷ Rectangle     ← add primitive
    ▷ Circle        ← subtract primitive (shown with red tint / minus badge)
▼ Island 2          ← auto-split from Island 1
    ▷ Polygon
```

- Islands are auto-named ("Island 1", "Island 2", …) and user-renameable.
- Clicking a primitive in the tree selects it and populates the right-panel inspector.
- Individual primitives can be **deleted** from the sidebar; the island recomputes immediately.
- Rectangle and polygon shapes support direct canvas editing (resize handles, vertex drag).

### Right sidebar — shape inspector

Displays geometry and metadata for the selected primitive. See **Shape inspector** section below.

---

## Topology rules

| Situation | Result |
|---|---|
| New add shape overlaps one island | Shape joins that island; polygon updated |
| New add shape overlaps no island | New island created; warning toast shown |
| New add shape overlaps two or more islands | All overlapping islands merged into one |
| Subtract shape overlaps one island | Hole carved; if result splits → two islands, split-off gets new name |
| Subtract shape overlaps two or more islands | Holes carved in all overlapping islands |
| Subtract shape overlaps no island | Rejected (red preview, not committed) |
| Subtract shape removes all area of an island | Island deleted |

---

## Override mode

The default boolean order is subtract-wins-over-add. Both add and subtract shapes have an **Override** toggle (shield icon in the sidebar, hover to reveal) that shifts them to a later evaluation step:

```
1. union(normal adds)
2. − union(normal subtracts)
3. ∪ union(override adds)
4. − union(override subtracts)
```

**Override add** shapes are immune to normal subtract shapes — they are unioned in after step 2. Use this for a bridge or fill that must exist regardless of surrounding cuts.

**Override subtract** shapes cut last — they carve through everything, including override add shapes. Use this when a cut must win unconditionally.

Both toggles are escape hatches from the default ordering; use them only when the geometry genuinely requires it. The shield icon shows in teal when active on an add shape, red on a subtract shape.

---

## Shape-to-island assignment

After each boolean recompute, every primitive shape is assigned to one or more islands for display in the sidebar. Assignment is **intersection-based**.

1. Each final island is mapped back to the add-union component it came from (the union of all add shapes, which may consist of multiple disconnected components before subtraction).

2. **Add shapes** are assigned by intersecting the shape's polygon against each add-union component. A shape belongs to the component it geometrically overlaps (always exactly one). If a subtract subsequently split that component into multiple final islands, a secondary intersection check against each sub-island resolves which one(s) the add shape contributes to.

3. **Subtract shapes** are assigned by intersecting the shape's polygon against all add-union components. A subtract shape appears under every island whose source component it touches — so a subtract spanning two disconnected islands correctly shows up in both island groups in the sidebar.

---

## Symmetry

### Motivation

CTW maps are always symmetric to some degree — teams must face equivalent challenges. The concept tool lets the author design one sector and have the rest of the map follow automatically, with the ability to break symmetry deliberately on specific axes when variation is wanted.

### Axis origin

All symmetry operations pivot around the **center point** defined in the Overview panel (Map Space → Center). This is the same center the pipeline uses when detecting symmetry on real maps.

### Two tiers of symmetry

Symmetry is organised in two tiers that compose on top of each other:

**Tier 1 — Main symmetry axis (required)**

The main axis defines the inter-team relationship and must be set before authoring begins. It determines how many team sectors exist and how they relate:

| Setting | Use case |
|---|---|
| Mirror X | 2-team map mirrored across Z = center_z |
| Mirror Z | 2-team map mirrored across X = center_x |
| Rotate 180° | 2-team map with 180° rotational symmetry around the center |
| Rotate 90° | 4-team map — only valid option for four teams |

This matches the `global_symmetry` value the pipeline detects on real maps.

**Tier 2 — Intra-team axes (optional, independently toggleable)**

These axes operate *within* the authored sector to produce symmetry inside a single team's portion of the map. The pipeline calls this intra-team symmetry. Available options are mirror X (within the sector) and mirror Z (within the sector) — the same four axis-aligned types, but scoped to one team's half rather than the full map.

Because intra-team axes are secondary to the main axis, the composed result is: shapes authored in the primary sector → apply intra-team axis → replicate the whole result via the main axis. Both team sides always see the same intra-team structure.

### Custom symmetry axis *(later stage)*

In addition to the axis-aligned options, the user can define an arbitrary line by placing two points on the canvas. That line acts as a mirror axis and can be toggled on or off independently. A custom axis is also a tier-2 (intra-team) axis: once enabled, it is replicated across the main symmetry axis to all other team sectors automatically. Multiple custom axes can coexist, each toggled separately.

This feature is intentionally deferred — it requires more UI surface (point placement, axis management) and is only needed for creative layouts that don't fit the standard axis-aligned options. Document it here so the architecture accounts for it.

### Live preview, not stored copies

When any symmetry axis is active, the canvas shows mirrored/rotated copies as a **live overlay** computed in real time from the authored shapes. These copies are not stored as primitives and do not appear in the shape list. Only the shapes the user actually drew are primary. This keeps the authoring surface unambiguous and the shape list readable.

### Per-axis toggle and deliberate asymmetry

Every axis — main and intra-team — can be toggled on and off at any point. This is the core authoring affordance: start with all required symmetry active to establish the base layout, then disable specific axes to introduce controlled variation.

**Example:** A team's two lanes should be symmetric (intra-team mirror Z active), but one lane should curve slightly more. The author designs the base layout with mirror Z on, then disables it and adjusts one lane's primitives. The other lane keeps its shape from when the axis was active. The result is mostly symmetric but with deliberate variation on one side. The main axis is still active throughout, so the opposing team sector always mirrors the result.

This maps directly onto what the pipeline detects: global symmetry present, intra-team symmetry partially broken.

---

## Shape inspector (right panel)

The right panel is visible in Layout activity only. It shows detail for the currently selected primitive shape. When no shape is selected it displays a prompt to select one.

### Header
Type icon + shape ID + type badge (Rectangle / Circle / Polygon).

### Operation section
Displays the shape's current add/subtract mode as a coloured badge.

### Geometry section
Per-type coordinate display:

| Type | Fields shown |
|---|---|
| Rectangle | Bounds table: X and Z each with MIN / MAX / SIZE |
| Circle | CENTER (X, Z) and RADIUS (blocks) |
| Polygon | Scrollable vertex table: index, X, Z — one row per vertex |

The inspector updates live as the user resizes a rectangle or drags a polygon vertex on the canvas.

### Simplify section (lasso shapes only)

Lasso-drawn shapes are tagged `source: "lasso"` and expose an additional section:

- **Area** — total polygon area in blocks² (shoelace formula), read-only.
- **Tolerance** — minimum effective triangle area in blocks². Any vertex whose triangle (formed with its two neighbours) has area below this threshold is a candidate for removal.
- **Generalize button** — runs Visvalingam–Whyatt simplification and immediately updates the shape on the canvas and in the island computation.

**How VW works:** the algorithm iteratively removes the vertex with the smallest triangle area (prev → vertex → next), recomputes its neighbours' areas after each removal, and stops when no vertex's area falls below the tolerance or when only 3 vertices remain. A tolerance of 50 blocks² is the default; raise it to remove more vertices, lower it to preserve more detail. Repeated presses reduce the shape further; the tolerance field persists across presses.

---

## Shape-specific notes

- **Circle primitives**: The drawn circle outline snaps to block boundaries (integer coordinates). Stored as a polygon approximation at block resolution.
- **Lasso shapes**: May produce non-simple polygons; the boolean library must handle self-intersecting inputs gracefully (auto-simplify or reject). Lasso shapes carry a `source: "lasso"` tag enabling the Simplify section in the inspector.

---

## What this replaces

The current model has:
- A flat shape list with per-shape island dropdowns
- Manually created islands via "+ Island" button
- A separate "Compute" step to see results
- No live feedback
- Implicit selection-based targeting for add/subtract

All of these are removed. The new model is geometry-driven, fully automatic, and always live.

---

## Out of scope (this version)

- Undo/redo
