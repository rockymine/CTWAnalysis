import * as api from "./api.js";

export class OverviewPanel {
  constructor(el) {
    this._el          = el;
    this._map         = null;
    this._data        = null;
    this._dirty       = false;

    this._nameEl      = el.querySelector("#ov-name");
    this._versionEl   = el.querySelector("#ov-version");
    this._objectiveEl = el.querySelector("#ov-objective");
    this._mbhEl       = el.querySelector("#ov-mbh");
    this._gamemodeEl  = el.querySelector("#ov-gamemode");
    this._phaseEl     = el.querySelector("#ov-phase");
    this._authorsEl   = el.querySelector("#ov-authors-list");
    this._saveBtn     = el.querySelector("#ov-save-btn");
    this._statusEl    = el.querySelector("#ov-save-status");

    for (const field of [this._nameEl, this._versionEl, this._objectiveEl,
                          this._mbhEl, this._gamemodeEl, this._phaseEl]) {
      field.addEventListener("input", () => this._setDirty(true));
    }

    this._saveBtn.addEventListener("click", () => this._save());

    el.querySelector("#ov-add-author").addEventListener("click", () => {
      this._addAuthorRow({});
      this._setDirty(true);
    });

    el.querySelector("#ov-advanced-toggle").addEventListener("click", () => {
      const adv = el.querySelector("#ov-advanced");
      adv.hidden = !adv.hidden;
      el.querySelector("#ov-advanced-caret").textContent = adv.hidden ? "▸" : "▾";
    });
  }

  async load(mapName) {
    this._map = mapName;
    this._setDirty(false);
    this._statusEl.textContent = "";
    try {
      this._data = await api.fetchMapData(mapName);
      this._populate();
    } catch (err) {
      this._statusEl.textContent = `Failed to load: ${err.message}`;
    }
  }

  _populate() {
    const d = this._data;
    this._nameEl.value      = d.name              ?? "";
    this._versionEl.value   = d.version           ?? "";
    this._objectiveEl.value = d.objective         ?? "";
    this._mbhEl.value       = d.max_build_height  ?? "";
    this._gamemodeEl.value  = d.gamemode          ?? "";
    this._phaseEl.value     = d.phase             ?? "";
    this._authorsEl.innerHTML = "";
    for (const author of (d.authors ?? [])) {
      this._addAuthorRow(author);
    }
    this._setDirty(false);
  }

  _addAuthorRow({ uuid = "", role = "author", contribution = "" } = {}) {
    const row = document.createElement("div");
    row.className = "ov-author-row";
    row.innerHTML = `
      <input class="ov-input ov-author-uuid" type="text" placeholder="Player UUID" value="${_esc(uuid)}"/>
      <select class="ov-input ov-author-role">
        <option value="author"      ${role === "author"      ? "selected" : ""}>Author</option>
        <option value="contributor" ${role === "contributor" ? "selected" : ""}>Contributor</option>
      </select>
      <input class="ov-input ov-author-contribution" type="text" placeholder="Contribution (optional)" value="${_esc(contribution ?? "")}"/>
      <button class="ov-author-remove" title="Remove">✕</button>
    `;
    row.querySelector(".ov-author-remove").addEventListener("click", () => {
      row.remove();
      this._setDirty(true);
    });
    for (const field of row.querySelectorAll("input, select")) {
      field.addEventListener("input", () => this._setDirty(true));
    }
    this._authorsEl.appendChild(row);
  }

  _collectAuthors() {
    return [...this._authorsEl.querySelectorAll(".ov-author-row")]
      .map(row => ({
        uuid:         row.querySelector(".ov-author-uuid").value.trim(),
        role:         row.querySelector(".ov-author-role").value,
        contribution: row.querySelector(".ov-author-contribution").value.trim() || null,
      }))
      .filter(a => a.uuid);
  }

  async _save() {
    if (!this._map) return;
    this._saveBtn.disabled = true;
    this._statusEl.textContent = "Saving…";
    const metadata = {
      name:             this._nameEl.value.trim()      || null,
      version:          this._versionEl.value.trim()   || null,
      objective:        this._objectiveEl.value.trim() || null,
      max_build_height: this._mbhEl.value ? parseInt(this._mbhEl.value, 10) : null,
      gamemode:         this._gamemodeEl.value.trim()  || null,
      phase:            this._phaseEl.value             || null,
      authors:          this._collectAuthors(),
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

  _setDirty(dirty) {
    this._dirty = dirty;
    this._saveBtn.disabled = !dirty;
  }
}

function _esc(str) {
  return String(str).replace(/&/g, "&amp;").replace(/"/g, "&quot;");
}
