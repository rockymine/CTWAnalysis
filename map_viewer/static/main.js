/**
 * Application bootstrap — wires components together.
 *
 * Cross-component communication flows through here as callbacks so each
 * component stays ignorant of the others.
 *
 * Selection model:
 *   - Clicking a layer row or canvas region → registry.select(id)
 *   - Registry fires onSelectionChange(primaryNode, selectedIds)
 *   - Canvas shows overlays for all selectedIds; inspector shows primaryNode
 *   - Clicking empty canvas → registry.deselect() → clears everything
 *
 * Map loading:
 *   - Map name is read from the ?map=<name> URL query parameter on load.
 *   - If not present, redirects back to the dashboard (/).
 */

import { MapCanvas }      from "./map-canvas.js";
import { RegionSidebar }  from "./region-sidebar.js";
import { RegionRegistry } from "./region-registry.js";
import { RegionDetail }          from "./region-detail.js";
import { deriveBoundsFromCoords } from "./region-types.js";
import * as api                   from "./api.js";
import { DeletedRegionHistory }   from "./deleted-region-history.js";
import { OverviewActivity }       from "./overview-activity.js";
import { RegionsActivity }        from "./regions-activity.js";

lucide.createIcons({ attrs: { "stroke-width": "1.5", width: "15", height: "15" } });

// ── Activity switching ─────────────────────────────────────────────────────

const activityBtns = document.querySelectorAll(".activity-btn");
const overviewBtn  = document.getElementById("activity-overview");
const regionsBtn   = document.getElementById("activity-regions");

const ACTIVITIES = {
  "activity-overview": new OverviewActivity(),
  "activity-regions":  new RegionsActivity(),
};

let currentActivityId = "activity-regions";

function switchActivity(id) {
  ACTIVITIES[currentActivityId].deactivate();
  currentActivityId = id;
  activityBtns.forEach(btn => btn.classList.toggle("active", btn.id === id));
  ACTIVITIES[id].activate({ mapName: currentMap });
}

overviewBtn.addEventListener("click", () => { if (!overviewBtn.disabled) switchActivity("activity-overview"); });
regionsBtn.addEventListener("click",  () => switchActivity("activity-regions"));

const exportBtn = document.getElementById("export-xml-btn");
exportBtn.addEventListener("click", async () => {
  if (!currentMap) return;
  try {
    const xml  = await api.fetchRegionsXml(currentMap);
    const blob = new Blob([xml], { type: "application/xml" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = `${currentMap}_regions.xml`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    setStatus(`Export failed: ${err.message}`);
  }
});

// ── component instances ────────────────────────────────────────────────────

let selectedNode    = null;
const multiSelected = new Set();  // ids currently Ctrl-clicked for grouping

const registry = new RegionRegistry({
  onSelectionChange: (primaryNode, selectedIds) => {
    selectedNode = primaryNode;
    canvas.setSelectedRegions(selectedIds);
    sidebar.setSelected(primaryNode?.id ?? null, selectedIds);
    if (primaryNode) {
      detail.show(primaryNode);
      canvas.showAnchors(primaryNode);
    } else {
      detail.clear();
      canvas.clearAnchors();
    }
  },
});

const coordsEl      = document.getElementById("cursor-coords");
const toolMoveBtn   = document.getElementById("tool-move");
const toolSelectBtn = document.getElementById("tool-select");
const toolRectBtn   = document.getElementById("tool-rect");

const canvas = new MapCanvas(
  document.getElementById("map-svg"),
  document.getElementById("canvas-wrap"),
  {
    onCoords: (x, z) => {
      coordsEl.textContent = x !== null ? `X ${x}  Z ${z}` : "";
    },
    onCanvasClick: (node) => {
      if (node) registry.select(node.id);
      else registry.deselect();
    },
    onRegionDraw: async (bounds) => {
      if (!currentMap) return;
      setTool(null);  // switch to select immediately — don't wait for the API response
      try {
        const { id: newId } = await api.createRegion(currentMap, bounds);
        const newNode = {
          id: newId, type: "rectangle", label: newId,
          color: "#64748b",
          bounds: { ...bounds },
          coords: { min_x: bounds.min_x, min_z: bounds.min_z,
                    max_x: bounds.max_x, max_z: bounds.max_z },
          is_negative: false, synthetic_id: false, children: [],
        };
        registry.register(newNode, null);
        canvas.addRegion(newNode);
        sidebar.appendRow(newNode);
        registry.select(newId);
        deleteHistory.clearRedo();
      } catch (err) {
        setStatus(`Create region failed: ${err.message}`);
      }
    },
    onBoundsChange: (node, bounds) => handleBoundsChange(node, bounds),
    onBoundsSave:   (node, bounds) => handleBoundsSave(node, bounds),
  },
);

let currentMap = null;
const deleteHistory = new DeletedRegionHistory({ onChange: renderHistory });

const detail = new RegionDetail(
  document.getElementById("region-detail"),
  {
    onBoundsChange:  (node, bounds) => handleBoundsChange(node, bounds),
    onBoundsSave:    (node, bounds) => handleBoundsSave(node, bounds),
    onCoordsChange:  (node, coords) => handleCoordsChange(node, coords),
    onCoordsSave:    (node, coords) => handleCoordsSave(node, coords),
    onIdChange: (node, oldId, newId) => {
      registry.renameNode(oldId, newId);
      sidebar.renameNode(oldId, newId);
      canvas.renameNode(oldId, newId);
      canvas.showAnchors(node);  // refresh overlay label
      if (!currentMap) return;
      api.renameRegion(currentMap, oldId, newId)
        .then(() => deleteHistory.clearRedo())
        .catch((err) => { console.error("Region rename failed:", err); });
    },
  },
);

const sidebar = new RegionSidebar(
  document.getElementById("region-list"),
  {
    onSelect: (node, isCtrl) => {
      if (isCtrl) {
        // Seed the multi-set with the current single selection if this is the first Ctrl+click
        if (multiSelected.size === 0 && selectedNode && selectedNode.id !== node.id) {
          multiSelected.add(selectedNode.id);
        }
        if (multiSelected.has(node.id)) multiSelected.delete(node.id);
        else                            multiSelected.add(node.id);
        sidebar.setMultiSelected([...multiSelected]);
      } else {
        multiSelected.clear();
        sidebar.setMultiSelected([]);
        registry.select(node.id);
      }
    },
    onVisibilityToggle: (id, hidden) => {
      // Propagate to the full subtree (hiding a union hides all its children)
      const affectedIds = collectSubtreeIds(registry.getNode(id));
      for (const affectedId of affectedIds) {
        canvas.setRegionVisible(affectedId, !hidden);
        sidebar.setHidden(affectedId, hidden);
      }
      // If the currently selected region is being hidden, deselect it so
      // the canvas doesn't keep it visible due to its selected state.
      if (hidden && selectedNode && affectedIds.includes(selectedNode.id)) {
        registry.deselect();
      }
    },
  },
);

// ── draw toolbar ──────────────────────────────────────────────────────────

function setTool(tool) {
  canvas.setActiveTool(tool);
  toolMoveBtn.classList.toggle("draw-tool-btn--active",   tool === "move");
  toolSelectBtn.classList.toggle("draw-tool-btn--active", tool === null);
  toolRectBtn.classList.toggle("draw-tool-btn--active",   tool === "rectangle");
}

toolMoveBtn.addEventListener("click", () => setTool("move"));
toolSelectBtn.addEventListener("click", () => setTool(null));
toolRectBtn.addEventListener("click", () => {
  setTool(toolRectBtn.classList.contains("draw-tool-btn--active") ? "move" : "rectangle");
});

document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" ||
      e.target.tagName === "SELECT" || e.target.isContentEditable) return;
  if (e.ctrlKey && e.key === "z" && currentMap) {
    e.preventDefault();
    deleteHistory.undo(restoreDeletedRegion, err => setStatus(`Undo failed: ${err.message}`));
    return;
  }
  if (e.ctrlKey && e.key === "y" && currentMap) {
    e.preventDefault();
    deleteHistory.redo(redeleteRegion, err => setStatus(`Redo failed: ${err.message}`));
    return;
  }
  if ((e.key === "m" || e.key === "M") && currentMap) setTool("move");
  if ((e.key === "s" || e.key === "S") && currentMap) setTool(null);
  if ((e.key === "r" || e.key === "R") && currentMap) {
    setTool(toolRectBtn.classList.contains("draw-tool-btn--active") ? "move" : "rectangle");
  }
  if (e.key === "Escape") {
    setTool("move");
    multiSelected.clear();
    sidebar.setMultiSelected([]);
  }
  if ((e.key === "Delete" || e.key === "Backspace") && selectedNode) {
    e.preventDefault();
    deleteNode(selectedNode);
  }
  if ((e.key === "g" || e.key === "G") && e.ctrlKey && currentMap) {
    e.preventDefault();
    groupSelected();
  }
});

// ── layer toggles ─────────────────────────────────────────────────────────

document.getElementById("toggle-pois").addEventListener("change",  (e) => canvas.setPoisVisible(e.target.checked));
document.getElementById("toggle-build").addEventListener("change", (e) => canvas.setBuildVisible(e.target.checked));

const blockCache = new Map();  // mapName → top-surface data

document.getElementById("toggle-blocks").addEventListener("change", async (e) => {
  if (!e.target.checked) { canvas.setBlocksVisible(false); return; }
  if (!currentMap) { e.target.checked = false; return; }
  try {
    if (!blockCache.has(currentMap)) {
      setStatus("Loading block layer…");
      blockCache.set(currentMap, await api.fetchTopSurface(currentMap));
    }
    canvas.loadBlockLayer(blockCache.get(currentMap));
    canvas.setBlocksVisible(true);
    setStatus("");
  } catch (err) {
    setStatus(`Block layer failed: ${err.message}`);
    e.target.checked = false;
  }
});

// ── map loading ────────────────────────────────────────────────────────────

async function loadMap(name) {
  currentMap = name;
  setTool("move");
  exportBtn.disabled = true;
  setStatus("Loading…");
  try {
    const [ctx, groups] = await Promise.all([
      api.fetchContext(name),
      api.fetchRegions(name),
    ]);
    registry.clear();
    deleteHistory.clear();
    canvas.render(ctx, groups);
    sidebar.build(groups);
    detail.clear();
    canvas.clearAnchors();
    document.getElementById("toggle-blocks").checked = false;
    canvas.setBlocksVisible(false);
    // Register all nodes so registry can resolve ids to node objects
    for (const group of groups) {
      for (const root of group.regions) registry.register(root, null);
    }
    exportBtn.disabled     = false;
    overviewBtn.disabled   = false;
    toolMoveBtn.disabled   = false;
    toolSelectBtn.disabled = false;
    toolRectBtn.disabled   = false;
    setTool("move");
    setStatus(
      `${ctx.map_name} v${ctx.map_version || "?"} · ` +
      `${ctx.island_count} island(s) · ${countRegions(groups)} region(s)`,
    );
  } catch (err) {
    setStatus(`Error: ${err.message}`);
  }
}

window.addEventListener("resize", () => canvas.resize());

// ── helpers ────────────────────────────────────────────────────────────────

function setStatus(msg) {
  document.getElementById("status").textContent = msg;
}

function renderHistory() {
  const listEl = document.getElementById("history-list");
  if (!listEl) return;
  listEl.innerHTML = "";
  const { undoStack, redoStack } = deleteHistory.getState();

  if (undoStack.length === 0 && redoStack.length === 0) {
    const el = document.createElement("div");
    el.className = "history-entry history-entry--empty";
    el.textContent = "no history";
    listEl.appendChild(el);
    return;
  }

  for (let i = 0; i < undoStack.length; i++) {
    const el = document.createElement("div");
    el.className = "history-entry history-entry--undo";
    el.textContent = `Delete "${undoStack[i]}"`;
    listEl.appendChild(el);
  }

  if (redoStack.length > 0) {
    const sep = document.createElement("div");
    sep.className = "history-entry history-entry--divider";
    sep.textContent = "── now ──";
    listEl.appendChild(sep);
    for (let i = redoStack.length - 1; i >= 0; i--) {
      const el = document.createElement("div");
      el.className = "history-entry history-entry--redo";
      el.textContent = `Delete "${redoStack[i]}"`;
      listEl.appendChild(el);
    }
  }

  // Scroll to bottom so the most recent action is visible
  listEl.scrollTop = listEl.scrollHeight;
}

function deleteNode(node) {
  if (!node || node.synthetic_id || !currentMap) return;
  api.deleteRegion(currentMap, node.id)
    .then(({ snapshot }) => {
      for (const id of collectSubtreeIds(node)) {
        canvas.removeRegion(id);
        sidebar.removeRow(id);
      }
      registry.unregister(node.id);  // fires deselect → clears detail + anchors
      deleteHistory.pushDelete(snapshot);
    })
    .catch(err => setStatus(`Delete failed: ${err.message}`));
}

async function reloadRegions() {
  const groups = await api.fetchRegions(currentMap);
  registry.clear();
  canvas.refreshRegions(groups);
  sidebar.build(groups);
  detail.clear();
  canvas.clearAnchors();
  for (const group of groups) {
    for (const root of group.regions) registry.register(root, null);
  }
  return groups;
}

async function restoreDeletedRegion(snapshot) {
  await api.restoreRegion(currentMap, snapshot);
  await reloadRegions();
  registry.select(snapshot.root_id);
  setStatus(`Restored "${snapshot.root_id}".`);
}

async function redeleteRegion(snapshot) {
  await api.deleteRegion(currentMap, snapshot.root_id);
  await reloadRegions();
  setStatus(`Re-deleted "${snapshot.root_id}".`);
}

function collectSubtreeIds(node) {
  if (!node) return [];
  const ids = [node.id];
  for (const child of (node.children || [])) {
    if (child.id) ids.push(...collectSubtreeIds(child));
  }
  return ids;
}

function countRegions(groupsOrNodes) {
  let n = 0;
  for (const item of groupsOrNodes) {
    if (item.regions) { n += countRegions(item.regions); }
    else { if (item.id) n++; n += countRegions(item.children || []); }
  }
  return n;
}

// ── shared bounds handlers (used by detail panel and canvas resize) ───────

function handleBoundsChange(node, bounds) {
  canvas.updateRegionBounds(node, bounds);
  detail.updateXmlPreview(node);
  for (const ancestor of registry.recomputeAncestorBounds(node.id)) {
    canvas.updateRegionBounds(ancestor, ancestor.bounds);
  }
}

function handleBoundsSave(node, bounds) {
  if (!currentMap) return;
  api.patchRegion(currentMap, node.id, bounds)
    .then(() => deleteHistory.clearRedo())
    .catch((err) => { console.error("Region save failed:", err); });
}

function handleCoordsChange(node, coords) {
  const newBounds = deriveBoundsFromCoords(node.type, coords);
  if (newBounds) {
    node.bounds = newBounds;
    canvas.updateRegionBounds(node, newBounds);
    detail.updateXmlPreview(node);
    for (const ancestor of registry.recomputeAncestorBounds(node.id)) {
      canvas.updateRegionBounds(ancestor, ancestor.bounds);
    }
  }
}

function handleCoordsSave(node, coords) {
  if (!currentMap) return;
  api.updateRegionCoords(currentMap, node.id, coords)
    .then(res => {
      if (res.bounds) {
        node.bounds = res.bounds;
        canvas.updateRegionBounds(node, res.bounds);
      }
      deleteHistory.clearRedo();
    })
    .catch(err => console.error("Coord save failed:", err));
}

// ── region grouping ────────────────────────────────────────────────────────

async function groupSelected() {
  if (multiSelected.size < 2) {
    setStatus("Select 2+ regions with Ctrl+click, then press Ctrl+G to group.");
    return;
  }
  const childIds = [...multiSelected];
  multiSelected.clear();
  sidebar.setMultiSelected([]);
  try {
    const { id: newId } = await api.groupRegions(currentMap, childIds);
    await reloadRegions();
    registry.select(newId);
    setStatus(`Grouped ${childIds.length} regions into "${newId}".`);
  } catch (err) {
    setStatus(`Group failed: ${err.message}`);
  }
}

// ── start: read map from URL query param ──────────────────────────────────

const urlParams = new URLSearchParams(window.location.search);
const mapParam  = urlParams.get("map");

if (!mapParam) {
  window.location.replace("/");
} else {
  const display = document.getElementById("map-name-display");
  if (display) display.textContent = mapParam.replace(/_/g, " ");
  renderHistory();
  loadMap(mapParam);
}
