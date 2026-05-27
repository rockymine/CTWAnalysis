/**
 * ObjectiveActivity — workspace wrapper for the Objective activity.
 *
 * Shows the map canvas with wool (◆) and monument (⊕) POI markers enabled,
 * and a left-panel with two sections:
 *   • Top: wool list (one row per distinct color+location) + "+ Add wool" button.
 *   • Bottom: region list (wool_room and monument regions shown on the canvas).
 * A right-panel inspector shows editable fields for the selected wool room.
 *
 * Canvas/region selection reuses the same RegionRegistry + showAnchors path as
 * TeamsActivity, so the visual response is immediate and consistent.
 *
 * Canvas interaction (select tool):
 *   - Click a wool ◆ marker   → select the wool at that location
 *   - Click a monument ⊕ marker → select the wool that captures there
 *   - Click a region (canvas or sidebar) → select the wool whose room it is;
 *                                 if none owns it and a wool is already selected,
 *                                 assign it as the room region for that wool (fallback)
 *
 * Toolbar: move (pan) and select tools, following the same pattern as
 *   TeamsActivity (#pt-tool-move / #pt-tool-select).
 *
 * Public API consumed by main.js:
 *   activate({ mapName })   — show workspace; load map if name changed
 *   deactivate()            — hide workspace
 *   resize()                — delegate to canvas.resize()
 */

import { MapCanvas }      from "../canvas/map-canvas.js";
import { ObjectivePanel } from "../panels/objective-panel.js";
import { RegionRegistry } from "../region/region-registry.js";
import { ToolManager }    from "../shared/tool-manager.js";
import * as api           from "../api.js";

export class ObjectiveActivity {
  // ── private fields ────────────────────────────────────────────────────────

  #el        = null;
  #canvas    = null;
  #panel     = null;
  #registry  = null;
  #mapName   = null;
  #ctx       = null;   // last-rendered canvas context (augmented with monuments)
  #objGroups = null;   // last-rendered region groups

  #coordsEl = null;
  #zoomEl   = null;
  #tools    = null;

  constructor() {
    this.#el       = document.getElementById("obj-workspace");
    this.#coordsEl = document.getElementById("obj-cursor-coords");
    this.#zoomEl   = document.getElementById("obj-zoom-level");

    // Registry owns canvas-level region selection.  onSelectionChange fires
    // synchronously so the visual response is immediate (same as Teams).
    this.#registry = new RegionRegistry({
      onSelectionChange: (node, ids) => {
        this.#canvas.setSelectedRegions(ids);
        if (node) {
          this.#canvas.showAnchors(node);
          this.#panel.highlightRegionRow(node.id);
        } else {
          this.#canvas.clearAnchors();
          this.#panel.highlightRegionRow(null);
        }
      },
    });

    this.#panel = new ObjectivePanel({
      onWoolSelect:     (wool)     => this.#onWoolSelect(wool),
      onWoolSave:       ()         => this.#refreshCanvas(),
      onRegionRowClick: (regionId) => this.#onRegionRowClick(regionId),
    });

    this.#initCanvas();
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  activate({ mapName } = {}) {
    this.#el.hidden = false;

    if (mapName && mapName !== this.#mapName) {
      this.#mapName = mapName;
      this.#loadMap(mapName);
    }
  }

  deactivate() {
    this.#el.hidden = true;
  }

  resize() {
    this.#canvas.resize();
  }

  // ── Canvas init ─────────────────────────────────────────────────────────────

  #initCanvas() {
    const svgEl  = document.getElementById("obj-map-svg");
    const wrapEl = document.getElementById("obj-svg-area");

    this.#canvas = new MapCanvas(svgEl, wrapEl, {
      onCoords: (x, z) => {
        this.#coordsEl.textContent = x !== null ? `X ${x}  Z ${z}` : "";
      },
      onZoom: (scale) => {
        this.#zoomEl.textContent = `${Math.round(scale * 100)}%`;
      },
      // Click on a region: immediately select it via the registry (gives instant
      // visual feedback — same mechanism as Teams/Regions), then sync the panel.
      onCanvasClick: (node) => {
        if (!node) {
          this.#registry.deselect();
          return;
        }
        // Registry fires onSelectionChange synchronously → setSelectedRegions +
        // showAnchors happen before the panel does any inspector DOM work.
        this.#registry.select(node.id);
        const found = this.#panel.selectRoomByRegion(node.id);
        if (!found && this.#panel.hasSelectedWool()) {
          this.#panel.assignWoolRoom(node.id);
        }
      },
      // Click on a wool ◆ or monument ⊕ marker: select the corresponding wool.
      onPoiClick: (type, data) => {
        if (type === "wool") {
          this.#panel.selectRoomByLocation(data.x, data.z);
        } else if (type === "monument") {
          this.#panel.selectRoomByMonument(data.x, data.z);
        }
      },
    });

    // Always show wool ◆ and monument ⊕ markers in the Objective activity
    this.#canvas.setPoisVisible(true);

    // Wire toolbar buttons
    const moveBtn   = document.getElementById("obj-tool-move");
    const selectBtn = document.getElementById("obj-tool-select");
    this.#tools = new ToolManager(this.#canvas, { move: moveBtn, select: selectBtn });
    moveBtn.addEventListener("click",   () => this.#tools.setTool("move"));
    selectBtn.addEventListener("click", () => this.#tools.setTool(null));
    this.#tools.enable();
    this.#tools.setTool(null);  // default: select tool
  }

  // ── Map loading ─────────────────────────────────────────────────────────────

  async #loadMap(mapName) {
    try {
      const [ctx, mapData, groups] = await Promise.all([
        api.fetchContext(mapName),
        api.fetchMapData(mapName),
        api.fetchRegions(mapName),
      ]);

      // Augment context with monument markers so the canvas can render ⊕ glyphs
      ctx.monuments = (mapData.wools ?? []).map(wool => ({
        x:          wool.monument.x,
        z:          wool.monument.z,
        wool_color: wool.color,
        team:       wool.team,
      }));

      // Show only wool-room and monument region categories on the canvas
      const objGroups = groups.filter(
        group => group.name === "wool_room" || group.name === "monument",
      );

      this.#ctx       = ctx;
      this.#objGroups = objGroups;
      this.#canvas.render(ctx, objGroups);
      requestAnimationFrame(() => this.#canvas.resize());

      // Register region nodes so the registry can look them up by id for
      // instant selection (same pattern as TeamsActivity).
      this.#registry.clear();
      for (const group of objGroups) {
        for (const root of group.regions) this.#registry.register(root, null);
      }

      this.#panel.load(mapName, mapData);
      this.#panel.loadRegions(objGroups);
    } catch (err) {
      console.error("Objective: failed to load map:", err);
    }
  }

  // ── Canvas refresh (called after any wool edit) ──────────────────────────────

  async #refreshCanvas() {
    if (!this.#mapName || !this.#ctx) return;
    try {
      const mapData = await api.fetchMapData(this.#mapName);
      this.#ctx.monuments = (mapData.wools ?? []).map(wool => ({
        x:          wool.monument.x,
        z:          wool.monument.z,
        wool_color: wool.color,
        team:       wool.team,
      }));
      if (!this.#ctx.poi_assignments) this.#ctx.poi_assignments = {};
      this.#ctx.poi_assignments.wools = (mapData.wools ?? []).map(wool => ({
        x:          wool.location.x,
        z:          wool.location.z,
        wool_color: wool.color,
      }));
      this.#canvas.render(this.#ctx, this.#objGroups);
      // Re-apply the region highlight + anchors for the currently selected wool.
      // canvas.render() resets #selectedNode, so showAnchors must be re-called.
      if (this.#panel.hasSelectedWool()) {
        const regionId = this.#panel.selectedWoolRoomRegion();
        if (regionId) {
          const node = this.#registry.getNode(regionId);
          this.#canvas.setSelectedRegions([regionId]);
          if (node) this.#canvas.showAnchors(node);
        } else {
          this.#canvas.setSelectedRegions([]);
        }
      }
    } catch (err) {
      console.error("Objective: failed to refresh canvas:", err);
    }
  }

  // ── Wool selection ──────────────────────────────────────────────────────────

  /**
   * Called by the panel when the user selects a wool from the wool list.
   * Routes through the registry so setSelectedRegions + showAnchors both fire
   * (same mechanism used by canvas clicks and region row clicks).
   */
  #onWoolSelect(room) {
    const regionId = room?.woolRoomRegion ?? null;
    if (regionId && this.#registry.getNode(regionId)) {
      this.#registry.select(regionId);
    } else {
      this.#registry.deselect();
    }
  }

  /**
   * Called by the panel when the user clicks a region row in the sidebar.
   * Selects the region via the registry (visual), then tries to select the
   * corresponding wool — same logic as a canvas click.
   */
  #onRegionRowClick(regionId) {
    if (!this.#registry.getNode(regionId)) return;
    this.#registry.select(regionId);
    const found = this.#panel.selectRoomByRegion(regionId);
    if (!found && this.#panel.hasSelectedWool()) {
      this.#panel.assignWoolRoom(regionId);
    }
  }
}
