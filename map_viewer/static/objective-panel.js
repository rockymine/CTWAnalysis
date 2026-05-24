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
    this._woolRoomSelEl     = document.getElementById("obj-wool-room-sel");
    this._woolRoomClearBtn  = document.getElementById("obj-wool-room-clear-btn");
    this._respawnBadgeEl    = document.getElementById("obj-respawn-badge");
    this._respawnDetailEl   = document.getElementById("obj-respawn-detail");
    this._woolXmlWrapEl     = document.getElementById("obj-wool-xml-wrap");
    this._woolXmlEl         = document.getElementById("obj-wool-xml");
    this._locationEl        = document.getElementById("obj-inspector-location");
    this._capturesEl        = document.getElementById("obj-inspector-captures");
    this._deleteWoolBtn     = document.getElementById("obj-delete-wool-btn");

    this._onWoolSelect    = onWoolSelect ?? (() => {});
    this._onWoolSave      = opts.onWoolSave   ?? (() => {});
    this._mapName         = null;
    this._teams           = [];
    this._woolRooms       = [];   // derived, one entry per distinct wool room
    this._woolRoomOptions = [];   // region IDs eligible as wool room candidates
    this._selectedRoom    = null; // currently selected wool room (for click-to-assign)

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
            this._updateWoolXml?.(status.wool_xml);
          }
        })
        .catch(() => {});
    }

    // ── Wool XML preview (built synchronously from room data + server XML) ──
    this._buildWoolXmlPreview(room);

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

  // ── Respawn detail card ──────────────────────────────────────────────────────

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

    const kv = (key, val) => {
      if (val == null || val === "") return;
      const row = document.createElement("div");
      row.className = "obj-respawn-kv";
      const k = document.createElement("span");
      k.className = "obj-respawn-kv-key";
      k.textContent = key;
      const v = document.createElement("span");
      v.className = "obj-respawn-kv-val";
      v.textContent = String(val);
      row.append(k, v);
      el.appendChild(row);
    };

    const xml = (src) => {
      if (!src) return;
      const pre = document.createElement("pre");
      pre.className = "detail-xml-pre";
      pre.textContent = src;
      el.appendChild(pre);
    };

    if (type === "chest") {
      // Group chest wool by color; sum item counts, deduplicate chest positions by (x,y,z)
      const byColor = new Map();
      for (const item of status.chest_wool ?? []) {
        const name = item.color_name ?? "wool";
        if (!byColor.has(name)) byColor.set(name, { count: 0, positions: new Set() });
        const entry = byColor.get(name);
        entry.count += item.count ?? 0;
        entry.positions.add(`${item.x},${item.y},${item.z}`);
      }
      if (byColor.size > 0) {
        for (const [color, { count, positions }] of byColor) {
          const n = positions.size;
          kv(color, `×${count}  (${n} chest${n !== 1 ? "s" : ""})`);
        }
      } else {
        kv("total", `${status.chest_wool_count} wool stack${status.chest_wool_count !== 1 ? "s" : ""}`);
      }

    } else if (type === "mob_spawner") {
      const s = status.mob_spawners?.[0];
      if (s) {
        const itemLabel = s.spawn_item_id
          ? s.spawn_item_id.replace("minecraft:", "") + (s.spawn_item_damage != null ? ` (dmg ${s.spawn_item_damage})` : "")
          : (s.entity_id ?? "—");
        kv("spawns", itemLabel);
        if (s.spawn_count != null)        kv("per activation", s.spawn_count);
        if (s.min_spawn_delay != null && s.max_spawn_delay != null)
          kv("delay", `${s.min_spawn_delay}–${s.max_spawn_delay} ticks`);
        if (s.spawn_range != null)            kv("spawn range", `${s.spawn_range} blocks`);
        if (s.required_player_range != null)  kv("activation", `${s.required_player_range} blocks`);
        if (s.max_nearby_entities != null)    kv("entity cap", s.max_nearby_entities);
        if (status.mob_spawner_count > 1)     kv("spawners", status.mob_spawner_count);
      }

    } else if (type === "pgm_spawner") {
      const s = status.pgm_spawner;
      if (s) {
        if (s.spawn_region)   kv("spawn region",  s.spawn_region);
        if (s.player_region)  kv("player region", s.player_region);
        if (s.max_entities != null) kv("max entities", s.max_entities);
        for (const item of s.items ?? []) {
          const dmgSuffix = item.damage != null ? ` (dmg ${item.damage})` : "";
          const amtSuffix = (item.amount ?? 1) !== 1 ? ` ×${item.amount}` : "";
          kv("item", `${item.material}${dmgSuffix}${amtSuffix}`);
        }
      }
      xml(status.pgm_spawner_xml);

    } else if (type === "renewable") {
      for (const r of status.renewables ?? []) {
        if (r.region_id)      kv("region",  r.region_id);
        if (r.renew_filter)   kv("renew",   r.renew_filter);
        if (r.replace_filter) kv("replace", r.replace_filter);
        if (r.rate != null && r.rate !== 1.0) kv("rate", r.rate);
      }
      for (const rule of status.block_drop_rules ?? []) {
        if (rule.filter_id)    kv("filter",      rule.filter_id);
        if (rule.replacement)  kv("replacement", rule.replacement);
        const items = rule.items ?? [];
        if (items.length > 0) kv("drops", items.map(i => i.material).join(", "));
      }
    }
  }

  // ── Wool XML preview ─────────────────────────────────────────────────────────

  _buildWoolXmlPreview(room) {
    // Shown immediately (synchronous) using a client-side reconstruction.
    // When the server response arrives it updates with the authoritative version.
    const wrapEl = this._woolXmlWrapEl;
    const xmlEl  = this._woolXmlEl;

    // Build a client-side preview from what we already know
    const team  = room.captures[0]?.team ?? "";
    const color = (room.color ?? "").replace(/_/g, " ");
    const region = room.woolRoomRegion ?? null;
    const loc = room.location;
    const mon = room.captures[0]?.monument;

    const lines = [`<wool team="${team}" color="${color}">`];
    if (region) {
      lines.push(`  <block region="${region}"/>`);
    } else if (loc) {
      lines.push(`  <!-- location: ${loc.x?.toFixed(1)}, ${loc.y?.toFixed(1)}, ${loc.z?.toFixed(1)} -->`);
    }
    if (mon) {
      lines.push("  <monument>");
      if (mon.region_id) {
        lines.push(`    <block region="${mon.region_id}"/>`);
      } else if (mon.x != null) {
        lines.push(`    <block>${Math.round(mon.x)} ${Math.round(mon.y ?? 0)} ${Math.round(mon.z)}</block>`);
      }
      lines.push("  </monument>");
    }
    lines.push("</wool>");

    const pre = document.createElement("pre");
    pre.className = "detail-xml-pre";
    pre.textContent = lines.join("\n");
    xmlEl.innerHTML = "";
    xmlEl.appendChild(pre);
    wrapEl.hidden = false;

    // When the full status arrives, replace with the server's authoritative XML.
    this._updateWoolXml = (woolXml) => {
      if (woolXml && this._selectedRoom === room) {
        const pre2 = document.createElement("pre");
        pre2.className = "detail-xml-pre";
        pre2.textContent = woolXml;
        xmlEl.innerHTML = "";
        xmlEl.appendChild(pre2);
      }
    };
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
