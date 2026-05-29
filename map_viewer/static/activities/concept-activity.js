/**
 * ConceptActivity — layout concepting and sketching tool.
 *
 * Manages the full concept page: canvas, shape list, island groups, compute,
 * and JSON export.  Instantiated once by concept.js.
 */

import { ConceptCanvas } from "../canvas/concept-canvas.js";
import { ToolManager }   from "../shared/tool-manager.js";

const ISLAND_COLORS = [
  "#4ade80", "#60a5fa", "#f472b6", "#fb923c",
  "#a78bfa", "#34d399", "#facc15", "#f87171",
];

export class ConceptActivity {
  // ── state ──────────────────────────────────────────────────────────────────
  #shapes    = new Map();   // id → shape object
  #islands   = new Map();   // id → { id, name, color }
  #shapeSeq  = 0;
  #islandSeq = 0;

  #canvas      = null;
  #tools       = null;
  #activeIslandId = null;

  constructor() {
    this.#initCanvas();
    this.#initToolbar();
    this.#initSidebars();
    this.#newIsland("Island 1");   // default island
    window.addEventListener("resize", () => this.#canvas.resize());
  }

  // ── canvas setup ───────────────────────────────────────────────────────────

  #initCanvas() {
    const svg  = document.getElementById("concept-svg");
    const wrap = document.getElementById("concept-svg-area");

    this.#canvas = new ConceptCanvas(svg, wrap, {
      onCoords:        (x, z)  => this.#updateCoords(x, z),
      onShapeCreated:  (partial) => this.#addShape(partial),
      onShapeUpdated:  (shape)   => this.#onShapeUpdated(shape),
      onShapeSelected: (id)      => this.#selectShape(id),
      onShapeDeleted:  (id)      => this.#deleteShape(id),
    });
  }

  // ── toolbar ────────────────────────────────────────────────────────────────

  #initToolbar() {
    const btnMove = document.getElementById("ct-tool-move");
    const btnRect = document.getElementById("ct-tool-rect");
    const btnCirc = document.getElementById("ct-tool-circ");
    const btnPoly = document.getElementById("ct-tool-poly");

    this.#tools = new ToolManager(this.#canvas, {
      select:    btnMove,
      rectangle: btnRect,
      circle:    btnCirc,
      polygon:   btnPoly,
    });

    // Button click handlers
    btnMove.addEventListener("click", () => this.#tools.setTool(null));
    btnRect.addEventListener("click", () => this.#tools.setTool("rectangle"));
    btnCirc.addEventListener("click", () => this.#tools.setTool("circle"));
    btnPoly.addEventListener("click", () => this.#tools.setTool("polygon"));

    // Keyboard shortcuts
    document.addEventListener("keydown", (e) => {
      if (["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
      if (e.key === "m" || e.key === "M") this.#tools.setTool(null);
      if (e.key === "r" || e.key === "R") this.#tools.setTool("rectangle");
      if (e.key === "o" || e.key === "O") this.#tools.setTool("circle");
      if (e.key === "p" || e.key === "P") this.#tools.setTool("polygon");
    });

    this.#tools.setTool(null);

    // Add / subtract toggle
    const btnAdd = document.getElementById("ct-op-add");
    const btnSub = document.getElementById("ct-op-sub");
    const setOp = (op) => {
      this.#canvas.setOperation(op);
      btnAdd.classList.toggle("draw-tool-btn--active", op === "add");
      btnSub.classList.toggle("draw-tool-btn--active", op === "subtract");
    };
    btnAdd.addEventListener("click", () => setOp("add"));
    btnSub.addEventListener("click", () => setOp("subtract"));
    setOp("add");

    // Canvas size controls
    document.getElementById("ct-apply-size").addEventListener("click", () => {
      const half = Math.max(32, Math.min(2048,
        parseInt(document.getElementById("ct-canvas-half").value, 10) || 256));
      document.getElementById("ct-canvas-half").value = half;
      this.#canvas.setBBox(-half, half, -half, half);
    });
  }

  // ── sidebar wiring ─────────────────────────────────────────────────────────

  #initSidebars() {
    document.getElementById("ct-new-island").addEventListener("click",
      () => this.#newIsland(`Island ${this.#islandSeq + 1}`));
    document.getElementById("ct-compute-all").addEventListener("click",
      () => this.#computeAll());
    document.getElementById("ct-export").addEventListener("click",
      () => this.#exportJSON());
  }

  // ── island management ─────────────────────────────────────────────────────

  #newIsland(name) {
    const id    = `i${++this.#islandSeq}`;
    const color = ISLAND_COLORS[(this.#islandSeq - 1) % ISLAND_COLORS.length];
    this.#islands.set(id, { id, name, color, result: null });
    if (!this.#activeIslandId) this.#activeIslandId = id;
    this.#renderIslandList();
    this.#renderIslandSelect();
    return id;
  }

  #renderIslandList() {
    const list = document.getElementById("ct-island-list");
    list.innerHTML = "";
    for (const isl of this.#islands.values()) {
      const card = document.createElement("div");
      card.className = "concept-island-card" + (isl.id === this.#activeIslandId ? " concept-island-card--active" : "");
      card.dataset.id = isl.id;

      const shapeCount = [...this.#shapes.values()].filter(s => s.island_id === isl.id).length;
      const resultSummary = isl.result
        ? `${isl.result.exterior.length} exterior pts · ${isl.result.holes.length} hole(s)`
        : "no result";

      card.innerHTML = `
        <div class="concept-island-header">
          <span class="concept-island-dot" style="background:${isl.color}"></span>
          <input class="concept-island-name field-input" value="${_esc(isl.name)}" spellcheck="false"/>
          <button class="btn-remove concept-island-del" title="Delete island">×</button>
        </div>
        <div class="concept-island-meta">${shapeCount} shape(s) · <em>${resultSummary}</em></div>
        <div class="concept-island-actions">
          <button class="action-btn concept-island-active-btn" title="Set as active island for new shapes">
            ${isl.id === this.#activeIslandId ? "Active" : "Set active"}
          </button>
          <button class="action-btn action-btn--primary concept-island-compute-btn">Compute</button>
        </div>
      `;

      card.querySelector(".concept-island-name").addEventListener("change", (e) => {
        isl.name = e.target.value.trim() || isl.name;
        this.#renderShapeList();
      });
      card.querySelector(".concept-island-del").addEventListener("click", () => {
        this.#deleteIsland(isl.id);
      });
      card.querySelector(".concept-island-active-btn").addEventListener("click", () => {
        this.#activeIslandId = isl.id;
        this.#renderIslandList();
        this.#renderIslandSelect();
      });
      card.querySelector(".concept-island-compute-btn").addEventListener("click", () => {
        this.#computeIsland(isl.id);
      });

      list.appendChild(card);
    }
  }

  #deleteIsland(id) {
    if (this.#islands.size <= 1) return;  // keep at least one
    // Reassign shapes to the first remaining island
    const fallback = [...this.#islands.keys()].find(k => k !== id);
    for (const shape of this.#shapes.values()) {
      if (shape.island_id === id) {
        shape.island_id = fallback;
        this.#canvas.updateShape(shape);
      }
    }
    this.#islands.delete(id);
    if (this.#activeIslandId === id) this.#activeIslandId = fallback;
    this.#renderIslandList();
    this.#renderIslandSelect();
    this.#renderShapeList();
  }

  #renderIslandSelect() {
    const sel = document.getElementById("ct-island-select");
    if (!sel) return;
    const prev = sel.value;
    sel.innerHTML = "";
    for (const isl of this.#islands.values()) {
      const opt = document.createElement("option");
      opt.value = isl.id;
      opt.textContent = isl.name;
      sel.appendChild(opt);
    }
    sel.value = this.#islands.has(prev) ? prev : (this.#activeIslandId ?? "");
  }

  // ── shape management ───────────────────────────────────────────────────────

  #addShape(partial) {
    const id = `s${++this.#shapeSeq}`;
    const shape = {
      ...partial,
      id,
      island_id: this.#activeIslandId ?? [...this.#islands.keys()][0],
    };
    this.#shapes.set(id, shape);
    this.#canvas.addShape(shape);
    this.#selectShape(id);
    this.#renderShapeList();
    this.#renderIslandList();
  }

  #onShapeUpdated(shape) {
    this.#shapes.set(shape.id, shape);
    // Shape list label might need updating (e.g., size display)
    const row = document.querySelector(`[data-shape-id="${shape.id}"]`);
    if (row) {
      const lbl = row.querySelector(".concept-shape-label");
      if (lbl) lbl.textContent = this.#shapeLabel(shape);
    }
  }

  #selectShape(id) {
    this.#canvas.selectShape(id);
    document.querySelectorAll(".concept-shape-row").forEach(r => {
      r.classList.toggle("list-row--selected", r.dataset.shapeId === id);
    });
    // Sync island select dropdown to match the selected shape's island
    if (id) {
      const shape = this.#shapes.get(id);
      const sel = document.getElementById("ct-island-select");
      if (sel && shape) sel.value = shape.island_id;
    }
  }

  #deleteShape(id) {
    this.#shapes.delete(id);
    this.#canvas.removeShape(id);
    this.#renderShapeList();
    this.#renderIslandList();
  }

  #shapeLabel(shape) {
    if (shape.type === "rectangle") {
      const w = shape.max_x - shape.min_x, h = shape.max_z - shape.min_z;
      return `rect ${w}×${h}`;
    }
    if (shape.type === "circle")  return `circle r=${shape.radius}`;
    if (shape.type === "polygon") return `poly ${shape.vertices.length}v`;
    return shape.type;
  }

  #renderShapeList() {
    const list = document.getElementById("ct-shape-list");
    list.innerHTML = "";
    if (this.#shapes.size === 0) {
      list.innerHTML = '<div class="concept-empty">No shapes yet. Draw with the tools above.</div>';
      return;
    }
    for (const shape of this.#shapes.values()) {
      const isl   = this.#islands.get(shape.island_id);
      const isAdd = shape.operation !== "subtract";
      const row   = document.createElement("div");
      row.className = "list-row list-row--compact concept-shape-row";
      row.dataset.shapeId = shape.id;
      row.innerHTML = `
        <span class="concept-op-badge concept-op-badge--${isAdd ? "add" : "sub"}">${isAdd ? "add" : "sub"}</span>
        <span class="concept-shape-icon">${_typeIcon(shape.type)}</span>
        <span class="concept-shape-label">${this.#shapeLabel(shape)}</span>
        <span class="concept-island-dot" style="background:${isl?.color ?? "#475569"}" title="${_esc(isl?.name ?? "")}"></span>
        <button class="btn-remove" title="Delete shape">×</button>
      `;
      row.addEventListener("click", (e) => {
        if (e.target.classList.contains("btn-remove")) return;
        this.#selectShape(shape.id);
      });
      row.querySelector(".btn-remove").addEventListener("click", (e) => {
        e.stopPropagation();
        this.#deleteShape(shape.id);
      });
      list.appendChild(row);
    }

    // Island-select row (below list, for selected shape)
    const assignRow = document.createElement("div");
    assignRow.id = "ct-assign-row";
    assignRow.className = "concept-assign-row";
    assignRow.innerHTML = `
      <label class="field-label">Assign to island</label>
      <select id="ct-island-select" class="field-input"></select>
    `;
    assignRow.querySelector("select").addEventListener("change", (e) => {
      const selRow = document.querySelector(".concept-shape-row.list-row--selected");
      if (!selRow) return;
      const sid = selRow.dataset.shapeId;
      const shape = this.#shapes.get(sid);
      if (!shape) return;
      shape.island_id = e.target.value;
      this.#renderShapeList();
      this.#renderIslandList();
      this.#selectShape(sid);
    });
    list.appendChild(assignRow);
    this.#renderIslandSelect();
  }

  // ── compute ────────────────────────────────────────────────────────────────

  async #computeIsland(islandId) {
    this.#setStatus("Computing…");
    try {
      const isl    = this.#islands.get(islandId);
      const shapes = [...this.#shapes.values()].filter(s => s.island_id === islandId);
      const res    = await fetch("/api/concept/compute", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({
          shapes,
          islands: [{ id: islandId, name: isl.name, shape_ids: shapes.map(s => s.id) }],
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const resultIsland = data.islands?.[0];
      isl.result = resultIsland?.polygon ?? null;
      this.#canvas.setResultPolygons(
        [...this.#islands.values()].map(i => i.result).filter(Boolean)
      );
      this.#renderIslandList();
      this.#setStatus(isl.result ? "Computed." : "No geometry produced.");
    } catch (err) {
      this.#setStatus(`Error: ${err.message}`);
    }
  }

  async #computeAll() {
    this.#setStatus("Computing all islands…");
    try {
      const shapes  = [...this.#shapes.values()];
      const islands = [...this.#islands.values()].map(isl => ({
        id:        isl.id,
        name:      isl.name,
        shape_ids: shapes.filter(s => s.island_id === isl.id).map(s => s.id),
      }));
      const res = await fetch("/api/concept/compute", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ shapes, islands }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      for (const ri of (data.islands || [])) {
        const isl = this.#islands.get(ri.id);
        if (isl) isl.result = ri.polygon ?? null;
      }
      this.#canvas.setResultPolygons(
        [...this.#islands.values()].map(i => i.result).filter(Boolean)
      );
      this.#renderIslandList();
      this.#setStatus("All islands computed.");
    } catch (err) {
      this.#setStatus(`Error: ${err.message}`);
    }
  }

  // ── export ─────────────────────────────────────────────────────────────────

  #exportJSON() {
    const payload = [...this.#islands.values()].map(isl => ({
      name:    isl.name,
      polygon: isl.result ?? null,
    }));
    const json = JSON.stringify(payload, null, 2);
    const a    = document.createElement("a");
    a.href     = `data:application/json,${encodeURIComponent(json)}`;
    a.download = "concept-layout.json";
    a.click();
  }

  // ── utils ──────────────────────────────────────────────────────────────────

  #updateCoords(x, z) {
    const el = document.getElementById("ct-coords");
    if (!el) return;
    el.textContent = (x === null) ? "" : `x ${x}  z ${z}`;
  }

  #setStatus(msg) {
    const el = document.getElementById("status");
    if (el) el.textContent = msg;
  }
}

function _esc(str) {
  return String(str).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

function _typeIcon(type) {
  if (type === "rectangle") return "▭";
  if (type === "circle")    return "◯";
  if (type === "polygon")   return "⬡";
  return "?";
}
