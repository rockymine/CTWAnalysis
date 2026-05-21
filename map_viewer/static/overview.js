import * as api from "./api.js";
import { OverviewCanvas } from "./overview-canvas.js";

const SYM_LABELS = {
  mirror_x: "Mirror — vertical axis",
  mirror_z: "Mirror — horizontal axis",
  rot_180:  "Rotational — 180°",
  rot_90:   "Rotational — 90°",
};

export class OverviewPanel {
  constructor(el, { onStatusChange } = {}) {
    this._el             = el;
    this._map            = null;
    this._data           = null;
    this._symmetryData   = null;
    this._symmetryStatus = null;
    this._dirty          = false;
    this._onStatusChange = onStatusChange ?? null;

    this._nameEl      = el.querySelector("#ov-name");
    this._versionEl   = el.querySelector("#ov-version");
    this._objectiveEl = el.querySelector("#ov-objective");
    this._gamemodeEl  = el.querySelector("#ov-gamemode");
    this._authorsEl      = el.querySelector("#ov-authors-list");
    this._contributorsEl = el.querySelector("#ov-contributors-list");
    this._saveBtn        = el.querySelector("#ov-save-btn");
    this._statusEl       = el.querySelector("#ov-save-status");
    this._symBodyEl      = el.querySelector("#ov-sym-body");

    this._canvas = new OverviewCanvas(
      el.querySelector("#ov-map-svg"),
      el.querySelector("#ov-canvas-wrap"),
    );

    for (const field of [this._nameEl, this._versionEl, this._objectiveEl, this._gamemodeEl]) {
      field.addEventListener("input", () => this._setDirty(true));
    }

    this._saveBtn.addEventListener("click", () => this._save());
    el.querySelector("#ov-add-author").addEventListener("click", () => {
      this._addPersonRow(this._authorsEl, {});
      this._setDirty(true);
    });
    el.querySelector("#ov-add-contributor").addEventListener("click", () => {
      this._addPersonRow(this._contributorsEl, {});
      this._setDirty(true);
    });
  }

  async load(mapName) {
    this._map = mapName;
    this._setDirty(false);
    this._statusEl.textContent = "";
    this._symBodyEl.innerHTML = '<p class="ov-sym-loading">Loading…</p>';

    try {
      const [mapData, symmetryData, ctx, topSurface] = await Promise.all([
        api.fetchMapData(mapName),
        api.fetchSymmetry(mapName),
        api.fetchContext(mapName),
        api.fetchTopSurface(mapName).catch(() => null),
      ]);

      this._data           = mapData;
      this._symmetryData   = symmetryData;
      this._symmetryStatus = mapData.symmetry_status ?? null;

      this._populate();
      this._canvas.render(ctx);
      if (topSurface) {
        this._canvas.loadBlockLayer(topSurface);
        this._canvas.setBlocksVisible(true);
      }
      this._canvas.setSymmetryOverlay(symmetryData, this._symmetryStatus);
      this._renderSymmetryPanel();
    } catch (err) {
      this._statusEl.textContent = `Failed to load: ${err.message}`;
      this._symBodyEl.innerHTML = '<p class="ov-sym-error">Could not load symmetry data.</p>';
    }
  }

  // ── form ─────────────────────────────────────────────────────────────────

  _populate() {
    const mapData = this._data;
    this._nameEl.value      = mapData.name      ?? "";
    this._versionEl.value   = mapData.version   ?? "";
    this._objectiveEl.value = mapData.objective ?? "";
    this._gamemodeEl.value  = mapData.gamemode  ?? "";
    this._authorsEl.innerHTML      = "";
    this._contributorsEl.innerHTML = "";
    for (const person of (mapData.authors ?? [])) {
      const listEl = person.role === "contributor" ? this._contributorsEl : this._authorsEl;
      this._addPersonRow(listEl, person);
    }
    this._setDirty(false);
  }

  _addPersonRow(listEl, { uuid = "", contribution = "" } = {}) {
    const row = document.createElement("div");
    row.className = "ov-author-row";
    row.innerHTML = `
      <input class="ov-input ov-author-uuid" type="text" placeholder="Player UUID" value="${_esc(uuid)}"/>
      <input class="ov-input ov-author-contribution" type="text" placeholder="Contribution (optional)" value="${_esc(contribution ?? "")}"/>
      <button class="ov-author-remove" title="Remove">✕</button>
    `;
    row.querySelector(".ov-author-remove").addEventListener("click", () => {
      row.remove();
      this._setDirty(true);
    });
    for (const field of row.querySelectorAll("input")) {
      field.addEventListener("input", () => this._setDirty(true));
    }
    listEl.appendChild(row);
  }

  _collectAuthors() {
    const fromList = (listEl, role) =>
      [...listEl.querySelectorAll(".ov-author-row")]
        .map(row => ({
          uuid:         row.querySelector(".ov-author-uuid").value.trim(),
          role,
          contribution: row.querySelector(".ov-author-contribution").value.trim() || null,
        }))
        .filter(entry => entry.uuid);
    return [
      ...fromList(this._authorsEl,      "author"),
      ...fromList(this._contributorsEl, "contributor"),
    ];
  }

  async _save() {
    if (!this._map) return;
    this._saveBtn.disabled = true;
    this._statusEl.textContent = "Saving…";
    const metadata = {
      name:      this._nameEl.value.trim()      || null,
      version:   this._versionEl.value.trim()   || null,
      objective: this._objectiveEl.value.trim() || null,
      gamemode:  this._gamemodeEl.value.trim()  || null,
      authors:   this._collectAuthors(),
    };
    try {
      await api.saveMetadata(this._map, metadata);
      this._data = { ...this._data, ...metadata };
      this._setDirty(false);
      this._statusEl.textContent = "Saved.";
      setTimeout(() => { if (!this._dirty) this._statusEl.textContent = ""; }, 2000);
    } catch (err) {
      this._statusEl.textContent = `Save failed: ${err.message}`;
      this._saveBtn.disabled = false;
    }
  }

  _setDirty(isDirty) {
    this._dirty = isDirty;
    this._saveBtn.disabled = !isDirty;
    this._updateStatusDot();
  }

  // ── symmetry panel ────────────────────────────────────────────────────────

  _renderSymmetryPanel() {
    const symData = this._symmetryData;
    const status  = this._symmetryStatus;

    if (!symData) {
      this._symBodyEl.innerHTML = `
        <p class="ov-sym-none">No symmetry data found for this map.</p>
        <p class="ov-sym-hint">Run the pipeline first to detect the symmetry axis.</p>
        <div class="ov-sym-actions">
          <button id="ov-sym-mark-none" class="action-btn ${status === "none" ? "action-btn--primary" : ""}">
            Mark as asymmetric
          </button>
        </div>
      `;
      this._symBodyEl.querySelector("#ov-sym-mark-none")
        .addEventListener("click", () => this._setSymmetryStatus("none"));
      return;
    }

    const { center, global_symmetry } = symData;
    const detectedEntries = global_symmetry.filter(entry => entry.detected);
    const primaryEntry = [...detectedEntries].sort((a, b) => b.confidence - a.confidence)[0];

    const statusLabel = {
      confirmed: '<span class="ov-sym-badge ov-sym-badge--confirmed">Confirmed</span>',
      skipped:   '<span class="ov-sym-badge ov-sym-badge--skipped">Skipped</span>',
      none:      '<span class="ov-sym-badge ov-sym-badge--none">Asymmetric</span>',
    }[status] ?? '<span class="ov-sym-badge ov-sym-badge--pending">Not confirmed</span>';

    const primaryLabel = primaryEntry
      ? `${SYM_LABELS[primaryEntry.type] ?? primaryEntry.type} (${Math.round(primaryEntry.confidence * 100)}%)`
      : "None detected";

    const detectedList = detectedEntries.length
      ? detectedEntries.map(entry =>
          `<option value="${entry.type}" ${entry === primaryEntry ? "selected" : ""}>` +
          `${SYM_LABELS[entry.type] ?? entry.type} — ${Math.round(entry.confidence * 100)}%` +
          `</option>`
        ).join("")
      : `<option value="">None</option>`;

    this._symBodyEl.innerHTML = `
      <div class="ov-sym-status-row">${statusLabel}</div>
      <div class="ov-sym-info">
        <div class="ov-sym-row">
          <span class="ov-sym-key">Primary</span>
          <span class="ov-sym-val">${primaryLabel}</span>
        </div>
        <div class="ov-sym-row">
          <span class="ov-sym-key">Center</span>
          <span class="ov-sym-val">X ${center.center_x.toFixed(1)}, Z ${center.center_z.toFixed(1)}</span>
        </div>
        <div class="ov-sym-row">
          <span class="ov-sym-key">Type</span>
          <span class="ov-sym-val">${center.type ?? "—"}</span>
        </div>
      </div>
      <div class="ov-sym-actions">
        <button id="ov-sym-confirm" class="action-btn ${status === "confirmed" ? "action-btn--primary" : ""}">
          Confirm
        </button>
        <button id="ov-sym-skip" class="action-btn ${status === "skipped" ? "action-btn--primary" : ""}">
          Skip
        </button>
        <button id="ov-sym-adjust-toggle" class="action-btn">Adjust…</button>
      </div>
      <div id="ov-sym-adjust-form" class="ov-sym-adjust" hidden>
        <div class="ov-field">
          <label class="ov-label">Axis type</label>
          <select id="ov-sym-axis-select" class="ov-input">${detectedList}</select>
        </div>
        <div class="ov-field-row">
          <div class="ov-field">
            <label class="ov-label">Center X</label>
            <input id="ov-sym-cx" class="ov-input" type="number" step="0.5" value="${center.center_x}"/>
          </div>
          <div class="ov-field">
            <label class="ov-label">Center Z</label>
            <input id="ov-sym-cz" class="ov-input" type="number" step="0.5" value="${center.center_z}"/>
          </div>
        </div>
        <div class="ov-sym-actions">
          <button id="ov-sym-apply-adjust" class="action-btn action-btn--primary">Apply</button>
          <button id="ov-sym-mark-none" class="action-btn">No symmetry</button>
        </div>
      </div>
    `;

    const adjustForm   = this._symBodyEl.querySelector("#ov-sym-adjust-form");
    const adjustToggle = this._symBodyEl.querySelector("#ov-sym-adjust-toggle");

    this._symBodyEl.querySelector("#ov-sym-confirm")
      .addEventListener("click", () => this._setSymmetryStatus("confirmed"));
    this._symBodyEl.querySelector("#ov-sym-skip")
      .addEventListener("click", () => this._setSymmetryStatus("skipped"));
    adjustToggle.addEventListener("click", () => {
      adjustForm.hidden = !adjustForm.hidden;
      adjustToggle.textContent = adjustForm.hidden ? "Adjust…" : "Adjust ▾";
    });
    this._symBodyEl.querySelector("#ov-sym-apply-adjust")
      .addEventListener("click", () => this._applyAdjust());
    this._symBodyEl.querySelector("#ov-sym-mark-none")
      .addEventListener("click", () => this._setSymmetryStatus("none"));
  }

  async _setSymmetryStatus(newStatus) {
    if (!this._map) return;
    this._symmetryStatus = newStatus;
    try {
      await api.saveMetadata(this._map, { symmetry_status: newStatus });
      this._data = { ...this._data, symmetry_status: newStatus };
    } catch (err) {
      console.error("Failed to save symmetry status:", err);
    }
    this._canvas.setSymmetryOverlay(this._symmetryData, newStatus);
    this._renderSymmetryPanel();
  }

  _applyAdjust() {
    if (!this._symmetryData) return;
    const axisType = this._symBodyEl.querySelector("#ov-sym-axis-select")?.value;
    const newCX    = parseFloat(this._symBodyEl.querySelector("#ov-sym-cx")?.value);
    const newCZ    = parseFloat(this._symBodyEl.querySelector("#ov-sym-cz")?.value);

    if (isNaN(newCX) || isNaN(newCZ)) return;

    // Update local copy of symmetry data (does not persist to disk)
    this._symmetryData = {
      ...this._symmetryData,
      center: { ...this._symmetryData.center, center_x: newCX, center_z: newCZ },
      global_symmetry: this._symmetryData.global_symmetry.map(entry => ({
        ...entry,
        detected: axisType ? entry.type === axisType : entry.detected,
      })),
    };
    this._canvas.setSymmetryOverlay(this._symmetryData, this._symmetryStatus);
    this._renderSymmetryPanel();
  }

  // ── status dot ────────────────────────────────────────────────────────────

  _updateStatusDot() {
    if (!this._onStatusChange) return;
    const name     = this._nameEl.value.trim();
    const version  = this._versionEl.value.trim();
    const gamemode = this._gamemodeEl.value.trim();
    const dotStatus = (name && version && gamemode) ? "green" : "yellow";
    this._onStatusChange(dotStatus);
  }
}

function _esc(str) {
  return String(str).replace(/&/g, "&amp;").replace(/"/g, "&quot;");
}
