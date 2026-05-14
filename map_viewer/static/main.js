/**
 * Application bootstrap — wires components together.
 *
 * This is the only file that knows about all three components.
 * Cross-component communication (e.g. canvas click → sidebar highlight) is
 * added here as callbacks, keeping each component ignorant of the others.
 */

import { MapCanvas }      from "./map-canvas.js";
import { RegionSidebar }  from "./region-sidebar.js";
import { RegionRegistry } from "./region-registry.js";
import { RegionDetail }   from "./region-detail.js";
import * as api           from "./api.js";

// ── component instances ────────────────────────────────────────────────────

const registry = new RegionRegistry({
  onVisibilityChange: (id, visible) => canvas.setRegionVisible(id, visible),
});

const coordsEl = document.getElementById("cursor-coords");

const canvas = new MapCanvas(
  document.getElementById("map-svg"),
  document.getElementById("canvas-wrap"),
  {
    onCoords: (x, z) => {
      coordsEl.textContent = x !== null ? `X ${x}  Z ${z}` : "";
    },
  },
);

const detail = new RegionDetail(document.getElementById("region-detail"));

const sidebar = new RegionSidebar(
  document.getElementById("region-list"),
  registry,
  { onSelect: (node) => { detail.show(node); canvas.showAnchors(node); } },
);

// ── toggle-all wiring ──────────────────────────────────────────────────────

const toggleAllEl = document.getElementById("toggle-all");
registry.setToggleAllEl(toggleAllEl);
toggleAllEl.addEventListener("change", (e) => registry.setAllVisible(e.target.checked));

// ── POI layer toggles ─────────────────────────────────────────────────────

document.getElementById("toggle-spawns").addEventListener("change", (e) => canvas.setSpawnsVisible(e.target.checked));
document.getElementById("toggle-wools").addEventListener("change",  (e) => canvas.setWoolsVisible(e.target.checked));

// ── map selection ──────────────────────────────────────────────────────────

async function loadMap(name) {
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
