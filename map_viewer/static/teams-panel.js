/**
 * TeamsPanel — left and right panel logic for the Teams activity.
 *
 * Left panel (top):    list of teams with color swatches; "+ Add team" button.
 * Left panel (bottom): list of spawn-category regions with linked team info.
 * Right panel:         context-sensitive — team config OR RegionDetail + spawn
 *                      assignment (team/yaw/kit).
 *
 * Canvas selection is owned by the activity's RegionRegistry. This panel only
 * receives onRegionSelect(node) / onRegionDeselect() notifications and manages
 * the right-panel DOM accordingly.
 */

import { RegionDetail } from "./region-detail.js";
import * as api         from "./api.js";

/**
 * PGM chat colors — the `color` field on a team element.
 * Hex values are the standard Minecraft chat-color palette.
 * Values use spaces (matching PGM XML / map_data.json output).
 */
export const PGM_CHAT_COLORS = [
  { value: "black",        label: "Black",        hex: "#000000" },
  { value: "dark blue",    label: "Dark Blue",    hex: "#0000AA" },
  { value: "dark green",   label: "Dark Green",   hex: "#00AA00" },
  { value: "dark aqua",    label: "Dark Aqua",    hex: "#00AAAA" },
  { value: "dark red",     label: "Dark Red",     hex: "#AA0000" },
  { value: "dark purple",  label: "Dark Purple",  hex: "#AA00AA" },
  { value: "gold",         label: "Gold",         hex: "#FFAA00" },
  { value: "gray",         label: "Gray",         hex: "#AAAAAA" },
  { value: "dark gray",    label: "Dark Gray",    hex: "#555555" },
  { value: "blue",         label: "Blue",         hex: "#5555FF" },
  { value: "green",        label: "Green",        hex: "#55FF55" },
  { value: "aqua",         label: "Aqua",         hex: "#55FFFF" },
  { value: "red",          label: "Red",          hex: "#FF5555" },
  { value: "light purple", label: "Light Purple", hex: "#FF55FF" },
  { value: "yellow",       label: "Yellow",       hex: "#FFFF55" },
  { value: "white",        label: "White",        hex: "#FFFFFF" },
];

/**
 * Minecraft dye colors — the `dye_color` field on a team element.
 * Hex values are the armor-dye palette from pgm.dev/docs/reference/misc/colors.
 */
export const MINECRAFT_DYE_COLORS = [
  { value: "white",      label: "White",      hex: "#FFFFFF" },
  { value: "orange",     label: "Orange",     hex: "#D87F33" },
  { value: "magenta",    label: "Magenta",    hex: "#B24CD8" },
  { value: "light blue", label: "Light Blue", hex: "#6699D8" },
  { value: "yellow",     label: "Yellow",     hex: "#E5E533" },
  { value: "lime",       label: "Lime",       hex: "#7FCC19" },
  { value: "pink",       label: "Pink",       hex: "#F27FA5" },
  { value: "gray",       label: "Gray",       hex: "#4C4C4C" },
  { value: "silver",     label: "Silver",     hex: "#999999" },
  { value: "cyan",       label: "Cyan",       hex: "#4C7F99" },
  { value: "purple",     label: "Purple",     hex: "#7F3FB2" },
  { value: "blue",       label: "Blue",       hex: "#334CB2" },
  { value: "brown",      label: "Brown",      hex: "#664C33" },
  { value: "green",      label: "Green",      hex: "#667F33" },
  { value: "red",        label: "Red",        hex: "#993333" },
  { value: "black",      label: "Black",      hex: "#191919" },
];

/** Resolve a PGM chat color name → hex, falling back to a neutral gray. */
function colorHex(colorName) {
  // Normalise underscore variants (e.g. "dark_purple" → "dark purple")
  const normalised = (colorName ?? "").replace(/_/g, " ").toLowerCase();
  return PGM_CHAT_COLORS.find(c => c.value === normalised)?.hex ?? "#475569";
}

/** Resolve a Minecraft dye color name → hex, falling back to a neutral gray. */
function dyeColorHex(colorName) {
  const normalised = (colorName ?? "").replace(/_/g, " ").toLowerCase();
  return MINECRAFT_DYE_COLORS.find(c => c.value === normalised)?.hex ?? "#475569";
}

export class TeamsPanel {
  /**
   * @param {{
   *   onStatusChange?:  (status: string|null) => void,
   *   onSpawnRowClick?: (regionId: string) => void,
   *   onDeselectRegion?: () => void,
   *   onBoundsChange?:  (node, bounds) => void,
   *   onBoundsSave?:    (node, bounds) => void,
   *   onCoordsChange?:  (node, coords) => void,
   *   onCoordsSave?:    (node, coords) => void,
   *   onRegionRename?:  (node, oldId, newId) => void,
   * }} opts
   */
  constructor(opts = {}) {
    this._mapName          = null;
    this._teams            = [];   // team objects from map_data.json
    this._spawns           = [];   // spawn link objects from map_data.json
    this._spawnRegions     = [];   // spawn-category region nodes from /regions
    this._selectedTeamId   = null;
    this._selectedSpawnId  = null;  // read by activity's Delete handler

    // Routing callbacks provided by the activity
    this._opts = opts;

    // DOM refs — left panel
    this._teamsListEl  = document.getElementById("pt-teams-list");
    this._spawnListEl  = document.getElementById("pt-spawn-list");
    this._addTeamBtn   = document.getElementById("pt-add-team-btn");

    // DOM refs — right panel
    this._teamInspEl       = document.getElementById("pt-team-inspector");
    this._spawnInspEl      = document.getElementById("pt-spawn-inspector");
    this._spawnAssignEl    = document.getElementById("pt-spawn-assignment");
    this._emptyEl          = document.getElementById("pt-inspector-empty");

    // Team inspector inputs
    this._teamIdInput        = document.getElementById("pt-team-id");
    this._teamNameInput      = document.getElementById("pt-team-name");
    this._teamColorSel       = document.getElementById("pt-team-color");
    this._teamColorSwatch    = document.getElementById("pt-team-color-swatch");
    this._teamDyeColorSel    = document.getElementById("pt-team-dye-color");
    this._teamDyeColorSwatch = document.getElementById("pt-team-dye-color-swatch");
    this._teamMaxInput       = document.getElementById("pt-team-max");
    this._teamMinInput       = document.getElementById("pt-team-min");

    // Spawn assignment inputs (inside #pt-spawn-assignment)
    this._spawnTeamSel    = document.getElementById("pt-spawn-team");
    this._spawnYawInput   = document.getElementById("pt-spawn-yaw");
    this._spawnKitInput   = document.getElementById("pt-spawn-kit");
    this._spawnUnlinkBtn  = document.getElementById("pt-spawn-unlink-btn");

    // RegionDetail — lazily created on first use so the constructor doesn't
    // crash when the browser serves a stale-cached HTML without #pt-spawn-region-detail.
    this._detail     = null;
    this._detailOpts = {
      onBoundsChange: opts.onBoundsChange ?? null,
      onBoundsSave:   opts.onBoundsSave   ?? null,
      onCoordsChange: opts.onCoordsChange ?? null,
      onCoordsSave:   opts.onCoordsSave   ?? null,
      onIdChange: (node, oldId, newId) => this._handleRegionRename(node, oldId, newId),
    };

    this._buildColorDropdown();
    this._attachStaticListeners();
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  /**
   * Returns the currently-selected spawn region id, or null.
   * Preferred over accessing _selectedSpawnId directly from outside this class.
   */
  getSelectedRegionId() {
    return this._selectedSpawnId;
  }

  /** Load all teams + spawn data for the given map. */
  async load(mapName) {
    this._mapName = mapName;
    this._selectedTeamId  = null;
    this._selectedSpawnId = null;
    this._showEmptyState();

    try {
      const [mapData, regionGroups] = await Promise.all([
        api.fetchMapData(mapName),
        api.fetchRegions(mapName),
      ]);
      this._teams  = mapData.teams  ?? [];
      this._spawns = mapData.spawns ?? [];
      const linkedIds = this._spawnLinkedRegionIds(mapData);
      this._spawnRegions = this._extractSpawnRegions(regionGroups, linkedIds);
      this._renderTeamsList();
      this._renderSpawnList();
      this._updateStatusDot();
    } catch (err) {
      console.error("TeamsPanel load failed:", err);
    }
  }

  /**
   * Reload only the spawn list (used after delete/undo/redo — no full reload).
   * Does NOT reload teams or reset selection.
   */
  async reloadSpawnList(mapName) {
    try {
      const [mapData, regionGroups] = await Promise.all([
        api.fetchMapData(mapName),
        api.fetchRegions(mapName),
      ]);
      this._spawns = mapData.spawns ?? [];
      const linkedIds = this._spawnLinkedRegionIds(mapData);
      this._spawnRegions = this._extractSpawnRegions(regionGroups, linkedIds);
      this._renderSpawnList();
      this._updateStatusDot();
    } catch (err) {
      console.error("TeamsPanel reloadSpawnList failed:", err);
    }
  }

  /**
   * Called by the activity's registry when a spawn region is selected on the
   * canvas or via the spawn row list.
   */
  onRegionSelect(node) {
    this._selectedSpawnId = node.id;
    this._selectedTeamId  = null;
    this._highlightSpawnRow(node.id);
    this._clearTeamHighlight();
    this._teamInspEl.hidden  = true;
    this._spawnInspEl.hidden = false;
    this._emptyEl.hidden     = true;
    if (this._ensureDetail()) this._detail.show(node);
    this._populateSpawnAssignment(node.id);
  }

  /** Called when the canvas selection is cleared (empty click or after delete). */
  onRegionDeselect() {
    this._selectedSpawnId = null;
    this._clearSpawnHighlight();
    this._detail?.clear();
    this._showEmptyState();
  }

  /**
   * Called by the activity when the canvas finishes drawing a new region.
   * Creates the region (with category=spawn) and a spawn link.
   * Returns the new region id so the activity can select it.
   */
  async onCanvasDraw(mapName, drawResult, createRegionFn) {
    try {
      const payload        = { ...drawResult, category: "spawn" };
      const { id: newId }  = await createRegionFn(payload);
      await api.addSpawn(mapName, {
        region_id: newId,
        team:      this._selectedTeamId ?? "",
        yaw:       0,
        kit:       "",
      });
      return newId;
    } catch (err) {
      console.error("Failed to create spawn region:", err);
      return null;
    }
  }

  /** Return the spawn link object for a region id, or null if none. */
  getSpawnLink(regionId) {
    return this._spawnForRegion(regionId);
  }

  // ── Private: lazy RegionDetail ────────────────────────────────────────────

  /** Create the RegionDetail instance on first use (guards against stale HTML cache). */
  _ensureDetail() {
    if (this._detail) return true;
    const el = document.getElementById("pt-spawn-region-detail");
    if (!el) return false;
    this._detail = new RegionDetail(el, this._detailOpts);
    return true;
  }

  // ── Private: data helpers ──────────────────────────────────────────────────

  /**
   * Build the set of region IDs explicitly referenced by spawn links or
   * observer_spawn.  Only these should appear in the spawn list; regions in
   * the spawn category that are merely targeted by wool spawners are excluded.
   */
  _spawnLinkedRegionIds(mapData) {
    const ids = new Set();
    for (const spawn of mapData.spawns ?? []) {
      const ref = spawn.region;
      if (!ref) continue;
      const id = typeof ref === "string" ? ref : ref.id;
      if (id) ids.add(id);
    }
    const obs = mapData.observer_spawn;
    if (obs) {
      const id = typeof obs === "string" ? obs : (obs.id ?? obs.region?.id);
      if (id) ids.add(id);
    }
    return ids;
  }

  /**
   * Walk /regions groups and return only nodes whose IDs appear in linkedIds.
   * Falls back to all spawn-category nodes when linkedIds is empty (new map).
   */
  _extractSpawnRegions(groups, linkedIds) {
    const spawnGroups = groups.filter(g => g.name === "spawn_area" || g.name === "spawn_point");
    const collected   = [];
    const flatten = (nodes) => {
      for (const node of nodes ?? []) {
        if (node.id && (linkedIds.size === 0 || linkedIds.has(node.id))) {
          collected.push(node);
        }
        flatten(node.children);
      }
    };
    for (const group of spawnGroups) flatten(group.regions);
    return collected;
  }

  /** Find the spawn link whose region ref matches regionId. */
  _spawnForRegion(regionId) {
    return this._spawns.find(s => {
      const ref = s.region;
      if (!ref) return false;
      return typeof ref === "string" ? ref === regionId : ref.id === regionId;
    }) ?? null;
  }

  // ── Private: rendering ─────────────────────────────────────────────────────

  _renderTeamsList() {
    this._teamsListEl.innerHTML = "";
    if (this._teams.length === 0) {
      const el = document.createElement("div");
      el.className = "pt-spawn-empty";
      el.textContent = 'No teams yet. Click "+ Add team".';
      this._teamsListEl.appendChild(el);
      return;
    }
    for (const team of this._teams) {
      this._teamsListEl.appendChild(this._buildTeamRow(team));
    }
  }

  _buildTeamRow(team) {
    const row = document.createElement("div");
    row.className = "pt-team-row";
    row.dataset.teamId = team.id;
    if (team.id === this._selectedTeamId) row.classList.add("pt-team-row--selected");

    const swatch = document.createElement("span");
    swatch.className = "pt-team-swatch";
    swatch.style.background = colorHex(team.color);

    const label = document.createElement("span");
    label.className = "pt-team-label";
    label.textContent = team.name || team.id;

    const deleteBtn = document.createElement("button");
    deleteBtn.className = "pt-team-delete-btn";
    deleteBtn.title = "Delete team";
    deleteBtn.textContent = "✕";
    deleteBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      this._deleteTeam(team.id);
    });

    row.appendChild(swatch);
    row.appendChild(label);
    row.appendChild(deleteBtn);
    row.addEventListener("click", () => this._selectTeam(team.id));
    return row;
  }

  _renderSpawnList() {
    this._spawnListEl.innerHTML = "";
    if (this._spawnRegions.length === 0) {
      const el = document.createElement("div");
      el.className = "pt-spawn-empty";
      el.textContent = "No spawn regions. Draw a cylinder or point on the canvas.";
      this._spawnListEl.appendChild(el);
      return;
    }
    for (const region of this._spawnRegions) {
      this._spawnListEl.appendChild(this._buildSpawnRow(region));
    }
  }

  _buildSpawnRow(region) {
    const spawnLink = this._spawnForRegion(region.id);
    const teamId    = spawnLink?.team ?? null;
    const team      = this._teams.find(t => t.id === teamId) ?? null;

    const row = document.createElement("div");
    row.className = "pt-spawn-row";
    row.dataset.regionId = region.id;
    if (region.id === this._selectedSpawnId) row.classList.add("pt-spawn-row--selected");

    const dot = document.createElement("span");
    dot.className = "pt-spawn-team-dot";
    if (team) dot.style.background = colorHex(team.color);

    const labelEl = document.createElement("span");
    labelEl.className = "pt-spawn-label";
    labelEl.textContent = region.id;

    const tagEl = document.createElement("span");
    tagEl.className = "pt-spawn-team-tag";
    tagEl.textContent = team ? (team.name || team.id) : "—";

    row.appendChild(dot);
    row.appendChild(labelEl);
    row.appendChild(tagEl);
    // Route through the activity's registry so canvas + panel stay in sync
    row.addEventListener("click", () => this._opts.onSpawnRowClick?.(region.id));
    return row;
  }

  // ── Private: team selection ────────────────────────────────────────────────

  _selectTeam(teamId) {
    // Deselect any active canvas (spawn) selection first
    this._opts.onDeselectRegion?.();
    this._selectedTeamId  = teamId;
    this._selectedSpawnId = null;
    this._highlightTeamRow(teamId);
    this._clearSpawnHighlight();
    const team = this._teams.find(t => t.id === teamId);
    if (team) this._showTeamInspector(team);
  }

  _highlightTeamRow(teamId) {
    for (const row of this._teamsListEl.querySelectorAll(".pt-team-row")) {
      row.classList.toggle("pt-team-row--selected", row.dataset.teamId === teamId);
    }
  }

  _clearTeamHighlight() {
    for (const row of this._teamsListEl.querySelectorAll(".pt-team-row")) {
      row.classList.remove("pt-team-row--selected");
    }
  }

  _highlightSpawnRow(regionId) {
    for (const row of this._spawnListEl.querySelectorAll(".pt-spawn-row")) {
      row.classList.toggle("pt-spawn-row--selected", row.dataset.regionId === regionId);
    }
  }

  _clearSpawnHighlight() {
    for (const row of this._spawnListEl.querySelectorAll(".pt-spawn-row")) {
      row.classList.remove("pt-spawn-row--selected");
    }
  }

  // ── Private: inspector population ─────────────────────────────────────────

  _showEmptyState() {
    this._teamInspEl.hidden  = true;
    this._spawnInspEl.hidden = true;
    this._emptyEl.hidden     = false;
    this._detail?.clear();
  }

  _showTeamInspector(team) {
    this._teamInspEl.hidden  = false;
    this._spawnInspEl.hidden = true;
    this._emptyEl.hidden     = true;

    // Remove old listeners before re-populating
    this._teamIdInput.replaceWith(this._teamIdInput.cloneNode(true));
    this._teamIdInput    = document.getElementById("pt-team-id");
    this._teamNameInput.replaceWith(this._teamNameInput.cloneNode(true));
    this._teamNameInput  = document.getElementById("pt-team-name");
    this._teamColorSel.replaceWith(this._teamColorSel.cloneNode(false));
    this._teamColorSel   = document.getElementById("pt-team-color");
    this._teamDyeColorSel.replaceWith(this._teamDyeColorSel.cloneNode(false));
    this._teamDyeColorSel = document.getElementById("pt-team-dye-color");
    this._teamMaxInput.replaceWith(this._teamMaxInput.cloneNode(true));
    this._teamMaxInput   = document.getElementById("pt-team-max");
    this._teamMinInput.replaceWith(this._teamMinInput.cloneNode(true));
    this._teamMinInput   = document.getElementById("pt-team-min");
    this._teamColorSwatch    = document.getElementById("pt-team-color-swatch");
    this._teamDyeColorSwatch = document.getElementById("pt-team-dye-color-swatch");

    // Normalise underscore variants that may appear in older map_data.json files
    const chatColor = (team.color ?? "dark red").replace(/_/g, " ");
    const dyeColor  = (team.dye_color ?? "").replace(/_/g, " ");

    this._buildColorDropdown();
    this._buildDyeColorDropdown();

    this._teamIdInput.value      = team.id;
    this._teamNameInput.value    = team.name ?? "";
    this._teamColorSel.value     = chatColor;
    this._teamDyeColorSel.value  = dyeColor;
    this._teamMaxInput.value     = team.max_players ?? 20;
    this._teamMinInput.value     = team.min_players ?? 0;
    this._teamColorSwatch.style.background    = colorHex(chatColor);
    this._teamDyeColorSwatch.style.background = dyeColor ? dyeColorHex(dyeColor) : "transparent";

    const saveOnBlur = () => this._saveTeam(team.id);
    const saveOnChatColorChange = () => {
      this._teamColorSwatch.style.background = colorHex(this._teamColorSel.value);
      this._saveTeam(team.id);
    };
    const saveOnDyeColorChange = () => {
      const dye = this._teamDyeColorSel.value;
      this._teamDyeColorSwatch.style.background = dye ? dyeColorHex(dye) : "transparent";
      this._saveTeam(team.id);
    };

    this._teamIdInput.addEventListener("blur", saveOnBlur);
    this._teamNameInput.addEventListener("blur", saveOnBlur);
    this._teamColorSel.addEventListener("change", saveOnChatColorChange);
    this._teamDyeColorSel.addEventListener("change", saveOnDyeColorChange);
    this._teamMaxInput.addEventListener("blur", saveOnBlur);
    this._teamMinInput.addEventListener("blur", saveOnBlur);
  }

  /** Populate the team/yaw/kit fields in the spawn assignment section. */
  _populateSpawnAssignment(regionId) {
    // Clone inputs to remove stale listeners
    this._spawnTeamSel.replaceWith(this._spawnTeamSel.cloneNode(false));
    this._spawnTeamSel = document.getElementById("pt-spawn-team");
    this._spawnYawInput.replaceWith(this._spawnYawInput.cloneNode(true));
    this._spawnYawInput = document.getElementById("pt-spawn-yaw");
    this._spawnKitInput.replaceWith(this._spawnKitInput.cloneNode(true));
    this._spawnKitInput = document.getElementById("pt-spawn-kit");
    this._spawnUnlinkBtn.replaceWith(this._spawnUnlinkBtn.cloneNode(true));
    this._spawnUnlinkBtn = document.getElementById("pt-spawn-unlink-btn");

    const spawnLink = this._spawnForRegion(regionId);

    // Populate team dropdown
    const noneOpt = document.createElement("option");
    noneOpt.value = "";
    noneOpt.textContent = "— unassigned —";
    this._spawnTeamSel.appendChild(noneOpt);
    for (const team of this._teams) {
      const opt = document.createElement("option");
      opt.value = team.id;
      opt.textContent = team.name || team.id;
      this._spawnTeamSel.appendChild(opt);
    }

    this._spawnTeamSel.value  = spawnLink?.team ?? "";
    this._spawnYawInput.value = spawnLink?.yaw  ?? 0;
    this._spawnKitInput.value = spawnLink?.kit  ?? "";

    // Single change listener: creates the spawn link on first assignment if none
    // exists yet, then saves on subsequent changes.  A single handler avoids the
    // dual-listener race where both listeners would call api.addSpawn if saveSpawn
    // were ever extended to handle the no-link case.
    const onTeamChange = async () => {
      if (!this._spawnForRegion(regionId)) {
        // No link yet — create it
        try {
          await api.addSpawn(this._mapName, {
            region_id: regionId,
            team:      this._spawnTeamSel.value,
            yaw:       parseFloat(this._spawnYawInput.value) || 0,
            kit:       this._spawnKitInput.value.trim(),
          });
          const mapData = await api.fetchMapData(this._mapName);
          this._spawns = mapData.spawns ?? [];
          this._renderSpawnList();
          this._highlightSpawnRow(regionId);
          this._updateStatusDot();
        } catch (err) {
          console.error("Failed to create spawn link:", err);
        }
      } else {
        // Link exists — save normally
        await this._saveSpawn(regionId);
      }
    };
    this._spawnTeamSel.addEventListener("change", onTeamChange);

    const saveSpawn = async () => { await this._saveSpawn(regionId); };
    this._spawnYawInput.addEventListener("blur",  saveSpawn);
    this._spawnKitInput.addEventListener("blur",  saveSpawn);
    this._spawnUnlinkBtn.addEventListener("click", () => this._unlinkSpawn(regionId));
  }

  // ── Private: rename handling ───────────────────────────────────────────────

  _handleRegionRename(node, oldId, newId) {
    // Update any spawn link that referenced the old region id
    const spawn = this._spawns.find(s => {
      const ref = s.region;
      if (!ref) return false;
      return typeof ref === "string" ? ref === oldId : ref.id === oldId;
    });
    if (spawn && this._mapName) {
      // The spawn link is now broken (keyed by old id). Re-link under new id.
      api.deleteSpawn(this._mapName, oldId)
        .then(() => api.addSpawn(this._mapName, {
          region_id: newId,
          team: spawn.team ?? "",
          yaw:  spawn.yaw  ?? 0,
          kit:  spawn.kit  ?? "",
        }))
        .then(async () => {
          const mapData = await api.fetchMapData(this._mapName);
          this._spawns = mapData.spawns ?? [];
          this._renderSpawnList();
          this._highlightSpawnRow(newId);
          this._selectedSpawnId = newId;
        })
        .catch(err => console.error("Teams: spawn re-link after rename failed:", err));
    }
    // Delegate canvas + registry renaming to the activity
    this._opts.onRegionRename?.(node, oldId, newId);
  }

  // ── Private: CRUD operations ───────────────────────────────────────────────

  async _addTeam() {
    if (!this._mapName) return;
    let counter = this._teams.length + 1;
    let newId = `team_${counter}`;
    while (this._teams.some(t => t.id === newId)) { counter++; newId = `team_${counter}`; }
    const defaultColor = PGM_CHAT_COLORS[this._teams.length % PGM_CHAT_COLORS.length].value;
    try {
      const { team: created } = await api.addTeam(this._mapName, {
        id:          newId,
        name:        `Team ${counter}`,
        color:       defaultColor,
        dye_color:   "",
        max_players: 20,
        min_players: 0,
      });
      this._teams.push(created);
      this._renderTeamsList();
      this._updateStatusDot();
      this._selectTeam(created.id);
    } catch (err) {
      console.error("Failed to add team:", err);
    }
  }

  async _saveTeam(originalId) {
    if (!this._mapName) return;
    const newId  = this._teamIdInput.value.trim();
    const fields = {
      id:          newId || originalId,
      name:        this._teamNameInput.value.trim(),
      color:       this._teamColorSel.value,
      dye_color:   this._teamDyeColorSel.value,  // empty string = no dye color
      max_players: parseInt(this._teamMaxInput.value, 10) || 20,
      min_players: parseInt(this._teamMinInput.value, 10) || 0,
    };
    try {
      const { team: updated } = await api.updateTeam(this._mapName, originalId, fields);
      const idx = this._teams.findIndex(t => t.id === originalId);
      if (idx !== -1) this._teams[idx] = updated;
      if (updated.id !== originalId) this._selectedTeamId = updated.id;
      this._renderTeamsList();
      this._highlightTeamRow(this._selectedTeamId);
      this._updateStatusDot();
    } catch (err) {
      console.error("Failed to save team:", err);
    }
  }

  async _deleteTeam(teamId) {
    if (!this._mapName) return;
    try {
      await api.deleteTeam(this._mapName, teamId);
      this._teams  = this._teams.filter(t => t.id !== teamId);
      this._spawns = this._spawns.filter(s => s.team !== teamId);
      if (this._selectedTeamId === teamId) {
        this._selectedTeamId = null;
        this._showEmptyState();
      }
      this._renderTeamsList();
      this._renderSpawnList();
      this._updateStatusDot();
    } catch (err) {
      console.error("Failed to delete team:", err);
    }
  }

  async _saveSpawn(regionId) {
    if (!this._mapName) return;
    const spawnLink = this._spawnForRegion(regionId);
    if (!spawnLink) return; // no link yet — handled by the "once" listener
    try {
      await api.updateSpawn(this._mapName, regionId, {
        team: this._spawnTeamSel.value,
        yaw:  parseFloat(this._spawnYawInput.value) || 0,
        kit:  this._spawnKitInput.value.trim(),
      });
      const mapData = await api.fetchMapData(this._mapName);
      this._spawns = mapData.spawns ?? [];
      this._renderSpawnList();
      this._highlightSpawnRow(regionId);
      this._updateStatusDot();
    } catch (err) {
      console.error("Failed to save spawn:", err);
    }
  }

  async _unlinkSpawn(regionId) {
    if (!this._mapName) return;
    const spawnLink = this._spawnForRegion(regionId);
    if (!spawnLink) {
      this._opts.onDeselectRegion?.();
      return;
    }
    try {
      await api.deleteSpawn(this._mapName, regionId);
      this._spawns = this._spawns.filter(s => {
        const id = typeof s.region === "string" ? s.region : s.region?.id;
        return id !== regionId;
      });
      this._renderSpawnList();
      this._updateStatusDot();
      // Deselect via registry so canvas clears too
      this._opts.onDeselectRegion?.();
    } catch (err) {
      console.error("Failed to unlink spawn:", err);
    }
  }

  // ── Private: status dot ────────────────────────────────────────────────────

  _updateStatusDot() {
    if (!this._opts.onStatusChange) return;
    if (this._teams.length === 0) { this._opts.onStatusChange(null); return; }
    const linkedTeamIds = new Set(this._spawns.map(s => s.team).filter(Boolean));
    const allHaveSpawn  = this._teams.every(t => linkedTeamIds.has(t.id));
    this._opts.onStatusChange(allHaveSpawn ? "green" : "yellow");
  }

  // ── Private: static UI setup ───────────────────────────────────────────────

  _buildColorDropdown() {
    const sel = document.getElementById("pt-team-color");
    if (!sel) return;
    sel.innerHTML = "";
    for (const color of PGM_CHAT_COLORS) {
      const opt = document.createElement("option");
      opt.value = color.value;
      opt.textContent = color.label;
      sel.appendChild(opt);
    }
  }

  _buildDyeColorDropdown() {
    const sel = document.getElementById("pt-team-dye-color");
    if (!sel) return;
    sel.innerHTML = "";
    // Add an empty "none" option — dye_color is optional
    const noneOpt = document.createElement("option");
    noneOpt.value = "";
    noneOpt.textContent = "— none —";
    sel.appendChild(noneOpt);
    for (const color of MINECRAFT_DYE_COLORS) {
      const opt = document.createElement("option");
      opt.value = color.value;
      opt.textContent = color.label;
      sel.appendChild(opt);
    }
  }

  _attachStaticListeners() {
    this._addTeamBtn.addEventListener("click", () => this._addTeam());
  }
}
