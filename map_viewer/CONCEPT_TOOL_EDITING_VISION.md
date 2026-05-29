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

The left sidebar is a **2-level tree**:

```
▼ Island 1          ← computed island, user-renameable
    ▷ Rectangle     ← add primitive
    ▷ Circle        ← subtract primitive (shown with red tint / minus badge)
▼ Island 2          ← auto-split from Island 1
    ▷ Polygon
```

- Islands are auto-named ("Island 1", "Island 2", …) and user-renameable.
- Clicking an island selects it and highlights its computed polygon on the canvas.
- Individual primitives can be **deleted** from the sidebar; the island recomputes immediately.
- Primitives are not directly re-editable (handles, vertex drag) in this version — delete and redraw if a primitive needs to change.

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

## Shape-specific notes

- **Circle primitives**: The drawn circle outline snaps to block boundaries (integer coordinates). Stored as a polygon approximation at block resolution.
- **Lasso shapes**: May produce non-simple polygons; the boolean library must handle self-intersecting inputs gracefully (auto-simplify or reject).

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
- Re-editing primitive geometry (handles, vertex drag) — deletion only
