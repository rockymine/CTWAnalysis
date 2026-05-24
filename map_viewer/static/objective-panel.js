/**
 * ObjectivePanel — left and right panel logic for the Objective activity.
 *
 * Left panel:  wool rooms grouped by defending team.
 *              A "wool room" is one distinct physical wool (unique color +
 *              location).  Multiple teams may need to capture the same wool
 *              room; the defending team is whichever team is NOT listed as a
 *              capturing team.
 *
 * Right panel: read-only inspector for the selected wool room:
 *              shared spawn location + one capture card per capturing team
 *              (team color, monument XYZ, optional region_id).
 */

import { chatColorHex, dyeColorHex } from "./game-colors.js";

export class ObjectivePanel {
  constructor({ onWoolSelect } = {}) {
    this._woolListEl  = document.getElementById("obj-wool-list");
    this._inspectorEl = document.getElementById("obj-wool-inspector");
    this._emptyEl     = document.getElementById("obj-inspector-empty");
    this._swatchEl    = document.getElementById("obj-inspector-swatch");
    this._titleEl     = document.getElementById("obj-inspector-title");
    this._defenderEl  = document.getElementById("obj-inspector-defender");
    this._locationEl  = document.getElementById("obj-inspector-location");
    this._capturesEl  = document.getElementById("obj-inspector-captures");

    this._onWoolSelect = onWoolSelect ?? (() => {});
    this._teams        = [];
    this._woolRooms    = [];   // derived, one entry per distinct wool room
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  load(mapData) {
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
   * 2-team maps this is exactly one team; for N-team maps it is still one
   * team per wool room.
   */
  _deriveWoolRooms(wools) {
    const roomMap = new Map();   // key → room object
    for (const wool of wools) {
      const key = `${wool.color}:${wool.location.x},${wool.location.y},${wool.location.z}`;
      if (!roomMap.has(key)) {
        roomMap.set(key, { color: wool.color, location: wool.location, captures: [] });
      }
      roomMap.get(key).captures.push({ team: wool.team, monument: wool.monument });
    }

    const allTeamIds = new Set(this._teams.map(t => t.id));
    const rooms = [...roomMap.values()];

    for (const room of rooms) {
      const capturingIds = new Set(room.captures.map(c => c.team));
      const defenders    = [...allTeamIds].filter(id => !capturingIds.has(id));
      room.defendingTeamId = defenders.length === 1 ? defenders[0] : null;
    }

    return rooms;
  }

  // ── List rendering ──────────────────────────────────────────────────────────

  _renderList() {
    this._woolListEl.innerHTML = "";

    for (const room of this._woolRooms) {
      const row = document.createElement("div");
      row.className = "obj-wool-row";

      const swatch = document.createElement("span");
      swatch.className = "obj-wool-swatch";
      swatch.style.background = dyeColorHex(room.color);

      const label = document.createElement("span");
      label.className = "obj-wool-label";
      label.textContent = _capitalize(room.color);

      row.append(swatch, label);
      row.addEventListener("click", () => this._selectRoom(room, row));
      this._woolListEl.appendChild(row);
    }
  }

  // ── Selection ───────────────────────────────────────────────────────────────

  _selectRoom(room, rowEl) {
    this._woolListEl.querySelectorAll(".obj-wool-row--selected")
      .forEach(el => el.classList.remove("obj-wool-row--selected"));
    rowEl.classList.add("obj-wool-row--selected");
    this._showInspector(room);
    this._onWoolSelect(room);
  }

  // ── Inspector ───────────────────────────────────────────────────────────────

  _showEmpty() {
    this._inspectorEl.hidden = true;
    this._emptyEl.hidden     = false;
  }

  _showInspector(room) {
    this._emptyEl.hidden     = true;
    this._inspectorEl.hidden = false;

    // Title row: swatch + "Lime Wool"
    this._swatchEl.style.background = dyeColorHex(room.color);
    this._titleEl.textContent       = `${_capitalize(room.color)} Wool`;

    // Defending team
    this._renderDefender(this._defenderEl, room.defendingTeamId);

    // Shared spawn location
    this._renderCoords(this._locationEl, room.location);

    // Per-team capture cards
    this._capturesEl.innerHTML = "";
    for (const capture of room.captures) {
      this._capturesEl.appendChild(this._buildCaptureCard(capture));
    }
  }

  _buildCaptureCard(capture) {
    const team = this._teams.find(t => t.id === capture.team);

    const card = document.createElement("div");
    card.className = "obj-capture-card";

    // Header: team color dot + team display name
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

    // Monument coordinates, indented under the team name
    const monEl = document.createElement("div");
    monEl.className = "obj-capture-monument";
    this._renderCoords(monEl, capture.monument);

    // Optional region_id reference
    if (capture.monument.region_id) {
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

  _renderDefender(el, teamId) {
    el.innerHTML = "";
    const team = this._teams.find(t => t.id === teamId);
    const dot = document.createElement("span");
    dot.className = "obj-team-dot";
    dot.style.background = chatColorHex(team?.color);
    const nameEl = document.createElement("span");
    nameEl.className = "obj-defender-name";
    nameEl.textContent = team?.name ?? teamId ?? "—";
    el.append(dot, nameEl);
  }

  _renderCoords(el, coords) {
    el.innerHTML = "";
    for (const [axis, val] of [["X", coords.x], ["Y", coords.y], ["Z", coords.z]]) {
      const row = document.createElement("div");
      row.className = "obj-coord-row";
      const axisEl = document.createElement("span");
      axisEl.className = "obj-coord-axis";
      axisEl.textContent = axis;
      const valEl = document.createElement("span");
      valEl.className = "obj-coord-value";
      valEl.textContent = val;
      row.append(axisEl, valEl);
      el.appendChild(row);
    }
  }
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/** "light blue" → "Light Blue" */
function _capitalize(str) {
  return (str ?? "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}
