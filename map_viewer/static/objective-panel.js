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
import { typeIcon } from "./region-types.js";
import { coordGroup } from "./coord-group.js";
import * as api from "./api.js";
import { renderEmptyPlaceholder } from "./shared/ui-helpers.js";


export class ObjectivePanel {
  constructor(opts = {}) {
    const { onWoolSelect } = opts;
    // ── Left panel ──────────────────────────────────────────────────────────
    this._woolListEl   = document.getElementById("obj-wool-list");
    this._addWoolBtn   = document.getElementById("obj-add-wool-btn");
    this._regionListEl = document.getElementById("obj-region-list");

    // ── Right panel — shared ────────────────────────────────────────────────
    this._inspectorEl  = document.getElementById("obj-wool-inspector");
    this._emptyEl      = document.getElementById("obj-inspector-empty");

    // ── Right panel — inspector fields ──────────────────────────────────────
    this._woolColorSelEl    = document.getElementById("obj-wool-color-sel");
    this._woolColorSwatchEl = document.getElementById("obj-wool-color-swatch");
    this._defenderSelEl     = document.getElementById("obj-defender-sel");
    this._defenderSwatchEl  = document.getElementById("obj-defender-swatch");
    this._woolRoomSelEl     = document.getElementById("obj-wool-room-sel");
    this._woolRoomClearBtn  = document.getElementById("obj-wool-room-clear-btn");
    this._respawnBadgeEl    = document.getElementById("obj-respawn-badge");
    this._respawnDetailEl   = document.getElementById("obj-respawn-detail");
    this._locationEl        = document.getElementById("obj-inspector-location");
    this._capturesEl        = document.getElementById("obj-inspector-captures");
    this._deleteWoolBtn     = document.getElementById("obj-delete-wool-btn");

    this._onWoolSelect    = onWoolSelect ?? (() => {});
    this._onWoolSave      = opts.onWoolSave        ?? (() => {});
    this._onRegionRowClick = opts.onRegionRowClick ?? (() => {});
    this._mapName         = null;
    this._teams           = [];
    this._woolRooms       = [];   // derived, one entry per distinct wool room
    this._woolRoomOptions = [];   // region IDs eligible as wool room candidates
    this._selectedRoom    = null; // currently selected wool room (for click-to-assign)
    this._regionNodes     = [];   // flat list of obj-group region nodes (for sidebar)

    this._addWoolBtn?.addEventListener("click", () => this._addWool());
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  load(mapName, mapData) {
    this._mapName         = mapName;
    this._teams           = mapData.teams ?? [];
    this._woolRooms       = this._deriveWoolRooms(mapData.wools ?? []);
    this._woolRoomOptions = this._deriveWoolRoomOptions(mapData);
    this._selectedRoom    = null;
    this._renderList();
    this._showEmpty();
  }

  // ── Region sidebar ───────────────────────────────────────────────────────────

  /**
   * Populate the left-panel region list from the filtered region groups rendered
   * on the canvas (wool_room + monument categories).  Called once per map load.
   */
  loadRegions(objGroups) {
    this._regionNodes = this._flattenRegionNodes(objGroups);
    this._renderRegionList();
  }

  /**
   * Highlight the given region row (and deselect all others).
   * Pass null to clear all highlights.
   */
  highlightRegionRow(regionId) {
    for (const row of this._regionListEl.querySelectorAll(".list-row")) {
      row.classList.toggle("list-row--selected", row.dataset.regionId === regionId);
    }
  }

  // ── Public helpers for canvas interaction ───────────────────────────────────

  /** Returns true when a wool room is currently selected in the inspector. */
  hasSelectedWool() {
    return this._selectedRoom !== null;
  }

  /** Returns the wool_room_region ID of the currently selected wool, or null. */
  selectedWoolRoomRegion() {
    return this._selectedRoom?.woolRoomRegion ?? null;
  }

  /**
   * Assign regionId as the wool_room_region for the currently selected wool.
   * Called by ObjectiveActivity when the user clicks a region on the canvas
   * that does not belong to any existing wool room.
   */
  async assignWoolRoom(regionId) {
    if (!this._selectedRoom) return;
    this._woolRoomSelEl.value = regionId ?? "";
    await this._saveWoolRoom(this._selectedRoom, regionId);
  }

  /**
   * Select the wool room whose wool_room_region matches regionId.
   * Returns true if a match was found and selected, false otherwise.
   */
  selectRoomByRegion(regionId) {
    if (!regionId) return false;
    const room = this._woolRooms.find(r => r.woolRoomRegion === regionId);
    return room ? (this._selectRoomObject(room), true) : false;
  }

  /**
   * Select the wool room whose wool chest location matches (x, z).
   * Returns true if a match was found and selected, false otherwise.
   */
  selectRoomByLocation(x, z) {
    const room = this._woolRooms.find(
      r => Math.abs(r.location.x - x) < 1 && Math.abs(r.location.z - z) < 1,
    );
    return room ? (this._selectRoomObject(room), true) : false;
  }

  /**
   * Select the wool room that has a monument capture at (x, z).
   * Returns true if a match was found and selected, false otherwise.
   */
  selectRoomByMonument(x, z) {
    const room = this._woolRooms.find(r =>
      r.captures.some(c => Math.abs(c.monument.x - x) < 1 && Math.abs(c.monument.z - z) < 1),
    );
    return room ? (this._selectRoomObject(room), true) : false;
  }

  /** Internal: select a room object by finding its list row and calling _selectRoom. */
  _selectRoomObject(room) {
    const rowEl = this._woolListEl.querySelector(
      `[data-room-key="${CSS.escape(_roomKey(room))}"]`,
    );
    if (rowEl) this._selectRoom(room, rowEl);
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
          color:          wool.color,
          location:       { ...wool.location },
          captures:       [],
          woolRoomRegion: wool.wool_room_region ?? null,
        });
      } else if (roomMap.get(key).woolRoomRegion === null && wool.wool_room_region) {
        // Take the first non-null region ID found for this location
        roomMap.get(key).woolRoomRegion = wool.wool_room_region;
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

  /**
   * Build the list of region IDs eligible to appear in the Room Region dropdown.
   * Includes all regions except those in the "spawn" and "build" categories.
   */
  _deriveWoolRoomOptions(mapData) {
    const cats = mapData.region_categories ?? {};
    const excluded = new Set([
      ...(cats.spawn ?? []),
      ...(cats.build ?? []),
    ]);
    const allIds = Object.keys(mapData.regions ?? {});
    return allIds.filter(id => !excluded.has(id)).sort();
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
    row.className = "list-row";
    row.dataset.roomKey = _roomKey(room);

    const swatch = document.createElement("span");
    swatch.className = "list-swatch";
    swatch.style.background = dyeColorHex(room.color);

    const label = document.createElement("span");
    label.className = "list-label";
    label.textContent = _capitalize(room.color);

    row.append(swatch, label);
    row.addEventListener("click", () => this._selectRoom(room, row));
    return row;
  }

  // ── Selection ───────────────────────────────────────────────────────────────

  _selectRoom(room, rowEl) {
    this._woolListEl.querySelectorAll(".list-row--selected")
      .forEach(el => el.classList.remove("list-row--selected"));
    rowEl.classList.add("list-row--selected");
    this._selectedRoom = room;
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
    this._selectedRoom       = null;
  }

  _showInspector(room) {
    this._emptyEl.hidden     = true;
    this._inspectorEl.hidden = false;

    // Clone interactive elements to clear stale listeners
    this._woolColorSelEl.replaceWith(this._woolColorSelEl.cloneNode(false));
    this._woolColorSelEl    = document.getElementById("obj-wool-color-sel");
    this._defenderSelEl.replaceWith(this._defenderSelEl.cloneNode(false));
    this._defenderSelEl     = document.getElementById("obj-defender-sel");
    this._woolRoomSelEl.replaceWith(this._woolRoomSelEl.cloneNode(false));
    this._woolRoomSelEl     = document.getElementById("obj-wool-room-sel");
    this._woolRoomClearBtn.replaceWith(this._woolRoomClearBtn.cloneNode(true));
    this._woolRoomClearBtn  = document.getElementById("obj-wool-room-clear-btn");
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

    // ── Room region dropdown ────────────────────────────────────────────────
    this._buildWoolRoomDropdown(room.woolRoomRegion);
    this._woolRoomSelEl.addEventListener("change", () => {
      const selected = this._woolRoomSelEl.value || null;
      this._saveWoolRoom(room, selected);
    });
    this._woolRoomClearBtn.addEventListener("click", () => {
      this._woolRoomSelEl.value = "";
      this._saveWoolRoom(room, null);
    });

    // ── Respawn type (async — fetched from server) ──────────────────────────
    this._updateRespawnBadge("unknown");
    this._respawnDetailEl.hidden = true;
    this._respawnDetailEl.innerHTML = "";

    if (this._mapName && room.captures.length) {
      const { team, color } = { team: room.captures[0].team, color: room.color };
      api.fetchWoolRoomStatus(this._mapName, team, color)
        .then(status => {
          if (status && this._selectedRoom === room) {
            this._updateRespawnBadge(
              status.respawn_type ?? "unknown",
              status.mob_entity_types ?? [],
            );
            this._buildRespawnDetail(status);
          }
        })
        .catch(() => {});
    }

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

  _buildWoolRoomDropdown(currentRegionId) {
    this._woolRoomSelEl.innerHTML = "";
    const noneOpt = document.createElement("option");
    noneOpt.value       = "";
    noneOpt.textContent = "— none —";
    this._woolRoomSelEl.appendChild(noneOpt);
    for (const regionId of this._woolRoomOptions) {
      const opt = document.createElement("option");
      opt.value       = regionId;
      opt.textContent = regionId;
      this._woolRoomSelEl.appendChild(opt);
    }
    this._woolRoomSelEl.value = currentRegionId ?? "";
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

    // Build the group row via the shared helper, then move its children into
    // _locationEl (which IS the detail-group-row container in the HTML template).
    const row = coordGroup([
      { axis: "X", value: room.location.x, origValue: origLocation.x,
        onChange: (v) => { room.location.x = v; },
        onSave:   () => { this._saveWoolLocation(room, origLocation); },
        onRevert: () => { room.location.x = origLocation.x; } },
      { axis: "Y", value: room.location.y, origValue: origLocation.y,
        onChange: (v) => { room.location.y = v; },
        onSave:   () => { this._saveWoolLocation(room, origLocation); },
        onRevert: () => { room.location.y = origLocation.y; } },
      { axis: "Z", value: room.location.z, origValue: origLocation.z,
        onChange: (v) => { room.location.z = v; },
        onSave:   () => { this._saveWoolLocation(room, origLocation); },
        onRevert: () => { room.location.z = origLocation.z; } },
    ]);
    while (row.firstChild) this._locationEl.appendChild(row.firstChild);
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
        const swatch = rowEl.querySelector(".list-swatch");
        const label  = rowEl.querySelector(".list-label");
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

  async _saveWoolRoom(room, regionId) {
    if (!this._mapName || !room.captures.length) return;
    try {
      const capture = room.captures[0];
      await api.updateWool(this._mapName, capture.team, room.color, {
        wool_room_region: regionId,
      });
      room.woolRoomRegion = regionId;
      this._onWoolSave();
    } catch (err) {
      console.error("ObjectivePanel: failed to save wool room region:", err);
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

  // ── Respawn badge ────────────────────────────────────────────────────────────

  _updateRespawnBadge(type, mobEntityTypes = []) {
    const LABELS = {
      chest:       "Chest",
      pgm_spawner: "PGM Spawner",
      mob_spawner: "Mob Spawner",
      renewable:   "Renewable",
      unknown:     "Unknown",
    };
    const el = this._respawnBadgeEl;
    // Remove all respawn modifier classes
    el.className = "obj-respawn-badge";
    el.classList.add(`obj-respawn-${type}`);

    let label = LABELS[type] ?? type;
    if (type === "mob_spawner" && mobEntityTypes.length > 0) {
      label += ` (${mobEntityTypes.join(", ")})`;
    }
    el.textContent = label;
  }

  // ── Respawn detail fields ────────────────────────────────────────────────────

  _buildRespawnDetail(status) {
    const el = this._respawnDetailEl;
    const type = status?.respawn_type ?? "unknown";

    if (type === "unknown") {
      el.hidden = true;
      return;
    }

    el.hidden = false;
    el.innerHTML = "";
    el.className = `obj-respawn-detail obj-respawn-detail--${type}`;

    // ── field builders ────────────────────────────────────────────────────────

    const mkField = (label, value, inputType = "text") => {
      const wrap = document.createElement("div");
      wrap.className = "field";
      const lbl = document.createElement("label");
      lbl.className = "field-label";
      lbl.textContent = label;
      const inp = document.createElement("input");
      inp.type = inputType;
      inp.className = "field-input";
      inp.value = value ?? "";
      inp.disabled = true;
      inp.spellcheck = false;
      wrap.append(lbl, inp);
      return wrap;
    };

    const mkFieldRow = (...fields) => {
      const row = document.createElement("div");
      row.className = "field-row";
      for (const f of fields) row.appendChild(f);
      return row;
    };

    // Mark a field as narrow (for Amount / numeric columns in a field-row).
    const compact = (fieldEl) => { fieldEl.classList.add("field--compact"); return fieldEl; };

    // ── per-type layout ───────────────────────────────────────────────────────

    if (type === "chest") {
      // Group chest wool by color; sum counts across chests
      const byColor = new Map();
      for (const item of status.chest_wool ?? []) {
        const name = item.color_name ?? "wool";
        if (!byColor.has(name)) byColor.set(name, 0);
        byColor.set(name, byColor.get(name) + (item.count ?? 0));
      }
      if (byColor.size > 0) {
        for (const [color, count] of byColor) {
          el.appendChild(mkFieldRow(
            mkField("Item", color),
            compact(mkField("Amount", count, "number")),
          ));
        }
      } else if (status.chest_wool_count) {
        el.appendChild(mkFieldRow(
          mkField("Item", "wool"),
          compact(mkField("Amount", status.chest_wool_count, "number")),
        ));
      }

    } else if (type === "mob_spawner") {
      const s = status.mob_spawners?.[0];
      if (s) {
        const itemLabel = s.spawn_item_id
          ? s.spawn_item_id.replace("minecraft:", "") +
            (s.spawn_item_damage != null ? ` (dmg ${s.spawn_item_damage})` : "")
          : (s.entity_id ?? "—");
        el.appendChild(mkFieldRow(
          mkField("Item", itemLabel),
          compact(mkField("Amount", s.spawn_count ?? "", "number")),
        ));
        if (s.spawn_range != null || s.required_player_range != null) {
          el.appendChild(mkFieldRow(
            mkField("Range",      s.spawn_range ?? ""),
            mkField("Activation", s.required_player_range ?? ""),
          ));
        }
        if (s.min_spawn_delay != null && s.max_spawn_delay != null) {
          const delay = s.min_spawn_delay === s.max_spawn_delay
            ? String(s.min_spawn_delay)
            : `${s.min_spawn_delay}–${s.max_spawn_delay}`;
          el.appendChild(mkField("Delay", delay));
        }
        if (s.max_nearby_entities != null) {
          el.appendChild(mkField("Entity Cap", s.max_nearby_entities, "number"));
        }
        if (status.mob_spawner_count > 1) {
          el.appendChild(mkField("Spawners", status.mob_spawner_count, "number"));
        }
      }

    } else if (type === "pgm_spawner") {
      const s = status.pgm_spawner;
      if (s) {
        if (s.spawn_region)         el.appendChild(mkField("Spawn Region",  s.spawn_region));
        if (s.player_region)        el.appendChild(mkField("Player Region", s.player_region));
        if (s.max_entities != null) el.appendChild(mkField("Max Entities",  s.max_entities, "number"));
        for (const item of s.items ?? []) {
          const matLabel = item.material + (item.damage != null ? ` (dmg ${item.damage})` : "");
          el.appendChild(mkFieldRow(
            mkField("Item", matLabel),
            compact(mkField("Amount", item.amount ?? 1, "number")),
          ));
        }
      }

    } else if (type === "renewable") {
      for (const r of status.renewables ?? []) {
        if (r.region_id)      el.appendChild(mkField("Region",  r.region_id));
        if (r.renew_filter)   el.appendChild(mkField("Renew",   r.renew_filter));
        if (r.replace_filter) el.appendChild(mkField("Replace", r.replace_filter));
        if (r.rate != null && r.rate !== 1.0) el.appendChild(mkField("Rate", r.rate, "number"));
      }
      for (const rule of status.block_drop_rules ?? []) {
        if (rule.filter_id)   el.appendChild(mkField("Filter",      rule.filter_id));
        if (rule.replacement) el.appendChild(mkField("Replacement", rule.replacement));
        const items = rule.items ?? [];
        if (items.length > 0) el.appendChild(mkField("Drops", items.map(i => i.material).join(", ")));
      }
    }
  }

  // ── Monument capture group ────────────────────────────────────────────────────

  /**
   * Build one "MONUMENT" group for a single capture entry.
   * Uses the same field / field-label / field-input / detail-prefixed-field
   * input styles as the rest of the inspector, with all inputs disabled.
   */
  _buildCaptureCard(capture) {
    const team = this._teams.find(t => t.id === capture.team);
    const mon  = capture.monument ?? {};

    const group = document.createElement("div");
    group.className = "obj-monument-group";

    // ── Section title ────────────────────────────────────────────────────────
    const titleRow = document.createElement("div");
    titleRow.className = "section-header section-header--ruled";
    const title = document.createElement("h3");
    title.className = "section-title";
    title.textContent = "Monument";
    titleRow.appendChild(title);
    group.appendChild(titleRow);

    // ── Team ─────────────────────────────────────────────────────────────────
    const teamField = document.createElement("div");
    teamField.className = "field";

    const teamLabel = document.createElement("label");
    teamLabel.className = "field-label";
    teamLabel.textContent = "Team";

    const teamPickRow = document.createElement("div");
    teamPickRow.className = "field-pick-row";

    const teamSwatch = document.createElement("span");
    teamSwatch.className = "field-swatch";
    teamSwatch.style.background = chatColorHex(team?.color);

    const teamSel = document.createElement("select");
    teamSel.className = "field-input";
    teamSel.disabled = true;
    const teamOpt = document.createElement("option");
    teamOpt.value       = capture.team;
    teamOpt.textContent = team?.name ?? capture.team;
    teamSel.appendChild(teamOpt);

    teamPickRow.append(teamSwatch, teamSel);
    teamField.append(teamLabel, teamPickRow);
    group.appendChild(teamField);

    // ── ID (only if the monument is backed by a named region) ─────────────────
    if (mon.region_id) {
      const idField = document.createElement("div");
      idField.className = "field";

      const idLabel = document.createElement("label");
      idLabel.className = "field-label";
      idLabel.textContent = "ID";

      const idInput = document.createElement("input");
      idInput.type      = "text";
      idInput.className = "field-input";
      idInput.value     = mon.region_id;
      idInput.disabled  = true;
      idInput.spellcheck = false;

      idField.append(idLabel, idInput);
      group.appendChild(idField);
    }

    // ── Block coords ─────────────────────────────────────────────────────────
    const blockField = document.createElement("div");
    blockField.className = "field";

    const blockLabel = document.createElement("label");
    blockLabel.className = "field-label";
    blockLabel.textContent = "Block";

    const blockRow = coordGroup([
      { axis: "X", value: mon.x ?? 0, disabled: true },
      { axis: "Y", value: mon.y ?? 0, disabled: true },
      { axis: "Z", value: mon.z ?? 0, disabled: true },
    ]);

    blockField.append(blockLabel, blockRow);
    group.appendChild(blockField);

    return group;
  }

  // ── Region list rendering ─────────────────────────────────────────────────

  /**
   * Walk the groups tree and collect every named, non-negative, non-composite
   * region node that has bounds — the same set the canvas renders.
   */
  _flattenRegionNodes(groups) {
    const COMPOSITE_TYPES = new Set(["union", "intersect", "negative", "complement"]);
    const out = [];
    const walk = (items) => {
      for (const item of items ?? []) {
        if (item.regions) {
          walk(item.regions);
        } else {
          if (item.id && item.bounds && !item.is_negative && !COMPOSITE_TYPES.has(item.type)) {
            out.push(item);
          }
          walk(item.children);
        }
      }
    };
    walk(groups);
    return out;
  }

  _renderRegionList() {
    this._regionListEl.innerHTML = "";
    if (this._regionNodes.length === 0) {
      renderEmptyPlaceholder(this._regionListEl, "No wool room or monument regions.");
      return;
    }
    for (const node of this._regionNodes) {
      this._regionListEl.appendChild(this._buildRegionRow(node));
    }
  }

  _buildRegionRow(node) {
    const row = document.createElement("div");
    row.className = "list-row list-row--compact";
    row.dataset.regionId = node.id;

    const iconEl = typeIcon(node.type, node.synthetic_id ?? false);

    const label = document.createElement("span");
    label.className = "list-label list-label--mono";
    label.textContent = node.id;

    row.append(iconEl, label);
    row.addEventListener("click", () => this._onRegionRowClick(node.id));
    return row;
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
