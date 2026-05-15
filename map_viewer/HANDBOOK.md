# CTW Map Viewer — Handbook

A browser-based tool for inspecting and editing the XML region data attached to CTW maps.
Runs locally via Flask; all changes are written back to the map's `map_data.json`.

---

## Getting started

1. Start the server: `python -m flask --app map_viewer.app run --port 7891`
2. Open `http://localhost:7891` in a browser.
3. Pick a map from the dropdown in the top bar.

The viewer loads the map's island polygons, categorised region tree, and optional overlay layers.

---

## Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Top bar: map selector · status · Export XML                                │
├────────────────┬─────────────────────────────────────┬──────────────────────┤
│  Regions       │                                     │  Inspector           │
│  (sidebar)     │           Canvas                    │  (detail panel)      │
│                │                          ┌────────┐ │                      │
│  Tree of all   │  Island polygons,        │ LAYERS │ │  Selected region     │
│  named regions │  blocks, POIs, etc.      │ Blocks │ │  ID · type · bounds  │
│                │                          │ POIs   │ │  XML preview         │
│                │   [↖] [↗] [□]           │ Build  │ │                      │
│                │   (draw toolbar)         └────────┘ │                      │
└────────────────┴─────────────────────────────────────┴──────────────────────┘
```

---

## Navigation

| Action | How |
|--------|-----|
| Pan | **Move tool** + left-drag, or middle-mouse-button drag anywhere |
| Zoom | Scroll wheel |
| Reset view | Reload the map from the dropdown |

---

## Tools

Three tools live in the floating toolbar at the bottom-centre of the canvas.

| Tool | Shortcut | Icon | Purpose |
|------|----------|------|---------|
| Move | **M** | Hand | Pan the canvas by dragging |
| Select | **S** | Pointer | Click regions to select them |
| Rectangle | **R** | Square | Draw a new rectangle region |

- Pressing **R** while the rectangle tool is already active switches back to Move.
- **Esc** always returns to Move and clears any pending multi-selection.

---

## Selecting regions

Regions can be selected from the canvas or from the sidebar tree.

- **Canvas click** (Select tool active) — picks the smallest region under the cursor.
- **Sidebar click** — selects that region directly.
- **Click empty canvas** — deselects everything.

The selected region is highlighted in the sidebar (blue row) and on the canvas (solid blue outline with resize handles).

### Multi-select (for grouping)

Hold **Ctrl** and click rows in the sidebar to build a pending group (rows turn green).

- Ctrl-clicking a row that is already the *single* selected region automatically seeds the group with that region first.
- Ctrl-clicking a green row a second time removes it from the pending group.
- **Esc** cancels the pending group without making changes.

---

## Editing regions

### Rename

Click the region ID field at the top of the inspector, type the new name, then press **Enter** to save or **Esc** to revert. The rename is persisted immediately.

### Edit bounds

The bounds table in the inspector shows **X** and **Z** min/max values with a **Size** column. Each value is an editable input:

- Press **Enter** or click away to save (persists to disk).
- Press **Esc** to revert to the last saved value.
- Drag the **resize handles** on the canvas to adjust bounds visually; the inspector updates live. Release the handle to persist.

Ancestor bounds (union containers) are recomputed automatically when a child is edited.

### Delete

Select a region (canvas or sidebar), then press **Del** or **Backspace**.

- Composite regions (union, intersect, negative) are deleted together with **all descendants**.
- Deletion is immediate and persists to disk. There is no undo.

---

## Drawing new regions

1. Switch to the **Rectangle** tool (R).
2. Click and drag on the canvas to define the region; a preview outline follows the cursor.
3. Release to create — the tool automatically returns to Select, the new region appears in the sidebar and inspector.

Newly created regions are placed in the `other` category with an auto-generated ID (`region_1`, `region_2`, …). Rename them in the inspector afterwards.

---

## Grouping regions

Ctrl-click two or more sidebar rows (they turn green), then press **Ctrl+G**.

- A `union_N` region is created that contains the selected regions as children.
- The sidebar rebuilds and the new union is auto-selected.
- The union's bounding box is computed from its children.

Tip: select one region normally (single click), then Ctrl-click one more — that's enough to trigger grouping.

---

## Visibility toggles

The **Layers** panel floats in the top-right corner of the canvas.

| Layer | What it shows | Default |
|-------|---------------|---------|
| **Blocks** | Top-surface block colours from `layout_top_surface.parquet`. Each block is one pixel, rendered as a pixelated image. Island polygon fills are hidden when this layer is active so block colours are unobstructed; outlines remain. Data is fetched once per map and cached for the session. | Off |
| **POIs** | Spawn locations (★, team-coloured) and wool spawn points (◆, wool-coloured). | Off |
| **Build** | Build-allowed region (green overlay) derived from the map's void/complement rules. | Off |

Individual sidebar rows also have an **eye icon** (visible on hover) to hide or show a single region and its entire subtree on the canvas.

---

## Inspector panel

When a region is selected the right panel shows:

| Section | Content |
|---------|---------|
| **Header** | Coloured dot · editable ID · type badge |
| **Bounds** | Editable min/max X and Z with size column |
| **Children** | List of direct children for composite regions (union, intersect, negative) |
| **XML** | Live XML preview that updates as bounds or ID change |

---

## Exporting

Click **Export XML** in the top bar to download the full region tree as an XML file (`<mapname>_regions.xml`). The XML reflects the current state of `map_data.json` including any edits made in this session.

---

## Keyboard shortcuts summary

| Key | Action |
|-----|--------|
| M | Move tool |
| S | Select tool |
| R | Rectangle tool (toggle; R again → Move) |
| Esc | Move tool + cancel pending multi-select |
| Del / Backspace | Delete selected region (and all descendants) |
| Ctrl+click (sidebar) | Add/remove region from pending group |
| Ctrl+G | Create union from pending group |

---

## Data persistence

All edits (create, delete, rename, bounds change, group) write directly to:

```
output/<map-name>/map_data.json
```

The file is read on every page load, so changes made externally (e.g. by re-running `ctw run`) are picked up on the next map selection. There is no in-memory cache between sessions.

Block-layer data is read from:

```
output/<map-name>/layout_top_surface.parquet
```

This file is read-only from the viewer's perspective.
