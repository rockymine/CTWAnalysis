/**
 * TeamsActivity — workspace wrapper for the Teams activity.
 *
 * Uses the same RegionRegistry + DeletedRegionHistory infrastructure as the
 * Regions activity so the Teams canvas gets labels, anchor blocks, resize
 * handles, and undo/redo for free.  The only differences from Regions are:
 *   • Canvas is filtered to spawn-category regions only.
 *   • Drawing tools are limited to Cylinder and Point.
 *   • Right panel shows RegionDetail + team/yaw/kit assignment fields.
 */

import { MapCanvas }            from "./map-canvas.js";
import { TeamsPanel }           from "./teams-panel.js";
import { RegionRegistry }       from "./region-registry.js";
import { DeletedRegionHistory } from "./deleted-region-history.js";
import { deriveBoundsFromCoords } from "./region-types.js";
import * as api                 from "./api.js";

export class TeamsActivity {
  constructor({ onStatusChange } = {}) {
    this._el      = document.getElementById("pt-workspace");
    this._canvas  = null;   // MapCanvas — created on first activate
    this._mapName = null;

    // Tool buttons
    this._toolMoveBtn     = document.getElementById("pt-tool-move");
    this._toolSelectBtn   = document.getElementById("pt-tool-select");
    this._toolCylinderBtn = document.getElementById("pt-tool-cylinder");
    this._toolPointBtn    = document.getElementById("pt-tool-point");
    this._coordsEl        = document.getElementById("pt-cursor-coords");
    this._zoomEl          = document.getElementById("pt-zoom-level");

    // Registry — tracks the spawn-region node tree and selection state.
    // onSelectionChange fans out to canvas (outline, anchors/label) and panel.
    this._registry = new RegionRegistry({
      onSelectionChange: (node, selectedIds) => {
        this._canvas?.setSelectedRegions(selectedIds);
        if (node) {
          this._canvas?.showAnchors(node);   // renders name label + anchor blocks
          this._panel.onRegionSelect(node);
        } else {
          this._canvas?.clearAnchors();
          this._panel.onRegionDeselect();
        }
      },
    });

    this._deleteHistory  = new DeletedRegionHistory();
    this._spawnLinkCache = new Map();  // root_id → spawn link payload saved before delete

    // Panel — constructed after registry so we can pass routing callbacks.
    this._panel = new TeamsPanel({
      onStatusChange,
      onSpawnRowClick:  (regionId) => this._registry.select(regionId),
      onDeselectRegion: ()         => this._registry.deselect(),
      onBoundsChange:   (node, bounds) => this._handleBoundsChange(node, bounds),
      onBoundsSave:     (node, bounds) => this._handleBoundsSave(node, bounds),
      onCoordsChange:   (node, coords) => this._handleCoordsChange(node, coords),
      onCoordsSave:     (node, coords) => this._handleCoordsSave(node, coords),
      onRegionRename:   (node, oldId, newId) => this._handleRegionRename(node, oldId, newId),
    });
  }

  activate({ mapName } = {}) {
    this._el.hidden = false;

    if (!this._canvas) {
      this._initCanvas();
    }

    if (mapName && mapName !== this._mapName) {
      this._mapName = mapName;
      this._panel.load(mapName);
      this._loadMapIntoCanvas(mapName);
    }
  }

  deactivate() {
    this._el.hidden = true;
  }

  // ── Canvas init ────────────────────────────────────────────────────────────

  _initCanvas() {
    const svgEl  = document.getElementById("pt-map-svg");
    const wrapEl = document.getElementById("pt-svg-area");

    this._canvas = new MapCanvas(svgEl, wrapEl, {
      onCoords: (x, z) => {
        this._coordsEl.textContent = x !== null ? `X ${x}  Z ${z}` : "";
      },
      onZoom: (scale) => {
        this._zoomEl.textContent = `${Math.round(scale * 100)}%`;
      },
      onCanvasClick: (node) => {
        if (node) this._registry.select(node.id);
        else      this._registry.deselect();
      },
      onRegionDraw: async (drawResult) => {
        if (!this._mapName) return;
        this._setTool(null);
        const newId = await this._panel.onCanvasDraw(
          this._mapName,
          drawResult,
          async (payload) => api.createRegion(this._mapName, payload),
        );
        await this._reloadCanvas(this._mapName);
        await this._panel.reloadSpawnList(this._mapName);
        if (newId) this._registry.select(newId);
      },
      onBoundsChange: (node, bounds) => this._handleBoundsChange(node, bounds),
      onBoundsSave:   (node, bounds) => this._handleBoundsSave(node, bounds),
    });

    this._setTool("move");
    this._attachToolListeners();
    this._enableTools();
  }

  // ── Map loading ────────────────────────────────────────────────────────────

  async _loadMapIntoCanvas(mapName) {
    try {
      const [ctx, groups] = await Promise.all([
        api.fetchContext(mapName),
        api.fetchRegions(mapName),
      ]);
      const spawnGroups = this._filterSpawnGroups(groups);
      this._canvas.render(ctx, spawnGroups);
      this._registerNodes(spawnGroups);
    } catch (err) {
      console.error("Teams canvas: failed to load map:", err);
    }
  }

  /** Reload only the regions layer (used after undo/redo or delete). */
  async _reloadCanvas(mapName) {
    try {
      const groups = await api.fetchRegions(mapName);
      const spawnGroups = this._filterSpawnGroups(groups);
      this._canvas.refreshRegions(spawnGroups);
      this._registerNodes(spawnGroups);
    } catch (err) {
      console.error("Teams canvas: failed to reload:", err);
    }
  }

  _filterSpawnGroups(groups) {
    return groups.filter(g => g.name === "spawn_area" || g.name === "spawn_point");
  }

  _registerNodes(spawnGroups) {
    this._registry.clear();
    for (const group of spawnGroups) {
      for (const root of group.regions) this._registry.register(root, null);
    }
  }

  // ── Bounds / coords handlers (mirror main.js patterns) ─────────────────────

  _handleBoundsChange(node, bounds) {
    this._canvas.updateRegionBounds(node, bounds);
    for (const ancestor of this._registry.recomputeAncestorBounds(node.id)) {
      this._canvas.updateRegionBounds(ancestor, ancestor.bounds);
    }
  }

  _handleBoundsSave(node, bounds) {
    if (!this._mapName) return;
    api.patchRegion(this._mapName, node.id, bounds)
      .then(() => this._deleteHistory.clearRedo())
      .catch(err => console.error("Teams: region save failed:", err));
  }

  _handleCoordsChange(node, coords) {
    const newBounds = deriveBoundsFromCoords(node.type, coords);
    if (newBounds) {
      node.bounds = newBounds;
      this._canvas.updateRegionBounds(node, newBounds);
      for (const ancestor of this._registry.recomputeAncestorBounds(node.id)) {
        this._canvas.updateRegionBounds(ancestor, ancestor.bounds);
      }
    }
  }

  _handleCoordsSave(node, coords) {
    if (!this._mapName) return;
    api.updateRegionCoords(this._mapName, node.id, coords)
      .then(res => {
        if (res.bounds) {
          node.bounds = res.bounds;
          this._canvas.updateRegionBounds(node, res.bounds);
        }
        this._deleteHistory.clearRedo();
      })
      .catch(err => console.error("Teams: coord save failed:", err));
  }

  _handleRegionRename(node, oldId, newId) {
    this._registry.renameNode(oldId, newId);
    this._canvas.renameNode(oldId, newId);
    this._canvas.showAnchors(node);  // refresh overlay so new label appears
    if (!this._mapName) return;
    api.renameRegion(this._mapName, oldId, newId)
      .then(() => this._deleteHistory.clearRedo())
      .catch(err => console.error("Teams: rename failed:", err));
  }

  // ── Delete ────────────────────────────────────────────────────────────────

  async _deleteSelectedRegion(regionId) {
    if (!this._mapName) return;
    const node = this._registry.getNode(regionId);
    if (!node || node.synthetic_id) return;
    try {
      // Save the spawn link before deleting so undo can restore it
      const spawnLink = this._panel.getSpawnLink(regionId);
      await api.deleteSpawn(this._mapName, regionId).catch(() => {});
      const { snapshot } = await api.deleteRegion(this._mapName, regionId);
      if (spawnLink) {
        this._spawnLinkCache.set(snapshot.root_id, {
          region_id: regionId,
          team: spawnLink.team ?? "",
          yaw:  spawnLink.yaw  ?? 0,
          kit:  spawnLink.kit  ?? "",
        });
      }
      this._canvas.removeRegion(regionId);
      this._registry.unregister(regionId);  // fires deselect → clears anchors + panel
      this._deleteHistory.pushDelete(snapshot);
      await this._panel.reloadSpawnList(this._mapName);
    } catch (err) {
      console.error("Teams: failed to delete region:", err);
    }
  }

  // ── Tool management ────────────────────────────────────────────────────────

  _setTool(tool) {
    this._canvas.setActiveTool(tool);
    this._toolMoveBtn.classList.toggle("draw-tool-btn--active",     tool === "move");
    this._toolSelectBtn.classList.toggle("draw-tool-btn--active",   tool === null);
    this._toolCylinderBtn.classList.toggle("draw-tool-btn--active", tool === "cylinder");
    this._toolPointBtn.classList.toggle("draw-tool-btn--active",    tool === "point");
  }

  _enableTools() {
    this._toolMoveBtn.disabled     = false;
    this._toolSelectBtn.disabled   = false;
    this._toolCylinderBtn.disabled = false;
    this._toolPointBtn.disabled    = false;
  }

  _attachToolListeners() {
    this._toolMoveBtn.addEventListener("click", () => this._setTool("move"));
    this._toolSelectBtn.addEventListener("click", () => this._setTool(null));
    this._toolCylinderBtn.addEventListener("click", () => {
      this._setTool(
        this._toolCylinderBtn.classList.contains("draw-tool-btn--active") ? "move" : "cylinder",
      );
    });
    this._toolPointBtn.addEventListener("click", () => {
      this._setTool(
        this._toolPointBtn.classList.contains("draw-tool-btn--active") ? "move" : "point",
      );
    });

    document.addEventListener("keydown", (e) => {
      if (this._el.hidden) return;
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" ||
          e.target.tagName === "SELECT" || e.target.isContentEditable) return;

      // Undo / redo
      if (e.ctrlKey && e.key === "z" && this._mapName) {
        e.preventDefault();
        this._deleteHistory.undo(
          async (snapshot) => {
            await api.restoreRegion(this._mapName, snapshot);
            // Re-create the spawn link that was deleted alongside the region
            const savedLink = this._spawnLinkCache.get(snapshot.root_id);
            if (savedLink) {
              await api.addSpawn(this._mapName, savedLink).catch(() => {});
              this._spawnLinkCache.delete(snapshot.root_id);
            }
            await this._reloadCanvas(this._mapName);
            await this._panel.reloadSpawnList(this._mapName);
            this._registry.select(snapshot.root_id);
          },
          err => console.error("Teams undo failed:", err),
        );
        return;
      }
      if (e.ctrlKey && e.key === "y" && this._mapName) {
        e.preventDefault();
        this._deleteHistory.redo(
          async (snapshot) => {
            // Save the spawn link again before re-deleting (mirrors _deleteSelectedRegion)
            const regionId = snapshot.root_id;
            const spawnLink = this._panel.getSpawnLink(regionId);
            await api.deleteSpawn(this._mapName, regionId).catch(() => {});
            if (spawnLink) {
              this._spawnLinkCache.set(regionId, {
                region_id: regionId,
                team: spawnLink.team ?? "",
                yaw:  spawnLink.yaw  ?? 0,
                kit:  spawnLink.kit  ?? "",
              });
            }
            await api.deleteRegion(this._mapName, regionId);
            await this._reloadCanvas(this._mapName);
            await this._panel.reloadSpawnList(this._mapName);
          },
          err => console.error("Teams redo failed:", err),
        );
        return;
      }

      // Tool shortcuts
      if (e.key === "m" || e.key === "M") this._setTool("move");
      if (e.key === "s" || e.key === "S") this._setTool(null);
      if (e.key === "y" || e.key === "Y") {
        this._setTool(
          this._toolCylinderBtn.classList.contains("draw-tool-btn--active") ? "move" : "cylinder",
        );
      }
      if (e.key === "p" || e.key === "P") {
        this._setTool(
          this._toolPointBtn.classList.contains("draw-tool-btn--active") ? "move" : "point",
        );
      }
      if (e.key === "Escape") this._setTool("move");

      // Delete selected spawn region
      if ((e.key === "Delete" || e.key === "Backspace") && this._panel._selectedSpawnId) {
        e.preventDefault();
        this._deleteSelectedRegion(this._panel._selectedSpawnId);
      }
    });
  }
}
