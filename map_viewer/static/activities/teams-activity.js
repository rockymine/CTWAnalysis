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

import { MapCanvas }            from "../canvas/map-canvas.js";
import { TeamsPanel }           from "../panels/teams-panel.js";
import { RegionRegistry }       from "../region/region-registry.js";
import { DeletedRegionHistory } from "../region/deleted-region-history.js";
import { createRegionHandlers } from "../region/region-handlers.js";
import { isEditableTarget }     from "../shared/ui-helpers.js";
import { ToolManager }          from "../shared/tool-manager.js";
import * as api                from "../api.js";

export class TeamsActivity {
  // ── private fields ────────────────────────────────────────────────────────

  #el            = null;
  #canvas        = null;
  #mapName       = null;

  #coordsEl      = null;
  #zoomEl        = null;

  #registry      = null;
  #deleteHistory = null;
  #spawnLinkCache = null;  // root_id → spawn link payload saved before delete
  #panel         = null;
  #handlers      = null;
  #tools         = null;

  constructor({ onStatusChange } = {}) {
    this.#el       = document.getElementById("pt-workspace");
    this.#coordsEl = document.getElementById("pt-cursor-coords");
    this.#zoomEl   = document.getElementById("pt-zoom-level");

    // Registry — tracks the spawn-region node tree and selection state.
    // onSelectionChange fans out to canvas (outline, anchors/label) and panel.
    this.#registry = new RegionRegistry({
      onSelectionChange: (node, selectedIds) => {
        this.#canvas.setSelectedRegions(selectedIds);
        if (node) {
          this.#canvas.showAnchors(node);   // renders name label + anchor blocks
          this.#panel.onRegionSelect(node);
        } else {
          this.#canvas.clearAnchors();
          this.#panel.onRegionDeselect();
        }
      },
    });

    this.#deleteHistory  = new DeletedRegionHistory();
    this.#spawnLinkCache = new Map();

    // Panel — constructed after registry so we can pass routing callbacks.
    this.#panel = new TeamsPanel({
      onStatusChange,
      onSpawnRowClick:  (regionId) => this.#registry.select(regionId),
      onDeselectRegion: ()         => this.#registry.deselect(),
      onBoundsChange:   (node, bounds) => this.#handleBoundsChange(node, bounds),
      onBoundsSave:     (node, bounds) => this.#handleBoundsSave(node, bounds),
      onCoordsChange:   (node, coords) => this.#handleCoordsChange(node, coords),
      onCoordsSave:     (node, coords) => this.#handleCoordsSave(node, coords),
      onRegionRename:   (node, oldId, newId) => this.#handlers.onRenameRegion(node, oldId, newId),
    });

    this.#initCanvas();
  }

  activate({ mapName } = {}) {
    this.#el.hidden = false;

    if (mapName && mapName !== this.#mapName) {
      this.#mapName = mapName;
      this.#panel.load(mapName);
      this.#loadMapIntoCanvas(mapName);
    }
  }

  deactivate() {
    this.#el.hidden = true;
  }

  resize() {
    this.#canvas.resize();
  }

  // ── Canvas init ────────────────────────────────────────────────────────────

  #initCanvas() {
    const svgEl  = document.getElementById("pt-map-svg");
    const wrapEl = document.getElementById("pt-svg-area");

    this.#canvas = new MapCanvas(svgEl, wrapEl, {
      onCoords: (x, z) => {
        this.#coordsEl.textContent = x !== null ? `X ${x}  Z ${z}` : "";
      },
      onZoom: (scale) => {
        this.#zoomEl.textContent = `${Math.round(scale * 100)}%`;
      },
      onCanvasClick: (node) => {
        if (node) this.#registry.select(node.id);
        else      this.#registry.deselect();
      },
      onRegionDraw: async (drawResult) => {
        if (!this.#mapName) return;
        this.#tools.setTool(null);
        const newId = await this.#panel.onCanvasDraw(
          this.#mapName,
          drawResult,
          async (payload) => api.createRegion(this.#mapName, payload),
        );
        await this.#reloadCanvas(this.#mapName);
        await this.#panel.reloadSpawnList(this.#mapName);
        if (newId) this.#registry.select(newId);
      },
      onBoundsChange: (node, bounds) => this.#handleBoundsChange(node, bounds),
      onBoundsSave:   (node, bounds) => this.#handleBoundsSave(node, bounds),
    });

    // Create shared bounds/coords handlers now that canvas is available.
    this.#handlers = createRegionHandlers({
      canvas:     this.#canvas,
      registry:   this.#registry,
      detail:     null,             // Teams has no XML-preview on bounds change
      getMapName: () => this.#mapName,
      getHistory: () => this.#deleteHistory,
    });

    this.#tools = new ToolManager(this.#canvas, {
      move:     document.getElementById("pt-tool-move"),
      select:   document.getElementById("pt-tool-select"),
      cylinder: document.getElementById("pt-tool-cylinder"),
      point:    document.getElementById("pt-tool-point"),
    });
    this.#tools.enable();
    this.#tools.setTool("move");
    this.#attachToolListeners();
  }

  // ── Map loading ────────────────────────────────────────────────────────────

  async #loadMapIntoCanvas(mapName) {
    try {
      const [ctx, groups] = await Promise.all([
        api.fetchContext(mapName),
        api.fetchRegions(mapName),
      ]);
      const spawnGroups = this.#filterSpawnGroups(groups);
      this.#canvas.render(ctx, spawnGroups);
      this.#registerNodes(spawnGroups);
    } catch (err) {
      console.error("Teams canvas: failed to load map:", err);
    }
  }

  /** Reload only the regions layer (used after undo/redo or delete). */
  async #reloadCanvas(mapName) {
    try {
      const groups = await api.fetchRegions(mapName);
      const spawnGroups = this.#filterSpawnGroups(groups);
      this.#canvas.refreshRegions(spawnGroups);
      this.#registerNodes(spawnGroups);
    } catch (err) {
      console.error("Teams canvas: failed to reload:", err);
    }
  }

  #filterSpawnGroups(groups) {
    return groups.filter(g => g.name === "spawn_area" || g.name === "spawn_point");
  }

  #registerNodes(spawnGroups) {
    this.#registry.clear();
    for (const group of spawnGroups) {
      for (const root of group.regions) this.#registry.register(root, null);
    }
  }

  // ── Bounds / coords handlers — delegated to createRegionHandlers() ─────────

  #handleBoundsChange(node, bounds)  { this.#handlers.onBoundsChange(node, bounds); }
  #handleBoundsSave(node, bounds)    { this.#handlers.onBoundsSave(node, bounds); }
  #handleCoordsChange(node, coords)  { this.#handlers.onCoordsChange(node, coords); }
  #handleCoordsSave(node, coords)    { this.#handlers.onCoordsSave(node, coords); }

  // ── Delete ────────────────────────────────────────────────────────────────

  async #deleteSelectedRegion(regionId) {
    if (!this.#mapName) return;
    const node = this.#registry.getNode(regionId);
    if (!node || node.synthetic_id) return;
    try {
      // Save the spawn link before deleting so undo can restore it
      const spawnLink = this.#panel.getSpawnLink(regionId);
      await api.deleteSpawn(this.#mapName, regionId).catch(() => {});
      const { snapshot } = await api.deleteRegion(this.#mapName, regionId);
      if (spawnLink) {
        this.#spawnLinkCache.set(snapshot.root_id, {
          region_id: regionId,
          team: spawnLink.team ?? "",
          yaw:  spawnLink.yaw  ?? 0,
          kit:  spawnLink.kit  ?? "",
        });
      }
      this.#canvas.removeRegion(regionId);
      this.#registry.unregister(regionId);  // fires deselect → clears anchors + panel
      this.#deleteHistory.pushDelete(snapshot);
      await this.#panel.reloadSpawnList(this.#mapName);
    } catch (err) {
      console.error("Teams: failed to delete region:", err);
    }
  }

  // ── Tool management ────────────────────────────────────────────────────────

  #attachToolListeners() {
    document.getElementById("pt-tool-move").addEventListener("click",     () => this.#tools.setTool("move"));
    document.getElementById("pt-tool-select").addEventListener("click",   () => this.#tools.setTool(null));
    document.getElementById("pt-tool-cylinder").addEventListener("click", () => {
      this.#tools.setTool(this.#tools.activeTool === "cylinder" ? "move" : "cylinder");
    });
    document.getElementById("pt-tool-point").addEventListener("click", () => {
      this.#tools.setTool(this.#tools.activeTool === "point" ? "move" : "point");
    });

    document.addEventListener("keydown", (e) => {
      if (this.#el.hidden) return;
      if (isEditableTarget(e)) return;

      // Undo / redo
      if (e.ctrlKey && e.key === "z" && this.#mapName) {
        e.preventDefault();
        this.#deleteHistory.undo(
          async (snapshot) => {
            await api.restoreRegion(this.#mapName, snapshot);
            // Re-create the spawn link that was deleted alongside the region
            const savedLink = this.#spawnLinkCache.get(snapshot.root_id);
            if (savedLink) {
              await api.addSpawn(this.#mapName, savedLink).catch(() => {});
              this.#spawnLinkCache.delete(snapshot.root_id);
            }
            await this.#reloadCanvas(this.#mapName);
            await this.#panel.reloadSpawnList(this.#mapName);
            this.#registry.select(snapshot.root_id);
          },
          err => console.error("Teams undo failed:", err),
        );
        return;
      }
      if (e.ctrlKey && e.key === "y" && this.#mapName) {
        e.preventDefault();
        this.#deleteHistory.redo(
          async (snapshot) => {
            // Save the spawn link again before re-deleting (mirrors #deleteSelectedRegion)
            const regionId = snapshot.root_id;
            const spawnLink = this.#panel.getSpawnLink(regionId);
            await api.deleteSpawn(this.#mapName, regionId).catch(() => {});
            if (spawnLink) {
              this.#spawnLinkCache.set(regionId, {
                region_id: regionId,
                team: spawnLink.team ?? "",
                yaw:  spawnLink.yaw  ?? 0,
                kit:  spawnLink.kit  ?? "",
              });
            }
            await api.deleteRegion(this.#mapName, regionId);
            await this.#reloadCanvas(this.#mapName);
            await this.#panel.reloadSpawnList(this.#mapName);
          },
          err => console.error("Teams redo failed:", err),
        );
        return;
      }

      // Tool shortcuts
      if (e.key === "m" || e.key === "M") this.#tools.setTool("move");
      if (e.key === "s" || e.key === "S") this.#tools.setTool(null);
      if (e.key === "y" || e.key === "Y") {
        this.#tools.setTool(this.#tools.activeTool === "cylinder" ? "move" : "cylinder");
      }
      if (e.key === "p" || e.key === "P") {
        this.#tools.setTool(this.#tools.activeTool === "point" ? "move" : "point");
      }
      if (e.key === "Escape") this.#tools.setTool("move");

      // Delete selected spawn region
      const selectedSpawnId = this.#panel.getSelectedRegionId();
      if ((e.key === "Delete" || e.key === "Backspace") && selectedSpawnId) {
        e.preventDefault();
        this.#deleteSelectedRegion(selectedSpawnId);
      }
    });
  }
}
