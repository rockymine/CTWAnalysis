/**
 * ObjectivePanel — left and right panel logic for the Objective activity.
 *
 * Left panel:  flat list of wool rooms (one row per distinct color + location).
 *              "+ Add wool" button creates a new entry.
 *
 * Right panel: editable inspector for the selected wool room:
 *   - Wool Color dropdown (dye colors)
 *   - Defended by dropdown (teams)
 *   - Location X/Y/Z inputs (point-region style)
 *   - Monument Captures — read-only cards per capturing team
 *   - Delete wool button
 */

import { chatColorHex, dyeColorHex, MINECRAFT_DYE_COLORS } from "./game-colors.js";
import * as api from "./api.js";

export class ObjectivePanel {
  constructor(opts = {}) {
    const { onWoolSelect } = opts;
    // ── Left panel ──────────────────────────────────────────────────────────
    this._woolListEl   = document.getElementById("obj-wool-list");
    this._addWoolBtn   = document.getElementById("obj-add-wool-btn");

    // ── Right panel — shared ────────────────────────────────────────────────
    this._inspectorEl  = document.getElementById("obj-wool-inspector");
    this._emptyEl      = document.getElementById("obj-inspector-empty");

    // ── Right panel — inspector fields ──────────────────────────────────────
    this._woolColorSelEl    = document.getElementById("obj-wool-color-sel");
    this._woolColorSwatchEl = document.getElementById("obj-wool-color-swatch");
    this._defenderSelEl     = document.getElementById("obj-defender-sel");
    this._defenderSwatchEl  = document.getElementById("obj-defender-swatch");
    this._locationEl        = document.getElementById("obj-inspector-location");
    this._capturesEl        = document.getElementById("obj-inspector-captures");
    this._deleteWoolBtn     = document.getElementById("obj-delete-wool-btn");

    this._onWoolSelect = onWoolSelect ?? (() => {});
    this._onWoolSave   = opts.onWoolSave   ?? (() => {});
    this._mapName      = null;
    this._teams        = [];
    this._woolRooms    = [];   // derived, one entry per distinct wool room

    this._addWoolBtn?.addEventListener("click", () => this._addWool());
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  load(mapName, mapData) {
    this._mapName   = mapName;
    this._teams     = mapData.teams ?? [];
    this._woolRooms = this._deriveWoolRooms(mapData.wools ?? []);
    this._renderList();
    this._showEmpty();
  }

  // ── Data preparation ────────────────────────────────────────────────────────

  /**
   * Collapse the flat wools array into one entry per distinct wool room
   * (unique color + location).  Each room tracks all teams that must
   * capture it and their respective monument coordinates.
   *
   * Defending team = any team NOT in the capture list.  For well-formed
   * 2-team maps this is exactly one team.
   */
  _deriveWoolRooms(wools) {
    const roomMap = new Map();   // key → room object
    for (const wool of wools) {
      const key = `${wool.color}:${wool.location.x},${wool.location.y},${wool.location.z}`;
      if (!roomMap.has(key)) {
        roomMap.set(key, {
          color:    wool.color,
          location: { ...wool.location },
          captures: [],
        });
      }
      roomMap.get(key).captures.push({ team: wool.team, monument: wool.monument });
    }

    const allTeamIds = new Set(this._teams.map(t => t.id));
    const rooms = [...roomMap.values()];

    for (const room of rooms) {
      const capturingIds   = new Set(room.captures.map(c => c.team));
      const defenders      = [...allTeamIds].filter(id => !capturingIds.has(id));
      room.defendingTeamId = defenders.length === 1 ? defenders[0] : null;
    }

    return rooms;
  }

  // ── List rendering ──────────────────────────────────────────────────────────

  _renderList() {
    this._woolListEl.innerHTML = "";

    for (const room of this._woolRooms) {
      this._woolListEl.appendChild(this._buildWoolRow(room));
    }
  }

  _buildWoolRow(room) {
    const row = document.createElement("div");
    row.className = "obj-wool-row";
    row.dataset.roomKey = _roomKey(room);

    const swatch = document.createElement("span");
    swatch.className = "obj-wool-swatch";
    swatch.style.background = dyeColorHex(room.color);

    const label = document.createElement("span");
    label.className = "obj-wool-label";
    label.textContent = _capitalize(room.color);

    row.append(swatch, label);
    row.addEventListener("click", () => this._selectRoom(room, row));
    return row;
  }

  // ── Selection ───────────────────────────────────────────────────────────────

  _selectRoom(room, rowEl) {
    this._woolListEl.querySelectorAll(".obj-wool-row--selected")
      .forEach(el => el.classList.remove("obj-wool-row--selected"));
    rowEl.classList.add("obj-wool-row--selected");
    this._showInspector(room);
    this._onWoolSelect(room);
  }

  // ── Add wool ────────────────────────────────────────────────────────────────

  async _addWool() {
    if (!this._mapName || !this._teams.length) return;

    // Pick the first dye color not already present in the room list
    const usedColors = new Set(this._woolRooms.map(r => r.color));
    const defaultColor = MINECRAFT_DYE_COLORS.find(c => !usedColors.has(c.value))?.value ?? "white";

    // Default capturing team = first team (defender = second team for 2-team maps)
    const capturingTeam = this._teams[0].id;

    try {
      const { wool } = await api.addWool(this._mapName, {
        team:     capturingTeam,
        color:    defaultColor,
        location: { x: 0, y: 0, z: 0 },
        monument: { x: 0, y: 0, z: 0 },
      });

      // Build a synthetic room and append it
      const allTeamIds   = new Set(this._teams.map(t => t.id));
      const capturingIds = new Set([wool.team]);
      const defenders    = [...allTeamIds].filter(id => !capturingIds.has(id));
      const newRoom = {
        color:           wool.color,
        location:        { ...wool.location },
        captures:        [{ team: wool.team, monument: wool.monument }],
        defendingTeamId: defenders.length === 1 ? defenders[0] : null,
      };

      this._woolRooms.push(newRoom);
      this._renderList();
      this._onWoolSave();

      // Select the newly added row
      const newRow = this._woolListEl.querySelector(
        `[data-room-key="${CSS.escape(_roomKey(newRoom))}"]`,
      );
      if (newRow) this._selectRoom(newRoom, newRow);
    } catch (err) {
      console.error("ObjectivePanel: failed to add wool:", err);
    }
  }

  // ── Inspector ───────────────────────────────────────────────────────────────

  _showEmpty() {
    this._inspectorEl.hidden = true;
    this._emptyEl.hidden     = false;
  }

  _showInspector(room) {
    this._emptyEl.hidden     = true;
    this._inspectorEl.hidden = false;

    // Clone selects and delete button to clear stale listeners
    this._woolColorSelEl.replaceWith(this._woolColorSelEl.cloneNode(false));
    this._woolColorSelEl    = document.getElementById("obj-wool-color-sel");
    this._defenderSelEl.replaceWith(this._defenderSelEl.cloneNode(false));
    this._defenderSelEl     = document.getElementById("obj-defender-sel");
    this._deleteWoolBtn.replaceWith(this._deleteWoolBtn.cloneNode(true));
    this._deleteWoolBtn     = document.getElementById("obj-delete-wool-btn");

    // ── Wool color ──────────────────────────────────────────────────────────
    this._buildWoolColorDropdown(room.color);
    this._woolColorSelEl.value = room.color;
    this._woolColorSwatchEl.style.background = dyeColorHex(room.color);

    this._woolColorSelEl.addEventListener("change", () => {
      this._woolColorSwatchEl.style.background = dyeColorHex(this._woolColorSelEl.value);
      this._saveWoolColor(room);
    });

    // ── Defender team ───────────────────────────────────────────────────────
    this._buildDefenderDropdown();
    this._defenderSelEl.value = room.defendingTeamId ?? "";
    const defTeam = this._teams.find(t => t.id === room.defendingTeamId);
    this._defenderSwatchEl.style.background = defTeam ? chatColorHex(defTeam.color) : "transparent";

    this._defenderSelEl.addEventListener("change", () => {
      const selected = this._defenderSelEl.value;
      const team     = this._teams.find(t => t.id === selected);
      this._defenderSwatchEl.style.background = team ? chatColorHex(team.color) : "transparent";
      this._saveWoolDefender(room);
    });

    // ── Location inputs ─────────────────────────────────────────────────────
    this._buildLocationInputs(room);

    // ── Monument captures (read-only) ───────────────────────────────────────
    this._capturesEl.innerHTML = "";
    for (const capture of room.captures) {
      this._capturesEl.appendChild(this._buildCaptureCard(capture));
    }

    // ── Delete button ───────────────────────────────────────────────────────
    this._deleteWoolBtn.addEventListener("click", () => this._deleteWool(room));
  }

  // ── Dropdowns ───────────────────────────────────────────────────────────────

  _buildWoolColorDropdown(currentColor) {
    // Colors used by any room OTHER than the one currently being edited
    const usedColors = new Set(
      this._woolRooms
        .filter(r => r.color !== currentColor)
        .map(r => r.color),
    );
    this._woolColorSelEl.innerHTML = "";
    for (const color of MINECRAFT_DYE_COLORS) {
      const opt = document.createElement("option");
      opt.value       = color.value;
      opt.textContent = color.label;
      opt.disabled    = usedColors.has(color.value);
      this._woolColorSelEl.appendChild(opt);
    }
  }

  _buildDefenderDropdown() {
    this._defenderSelEl.innerHTML = "";
    const noneOpt = document.createElement("option");
    noneOpt.value       = "";
    noneOpt.textContent = "— unassigned —";
    this._defenderSelEl.appendChild(noneOpt);
    for (const team of this._teams) {
      const opt = document.createElement("option");
      opt.value       = team.id;
      opt.textContent = team.name ?? team.id;
      this._defenderSelEl.appendChild(opt);
    }
  }

  // ── Location inputs ─────────────────────────────────────────────────────────

  _buildLocationInputs(room) {
    this._locationEl.innerHTML = "";
    const origLocation = { ...room.location };

    for (const [axis, key] of [["X", "x"], ["Y", "y"], ["Z", "z"]]) {
      const field = document.createElement("div");
      field.className = "detail-prefixed-field";

      const prefix = document.createElement("span");
      prefix.className  = "detail-prefix";
      prefix.textContent = axis;

      const input = document.createElement("input");
      input.type      = "number";
      input.step      = "any";
      input.className = "detail-bounds-input";
      input.value     = room.location[key] ?? 0;

      input.addEventListener("input", () => {
        const parsed = parseFloat(input.value);
        if (!isNaN(parsed)) room.location[key] = parsed;
      });

      input.addEventListener("blur", () => {
        const parsed = parseFloat(input.value);
        if (isNaN(parsed)) {
          input.value     = origLocation[key];
          room.location[key] = origLocation[key];
        } else {
          room.location[key] = parsed;
          input.value        = parsed;
          this._saveWoolLocation(room, origLocation);
        }
      });

      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); input.blur(); }
        if (e.key === "Escape") {
          e.preventDefault();
          room.location[key] = origLocation[key];
          input.value        = origLocation[key];
        }
      });

      field.append(prefix, input);
      this._locationEl.appendChild(field);
    }
  }

  // ── Save operations ─────────────────────────────────────────────────────────

  async _saveWoolColor(room) {
    if (!this._mapName) return;
    const newColor  = this._woolColorSelEl.value;
    const oldColor  = room.color;
    if (newColor === oldColor) return;

    try {
      for (const capture of room.captures) {
        await api.updateWool(this._mapName, capture.team, oldColor, { color: newColor });
      }
      room.color = newColor;
      this._onWoolSave();

      // Update the list row in-place
      const rowEl = this._woolListEl.querySelector(
        `[data-room-key="${CSS.escape(_roomKey({ ...room, color: oldColor }))}"]`,
      );
      if (rowEl) {
        rowEl.dataset.roomKey = _roomKey(room);
        const swatch = rowEl.querySelector(".obj-wool-swatch");
        const label  = rowEl.querySelector(".obj-wool-label");
        if (swatch) swatch.style.background = dyeColorHex(newColor);
        if (label)  label.textContent       = _capitalize(newColor);
      }
    } catch (err) {
      console.error("ObjectivePanel: failed to save wool color:", err);
    }
  }

  async _saveWoolDefender(room) {
    if (!this._mapName) return;
    const newDefenderId = this._defenderSelEl.value;
    // New capturing teams = all teams except the new defender
    const newCapturers = this._teams.filter(t => t.id !== newDefenderId);
    if (!newCapturers.length) return;

    try {
      for (let captureIndex = 0; captureIndex < room.captures.length; captureIndex++) {
        const capture    = room.captures[captureIndex];
        const newTeamId  = (newCapturers[captureIndex] ?? newCapturers[0]).id;
        await api.updateWool(this._mapName, capture.team, room.color, { team: newTeamId });
        capture.team = newTeamId;
      }
      room.defendingTeamId = newDefenderId || null;
      this._onWoolSave();
    } catch (err) {
      console.error("ObjectivePanel: failed to save wool defender:", err);
    }
  }

  async _saveWoolLocation(room, originalLocation) {
    if (!this._mapName || !room.captures.length) return;
    const { x, y, z } = room.location;
    try {
      // Location is room-level: the backend updates all entries sharing (color, old_location)
      const capture = room.captures[0];
      await api.updateWool(this._mapName, capture.team, room.color, {
        location: { x, y, z },
      });
      // Keep origLocation in sync for future Esc reverts
      originalLocation.x = x;
      originalLocation.y = y;
      originalLocation.z = z;
      this._onWoolSave();
    } catch (err) {
      console.error("ObjectivePanel: failed to save wool location:", err);
    }
  }

  async _deleteWool(room) {
    if (!this._mapName) return;
    try {
      for (const capture of room.captures) {
        await api.deleteWool(this._mapName, capture.team, room.color);
      }
      this._woolRooms = this._woolRooms.filter(r => r !== room);
      this._renderList();
      this._showEmpty();
      this._onWoolSave();
    } catch (err) {
      console.error("ObjectivePanel: failed to delete wool:", err);
    }
  }

  // ── Monument capture card (read-only) ────────────────────────────────────────

  _buildCaptureCard(capture) {
    const team = this._teams.find(t => t.id === capture.team);

    const card = document.createElement("div");
    card.className = "obj-capture-card";

    const header = document.createElement("div");
    header.className = "obj-capture-header";
    const dot = document.createElement("span");
    dot.className = "obj-team-dot";
    dot.style.background = chatColorHex(team?.color);
    const nameEl = document.createElement("span");
    nameEl.className = "obj-team-name";
    nameEl.textContent = team?.name ?? capture.team;
    header.append(dot, nameEl);
    card.appendChild(header);

    const monEl = document.createElement("div");
    monEl.className = "obj-capture-monument";
    this._renderCoords(monEl, capture.monument);

    if (capture.monument?.region_id) {
      const idRow = document.createElement("div");
      idRow.className = "obj-coord-row";
      const axisEl = document.createElement("span");
      axisEl.className = "obj-coord-axis";
      axisEl.textContent = "ID";
      const valEl = document.createElement("span");
      valEl.className = "obj-region-id";
      valEl.textContent = capture.monument.region_id;
      idRow.append(axisEl, valEl);
      monEl.appendChild(idRow);
    }

    card.appendChild(monEl);
    return card;
  }

  _renderCoords(el, coords) {
    el.innerHTML = "";
    for (const [axis, val] of [["X", coords?.x], ["Y", coords?.y], ["Z", coords?.z]]) {
      const row = document.createElement("div");
      row.className = "obj-coord-row";
      const axisEl = document.createElement("span");
      axisEl.className = "obj-coord-axis";
      axisEl.textContent = axis;
      const valEl = document.createElement("span");
      valEl.className = "obj-coord-value";
      valEl.textContent = val ?? "?";
      row.append(axisEl, valEl);
      el.appendChild(row);
    }
  }
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Stable string key for a room — used as data-room-key on list rows. */
function _roomKey(room) {
  return `${room.color}:${room.location.x},${room.location.y},${room.location.z}`;
}

/** "light blue" → "Light Blue" */
function _capitalize(str) {
  return (str ?? "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}
