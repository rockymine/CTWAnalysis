/**
 * ObjectiveActivity — workspace wrapper for the Objective activity.
 *
 * Display-only for now: shows the map canvas with wool (◆) and monument (⊕)
 * POI markers enabled, and a left-panel wool list with a right-panel inspector.
 * Editing wool / monument positions is a future step.
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

  _coordsEl = null;
  _zoomEl   = null;

  constructor() {
    this._el      = document.getElementById("obj-workspace");
    this._coordsEl = document.getElementById("obj-cursor-coords");
    this._zoomEl   = document.getElementById("obj-zoom-level");

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
      // Read-only — no draw or region-edit callbacks needed
    });

    // Always show wool ◆ and monument ⊕ markers in the Objective activity
    this._canvas.setPoisVisible(true);
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
    } catch (err) {
      console.error("Objective: failed to refresh canvas:", err);
    }
  }

  // ── Wool selection ──────────────────────────────────────────────────────────

  _onWoolSelect(_wool) {
    // Future: pan/highlight the wool location on the canvas
  }
}
