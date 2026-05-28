/**
 * Configure page — layer selection, block exclusions, island review, save.
 *
 * Data flow:
 *   init → loadExistingConfig + loadLayerPreviews + loadIslandData (parallel)
 *          → checkAndShowContinue (if already configured + pipeline done)
 *   runLayerExtraction → SSE steps=layout_all → reload layer previews
 *   selectLayer → populate block dropdown → markDirty
 *   selectIsland → highlight SVG + list row + inspector
 *   saveConfig → PATCH /api/layout-config/<name>
 *             → runFullPipeline (SSE full pipeline, force=1)
 *             → loadIslandData (refresh from fresh map_context.json)
 *             → show Continue link
 */

import { blockDataToDataUrl } from "./shared/block-render.js";
import { boundsTable }        from "./shared/bounds-table.js";
import {
  fetchLayoutConfig,
  patchLayoutConfig,
  fetchLayoutLayers,
  fetchObserverIslandHint,
  fetchContext,
  fetchPipelineStatus,
} from "./api.js";

// ── Map name ──────────────────────────────────────────────────────────────

const MAP_NAME = new URLSearchParams(location.search).get("map") || "";

const topbarMapName = document.getElementById("topbar-map-name");
const topbarVersion = document.getElementById("topbar-version");
if (topbarMapName) topbarMapName.textContent = MAP_NAME.replace(/_/g, " ");
document.title = `Configure: ${MAP_NAME}`;

// ── State ──────────────────────────────────────────────────────────────────

const state = {
  selectedLayer:    null,  // "y0" | "bedrock" | "lowest_solid" | "top_surface"
  layerData:        {},    // layer → {unique_blocks, ...} from API
  excludeIds:       [],    // int block IDs excluded from extraction
  excludeIslands:   [],    // int island IDs excluded from analysis
  observerHintId:   null,  // island suggested as observer spawn
  selectedIslandId: null,  // currently selected island in the canvas
  activeTool:       "move",// "move" | "select"
  islandData:       [],    // all islands loaded from context
  viewBox:          null,  // {x, y, w, h} current SVG viewBox
  initialViewBox:   null,  // viewBox that fits all islands
  isRunning:        false,
  pipelineRunning:  false, // true while full pipeline SSE is in flight
  isDirty:          false, // true when config has changed since last save
  bboxIsAuto:       true,  // false once user has manually edited any bbox field
  boundsTable:      null,  // boundsTable instance (created after DOM is ready)
};

// ── DOM refs ───────────────────────────────────────────────────────────────

const runBtn                  = document.getElementById("run-extraction-btn");
const extractionStatus        = document.getElementById("extraction-status");
const extractionConsole       = document.getElementById("extraction-console");
const consoleOutput           = document.getElementById("console-output");
const consoleClearBtn         = document.getElementById("console-clear-btn");
const cfgWorkspaceLayers      = document.getElementById("cfg-layers-workspace");
const cfgWorkspaceExclusions  = document.getElementById("cfg-exclusions-workspace");
const cfgBtnLayers            = document.getElementById("cfg-btn-layers");
const cfgBtnExclusions        = document.getElementById("cfg-btn-exclusions");
const blockExcludeSelect      = document.getElementById("block-exclude-select");
const excludeList             = document.getElementById("exclude-list");
const islandUnavailable       = document.getElementById("island-unavailable");
const islandCanvasPlaceholder = document.getElementById("island-canvas-placeholder");
const islandList              = document.getElementById("island-list");
const cfgBboxSection          = document.getElementById("cfg-bbox-section");
const cfgBboxDivider          = document.getElementById("cfg-bbox-divider");
const saveBtn                 = document.getElementById("save-btn");
const saveStatus              = document.getElementById("save-status");
const dirtyBadge              = document.getElementById("dirty-badge");
const continueBtn             = document.getElementById("continue-btn");
const pipelineBar             = document.getElementById("cfg-pipeline-bar");
const pipelineStepList        = document.getElementById("cfg-pipeline-step-list");
const statusEl                = document.getElementById("status");
const cfgToolMove             = document.getElementById("cfg-tool-move");
const cfgToolSelect           = document.getElementById("cfg-tool-select");
const cfgCursorDisplay        = document.getElementById("cfg-cursor-display");
const cfgZoomDisplay          = document.getElementById("cfg-zoom-display");
const islandSvg               = document.getElementById("island-svg");
const islandMapG              = document.getElementById("island-map-g");
const cfgIslandInspector      = document.getElementById("cfg-island-inspector");

// ── Activity switching ─────────────────────────────────────────────────────

function showActivity(name) {
  const isLayers = name === "layers";
  cfgWorkspaceLayers.hidden     = !isLayers;
  cfgWorkspaceExclusions.hidden =  isLayers;
  cfgBtnLayers.classList.toggle("active",  isLayers);
  cfgBtnExclusions.classList.toggle("active", !isLayers);
}

cfgBtnLayers.addEventListener("click",     () => showActivity("layers"));
cfgBtnExclusions.addEventListener("click", () => showActivity("exclusions"));

// ── Layer panels ───────────────────────────────────────────────────────────

const LAYERS = ["y0", "bedrock", "lowest_solid", "top_surface"];

for (const layer of LAYERS) {
  const panel = document.getElementById(`panel-${layer}`);
  const radio = document.getElementById(`radio-${layer}`);
  if (!panel || !radio) continue;
  panel.addEventListener("click", () => { radio.checked = true; selectLayer(layer); });
  radio.addEventListener("change", () => { if (radio.checked) selectLayer(layer); });
}

function selectLayer(layer, silent = false) {
  state.selectedLayer = layer;
  for (const l of LAYERS) {
    const panel = document.getElementById(`panel-${l}`);
    if (panel) panel.classList.toggle("layer-panel--selected", l === layer);
  }
  populateBlockDropdown(layer);
  if (!silent) markDirty();
}

function populateBlockDropdown(layer) {
  const data = state.layerData[layer];
  blockExcludeSelect.innerHTML = "";
  if (!data || !data.unique_blocks || !data.unique_blocks.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = layer ? "No blocks found — run extraction first" : "Select layer to see blocks…";
    blockExcludeSelect.appendChild(opt);
    blockExcludeSelect.disabled = true;
    return;
  }
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Add block exclusion…";
  blockExcludeSelect.appendChild(placeholder);
  for (const block of data.unique_blocks) {
    if (state.excludeIds.includes(block.id)) continue;
    const opt = document.createElement("option");
    opt.value = block.id;
    opt.textContent = `${block.name}  (${block.id})`;
    blockExcludeSelect.appendChild(opt);
  }
  blockExcludeSelect.disabled = false;
}

// ── Layer preview rendering ────────────────────────────────────────────────

async function loadLayerPreviews() {
  try {
    const data = await fetchLayoutLayers(MAP_NAME);
    for (const layer of LAYERS) {
      const imgEl       = document.getElementById(`canvas-${layer}`);
      const placeholder = document.getElementById(`placeholder-${layer}`);
      if (!imgEl || !placeholder) continue;
      const layerData = data[layer];
      if (layerData) {
        state.layerData[layer] = layerData;
        imgEl.src          = blockDataToDataUrl(layerData);
        imgEl.hidden       = false;
        placeholder.hidden = true;
      } else {
        imgEl.hidden       = true;
        placeholder.hidden = false;
      }
    }
    if (state.selectedLayer) populateBlockDropdown(state.selectedLayer);
  } catch (err) {
    setStatus(`Layer preview error: ${err.message}`);
  }
}


// ── Layer extraction (SSE) ─────────────────────────────────────────────────

runBtn.addEventListener("click", () => runLayerExtraction(false));

function runLayerExtraction(force) {
  if (state.isRunning) return;
  state.isRunning = true;
  runBtn.disabled = true;
  extractionStatus.textContent = "";
  extractionConsole.hidden = false;
  consoleOutput.innerHTML  = "";
  appendConsole("Starting layer extraction…");

  const url = `/api/source-map/${enc(MAP_NAME)}/pipeline/run?steps=layout_all&force=${force ? 1 : 0}`;
  const es  = new EventSource(url);

  es.addEventListener("step", (e) => {
    const data = JSON.parse(e.data);
    if (data.status === "running") appendConsole(`  ${data.label}…`);
    else if (data.status === "done")  appendConsole(`  ✓ ${data.label}${data.detail ? ": " + data.detail : ""}`);
    else if (data.status === "error") appendConsole(`  ✗ ${data.label}: ${data.detail || "failed"}`, "error");
  });

  es.addEventListener("done", async () => {
    appendConsole("Layer extraction complete.", "success");
    es.close();
    state.isRunning = false;
    runBtn.disabled = false;
    extractionStatus.textContent = "";
    await loadLayerPreviews();
  });

  es.addEventListener("error", (e) => {
    if (e.data) {
      const data = JSON.parse(e.data);
      appendConsole(`Error: ${data.message}`, "error");
    }
    es.close();
    state.isRunning = false;
    runBtn.disabled = false;
  });

  es.addEventListener("log", (e) => {
    const data = JSON.parse(e.data);
    appendConsole(data.message, data.level === "warning" ? "warning" : "info");
  });

  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED && state.isRunning) {
      state.isRunning = false;
      runBtn.disabled = false;
    }
  };
}

function appendConsole(text, type = "info") {
  const line = document.createElement("div");
  line.className = `console-line console-line--${type}`;
  line.textContent = text;
  consoleOutput.appendChild(line);
  consoleOutput.scrollTop = consoleOutput.scrollHeight;
}

consoleClearBtn.addEventListener("click", () => { consoleOutput.innerHTML = ""; });

// ── Block exclusions ───────────────────────────────────────────────────────

blockExcludeSelect.addEventListener("change", () => {
  const val = blockExcludeSelect.value;
  if (!val) return;
  const id = parseInt(val, 10);
  if (!state.excludeIds.includes(id)) {
    state.excludeIds.push(id);
    renderExcludeList();
    populateBlockDropdown(state.selectedLayer);
    markDirty();
  }
  blockExcludeSelect.value = "";
});

function blockLabel(id) {
  const layerData = state.selectedLayer ? state.layerData[state.selectedLayer] : null;
  const block = layerData && layerData.unique_blocks && layerData.unique_blocks.find(b => b.id === id);
  return block ? `${block.name}  (${id})` : `Block ${id}`;
}

function blockSwatchColor(id) {
  const layerData = state.selectedLayer ? state.layerData[state.selectedLayer] : null;
  const block = layerData && layerData.unique_blocks && layerData.unique_blocks.find(b => b.id === id);
  return block ? block.color : "#808080";
}

function renderExcludeList() {
  excludeList.innerHTML = "";
  for (const id of state.excludeIds) {
    const row = document.createElement("div");
    row.className = "list-row list-row--compact";

    const swatch = document.createElement("span");
    swatch.className = "list-swatch";
    swatch.style.background = blockSwatchColor(id);

    const label = document.createElement("span");
    label.className = "list-label list-label--mono";
    label.textContent = blockLabel(id);

    const removeBtn = document.createElement("button");
    removeBtn.className = "btn-remove btn-remove--hover-only";
    removeBtn.textContent = "×";
    removeBtn.title = "Remove";
    removeBtn.addEventListener("click", () => {
      state.excludeIds = state.excludeIds.filter(x => x !== id);
      renderExcludeList();
      if (state.selectedLayer) populateBlockDropdown(state.selectedLayer);
      markDirty();
    });

    row.appendChild(swatch);
    row.appendChild(label);
    row.appendChild(removeBtn);
    excludeList.appendChild(row);
  }
}

// ── Island review — palette ────────────────────────────────────────────────

const ISLAND_PALETTE = [
  "#4f86c6", "#e07b39", "#5ca85c", "#b55ea0", "#c2a83e",
  "#5bc4c4", "#d65151", "#7c6fb0", "#7a8e3c", "#c46e8a",
];

// ── Island SVG map ─────────────────────────────────────────────────────────

function setViewBox(vb) {
  state.viewBox = vb;
  islandSvg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
  if (state.initialViewBox) {
    cfgZoomDisplay.textContent = `${Math.round(state.initialViewBox.w / vb.w * 100)}%`;
  }
}

function svgPoint(clientX, clientY) {
  const pt  = islandSvg.createSVGPoint();
  pt.x = clientX;
  pt.y = clientY;
  const p = pt.matrixTransform(islandSvg.getScreenCTM().inverse());
  return { x: p.x, z: p.y };
}

// Pan/zoom state
let isDragging = false;
let dragStart  = null;
let dragVBStart = null;
let dragScale  = null;  // { x, y } SVG units per screen pixel at drag start

islandSvg.addEventListener("wheel", (e) => {
  e.preventDefault();
  if (!state.viewBox) return;
  const factor   = e.deltaY < 0 ? 0.8 : 1.25;
  const { x, z } = svgPoint(e.clientX, e.clientY);
  const vb       = state.viewBox;
  setViewBox({
    x: x - (x - vb.x) * factor,
    y: z - (z - vb.y) * factor,
    w: vb.w * factor,
    h: vb.h * factor,
  });
}, { passive: false });

islandSvg.addEventListener("mousedown", (e) => {
  if (state.activeTool !== "move") return;
  isDragging  = true;
  dragStart   = { x: e.clientX, y: e.clientY };
  dragVBStart = { ...state.viewBox };
  const ctm   = islandSvg.getScreenCTM().inverse();
  dragScale   = { x: ctm.a, y: ctm.d };
  islandSvg.style.cursor = "grabbing";
  e.preventDefault();
});

window.addEventListener("mousemove", (e) => {
  if (!isDragging || !state.viewBox) return;
  setViewBox({
    ...dragVBStart,
    x: dragVBStart.x - (e.clientX - dragStart.x) * dragScale.x,
    y: dragVBStart.y - (e.clientY - dragStart.y) * dragScale.y,
  });
});

window.addEventListener("mouseup", () => {
  if (!isDragging) return;
  isDragging = false;
  if (state.activeTool === "move") islandSvg.style.cursor = "grab";
});

islandSvg.addEventListener("mousemove", (e) => {
  if (!state.viewBox) return;
  const { x, z } = svgPoint(e.clientX, e.clientY);
  cfgCursorDisplay.textContent = `${Math.round(x)}, ${Math.round(z)}`;
});

islandSvg.addEventListener("mouseleave", () => {
  cfgCursorDisplay.textContent = "";
});

// Click on SVG background → deselect
islandSvg.addEventListener("click", (e) => {
  if (state.activeTool !== "select") return;
  if (e.target === islandSvg || e.target === islandMapG) selectIsland(null);
});

// ── Tool switching ─────────────────────────────────────────────────────────

function setActiveTool(tool) {
  state.activeTool = tool;
  cfgToolMove.classList.toggle("draw-tool-btn--active",   tool === "move");
  cfgToolSelect.classList.toggle("draw-tool-btn--active", tool === "select");
  islandSvg.style.cursor = tool === "move" ? "grab" : "default";
}

cfgToolMove.addEventListener("click",   () => setActiveTool("move"));
cfgToolSelect.addEventListener("click", () => setActiveTool("select"));

// ── Island rendering ───────────────────────────────────────────────────────

function ensureHatchDefs() {
  if (islandSvg.querySelector("defs")) return;
  const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
  for (let i = 0; i < ISLAND_PALETTE.length; i++) {
    const pat = document.createElementNS("http://www.w3.org/2000/svg", "pattern");
    pat.setAttribute("id", `cfg-hatch-${i}`);
    pat.setAttribute("patternUnits", "userSpaceOnUse");
    pat.setAttribute("width", "8");
    pat.setAttribute("height", "8");
    pat.setAttribute("patternTransform", "rotate(45)");
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", "0"); line.setAttribute("y1", "0");
    line.setAttribute("x2", "0"); line.setAttribute("y2", "8");
    line.setAttribute("stroke", ISLAND_PALETTE[i]);
    line.setAttribute("stroke-width", "2");
    pat.appendChild(line);
    defs.appendChild(pat);
  }
  islandSvg.prepend(defs);
}

function renderIslandSVG(islands) {
  islandMapG.innerHTML = "";
  if (!islands.length) return;
  ensureHatchDefs();

  let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
  for (const island of islands) {
    const bb = island.bounding_box;
    if (!bb || bb.length < 4) continue;
    minX = Math.min(minX, bb[0]); maxX = Math.max(maxX, bb[1]);
    minZ = Math.min(minZ, bb[2]); maxZ = Math.max(maxZ, bb[3]);
  }
  if (!isFinite(minX)) return;

  const padX = Math.max((maxX - minX) * 0.05, 10);
  const padZ = Math.max((maxZ - minZ) * 0.05, 10);
  const vb = { x: minX - padX, y: minZ - padZ, w: (maxX - minX) + padX * 2, h: (maxZ - minZ) + padZ * 2 };
  state.initialViewBox = { ...vb };
  setViewBox(vb);

  for (let i = 0; i < islands.length; i++) {
    const island  = islands[i];
    const poly    = island.simplified_polygon;
    if (!poly || !poly.exterior || !poly.exterior.length) continue;

    const color    = ISLAND_PALETTE[i % ISLAND_PALETTE.length];
    const excluded = state.excludeIslands.includes(island.id);

    const d = poly.exterior.map((pt, j) => `${j === 0 ? "M" : "L"}${pt[0]},${pt[1]}`).join(" ") + " Z";

    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    const hatchId = `cfg-hatch-${i % ISLAND_PALETTE.length}`;
    path.setAttribute("fill",          excluded ? `url(#${hatchId})` : color);
    path.setAttribute("fill-opacity",  excluded ? "0.55" : "0.20");
    path.setAttribute("stroke",        color);
    path.setAttribute("stroke-width",  "1.5");
    path.setAttribute("stroke-opacity", "0.55");
    path.setAttribute("stroke-dasharray", "4,2");
    path.setAttribute("vector-effect", "non-scaling-stroke");
    path.dataset.islandId  = island.id;
    path.dataset.islandIdx = i;
    path.style.cursor = "pointer";

    path.addEventListener("click", (e) => {
      if (state.activeTool !== "select") return;
      e.stopPropagation();
      selectIsland(island.id);
    });

    islandMapG.appendChild(path);
  }
}

function updateIslandSVGState() {
  for (const path of islandMapG.querySelectorAll("path")) {
    const id       = parseInt(path.dataset.islandId);
    const idx      = parseInt(path.dataset.islandIdx);
    const color    = ISLAND_PALETTE[idx % ISLAND_PALETTE.length];
    const excluded = state.excludeIslands.includes(id);
    const selected = state.selectedIslandId === id;

    const hatchId = `cfg-hatch-${idx % ISLAND_PALETTE.length}`;
    path.setAttribute("fill",          excluded ? `url(#${hatchId})` : color);
    path.setAttribute("fill-opacity",  excluded ? "0.55" : (selected ? "0.22" : "0.20"));
    path.setAttribute("stroke",        color);
    path.setAttribute("stroke-width",  selected ? "2.5" : "1.5");
    path.setAttribute("stroke-opacity", selected ? "0.85" : "0.55");
    if (selected) {
      path.removeAttribute("stroke-dasharray");
    } else {
      path.setAttribute("stroke-dasharray", "4,2");
    }
  }
}

function renderIslandList(islands) {
  islandList.innerHTML = "";
  for (let i = 0; i < islands.length; i++) {
    const island   = islands[i];
    const color    = ISLAND_PALETTE[i % ISLAND_PALETTE.length];
    const isHint   = island.id === state.observerHintId;
    const excluded = state.excludeIslands.includes(island.id);

    const row = document.createElement("div");
    row.className = "list-row list-row--compact" + (island.id === state.selectedIslandId ? " list-row--selected" : "");
    row.dataset.islandId = island.id;
    row.addEventListener("click", () => selectIsland(island.id));

    const swatch = document.createElement("span");
    swatch.className = "list-swatch";
    swatch.style.background = color;
    if (excluded) swatch.style.opacity = "0.3";

    const label = document.createElement("span");
    label.className = "list-label";
    label.textContent = `Island ${island.id}`;

    row.appendChild(swatch);
    row.appendChild(label);

    const eyeBtn = document.createElement("button");
    eyeBtn.className = "vis-btn" + (excluded ? " vis-btn--hidden" : "");
    eyeBtn.title     = excluded ? "Excluded — click to include" : "Click to exclude";
    eyeBtn.innerHTML = `<i data-lucide="${excluded ? "eye-off" : "eye"}"></i>`;
    eyeBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleIslandExclude(island.id);
    });
    row.appendChild(eyeBtn);

    islandList.appendChild(row);
  }
  lucide.createIcons({ attrs: { "stroke-width": "1.5", width: "14", height: "14" } });
}

function toggleIslandExclude(id) {
  if (state.excludeIslands.includes(id)) {
    state.excludeIslands = state.excludeIslands.filter(x => x !== id);
  } else {
    state.excludeIslands.push(id);
  }
  if (state.bboxIsAuto) fillDefaultBbox();
  renderIslandList(state.islandData);
  updateIslandSVGState();
  markDirty();
}

// ── Island selection ───────────────────────────────────────────────────────

function selectIsland(id) {
  state.selectedIslandId = id;
  updateIslandSVGState();

  // Update list selection
  for (const row of islandList.querySelectorAll(".list-row")) {
    row.classList.toggle("list-row--selected", parseInt(row.dataset.islandId) === id);
  }

  // Update inspector
  const island = id !== null ? state.islandData.find(isl => isl.id === id) : null;
  renderInspector(island);
}

function renderInspector(island) {
  if (!island) {
    cfgIslandInspector.innerHTML = '<div class="panel-empty"><div class="panel-empty-msg">Select an island to inspect.</div></div>';
    return;
  }
  const isObserver = island.id === state.observerHintId;
  cfgIslandInspector.innerHTML = `
    <div class="cfg-inspector-body">
      <div class="field">
        <span class="field-label">Island ID</span>
        <span class="field-value">${island.id}${isObserver ? ' <span class="list-tag">observer</span>' : ''}</span>
      </div>
      <div class="field">
        <span class="field-label">Blocks</span>
        <span class="field-value">${island.area.toLocaleString()}</span>
      </div>
    </div>
  `;
}

// ── Bounds table (created once; inserted into #cfg-bbox-section on island load) ──

function ensureBoundsTable() {
  if (state.boundsTable) return;
  state.boundsTable = boundsTable(["X", "Z"], {
    onInput: () => { state.bboxIsAuto = false; markDirty(); },
  });
  cfgBboxSection.appendChild(state.boundsTable.el);
}

// ── Island data loading ────────────────────────────────────────────────────

function fillDefaultBbox() {
  if (!state.islandData.length || !state.boundsTable) return;
  let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
  for (const island of state.islandData) {
    if (state.excludeIslands.includes(island.id)) continue;
    const bb = island.bounding_box;
    if (!bb || bb.length < 4) continue;
    minX = Math.min(minX, bb[0]); maxX = Math.max(maxX, bb[1]);
    minZ = Math.min(minZ, bb[2]); maxZ = Math.max(maxZ, bb[3]);
  }
  if (!isFinite(minX)) return;
  state.boundsTable.setValues({ X: { min: minX, max: maxX }, Z: { min: minZ, max: maxZ } });
}

async function loadIslandData() {
  try {
    let context;
    try {
      context = await fetchContext(MAP_NAME);
    } catch (_) {
      islandUnavailable.hidden = false;
      islandList.hidden        = true;
      islandCanvasPlaceholder.hidden = false;
      cfgBboxSection.hidden = cfgBboxDivider.hidden = true;
      return;
    }
    if (topbarVersion && context.map_version) topbarVersion.textContent = `v${context.map_version}`;
    const islands = context.islands || [];

    if (!islands.length) {
      islandUnavailable.hidden = false;
      islandList.hidden        = true;
      islandCanvasPlaceholder.hidden = false;
      cfgBboxSection.hidden = cfgBboxDivider.hidden = true;
      return;
    }

    let observerHintId = null;
    try {
      const hintData = await fetchObserverIslandHint(MAP_NAME);
      observerHintId = hintData.island_id ?? null;
    } catch (_) {}
    state.observerHintId = observerHintId;

    ensureBoundsTable();
    state.islandData = islands;
    islandUnavailable.hidden = true;
    islandList.hidden        = false;
    islandCanvasPlaceholder.hidden = true;
    cfgBboxSection.hidden = cfgBboxDivider.hidden = false;

    if (state.bboxIsAuto) fillDefaultBbox();
    renderIslandSVG(islands);
    renderIslandList(islands);
  } catch (err) {
    setStatus(`Island load error: ${err.message}`);
  }
}

// ── Load existing config ───────────────────────────────────────────────────

async function loadExistingConfig() {
  try {
    const cfg = await fetchLayoutConfig(MAP_NAME);
    if (!cfg || cfg.skip) return;

    if (cfg.layer) {
      const radio = document.getElementById(`radio-${cfg.layer}`);
      if (radio) { radio.checked = true; selectLayer(cfg.layer, true); }
    }

    if (cfg.exclude && cfg.exclude.length) {
      state.excludeIds = [...cfg.exclude];
      renderExcludeList();
    }

    if (cfg.exclude_islands && cfg.exclude_islands.length) {
      state.excludeIslands = [...cfg.exclude_islands];
    }

    if (cfg.playable_bbox && cfg.playable_bbox.length === 4) {
      ensureBoundsTable();
      state.boundsTable.setValues({
        X: { min: cfg.playable_bbox[0], max: cfg.playable_bbox[2] },
        Z: { min: cfg.playable_bbox[1], max: cfg.playable_bbox[3] },
      });
      state.bboxIsAuto = false;
    }
    markClean();
  } catch (_) {}
}

// ── Save configuration ─────────────────────────────────────────────────────

saveBtn.addEventListener("click", saveConfig);

async function saveConfig() {
  if (state.isRunning || state.pipelineRunning) return;
  if (!state.selectedLayer) {
    flashSave("Select a layer first.", true);
    return;
  }

  let playable_bbox = null;
  if (state.boundsTable && state.boundsTable.hasValues()) {
    const vals = state.boundsTable.getValues();
    const { X, Z } = vals;
    if (X.min === null || X.max === null || Z.min === null || Z.max === null) {
      flashSave("Bounding box values must be numbers.", true); return;
    }
    playable_bbox = [X.min, Z.min, X.max, Z.max];
  }

  const payload = {
    layer:           state.selectedLayer,
    exclude:         state.excludeIds,
    skip:            false,
    exclude_islands: state.excludeIslands,
    playable_bbox:   playable_bbox,
  };

  try {
    saveBtn.disabled = true;
    await patchLayoutConfig(MAP_NAME, payload);
    markClean();
    saveStatus.textContent = "Saved. Running pipeline…";
    saveStatus.className   = "config-save-msg config-save-msg--ok";
    await runFullPipeline();
    saveStatus.textContent = "Pipeline complete.";
    setTimeout(() => { saveStatus.textContent = ""; saveStatus.className = "config-save-msg"; }, 3000);
    continueBtn.href   = `/editor?map=${enc(MAP_NAME)}`;
    continueBtn.hidden = false;
    await loadIslandData();
  } catch (err) {
    flashSave(`Error: ${err.message}`, true);
  } finally {
    saveBtn.disabled        = false;
    state.pipelineRunning   = false;
  }
}

function flashSave(msg, isError = false) {
  saveStatus.textContent = msg;
  saveStatus.className   = "config-save-msg" + (isError ? " config-save-msg--error" : " config-save-msg--ok");
  setTimeout(() => { saveStatus.textContent = ""; saveStatus.className = "config-save-msg"; }, 3000);
}

// ── Dirty state ────────────────────────────────────────────────────────────

function markDirty() {
  state.isDirty      = true;
  dirtyBadge.hidden  = false;
  continueBtn.hidden = true;
}

function markClean() {
  state.isDirty     = false;
  dirtyBadge.hidden = true;
}

// ── Full pipeline (post-save) ──────────────────────────────────────────────

function runFullPipeline() {
  return new Promise((resolve, reject) => {
    state.pipelineRunning  = true;
    pipelineBar.hidden     = false;
    pipelineStepList.innerHTML = "";
    const stepEls = {};
    let settled   = false;

    const url = `/api/source-map/${enc(MAP_NAME)}/pipeline/run?force=1`;
    const es  = new EventSource(url);

    es.addEventListener("step", (e) => {
      const { step, status, label, detail } = JSON.parse(e.data);
      if (!stepEls[step]) {
        const el = document.createElement("span");
        el.className  = "cfg-pipeline-step";
        el.dataset.step = step;
        el.textContent  = label;
        pipelineStepList.appendChild(el);
        stepEls[step] = el;
      }
      stepEls[step].dataset.status = status;
      if (status === "done" && detail) stepEls[step].title = detail;
    });

    es.addEventListener("done", () => {
      if (settled) return;
      settled = true;
      es.close();
      resolve();
    });

    es.addEventListener("error", (e) => {
      if (settled) return;
      settled = true;
      const data = e.data ? JSON.parse(e.data) : {};
      es.close();
      reject(new Error(data.message || "Pipeline failed"));
    });

    es.onerror = () => {
      if (settled) return;
      if (es.readyState === EventSource.CLOSED) {
        settled = true;
        reject(new Error("Pipeline connection lost"));
      }
    };
  });
}

// ── Utilities ──────────────────────────────────────────────────────────────

function enc(s) { return encodeURIComponent(s); }

function setStatus(msg) {
  if (statusEl) statusEl.textContent = msg;
}

// ── Init ───────────────────────────────────────────────────────────────────

async function checkAndShowContinue() {
  if (!state.selectedLayer) return;
  try {
    const status = await fetchPipelineStatus(MAP_NAME);
    if (status.all_done) {
      continueBtn.href   = `/editor?map=${enc(MAP_NAME)}`;
      continueBtn.hidden = false;
    }
  } catch (_) {}
}

async function init() {
  await Promise.all([
    loadExistingConfig(),
    loadLayerPreviews(),
    loadIslandData(),
  ]);
  await checkAndShowContinue();
}

init();
