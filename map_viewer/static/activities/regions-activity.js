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

import { MapCanvas }          from "../canvas/map-canvas.js";
import { RegionSidebar }      from "../panels/region-sidebar.js";
import { RegionRegistry }     from "../region/region-registry.js";
import { RegionDetail }       from "../panels/region-detail.js";
import { DeletedRegionHistory } from "../region/deleted-region-history.js";
import { COMPOUND_TYPES, DRAW_TOOLS, deriveBoundsFromCoords } from "../region/region-types.js";
import { createRegionHandlers }  from "../region/region-handlers.js";
import { isEditableTarget }   from "../shared/ui-helpers.js";
import { ToolManager }        from "../shared/tool-manager.js";
import * as api               from "../api.js";

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

  #tools        = null;   // ToolManager — toolbar state + canvas.setActiveTool
  #ctxMenu      = null;   // floating context-menu element

  // ── constructor ────────────────────────────────────────────────────────────

  constructor({ setStatus } = {}) {
    this.#el           = document.getElementById("regions-workspace");
    this.#setStatus    = setStatus ?? (() => {});
    this.#multiSelected = new Set();
    this.#blockCache   = new Map();

    this.#initComponents();
    this.#initContextMenu();
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

  /** Called during map load to disable toolbar while loading, re-enable after. */
  setButtonsEnabled(enabled) {
    this.#tools.setEnabled(enabled);
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
          this.#tools.setTool(null);
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
        onIdChange: (node, oldId, newId) => this.#handlers?.onRenameRegion(node, oldId, newId),
      },
    );

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
        onContextMenu: (node, pos, ctx) => this.#showContextMenu(node, pos, ctx),
      },
    );

    // Handlers created last so sidebar and detail are both available.
    this.#handlers = createRegionHandlers({
      canvas:     this.#canvas,
      registry:   this.#registry,
      detail:     this.#detail,
      sidebar:    this.#sidebar,
      getMapName: () => this.#mapName,
      getHistory: () => this.#deleteHistory,
    });
  }

  // ── toolbar ────────────────────────────────────────────────────────────────

  #initToolbar() {
    const moveBtn   = document.getElementById("tool-move");
    const selectBtn = document.getElementById("tool-select");
    const btnMap    = { move: moveBtn, select: selectBtn };
    const drawDescs = new Map();

    for (const [type, desc] of Object.entries(DRAW_TOOLS)) {
      const btn = document.getElementById(`tool-${type}`);
      if (!btn) continue;
      btnMap[type] = btn;
      drawDescs.set(type, desc);
    }

    this.#tools = new ToolManager(this.#canvas, btnMap);

    moveBtn.addEventListener("click",   () => this.#tools.setTool("move"));
    selectBtn.addEventListener("click", () => this.#tools.setTool(null));
    for (const [type, desc] of drawDescs) {
      const btn = btnMap[type];
      btn.addEventListener("click", () => {
        this.#tools.setTool(desc.toggleOff && this.#tools.activeTool === type ? "move" : type);
      });
    }
  }

  // ── layer toggles ──────────────────────────────────────────────────────────

  #initLayerToggles() {
    document.getElementById("toggle-resolved").addEventListener("change",
      (e) => this.#canvas.setResolvedMode(e.target.checked));
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

  // ── context menu ──────────────────────────────────────────────────────────

  #initContextMenu() {
    const menu = document.createElement("div");
    menu.className = "ctx-menu";
    menu.hidden = true;
    document.body.appendChild(menu);
    this.#ctxMenu = menu;

    document.addEventListener("click",     () => this.#hideContextMenu(), true);
    document.addEventListener("keydown",   (e) => { if (e.key === "Escape") this.#hideContextMenu(); }, true);
    document.addEventListener("contextmenu", (e) => {
      if (!menu.contains(e.target)) this.#hideContextMenu();
    }, true);
  }

  #showContextMenu(node, { x, y }, { parentId = null, parentType = null, childIndex = 0, siblingCount = 0 } = {}) {
    const menu = this.#ctxMenu;
    menu.innerHTML = "";

    const item = (label, shortcut, action, danger = false) => {
      const el = document.createElement("button");
      el.className = "ctx-item" + (danger ? " ctx-item--danger" : "");
      const labelSpan = document.createElement("span");
      labelSpan.textContent = label;
      el.appendChild(labelSpan);
      if (shortcut) {
        const kbdEl = document.createElement("kbd");
        kbdEl.textContent = shortcut;
        el.appendChild(kbdEl);
      }
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        this.#hideContextMenu();
        action();
      });
      return el;
    };

    const canGroup           = this.#multiSelected.size >= 2;
    const isUnion            = node.type === "union";
    const isCompound         = COMPOUND_TYPES.has(node.type);
    const canSetBase         = parentType === "complement" && childIndex > 0 && siblingCount >= 2;
    const canRemoveFromGroup = COMPOUND_TYPES.has(parentType);

    if (canSetBase) {
      menu.appendChild(item("Set as base", null, () => this.#setBaseChild(parentId, node.id)));
    }
    if (canRemoveFromGroup) {
      menu.appendChild(item("Remove from group", null, () => this.#removeFromGroup(parentId, node.id)));
    }
    if (isCompound) {
      menu.appendChild(this.#changeTypeSubmenu(node));
    }
    if (isUnion) {
      menu.appendChild(item("Ungroup", "Ctrl+G", () => this.#ungroupSelected()));
    }
    if (canGroup) {
      menu.appendChild(item("Group", "Ctrl+G", () => this.#groupSelected()));
    }
    const hasFocus = node.bounds || node.polygon_2d?.exterior?.length;
    if (hasFocus) {
      menu.appendChild(item("Focus", null, () => this.#canvas.focusRegion(node)));
    }
    if ((canSetBase || canRemoveFromGroup || isCompound || isUnion || canGroup || hasFocus) && !node.synthetic_id) {
      const sep = document.createElement("div");
      sep.className = "ctx-sep";
      menu.appendChild(sep);
    }
    if (!node.synthetic_id) {
      menu.appendChild(item("Delete", "Del", () => this.#deleteNode(node), true));
    }

    if (!menu.children.length) return;

    menu.hidden = false;
    const vw = window.innerWidth, vh = window.innerHeight;
    const mw = 180, mh = menu.offsetHeight || 120;
    menu.style.left = (x + mw > vw ? vw - mw - 4 : x) + "px";
    menu.style.top  = (y + mh > vh ? vh - mh - 4 : y) + "px";
  }

  #hideContextMenu() {
    if (this.#ctxMenu) this.#ctxMenu.hidden = true;
  }

  // ── keyboard shortcuts ─────────────────────────────────────────────────────

  #initKeyboard() {
    document.addEventListener("keydown", (e) => {
      // Only fire when this activity is visible
      if (this.#el.hidden) return;
      if (isEditableTarget(e)) return;

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
        this.#tools.setTool("move");
        return;
      }
      if ((e.key === "s" || e.key === "S") && this.#mapName) {
        this.#tools.setTool(null);
        return;
      }
      for (const [type, desc] of Object.entries(DRAW_TOOLS)) {
        if (e.key.toLowerCase() === desc.key && !e.ctrlKey && this.#mapName) {
          this.#tools.setTool(desc.toggleOff && this.#tools.activeTool === type ? "move" : type);
          return;
        }
      }

      if (e.key === "Escape") {
        this.#tools.setTool("move");
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
        if (this.#multiSelected.size === 0 && this.#selectedNode?.type === "union") {
          this.#ungroupSelected();
        } else {
          this.#groupSelected();
        }
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
      this.#tools.setTool("move");
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

  async #removeFromGroup(parentId, childId) {
    try {
      await api.removeFromGroup(this.#mapName, parentId, childId);
      await this.#reloadRegions();
      this.#setStatus(`"${childId}" removed from "${parentId}".`);
    } catch (err) {
      this.#setStatus(`Remove from group failed: ${err.message}`);
    }
  }

  #changeTypeSubmenu(node) {
    const btn = document.createElement("button");
    btn.className = "ctx-item ctx-item--sub";
    const labelSpan = document.createElement("span");
    labelSpan.textContent = "Change type";
    const arrow = document.createElement("span");
    arrow.textContent = "▶";
    arrow.style.cssText = "font-size:9px; color:var(--text-muted)";
    btn.appendChild(labelSpan);
    btn.appendChild(arrow);

    const sub = document.createElement("div");
    sub.className = "ctx-submenu";
    for (const t of COMPOUND_TYPES) {
      if (t === node.type) continue;
      const opt = document.createElement("button");
      opt.className = "ctx-item";
      opt.textContent = t.charAt(0).toUpperCase() + t.slice(1);
      opt.addEventListener("click", (e) => {
        e.stopPropagation();
        this.#hideContextMenu();
        this.#changeType(node.id, t);
      });
      sub.appendChild(opt);
    }
    btn.appendChild(sub);
    return btn;
  }

  async #changeType(regionId, newType) {
    try {
      await api.changeRegionType(this.#mapName, regionId, newType);
      await this.#reloadRegions();
      this.#setStatus(`Changed "${regionId}" to ${newType}.`);
    } catch (err) {
      this.#setStatus(`Change type failed: ${err.message}`);
    }
  }

  async #setBaseChild(parentId, childId) {
    try {
      await api.setBaseChild(this.#mapName, parentId, childId);
      await this.#reloadRegions();
      this.#setStatus(`"${childId}" is now the base of "${parentId}".`);
    } catch (err) {
      this.#setStatus(`Set base failed: ${err.message}`);
    }
  }

  async #ungroupSelected() {
    const node = this.#selectedNode;
    if (!node || node.type !== "union") return;
    try {
      const { child_ids: childIds } = await api.ungroupRegion(this.#mapName, node.id);
      await this.#reloadRegions();
      this.#setStatus(`Ungrouped "${node.id}" into ${childIds.length} region(s).`);
    } catch (err) {
      this.#setStatus(`Ungroup failed: ${err.message}`);
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
