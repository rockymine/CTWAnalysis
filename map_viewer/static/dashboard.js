/**
 * Dashboard page — configuration, map selection, and pipeline management.
 *
 * State flows:
 *   init → loadConfig → loadSourceMaps → populateMapList
 *   selectMap → validateMap + loadPipelineStatus → renderDetail
 *   runPipeline → SSE stream → update step indicators → refresh status
 */

import * as api from "./api.js";

// ── State ──────────────────────────────────────────────────────────────────

const state = {
  config:         null,   // {maps_folder, output_folder}
  maps:           [],     // [{name, display_name, preprocessed}]
  selectedMap:    null,   // string name
  validation:     null,   // {valid, issues}
  pipelineStatus: null,   // {steps, all_done}
  isRunning:      false,
  pipelineSteps:  {},     // step-id → {status, detail} while running
};

// ── DOM references ─────────────────────────────────────────────────────────

const mapsFolderInput   = document.getElementById("maps-folder-input");
const outputFolderInput = document.getElementById("output-folder-input");
const saveConfigBtn     = document.getElementById("save-config-btn");
const configSaveStatus  = document.getElementById("config-save-status");
const mapListEl         = document.getElementById("map-list");
const mapFilterEl       = document.getElementById("map-filter");
const mapDetailEmpty    = document.getElementById("map-detail-empty");
const mapDetailContent  = document.getElementById("map-detail-content");
const detailMapName     = document.getElementById("detail-map-name");
const detailValidation  = document.getElementById("detail-validation");
const detailSteps       = document.getElementById("detail-steps");
const detailActions     = document.getElementById("detail-actions");
const pipelineConsole   = document.getElementById("pipeline-console");
const consoleOutput     = document.getElementById("console-output");
const consoleClearBtn   = document.getElementById("console-clear-btn");
const openEditorWrap    = document.getElementById("open-editor-wrap");
const openEditorBtn     = document.getElementById("open-editor-btn");
const statusEl          = document.getElementById("status");

// ── Config ─────────────────────────────────────────────────────────────────

async function loadConfig() {
  try {
    state.config = await api.fetchConfig();
    mapsFolderInput.value   = state.config.maps_folder   || "";
    outputFolderInput.value = state.config.output_folder || "";
  } catch (err) {
    setStatus(`Config load failed: ${err.message}`);
  }
}

saveConfigBtn.addEventListener("click", async () => {
  const newConfig = {
    maps_folder:   mapsFolderInput.value.trim(),
    output_folder: outputFolderInput.value.trim(),
  };
  try {
    await api.saveConfig(newConfig);
    state.config = newConfig;
    flashSaveStatus("Saved");
    await loadSourceMaps();
  } catch (err) {
    flashSaveStatus(`Error: ${err.message}`, true);
  }
});

function flashSaveStatus(msg, isError = false) {
  configSaveStatus.textContent  = msg;
  configSaveStatus.className    = "config-save-msg" + (isError ? " config-save-msg--error" : " config-save-msg--ok");
  setTimeout(() => { configSaveStatus.textContent = ""; configSaveStatus.className = "config-save-msg"; }, 3000);
}

// ── Source map list ────────────────────────────────────────────────────────

async function loadSourceMaps() {
  mapListEl.innerHTML = '<div class="list-placeholder">Loading…</div>';
  try {
    state.maps = await api.fetchSourceMaps();
    renderMapList();
  } catch (err) {
    mapListEl.innerHTML = `<div class="list-placeholder list-placeholder--error">${err.message}</div>`;
  }
}

function renderMapList() {
  const filter = mapFilterEl.value.toLowerCase();
  const visible = filter
    ? state.maps.filter(m => m.name.toLowerCase().includes(filter) || m.display_name.toLowerCase().includes(filter))
    : state.maps;

  if (!visible.length) {
    mapListEl.innerHTML = '<div class="list-placeholder">No maps found.</div>';
    return;
  }

  mapListEl.innerHTML = "";
  for (const map of visible) {
    const row = document.createElement("div");
    row.className = "map-list-item" + (map.name === state.selectedMap ? " map-list-item--selected" : "");
    row.dataset.name = map.name;

    const dot = document.createElement("span");
    dot.className = "map-status-dot" + (map.preprocessed ? " map-status-dot--done" : "");
    dot.title = map.preprocessed ? "All pipeline steps complete" : "Not fully preprocessed";

    const label = document.createElement("span");
    label.className = "map-list-label";
    label.textContent = map.name;

    row.appendChild(dot);
    row.appendChild(label);
    row.addEventListener("click", () => selectMap(map.name));
    mapListEl.appendChild(row);
  }
}

mapFilterEl.addEventListener("input", renderMapList);

// ── Map selection & detail ─────────────────────────────────────────────────

async function selectMap(name) {
  state.selectedMap   = name;
  state.validation    = null;
  state.pipelineStatus = null;
  state.pipelineSteps = {};

  renderMapList();
  showDetail();
  detailMapName.textContent = name.replace(/_/g, " ");

  // Load validation and pipeline status in parallel
  try {
    const [validation, pipelineStatus] = await Promise.all([
      api.validateSourceMap(name),
      api.fetchPipelineStatus(name),
    ]);
    state.validation    = validation;
    state.pipelineStatus = pipelineStatus;
    renderValidation();
    renderSteps();
    renderActions();
    renderOpenEditor();
  } catch (err) {
    detailValidation.innerHTML = `<span class="tag tag--error">Failed: ${err.message}</span>`;
  }
}

function showDetail() {
  mapDetailEmpty.hidden   = true;
  mapDetailContent.hidden = false;
  detailValidation.innerHTML = '<span class="tag tag--loading">Checking…</span>';
  detailSteps.innerHTML      = '<span class="tag tag--loading">Loading…</span>';
  detailActions.innerHTML    = "";
  pipelineConsole.hidden     = true;
  openEditorBtn.hidden       = true;
}

function renderValidation() {
  const v = state.validation;
  if (!v) { detailValidation.innerHTML = ""; return; }

  if (v.valid) {
    detailValidation.innerHTML = '<span class="tag tag--ok">&#10003; Valid map folder</span>';
  } else {
    const issues = v.issues.map(i => `<li>${i}</li>`).join("");
    detailValidation.innerHTML =
      `<span class="tag tag--error">&#10005; Invalid</span>` +
      `<ul class="issue-list">${issues}</ul>`;
  }
}

function renderSteps() {
  const status = state.pipelineStatus;
  if (!status) { detailSteps.innerHTML = ""; return; }

  detailSteps.innerHTML = "";
  for (const step of status.steps) {
    const running = state.pipelineSteps[step.id];
    let stepStatus = step.done ? "done" : "pending";
    let stepDetail = step.done ? step.file : "";

    if (running) {
      stepStatus = running.status;
      stepDetail = running.detail || "";
    }

    const row = document.createElement("div");
    row.className = "step-row";
    row.id = `step-row-${step.id}`;

    const icon = document.createElement("span");
    icon.className = `step-icon step-icon--${stepStatus}`;
    icon.textContent = stepStatus === "done" ? "✓"
                     : stepStatus === "running" ? "⟳"
                     : stepStatus === "error"   ? "✗"
                     : "○";

    const labelEl = document.createElement("span");
    labelEl.className = "step-label";
    labelEl.textContent = step.label;

    const detailEl = document.createElement("span");
    detailEl.className = "step-detail";
    detailEl.id = `step-detail-${step.id}`;
    detailEl.textContent = stepDetail;

    row.appendChild(icon);
    row.appendChild(labelEl);
    row.appendChild(detailEl);
    detailSteps.appendChild(row);
  }
}

function updateStepRow(stepId, status, detail) {
  const row = document.getElementById(`step-row-${stepId}`);
  if (!row) return;

  const icon = row.querySelector(".step-icon");
  if (icon) {
    icon.className = `step-icon step-icon--${status}`;
    icon.textContent = status === "done" ? "✓"
                     : status === "running" ? "⟳"
                     : status === "error"   ? "✗"
                     : "○";
  }

  const detailEl = document.getElementById(`step-detail-${stepId}`);
  if (detailEl && detail !== undefined) detailEl.textContent = detail;
}

function renderActions() {
  detailActions.innerHTML = "";
  if (state.isRunning) return;

  const v = state.validation;
  if (!v || !v.valid) return;

  const status = state.pipelineStatus;
  const allDone = status && status.all_done;

  const runBtn = document.createElement("button");
  runBtn.className = "action-btn action-btn--primary";
  runBtn.textContent = allDone ? "Regenerate" : "Run Pipeline";
  runBtn.title = allDone ? "Re-run all pipeline steps (force)" : "Run missing pipeline steps";
  runBtn.addEventListener("click", () => runPipeline(allDone));
  detailActions.appendChild(runBtn);

  if (allDone) {
    const regenBtn = document.createElement("button");
    regenBtn.className = "action-btn";
    regenBtn.textContent = "Run (force all)";
    regenBtn.title = "Regenerate all outputs even if already present";
    regenBtn.addEventListener("click", () => runPipeline(true));
    detailActions.appendChild(regenBtn);
  }
}

function renderOpenEditor() {
  const status = state.pipelineStatus;
  if (status && status.all_done) {
    openEditorBtn.href   = `/editor?map=${encodeURIComponent(state.selectedMap)}`;
    openEditorBtn.hidden = false;
  } else {
    openEditorBtn.hidden = true;
  }
}

// ── Pipeline execution ──────────────────────────────────────────────────────

async function runPipeline(force = false) {
  if (!state.selectedMap || state.isRunning) return;

  state.isRunning   = true;
  state.pipelineSteps = {};

  // Show console, reset step UI
  pipelineConsole.hidden = false;
  consoleOutput.innerHTML = "";
  renderActions();
  renderOpenEditor();

  // Mark all steps as pending
  if (state.pipelineStatus) {
    for (const step of state.pipelineStatus.steps) {
      updateStepRow(step.id, "pending", "");
    }
  }

  appendConsole("Starting pipeline…");

  const url = `/api/source-map/${encodeURIComponent(state.selectedMap)}/pipeline/run?force=${force ? 1 : 0}`;
  const eventSource = new EventSource(url);

  eventSource.addEventListener("step", (e) => {
    const data = JSON.parse(e.data);
    state.pipelineSteps[data.step] = data;
    updateStepRow(data.step, data.status, data.detail || "");
    if (data.status === "running") {
      appendConsole(`  ${data.label}…`);
    } else if (data.status === "done") {
      appendConsole(`  ✓ ${data.label}${data.detail ? ": " + data.detail : ""}`);
    } else if (data.status === "error") {
      appendConsole(`  ✗ ${data.label}: ${data.detail || "failed"}`, "error");
    }
  });

  eventSource.addEventListener("done", async (e) => {
    const data = JSON.parse(e.data);
    appendConsole(`\n${data.message}`, "success");
    eventSource.close();
    await finalizePipeline();
  });

  eventSource.addEventListener("error", (e) => {
    if (e.data) {
      const data = JSON.parse(e.data);
      appendConsole(`Error: ${data.message}`, "error");
    }
    eventSource.close();
    finalizePipeline();
  });

  eventSource.addEventListener("skipped", (e) => {
    const data = JSON.parse(e.data);
    appendConsole(`Skipped: ${data.reason}`, "warning");
    eventSource.close();
    finalizePipeline();
  });

  // Fallback: close if the connection drops without a done/error event
  eventSource.onerror = () => {
    if (eventSource.readyState === EventSource.CLOSED) {
      finalizePipeline();
    }
  };
}

async function finalizePipeline() {
  state.isRunning = false;
  try {
    const [pipelineStatus, validation] = await Promise.all([
      api.fetchPipelineStatus(state.selectedMap),
      api.validateSourceMap(state.selectedMap),
    ]);
    state.pipelineStatus = pipelineStatus;
    state.validation     = validation;

    // Refresh map list to update dots
    const maps = await api.fetchSourceMaps();
    state.maps = maps;
    renderMapList();
  } catch (_) {
    // best-effort
  }
  state.pipelineSteps = {};
  renderSteps();
  renderActions();
  renderOpenEditor();
}

// ── Console output ─────────────────────────────────────────────────────────

function appendConsole(text, type = "info") {
  const line = document.createElement("div");
  line.className = `console-line console-line--${type}`;
  line.textContent = text;
  consoleOutput.appendChild(line);
  consoleOutput.scrollTop = consoleOutput.scrollHeight;
}

consoleClearBtn.addEventListener("click", () => {
  consoleOutput.innerHTML = "";
});

// ── Status bar ─────────────────────────────────────────────────────────────

function setStatus(msg) {
  statusEl.textContent = msg;
}

// ── Startup ────────────────────────────────────────────────────────────────

async function init() {
  await loadConfig();
  if (state.config && state.config.maps_folder) {
    await loadSourceMaps();
  }
}

init();
