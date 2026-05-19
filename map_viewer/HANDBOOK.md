# CTW Map Viewer — User Manual

A browser-based tool for inspecting and editing the region data attached to CTW maps. Open it, pick a map, run the pipeline if needed, and start exploring or editing regions directly in the browser.

---

## Starting the viewer

```
python ctw.py viewer
```

Then open `http://localhost:7891` in a browser. To start without automatically opening a tab:

```
python -m map_viewer.app --no-browser
```

To stop the server, find the process ID listening on port 7891 and kill it:

```powershell
Get-NetTCPConnection -LocalPort 7891 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

---

## The Dashboard

The first page you see is the dashboard. It has two jobs: pointing the viewer at your map folders, and preparing a map for editing.

### Configure your folders

At the top of the page, set:

- **Maps folder** — the directory that contains your map subfolders (each with a `map.xml`).
- **Output folder** — where the pipeline writes its output files.

Click **Save Configuration**. The map list will populate on the left.

### Pick a map

Click any map in the list to see its status on the right. A green dot means all pipeline steps have completed and the map is ready to open.

### Run the pipeline

Before a map can be opened in the editor, it must be processed. Select the map and click **Run**. A console at the bottom of the page streams progress. When all steps show a checkmark, the **Open in Editor** button appears.

If the map has already been processed and you want to reprocess it (e.g. after changes to the source XML), click **Regenerate**.

---

## The Editor

Clicking **Open in Editor** takes you to the main editing view.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Top bar: ← Dashboard · map name · version · Export XML                     │
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

## Navigating the canvas

| Action | How |
|--------|-----|
| Pan | Hold the **Move tool** and left-drag, or drag with the middle mouse button anywhere |
| Zoom | Scroll wheel |
| Reset view | Reload the map from the top bar |

---

## Tools

Three tools live in the floating toolbar at the bottom-centre of the canvas.

| Tool | Shortcut | Purpose |
|------|----------|---------|
| Move | **M** | Pan the canvas by dragging |
| Select | **S** | Click regions to select them |
| Rectangle | **R** | Draw a new rectangle region |

- Pressing **R** while the rectangle tool is already active switches back to Move.
- **Esc** always returns to Move and clears any pending multi-selection.

---

## Selecting regions

Regions can be selected from the canvas or from the sidebar tree.

- **Canvas click** (Select tool active) — picks the smallest region under the cursor.
- **Sidebar click** — selects that region directly.
- **Click empty canvas** — deselects everything.

The selected region is highlighted in the sidebar (blue row) and on the canvas (solid outline with resize handles).

---

## Editing regions

### Rename

Click the region ID field at the top of the inspector, type the new name, then press **Enter** to save or **Esc** to revert.

### Edit bounds

The bounds table in the inspector shows **X** and **Z** min/max values. Click any value to edit it:

- Press **Enter** or click away to save.
- Press **Esc** to revert to the last saved value.
- Drag the **resize handles** on the canvas to adjust bounds visually. The inspector updates live and the change is saved when you release.

Ancestor bounds (union containers) are recomputed automatically when a child is edited.

### Delete

Select a region, then press **Del** or **Backspace**.

- Composite regions (union, intersect, negative) are deleted together with **all their descendants**.
- Deletion can be undone with **Ctrl+Z** and redone with **Ctrl+Y** (up to 20 deletions per map session).
- The undo/redo history is shown in the **History** panel at the bottom of the inspector. Entries above the divider can be undone; entries below it can be redone.
- Any non-delete mutation (rename, bounds edit, create, group) clears the redo stack.

---

## Drawing new regions

1. Switch to the **Rectangle** tool (**R**).
2. Click and drag on the canvas to define the region — a preview outline follows the cursor.
3. Release to create. The tool returns to Select automatically, and the new region appears in the sidebar and inspector.

New regions are placed in the `other` category with an auto-generated ID (`region_1`, `region_2`, …). Rename them in the inspector afterwards.

---

## Grouping regions

Ctrl-click two or more sidebar rows (they turn green), then press **Ctrl+G**.

- A `union_N` region is created containing the selected regions as children.
- The sidebar rebuilds and the new union is selected automatically.

Tip: click one region normally to select it, then Ctrl-click one more — that's the minimum needed to trigger grouping.

---

## Layers

The **Layers** panel floats in the top-right corner of the canvas.

| Layer | What it shows | Default |
|-------|---------------|---------|
| **Blocks** | Top-surface block colours (one pixel per block). Island fills are hidden when this layer is on so colours are unobstructed; outlines remain. Data is fetched once per map and cached for the session. | Off |
| **POIs** | Spawn locations (★, team-coloured) and wool spawn points (◆, wool-coloured). | Off |
| **Build** | Build-allowed area (green overlay) derived from the map's void/complement rules. | Off |

Individual regions also have a visibility toggle — hover over a sidebar row to reveal the eye icon. Hiding a region hides its entire subtree on the canvas.

---

## Inspector panel

When a region is selected, the right panel shows:

| Section | Content |
|---------|---------|
| **Header** | Coloured dot · editable ID · type badge |
| **Bounds** | Editable min/max X and Z with size column |
| **Children** | List of direct children (for union, intersect, negative regions) |
| **XML** | Live XML preview that updates as bounds or ID change |

---

## Exporting

Click **Export XML** in the top bar to download the full region tree as an XML file (`<mapname>_regions.xml`). The export reflects all edits made in the current session.

---

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| M | Move tool |
| S | Select tool |
| R | Rectangle tool (press again to return to Move) |
| Esc | Move tool + cancel pending multi-select |
| Del / Backspace | Delete selected region and all descendants |
| Ctrl+Z | Undo last deletion |
| Ctrl+Y | Redo last undone deletion |
| Ctrl+click (sidebar) | Add/remove from pending group |
| Ctrl+G | Create union from pending group |

---

## Technical notes

### Where edits are saved

All edits — create, delete, rename, bounds change, group — write directly to:

```
output/<map-name>/map_data.json
```

The file is read fresh on every map load. Changes made externally (e.g. by re-running `ctw run`) are picked up automatically on the next map selection.

### Block layer data

Block colours are read from:

```
output/<map-name>/layout_top_surface.parquet
```

This file is read-only from the viewer's perspective.

### Pipeline output files

The dashboard pipeline produces these files in `output/<map-name>/`:

| Step | Output file |
|------|-------------|
| Layout | `layout_bedrock.parquet` |
| Islands | `islands.json` |
| Symmetry | `symmetry.json` |
| XML | `map_data.json` |
| Assembly | `map_context.json` |
