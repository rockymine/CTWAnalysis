/**
 * RegionsActivity — workspace wrapper for the Regions activity.
 *
 * Owns all region-editing infrastructure: canvas, registry, sidebar, detail
 * panel, delete history, draw toolbar, and keyboard shortcuts.  main.js
 * becomes a thin orchestrator after this class absorbs the former God-module
 * logic.
 *
 * Public API consumed by main.js:
 *   activate({ mapName })        — show workspace; load map if name changed
 *   deactivate()                 — hide workspace
 *   resize()                     — delegate to canvas.resize()
 *   setButtonsEnabled(enabled)   — enable/disable toolbar after map load
 */

import { MapCanvas }          from "./map-canvas.js";
import { RegionSidebar }      from "./region-sidebar.js";
import { RegionRegistry }     from "./region-registry.js";
import { RegionDetail }       from "./region-detail.js";
import { DeletedRegionHistory } from "./deleted-region-history.js";
import { DRAW_TOOLS, deriveBoundsFromCoords } from "./region-types.js";
import { createRegionHandlers }  from "./region-handlers.js";
import * as api               from "./api.js";

export class RegionsActivity {
  // ── private fields ────────────────────────────────────────────────────────

  #el           = null;   // root workspace element
  #mapName      = null;   // currently-loaded map slug
  #setStatus    = null;   // callback to main.js status bar

  #canvas       = null;
  #registry     = null;
  #sidebar      = null;
  #detail       = null;
  #deleteHistory = null;
  #handlers     = null;   // createRegionHandlers() result

  #selectedNode  = null;
  #multiSelected = null;  // Set of ids for Ctrl+click grouping

  #blockCache   = null;   // Map: mapName → top-surface data

  // Toolbar button elements
  #toolMoveBtn     = null;
  #toolSelectBtn   = null;
  #toolBtns        = null;   // Map<type, btn>  (DRAW_TOOLS keys)
  #activeTool      = null;   // current tool string (or null = select)

  // ── constructor ────────────────────────────────────────────────────────────

  constructor({ setStatus } = {}) {
    this.#el           = document.getElementById("regions-workspace");
    this.#setStatus    = setStatus ?? (() => {});
    this.#multiSelected = new Set();
    this.#blockCache   = new Map();
    this.#toolBtns     = new Map();

    this.#initComponents();
    this.#initToolbar();
    this.#initLayerToggles();
    this.#initKeyboard();
    this.#renderHistory();  // prime the history panel with "no history"
  }

  // ── public API ─────────────────────────────────────────────────────────────

  activate({ mapName } = {}) {
    this.#el.hidden = false;
    if (mapName && mapName !== this.#mapName) {
      // New map — do a full load (fetch context + regions, reset state)
      this.#mapName = mapName;
      this.#loadMap(mapName);
    } else if (mapName && this.#mapName) {
      // Same map, re-activating after another activity may have mutated regions
      // (e.g. Teams deleted/renamed a spawn region).  Reload without resetting
      // the canvas transform or tool state.
      this.#reloadRegions().catch(err => this.#setStatus(`Reload failed: ${err.message}`));
    }
  }

  deactivate() {
    this.#el.hidden = true;
  }

  resize() {
    this.#canvas?.resize();
  }

  /** Called by main.js loadMap() to disable toolbar while loading, re-enable after. */
  setButtonsEnabled(enabled) {
    this.#toolMoveBtn.disabled   = !enabled;
    this.#toolSelectBtn.disabled = !enabled;
    for (const btn of this.#toolBtns.values()) btn.disabled = !enabled;
  }

  // ── component init ─────────────────────────────────────────────────────────

  #initComponents() {
    this.#registry = new RegionRegistry({
      onSelectionChange: (primaryNode, selectedIds) => {
        this.#selectedNode = primaryNode;
        this.#canvas.setSelectedRegions(selectedIds);
        this.#sidebar.setSelected(primaryNode?.id ?? null, selectedIds);
        if (primaryNode) {
          this.#detail.show(primaryNode);
          this.#canvas.showAnchors(primaryNode);
        } else {
          this.#detail.clear();
          this.#canvas.clearAnchors();
        }
      },
    });

    this.#deleteHistory = new DeletedRegionHistory({ onChange: () => this.#renderHistory() });

    // Canvas and detail share regionHandlers — create placeholders first,
    // then initialize handlers after both exist.
    this.#canvas = new MapCanvas(
      document.getElementById("rgn-map-svg"),
      document.getElementById("rgn-svg-area"),
      {
        onCoords: (x, z) => {
          document.getElementById("rgn-cursor-coords").textContent =
            x !== null ? `X ${x}  Z ${z}` : "";
        },
        onZoom: (scale) => {
          document.getElementById("rgn-zoom-level").textContent =
            `${Math.round(scale * 100)}%`;
        },
        onCanvasClick: (node) => {
          if (node) this.#registry.select(node.id);
          else      this.#registry.deselect();
        },
        onRegionDraw: async (drawResult) => {
          if (!this.#mapName) return;
          this.#setToolActive(null);
          try {
            const payload  = this.#buildCreatePayload(drawResult);
            const { id: newId } = await api.createRegion(this.#mapName, payload);
            const newNode  = this.#buildNewNode(newId, drawResult);
            this.#registry.register(newNode, null);
            this.#canvas.addRegion(newNode);
            this.#sidebar.appendRow(newNode);
            this.#registry.select(newId);
            this.#deleteHistory.clearRedo();
          } catch (err) {
            this.#setStatus(`Create region failed: ${err.message}`);
          }
        },
        onBoundsChange: (node, bounds) => this.#handlers?.onBoundsChange(node, bounds),
        onBoundsSave:   (node, bounds) => this.#handlers?.onBoundsSave(node, bounds),
      },
    );

    this.#detail = new RegionDetail(
      document.getElementById("region-detail"),
      {
        onBoundsChange:  (node, bounds) => this.#handlers?.onBoundsChange(node, bounds),
        onBoundsSave:    (node, bounds) => this.#handlers?.onBoundsSave(node, bounds),
        onCoordsChange:  (node, coords) => this.#handlers?.onCoordsChange(node, coords),
        onCoordsSave:    (node, coords) => this.#handlers?.onCoordsSave(node, coords),
        onIdChange: (node, oldId, newId) => {
          this.#registry.renameNode(oldId, newId);
          this.#sidebar.renameNode(oldId, newId);
          this.#canvas.renameNode(oldId, newId);
          this.#canvas.showAnchors(node);
          if (!this.#mapName) return;
          api.renameRegion(this.#mapName, oldId, newId)
            .then(() => this.#deleteHistory.clearRedo())
            .catch(err => console.error("Region rename failed:", err));
        },
      },
    );

    this.#handlers = createRegionHandlers({
      canvas:     this.#canvas,
      registry:   this.#registry,
      detail:     this.#detail,
      getMapName: () => this.#mapName,
      getHistory: () => this.#deleteHistory,
    });

    this.#sidebar = new RegionSidebar(
      document.getElementById("region-list"),
      {
        onSelect: (node, isCtrl) => {
          if (isCtrl) {
            if (this.#multiSelected.size === 0 && this.#selectedNode &&
                this.#selectedNode.id !== node.id) {
              this.#multiSelected.add(this.#selectedNode.id);
            }
            if (this.#multiSelected.has(node.id)) this.#multiSelected.delete(node.id);
            else                                   this.#multiSelected.add(node.id);
            this.#sidebar.setMultiSelected([...this.#multiSelected]);
          } else {
            this.#multiSelected.clear();
            this.#sidebar.setMultiSelected([]);
            this.#registry.select(node.id);
          }
        },
        onVisibilityToggle: (id, hidden) => {
          const affectedIds = this.#collectSubtreeIds(this.#registry.getNode(id));
          for (const affectedId of affectedIds) {
            this.#canvas.setRegionVisible(affectedId, !hidden);
            this.#sidebar.setHidden(affectedId, hidden);
          }
          if (hidden && this.#selectedNode &&
              affectedIds.includes(this.#selectedNode.id)) {
            this.#registry.deselect();
          }
        },
      },
    );
  }

  // ── toolbar ────────────────────────────────────────────────────────────────

  #initToolbar() {
    this.#toolMoveBtn   = document.getElementById("tool-move");
    this.#toolSelectBtn = document.getElementById("tool-select");

    this.#toolMoveBtn.addEventListener("click",   () => this.#setToolActive("move"));
    this.#toolSelectBtn.addEventListener("click", () => this.#setToolActive(null));

    for (const [type, desc] of Object.entries(DRAW_TOOLS)) {
      const btn = document.getElementById(`tool-${type}`);
      if (!btn) continue;
      this.#toolBtns.set(type, btn);
      btn.addEventListener("click", () => {
        const currentlyActive = btn.classList.contains("draw-tool-btn--active");
        this.#setToolActive(desc.toggleOff && currentlyActive ? "move" : type);
      });
    }
  }

  #setToolActive(tool) {
    this.#activeTool = tool;
    this.#canvas.setActiveTool(tool);
    this.#toolMoveBtn.classList.toggle("draw-tool-btn--active",   tool === "move");
    this.#toolSelectBtn.classList.toggle("draw-tool-btn--active", tool === null);
    for (const [type, btn] of this.#toolBtns) {
      btn.classList.toggle("draw-tool-btn--active", tool === type);
    }
  }

  // ── layer toggles ──────────────────────────────────────────────────────────

  #initLayerToggles() {
    document.getElementById("toggle-pois").addEventListener("change",
      (e) => this.#canvas.setPoisVisible(e.target.checked));
    document.getElementById("toggle-build").addEventListener("change",
      (e) => this.#canvas.setBuildVisible(e.target.checked));

    document.getElementById("toggle-blocks").addEventListener("change", async (e) => {
      if (!e.target.checked) { this.#canvas.setBlocksVisible(false); return; }
      if (!this.#mapName)    { e.target.checked = false; return; }
      try {
        if (!this.#blockCache.has(this.#mapName)) {
          this.#setStatus("Loading block layer…");
          this.#blockCache.set(this.#mapName, await api.fetchTopSurface(this.#mapName));
        }
        this.#canvas.loadBlockLayer(this.#blockCache.get(this.#mapName));
        this.#canvas.setBlocksVisible(true);
        this.#setStatus("");
      } catch (err) {
        this.#setStatus(`Block layer failed: ${err.message}`);
        e.target.checked = false;
      }
    });
  }

  // ── keyboard shortcuts ─────────────────────────────────────────────────────

  #initKeyboard() {
    document.addEventListener("keydown", (e) => {
      // Only fire when this activity is visible
      if (this.#el.hidden) return;
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" ||
          e.target.tagName === "SELECT" || e.target.isContentEditable) return;

      // Undo / Redo (delete history)
      if (e.ctrlKey && e.key === "z" && this.#mapName) {
        e.preventDefault();
        this.#deleteHistory.undo(
          (snapshot) => this.#restoreDeletedRegion(snapshot),
          err => this.#setStatus(`Undo failed: ${err.message}`),
        );
        return;
      }
      if (e.ctrlKey && e.key === "y" && this.#mapName) {
        e.preventDefault();
        this.#deleteHistory.redo(
          (snapshot) => this.#redeleteRegion(snapshot),
          err => this.#setStatus(`Redo failed: ${err.message}`),
        );
        return;
      }

      // Tool shortcuts: M / S are handled explicitly; DRAW_TOOLS covers the rest
      if ((e.key === "m" || e.key === "M") && this.#mapName) {
        this.#setToolActive("move");
        return;
      }
      if ((e.key === "s" || e.key === "S") && this.#mapName) {
        this.#setToolActive(null);
        return;
      }
      for (const [type, desc] of Object.entries(DRAW_TOOLS)) {
        if (e.key.toLowerCase() === desc.key && !e.ctrlKey && this.#mapName) {
          const btn = this.#toolBtns.get(type);
          const currentlyActive = btn?.classList.contains("draw-tool-btn--active");
          this.#setToolActive(desc.toggleOff && currentlyActive ? "move" : type);
          return;
        }
      }

      if (e.key === "Escape") {
        this.#setToolActive("move");
        this.#multiSelected.clear();
        this.#sidebar.setMultiSelected([]);
        return;
      }
      if ((e.key === "Delete" || e.key === "Backspace") && this.#selectedNode) {
        e.preventDefault();
        this.#deleteNode(this.#selectedNode);
        return;
      }
      if ((e.key === "g" || e.key === "G") && e.ctrlKey && this.#mapName) {
        e.preventDefault();
        this.#groupSelected();
      }
    });
  }

  // ── map loading ────────────────────────────────────────────────────────────

  async #loadMap(mapName) {
    this.#setStatus("Loading…");
    this.setButtonsEnabled(false);
    try {
      const [ctx, groups] = await Promise.all([
        api.fetchContext(mapName),
        api.fetchRegions(mapName),
      ]);
      this.#registry.clear();
      this.#deleteHistory.clear();
      this.#canvas.render(ctx, groups);
      this.#sidebar.build(groups);
      this.#detail.clear();
      this.#canvas.clearAnchors();
      document.getElementById("toggle-blocks").checked = false;
      this.#canvas.setBlocksVisible(false);
      for (const group of groups) {
        for (const root of group.regions) this.#registry.register(root, null);
      }
      this.setButtonsEnabled(true);
      this.#setToolActive("move");
      this.#setStatus("");
      requestAnimationFrame(() => this.#canvas.resize());
    } catch (err) {
      this.#setStatus(`Error: ${err.message}`);
    }
  }

  async #reloadRegions() {
    const groups = await api.fetchRegions(this.#mapName);
    this.#registry.clear();
    this.#canvas.refreshRegions(groups);
    this.#sidebar.build(groups);
    this.#detail.clear();
    this.#canvas.clearAnchors();
    for (const group of groups) {
      for (const root of group.regions) this.#registry.register(root, null);
    }
    return groups;
  }

  // ── region CRUD ────────────────────────────────────────────────────────────

  #deleteNode(node) {
    if (!node || node.synthetic_id || !this.#mapName) return;
    api.deleteRegion(this.#mapName, node.id)
      .then(({ snapshot }) => {
        for (const id of this.#collectSubtreeIds(node)) {
          this.#canvas.removeRegion(id);
          this.#sidebar.removeRow(id);
        }
        this.#registry.unregister(node.id);
        this.#deleteHistory.pushDelete(snapshot);
      })
      .catch(err => this.#setStatus(`Delete failed: ${err.message}`));
  }

  async #restoreDeletedRegion(snapshot) {
    await api.restoreRegion(this.#mapName, snapshot);
    await this.#reloadRegions();
    this.#registry.select(snapshot.root_id);
    this.#setStatus(`Restored "${snapshot.root_id}".`);
  }

  async #redeleteRegion(snapshot) {
    await api.deleteRegion(this.#mapName, snapshot.root_id);
    await this.#reloadRegions();
    this.#setStatus(`Re-deleted "${snapshot.root_id}".`);
  }

  async #groupSelected() {
    if (this.#multiSelected.size < 2) {
      this.#setStatus("Select 2+ regions with Ctrl+click, then press Ctrl+G to group.");
      return;
    }
    const childIds = [...this.#multiSelected];
    this.#multiSelected.clear();
    this.#sidebar.setMultiSelected([]);
    try {
      const { id: newId } = await api.groupRegions(this.#mapName, childIds);
      await this.#reloadRegions();
      this.#registry.select(newId);
      this.#setStatus(`Grouped ${childIds.length} regions into "${newId}".`);
    } catch (err) {
      this.#setStatus(`Group failed: ${err.message}`);
    }
  }

  // ── delete-history rendering ───────────────────────────────────────────────

  #renderHistory() {
    const listEl = document.getElementById("history-list");
    if (!listEl) return;
    listEl.innerHTML = "";
    const { undoStack, redoStack } = this.#deleteHistory.getState();

    if (undoStack.length === 0 && redoStack.length === 0) {
      const el = document.createElement("div");
      el.className = "history-entry history-entry--empty";
      el.textContent = "no history";
      listEl.appendChild(el);
      return;
    }

    for (const entry of undoStack) {
      const el = document.createElement("div");
      el.className = "history-entry history-entry--undo";
      el.textContent = `Delete "${entry}"`;
      listEl.appendChild(el);
    }

    if (redoStack.length > 0) {
      const sep = document.createElement("div");
      sep.className = "history-entry history-entry--divider";
      sep.textContent = "── now ──";
      listEl.appendChild(sep);
      for (let i = redoStack.length - 1; i >= 0; i--) {
        const el = document.createElement("div");
        el.className = "history-entry history-entry--redo";
        el.textContent = `Delete "${redoStack[i]}"`;
        listEl.appendChild(el);
      }
    }

    listEl.scrollTop = listEl.scrollHeight;
  }

  // ── draw result → API payload / client node ───────────────────────────────

  #buildCreatePayload(d) {
    switch (d.type) {
      case "rectangle":
      case "cuboid":
        return { type: d.type, min_x: d.min_x, min_z: d.min_z, max_x: d.max_x, max_z: d.max_z };
      case "point":
      case "block":
        return { type: d.type, x: d.x, z: d.z };
      case "cylinder":
        return { type: "cylinder", base_x: d.base_x, base_z: d.base_z, radius: d.radius };
      case "circle":
        return { type: "circle", center_x: d.center_x, center_z: d.center_z, radius: d.radius };
      default:
        throw new Error(`Unknown draw type: ${d.type}`);
    }
  }

  #buildNewNode(id, d) {
    const base = { id, label: id, color: "#64748b", is_negative: false, synthetic_id: false, children: [] };
    switch (d.type) {
      case "rectangle":
        return { ...base, type: "rectangle",
          bounds: { min_x: d.min_x, min_z: d.min_z, max_x: d.max_x, max_z: d.max_z },
          coords: { min_x: d.min_x, min_z: d.min_z, max_x: d.max_x, max_z: d.max_z } };
      case "cuboid":
        return { ...base, type: "cuboid",
          bounds: { min_x: d.min_x, min_z: d.min_z, max_x: d.max_x, max_z: d.max_z },
          coords: { min_x: d.min_x, min_z: d.min_z, max_x: d.max_x, max_z: d.max_z, min_y: 0, max_y: 256 } };
      case "point":
      case "block": {
        const bounds = deriveBoundsFromCoords(d.type, { x: d.x, z: d.z });
        return { ...base, type: d.type, bounds, coords: { x: d.x, y: 64, z: d.z } };
      }
      case "cylinder": {
        const r = d.radius;
        return { ...base, type: "cylinder",
          bounds: { min_x: d.base_x - r, max_x: d.base_x + r, min_z: d.base_z - r, max_z: d.base_z + r },
          coords: { base_x: d.base_x, base_y: 64, base_z: d.base_z, radius: r, height: 10 } };
      }
      case "circle": {
        const r = d.radius;
        return { ...base, type: "circle",
          bounds: { min_x: d.center_x - r, max_x: d.center_x + r, min_z: d.center_z - r, max_z: d.center_z + r },
          coords: { center_x: d.center_x, center_z: d.center_z, radius: r } };
      }
      default:
        throw new Error(`Unknown draw type: ${d.type}`);
    }
  }

  // ── utilities ──────────────────────────────────────────────────────────────

  #collectSubtreeIds(node) {
    if (!node) return [];
    const ids = [node.id];
    for (const child of (node.children || [])) {
      if (child.id) ids.push(...this.#collectSubtreeIds(child));
    }
    return ids;
  }
}
