/**
 * ObjectiveActivity — workspace wrapper for the Objective activity.
 *
 * Shows the map canvas with wool (◆) and monument (⊕) POI markers enabled,
 * and a left-panel wool list with a right-panel inspector.  The inspector
 * supports editing color, defender, location, and wool room region assignment.
 *
 * Canvas interaction (select tool):
 *   - Click a wool ◆ marker   → select the wool at that location
 *   - Click a monument ⊕ marker → select the wool that captures there
 *   - Click a region            → select the wool whose room it is; if none
 *                                 owns it and a wool is already selected, assign
 *                                 it as the room region for that wool (fallback)
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
import * as api           from "./api.js";

export class ObjectiveActivity {
  _el        = null;
  _canvas    = null;
  _panel     = null;
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

    this._panel = new ObjectivePanel({
      onWoolSelect: (wool) => this._onWoolSelect(wool),
      onWoolSave:   ()     => this._refreshCanvas(),
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
      // Click on a region: try to select the wool that owns it; if none matches,
      // fall back to assigning it as the wool room for the currently selected wool.
      onCanvasClick: (node) => {
        if (!node) return;
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

      this._panel.load(mapName, mapData);
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
      // Re-apply the region highlight for the currently selected wool
      if (this._panel.hasSelectedWool()) {
        const regionId = this._panel.selectedWoolRoomRegion();
        this._canvas.setSelectedRegions(regionId ? [regionId] : []);
      }
    } catch (err) {
      console.error("Objective: failed to refresh canvas:", err);
    }
  }

  // ── Wool selection ──────────────────────────────────────────────────────────

  _onWoolSelect(room) {
    // Highlight the wool room region on the canvas (if assigned)
    const regionId = room?.woolRoomRegion ?? null;
    this._canvas.setSelectedRegions(regionId ? [regionId] : []);
  }
}
