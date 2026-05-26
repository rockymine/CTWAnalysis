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

import { MapCanvas }      from "./map-canvas.js";
import { ObjectivePanel } from "./objective-panel.js";
import { RegionRegistry } from "./region-registry.js";
import * as api           from "./api.js";

export class ObjectiveActivity {
  _el        = null;
  _canvas    = null;
  _panel     = null;
  _registry  = null;
  _mapName   = null;
  _ctx       = null;   // last-rendered canvas context (augmented with monuments)
  _objGroups = null;   // last-rendered region groups

  _coordsEl    = null;
  _zoomEl      = null;
  _toolMoveBtn = null;
  _toolSelBtn  = null;

  constructor() {
    this._el          = document.getElementById("obj-workspace");
    this._coordsEl    = document.getElementById("obj-cursor-coords");
    this._zoomEl      = document.getElementById("obj-zoom-level");
    this._toolMoveBtn = document.getElementById("obj-tool-move");
    this._toolSelBtn  = document.getElementById("obj-tool-select");

    // Registry owns canvas-level region selection.  onSelectionChange fires
    // synchronously so the visual response is immediate (same as Teams).
    this._registry = new RegionRegistry({
      onSelectionChange: (node, ids) => {
        this._canvas?.setSelectedRegions(ids);
        if (node) {
          this._canvas?.showAnchors(node);
          this._panel.highlightRegionRow(node.id);
        } else {
          this._canvas?.clearAnchors();
          this._panel.highlightRegionRow(null);
        }
      },
    });

    this._panel = new ObjectivePanel({
      onWoolSelect:     (wool)     => this._onWoolSelect(wool),
      onWoolSave:       ()         => this._refreshCanvas(),
      onRegionRowClick: (regionId) => this._onRegionRowClick(regionId),
    });
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  activate({ mapName } = {}) {
    this._el.hidden = false;

    if (!this._canvas) {
      this._initCanvas();
    }

    if (mapName && mapName !== this._mapName) {
      this._mapName = mapName;
      this._loadMap(mapName);
    }
  }

  deactivate() {
    this._el.hidden = true;
  }

  resize() {
    this._canvas?.resize();
  }

  // ── Canvas init ─────────────────────────────────────────────────────────────

  _initCanvas() {
    const svgEl  = document.getElementById("obj-map-svg");
    const wrapEl = document.getElementById("obj-svg-area");

    this._canvas = new MapCanvas(svgEl, wrapEl, {
      onCoords: (x, z) => {
        this._coordsEl.textContent = x !== null ? `X ${x}  Z ${z}` : "";
      },
      onZoom: (scale) => {
        this._zoomEl.textContent = `${Math.round(scale * 100)}%`;
      },
      // Click on a region: immediately select it via the registry (gives instant
      // visual feedback — same mechanism as Teams/Regions), then sync the panel.
      onCanvasClick: (node) => {
        if (!node) {
          this._registry.deselect();
          return;
        }
        // Registry fires onSelectionChange synchronously → setSelectedRegions +
        // showAnchors happen before the panel does any inspector DOM work.
        this._registry.select(node.id);
        const found = this._panel.selectRoomByRegion(node.id);
        if (!found && this._panel.hasSelectedWool()) {
          this._panel.assignWoolRoom(node.id);
        }
      },
      // Click on a wool ◆ or monument ⊕ marker: select the corresponding wool.
      onPoiClick: (type, data) => {
        if (type === "wool") {
          this._panel.selectRoomByLocation(data.x, data.z);
        } else if (type === "monument") {
          this._panel.selectRoomByMonument(data.x, data.z);
        }
      },
    });

    // Always show wool ◆ and monument ⊕ markers in the Objective activity
    this._canvas.setPoisVisible(true);

    // Wire toolbar buttons
    this._toolMoveBtn.addEventListener("click", () => this._setTool("move"));
    this._toolSelBtn.addEventListener("click",  () => this._setTool(null));
    this._toolMoveBtn.disabled = false;
    this._toolSelBtn.disabled  = false;
    this._setTool(null);  // default: select tool
  }

  _setTool(tool) {
    this._canvas.setActiveTool(tool);
    this._toolMoveBtn.classList.toggle("draw-tool-btn--active", tool === "move");
    this._toolSelBtn.classList.toggle("draw-tool-btn--active",  tool === null);
  }

  // ── Map loading ─────────────────────────────────────────────────────────────

  async _loadMap(mapName) {
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

      this._ctx       = ctx;
      this._objGroups = objGroups;
      this._canvas.render(ctx, objGroups);
      requestAnimationFrame(() => this._canvas.resize());

      // Register region nodes so the registry can look them up by id for
      // instant selection (same pattern as TeamsActivity).
      this._registry.clear();
      for (const group of objGroups) {
        for (const root of group.regions) this._registry.register(root, null);
      }

      this._panel.load(mapName, mapData);
      this._panel.loadRegions(objGroups);
    } catch (err) {
      console.error("Objective: failed to load map:", err);
    }
  }

  // ── Canvas refresh (called after any wool edit) ──────────────────────────────

  async _refreshCanvas() {
    if (!this._mapName || !this._ctx) return;
    try {
      const mapData = await api.fetchMapData(this._mapName);
      this._ctx.monuments = (mapData.wools ?? []).map(wool => ({
        x:          wool.monument.x,
        z:          wool.monument.z,
        wool_color: wool.color,
        team:       wool.team,
      }));
      if (!this._ctx.poi_assignments) this._ctx.poi_assignments = {};
      this._ctx.poi_assignments.wools = (mapData.wools ?? []).map(wool => ({
        x:          wool.location.x,
        z:          wool.location.z,
        wool_color: wool.color,
      }));
      this._canvas.render(this._ctx, this._objGroups);
      // Re-apply the region highlight + anchors for the currently selected wool.
      // canvas.render() resets #selectedNode, so showAnchors must be re-called.
      if (this._panel.hasSelectedWool()) {
        const regionId = this._panel.selectedWoolRoomRegion();
        if (regionId) {
          const node = this._registry?.getNode(regionId);
          this._canvas.setSelectedRegions([regionId]);
          if (node) this._canvas.showAnchors(node);
        } else {
          this._canvas.setSelectedRegions([]);
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
  _onWoolSelect(room) {
    const regionId = room?.woolRoomRegion ?? null;
    if (regionId && this._registry?.getNode(regionId)) {
      this._registry.select(regionId);
    } else {
      this._registry?.deselect();
    }
  }

  /**
   * Called by the panel when the user clicks a region row in the sidebar.
   * Selects the region via the registry (visual), then tries to select the
   * corresponding wool — same logic as a canvas click.
   */
  _onRegionRowClick(regionId) {
    if (!this._registry?.getNode(regionId)) return;
    this._registry.select(regionId);
    const found = this._panel.selectRoomByRegion(regionId);
    if (!found && this._panel.hasSelectedWool()) {
      this._panel.assignWoolRoom(regionId);
    }
  }
}
