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
 */

import { MapCanvas }      from "./map-canvas.js";
import { RegionSidebar }  from "./region-sidebar.js";
import { RegionRegistry } from "./region-registry.js";
import { RegionDetail }   from "./region-detail.js";
import * as api           from "./api.js";

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

const registry = new RegionRegistry({
  onSelectionChange: (primaryNode, selectedIds) => {
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

const coordsEl  = document.getElementById("cursor-coords");
const toolRectBtn = document.getElementById("tool-rect");

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
      } catch (err) {
        setStatus(`Create region failed: ${err.message}`);
      }
    },
    onBoundsChange: (node, bounds) => handleBoundsChange(node, bounds),
    onBoundsSave:   (node, bounds) => handleBoundsSave(node, bounds),
  },
);

let currentMap = null;

const detail = new RegionDetail(
  document.getElementById("region-detail"),
  {
    onBoundsChange: (node, bounds) => handleBoundsChange(node, bounds),
    onBoundsSave:   (node, bounds) => handleBoundsSave(node, bounds),
    onIdChange: (node, oldId, newId) => {
      registry.renameNode(oldId, newId);
      sidebar.renameNode(oldId, newId);
      canvas.renameNode(oldId, newId);
      canvas.showAnchors(node);  // refresh overlay label
      if (!currentMap) return;
      api.renameRegion(currentMap, oldId, newId).catch((err) => {
        console.error("Region rename failed:", err);
      });
    },
  },
);

const sidebar = new RegionSidebar(
  document.getElementById("region-list"),
  { onSelect: (node) => registry.select(node.id) },
);

// ── draw toolbar ──────────────────────────────────────────────────────────

toolRectBtn.addEventListener("click", () => {
  const isNowActive = toolRectBtn.classList.toggle("draw-tool-btn--active");
  canvas.setActiveTool(isNowActive ? "rectangle" : null);
});

document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
  if ((e.key === "r" || e.key === "R") && currentMap) {
    const isNowActive = toolRectBtn.classList.toggle("draw-tool-btn--active");
    canvas.setActiveTool(isNowActive ? "rectangle" : null);
  }
  if (e.key === "Escape") {
    canvas.setActiveTool(null);
    toolRectBtn.classList.remove("draw-tool-btn--active");
  }
});

// ── POI layer toggles ─────────────────────────────────────────────────────

document.getElementById("toggle-spawns").addEventListener("change", (e) => canvas.setSpawnsVisible(e.target.checked));
document.getElementById("toggle-wools").addEventListener("change",  (e) => canvas.setWoolsVisible(e.target.checked));

// ── map selection ──────────────────────────────────────────────────────────

async function loadMap(name) {
  currentMap = name;
  canvas.setActiveTool(null);
  toolRectBtn.classList.remove("draw-tool-btn--active");
  exportBtn.disabled = true;
  setStatus("Loading…");
  try {
    const [ctx, groups] = await Promise.all([
      api.fetchContext(name),
      api.fetchRegions(name),
    ]);
    registry.clear();
    canvas.render(ctx, groups);
    sidebar.build(groups);
    detail.clear();
    canvas.clearAnchors();
    // Register all nodes so registry can resolve ids to node objects
    for (const group of groups) {
      for (const root of group.regions) registry.register(root, null);
    }
    exportBtn.disabled  = false;
    toolRectBtn.disabled = false;
    setStatus(
      `${ctx.map_name} v${ctx.map_version || "?"} · ` +
      `${ctx.island_count} island(s) · ${countRegions(groups)} region(s)`,
    );
  } catch (err) {
    setStatus(`Error: ${err.message}`);
  }
}

async function initMapList() {
  const maps = await api.fetchMaps();
  const sel = document.getElementById("map-select");
  for (const m of maps) {
    const opt = document.createElement("option");
    opt.value = m.name;
    opt.textContent = m.display_name;
    sel.appendChild(opt);
  }
}

document.getElementById("map-select").addEventListener("change", (e) => {
  if (e.target.value) loadMap(e.target.value);
});

window.addEventListener("resize", () => canvas.resize());

// ── helpers ────────────────────────────────────────────────────────────────

function setStatus(msg) {
  document.getElementById("status").textContent = msg;
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
  api.patchRegion(currentMap, node.id, bounds).catch((err) => {
    console.error("Region save failed:", err);
  });
}

// ── start ──────────────────────────────────────────────────────────────────
initMapList();
