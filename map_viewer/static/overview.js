import * as api from "./api.js";
import { OverviewCanvas } from "./overview-canvas.js";

const SYM_LABELS = {
  mirror_x: "Mirror — vertical axis",
  mirror_z: "Mirror — horizontal axis",
  rot_180:  "Rotational — 180°",
  rot_90:   "Rotational — 90°",
};

// ── symmetry preview SVG diagrams ─────────────────────────────────────────────

function _symPreviewSvg(type) {
  const p  = "#a855f7";
  const r1 = { fill: "#f9a8d4", stroke: "#f472b6" };
  const r2 = { fill: "#fde68a", stroke: "#fbbf24" };
  const r3 = { fill: "#93c5fd", stroke: "#60a5fa" };
  const r4 = { fill: "#bbf7d0", stroke: "#4ade80" };
  const rect = (x, y, w, h, c) =>
    `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="4" fill="${c.fill}" fill-opacity="0.45" stroke="${c.stroke}" stroke-width="1.5"/>`;
  const dot = (cx, cy) =>
    `<circle cx="${cx}" cy="${cy}" r="3.5" fill="none" stroke="${p}" stroke-width="1.5"/>` +
    `<circle cx="${cx}" cy="${cy}" r="1.5" fill="${p}"/>`;
  const lbl = (t, x, y) =>
    `<text x="${x}" y="${y}" text-anchor="end" font-size="9.5" fill="${p}" font-family="ui-monospace,monospace" opacity="0.85">${t}</text>`;
  const axis = `stroke="${p}" stroke-width="1.5" stroke-dasharray="5,3"`;

  if (type === "mirror_x") return `<svg viewBox="0 0 200 100" xmlns="http://www.w3.org/2000/svg">
    ${rect(14, 22, 72, 46, r1)} ${rect(114, 22, 72, 46, r2)}
    <line x1="100" y1="4" x2="100" y2="96" ${axis}/>
    ${dot(100, 50)} ${lbl("X · mirror", 196, 16)}</svg>`;

  if (type === "mirror_z") return `<svg viewBox="0 0 200 100" xmlns="http://www.w3.org/2000/svg">
    ${rect(35, 5, 130, 36, r1)} ${rect(35, 59, 130, 36, r2)}
    <line x1="4" y1="50" x2="196" y2="50" ${axis}/>
    ${dot(100, 50)} ${lbl("Z · mirror", 196, 16)}</svg>`;

  if (type === "rot_180") return `<svg viewBox="0 0 200 100" xmlns="http://www.w3.org/2000/svg">
    ${rect(10, 8, 70, 36, r1)} ${rect(120, 56, 70, 36, r2)}
    <path d="M 80,20 C 118,4 158,30 152,58" ${axis} fill="none"/>
    <polygon points="152,58 144,51 157,50" fill="${p}" opacity="0.85"/>
    ${dot(100, 50)} ${lbl("180° · n=2", 196, 16)}</svg>`;

  if (type === "rot_90") return `<svg viewBox="0 0 200 100" xmlns="http://www.w3.org/2000/svg">
    ${rect(67, 4, 66, 30, r1)} ${rect(122, 35, 66, 30, r3)}
    ${rect(67, 66, 66, 30, r2)} ${rect(12, 35, 66, 30, r4)}
    <path d="M 138,42 A 40,40 0 0 1 100,90" ${axis} fill="none"/>
    <polygon points="100,90 107,81 94,80" fill="${p}" opacity="0.85"/>
    ${dot(100, 50)} ${lbl("90° · n=4", 196, 16)}</svg>`;

  return `<svg viewBox="0 0 200 100" xmlns="http://www.w3.org/2000/svg">
    <text x="100" y="55" text-anchor="middle" font-size="11" fill="${p}" font-family="ui-monospace,monospace" opacity="0.5">—</text></svg>`;
}

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

  _addPersonRow(listEl, { uuid = "", name = "", contribution = "" } = {}) {
    const row = document.createElement("div");
    row.className = "author-row";
    row.dataset.uuid = uuid;

    const avatarSrc = uuid ? _avatarUrl(uuid) : _AVATAR_EMPTY;
    const displayName = name || uuid;  // show UUID as fallback until resolved

    row.innerHTML = `
      <img class="author-avatar" src="${_esc(avatarSrc)}" width="16" height="16" alt=""/>
      <input class="field-input author-name" type="text" placeholder="Minecraft username" value="${_esc(displayName)}"/>
      <input class="field-input author-contribution" type="text" placeholder="Contribution (optional)" value="${_esc(contribution ?? "")}"/>
      <button class="btn-remove" title="Remove">✕</button>
    `;

    const avatarImg = row.querySelector(".author-avatar");
    const nameInput = row.querySelector(".author-name");

    // Resolve username or UUID → canonical name + UUID on blur
    nameInput.addEventListener("blur", async () => {
      const val = nameInput.value.trim();
      if (!val || val === row.dataset.uuid || val === name) return;
      nameInput.dataset.resolving = "1";
      try {
        const player = await api.fetchMinecraftPlayer(val);
        row.dataset.uuid = player.uuid;
        nameInput.value  = player.name;
        nameInput.title  = player.uuid;
        avatarImg.src    = _avatarUrl(player.uuid);
        nameInput.classList.remove("author-name--error");
      } catch {
        row.dataset.uuid = "";
        avatarImg.src    = _AVATAR_EMPTY;
        nameInput.classList.add("author-name--error");
        nameInput.title  = "Player not found";
      } finally {
        delete nameInput.dataset.resolving;
      }
      this._setDirty(true);
    });

    // Auto-resolve UUID → name for legacy entries that have no name yet
    if (uuid && !name) {
      api.fetchMinecraftPlayer(uuid).then(player => {
        nameInput.value = player.name;
        nameInput.title = player.uuid;
        avatarImg.src   = _avatarUrl(player.uuid);
      }).catch(() => { /* leave UUID in field */ });
    }

    row.querySelector(".btn-remove").addEventListener("click", () => {
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
      [...listEl.querySelectorAll(".author-row")]
        .map(row => ({
          uuid:         row.dataset.uuid || "",
          name:         row.querySelector(".author-name").value.trim() || null,
          role,
          contribution: row.querySelector(".author-contribution").value.trim() || null,
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

    const badgeHtml = {
      confirmed: '<span class="ov-sym-badge ov-sym-badge--confirmed">Confirmed</span>',
      skipped:   '<span class="ov-sym-badge ov-sym-badge--skipped">Skipped</span>',
      none:      '<span class="ov-sym-badge ov-sym-badge--none">No symmetry</span>',
    }[status] ?? '<span class="ov-sym-badge ov-sym-badge--pending">Not confirmed</span>';

    const header = `<div class="section-header section-header--ruled">
      <span class="section-title">Symmetry Axis</span>${badgeHtml}</div>`;

    if (!symData) {
      this._symBodyEl.innerHTML = `${header}
        <p class="ov-sym-hint">No symmetry data found. Run the pipeline first.</p>
        <div class="ov-sym-actions">
          <button id="ov-sym-mark-none" class="action-btn">No symmetry</button>
        </div>`;
      this._symBodyEl.querySelector("#ov-sym-mark-none")
        .addEventListener("click", () => this._setSymmetryStatus("none"));
      return;
    }

    const { center, global_symmetry } = symData;
    const detectedEntries = global_symmetry.filter(e => e.detected);
    const primaryEntry = [...detectedEntries].sort((a, b) => b.confidence - a.confidence)[0];
    const coordLabel = primaryEntry?.type?.startsWith("mirror") ? "Center" : "Pivot";

    const options = detectedEntries.length
      ? detectedEntries.map(e =>
          `<option value="${e.type}" ${e === primaryEntry ? "selected" : ""}>` +
          `${SYM_LABELS[e.type] ?? e.type}</option>`).join("")
      : `<option value="">None detected</option>`;

    this._symBodyEl.innerHTML = `${header}
      <div class="field">
        <label class="field-label">Primary type</label>
        <select id="ov-sym-axis-select" class="field-input">${options}</select>
      </div>
      <div class="ov-sym-coord-section">
        <div class="ov-sym-coord-header">
          <span class="field-label" id="ov-sym-coord-label">${coordLabel}</span>
          <span class="field-label">blocks</span>
        </div>
        <div class="detail-group-row">
          <div class="detail-prefixed-field">
            <span class="detail-prefix">X</span>
            <input id="ov-sym-cx" class="detail-bounds-input" type="number" step="0.5" value="${center.center_x}"/>
          </div>
          <div class="detail-prefixed-field">
            <span class="detail-prefix">Z</span>
            <input id="ov-sym-cz" class="detail-bounds-input" type="number" step="0.5" value="${center.center_z}"/>
          </div>
        </div>
      </div>
      <div class="ov-sym-preview-section">
        <div class="section-title">Preview</div>
        <div id="ov-sym-preview-svg" class="ov-sym-preview-svg">${_symPreviewSvg(primaryEntry?.type ?? "mirror_x")}</div>
      </div>
      <div class="ov-sym-actions">
        <button id="ov-sym-confirm" class="action-btn action-btn--primary ov-sym-confirm-btn">Confirm</button>
        <button id="ov-sym-mark-none" class="action-btn ov-sym-none-btn">No symmetry</button>
      </div>`;

    const axisSelect   = this._symBodyEl.querySelector("#ov-sym-axis-select");
    const cxInput      = this._symBodyEl.querySelector("#ov-sym-cx");
    const czInput      = this._symBodyEl.querySelector("#ov-sym-cz");
    const previewSvgEl = this._symBodyEl.querySelector("#ov-sym-preview-svg");

    axisSelect.addEventListener("change", () => {
      const lbl = this._symBodyEl.querySelector("#ov-sym-coord-label");
      if (lbl) lbl.textContent = axisSelect.value.startsWith("mirror") ? "Center" : "Pivot";
      if (previewSvgEl) previewSvgEl.innerHTML = _symPreviewSvg(axisSelect.value);
      this._applyAdjust({ rerender: false });
    });
    cxInput.addEventListener("input", () => this._applyAdjust({ rerender: false }));
    czInput.addEventListener("input", () => this._applyAdjust({ rerender: false }));

    this._symBodyEl.querySelector("#ov-sym-confirm").addEventListener("click", () => {
      this._applyAdjust({ rerender: false });
      this._setSymmetryStatus("confirmed");
    });
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

  _applyAdjust({ rerender = true } = {}) {
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
    if (rerender) this._renderSymmetryPanel();
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

const _AVATAR_EMPTY = "data:image/gif;base64,R0lGODlhEAAQAAAAACwAAAAAEAAQAAABEIQBADs=";
function _avatarUrl(uuid) {
  return `https://mc-heads.net/avatar/${encodeURIComponent(uuid)}/16`;
}
