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

const coordsEl = document.getElementById("cursor-coords");

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
  },
);

let currentMap = null;

const detail = new RegionDetail(
  document.getElementById("region-detail"),
  {
    onBoundsChange: (node, bounds) => {
      canvas.updateRegionBounds(node, bounds);
    },
    onBoundsSave: (node, bounds) => {
      if (!currentMap) return;
      api.patchRegion(currentMap, node.id, bounds).catch((err) => {
        console.error("Region save failed:", err);
      });
    },
  },
);

const sidebar = new RegionSidebar(
  document.getElementById("region-list"),
  { onSelect: (node) => registry.select(node.id) },
);

// ── POI layer toggles ─────────────────────────────────────────────────────

document.getElementById("toggle-spawns").addEventListener("change", (e) => canvas.setSpawnsVisible(e.target.checked));
document.getElementById("toggle-wools").addEventListener("change",  (e) => canvas.setWoolsVisible(e.target.checked));

// ── map selection ──────────────────────────────────────────────────────────

async function loadMap(name) {
  currentMap = name;
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

// ── start ──────────────────────────────────────────────────────────────────
initMapList();
