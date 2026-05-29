/**
 * ConceptCanvas — SVG canvas for the map layout concepting tool.
 *
 * Shares transform utilities with MapCanvas but is purpose-built for
 * free-form island sketching.  Supports four draw tools:
 *   rectangle  — drag to draw, 8-handle resize after placement
 *   circle     — two-click radial, center then radius
 *   polygon    — click vertices, double-click or first-vertex-click to close;
 *                drag vertex handles to adjust after placement
 *   lasso      — hold mouse button and drag to trace a freeform outline;
 *                release to auto-close the polygon
 *
 * All coordinates snap to integer block positions.
 *
 * Callbacks:
 *   onCoords(x, z)              block coords under cursor (null,null on leave)
 *   onShapeCreated(partial)     new shape finished (no id yet)
 *   onShapeUpdated(shape)       shape mutated by resize / vertex drag
 *   onShapeSelected(id | null)  shape selected or canvas-click-deselected
 *   onZoom(scale)               zoom level changed
 */

import { buildTransform, buildInverseTransform, svgEl, polyToPath } from "./transform.js";

const ZOOM_FACTOR = 1.15;
const ZOOM_MIN    = 0.5;
const ZOOM_MAX    = 200;

const HANDLE_HALF  = 5;   // half-size of resize / vertex handles in screen px
const VERTEX_HALF  = 4;

// 8-handle definitions for rectangle resize
const HANDLE_DEFS = [
  { key: "nw", pos: b => [b.l, b.t], cursor: "nw-resize", xf: "min_x", zf: "min_z" },
  { key: "n",  pos: b => [b.mx,b.t], cursor: "n-resize",  xf: null,    zf: "min_z" },
  { key: "ne", pos: b => [b.r, b.t], cursor: "ne-resize", xf: "max_x", zf: "min_z" },
  { key: "w",  pos: b => [b.l, b.my],cursor: "w-resize",  xf: "min_x", zf: null    },
  { key: "e",  pos: b => [b.r, b.my],cursor: "e-resize",  xf: "max_x", zf: null    },
  { key: "sw", pos: b => [b.l, b.b], cursor: "sw-resize", xf: "min_x", zf: "max_z" },
  { key: "s",  pos: b => [b.mx,b.b], cursor: "s-resize",  xf: null,    zf: "max_z" },
  { key: "se", pos: b => [b.r, b.b], cursor: "se-resize", xf: "max_x", zf: "max_z" },
];

const ADD_FILL    = "#0d9488";
const ADD_STROKE  = "#0f766e";
const SUB_FILL    = "#dc2626";
const SUB_STROKE  = "#b91c1c";
const RES_FILL    = "#6366f1";
const RES_STROKE  = "#4338ca";

export class ConceptCanvas {
  #svg;
  #wrap;
  #callbacks;

  // ── transform ──────────────────────────────────────────────────────────────
  #bbox    = [-256, 256, -256, 256];   // [minX, maxX, minZ, maxZ]
  #toSvg   = null;
  #toWorld = null;

  // ── zoom / pan ─────────────────────────────────────────────────────────────
  #scale = 1;
  #panX  = 0;
  #panY  = 0;

  // ── pan drag state ─────────────────────────────────────────────────────────
  #isPanning    = false;
  #midPanning   = false;
  #panAnchor    = null;
  #didPan       = false;
  #clickWasDrag = false;

  // ── shapes ─────────────────────────────────────────────────────────────────
  #shapes     = new Map();   // id → shape
  #resultPolys = [];         // [{exterior,holes}] from compute
  #selectedId  = null;
  #shapeElMap  = new Map();  // id → SVG <g> element

  // ── tool state ─────────────────────────────────────────────────────────────
  #activeTool      = null;   // null | "rectangle" | "circle" | "polygon"
  #activeOperation = "add";

  // ── in-progress draw state ─────────────────────────────────────────────────
  #drawState = null;
  // rectangle: { startBx, startBz, currentBx, currentBz, previewRect }
  // circle:    { centerX, centerZ, currentRadius, previewCircle, dot }
  // polygon:   { vertices:[[x,z],...], dots:[SVGEl,...], lines:[SVGEl,...], previewLine:SVGEl }
  // lasso:     { vertices:[[x,z],...], previewPath:SVGEl }

  // ── edit drag state ────────────────────────────────────────────────────────
  #rectResizeState  = null;  // { shapeId, xf, zf }
  #vertexDragState  = null;  // { shapeId, vertexIdx }

  // ── center marker ──────────────────────────────────────────────────────────
  #centerX = 0;
  #centerZ = 0;

  // ── SVG layers ─────────────────────────────────────────────────────────────
  #viewportG      = null;
  #gridLayerEl    = null;
  #shapesLayerEl  = null;
  #resultLayerEl  = null;
  #drawLayerEl    = null;
  #handlesLayerEl = null;  // outside viewport — screen-space handles
  #centerLayerEl  = null;  // outside viewport — center crosshair marker
  #overlayLayerEl = null;  // outside viewport — coord label etc.

  constructor(svgElement, wrapElement, callbacks = {}) {
    this.#svg       = svgElement;
    this.#wrap      = wrapElement;
    this.#callbacks = callbacks;
    this.#repaint();
    this.#setupEvents();
  }

  // ── public API ──────────────────────────────────────────────────────────────

  setActiveTool(tool) {
    this.#cancelDraw();
    this.#activeTool = tool;
    this.#refreshCursor();
  }

  setOperation(op) { this.#activeOperation = op; }

  setBBox(minX, maxX, minZ, maxZ) {
    this.#bbox = [minX, maxX, minZ, maxZ];
    this.#scale = 1; this.#panX = 0; this.#panY = 0;
    this.#repaint();
    this.#reshapeAll();
  }

  setCenter(x, z) {
    this.#centerX = x;
    this.#centerZ = z;
    this.#refreshCenterMarker();
  }

  addShape(shape) {
    this.#shapes.set(shape.id, shape);
    if (this.#shapesLayerEl && this.#toSvg) {
      const g = this.#renderShapeEl(shape);
      this.#shapeElMap.set(shape.id, g);
      this.#shapesLayerEl.appendChild(g);
    }
  }

  updateShape(shape) {
    this.#shapes.set(shape.id, shape);
    const old = this.#shapeElMap.get(shape.id);
    if (old?.parentNode) old.parentNode.removeChild(old);
    if (this.#shapesLayerEl && this.#toSvg) {
      const g = this.#renderShapeEl(shape);
      this.#shapeElMap.set(shape.id, g);
      this.#shapesLayerEl.appendChild(g);
    }
    if (this.#selectedId === shape.id) this.#refreshHandles();
  }

  removeShape(id) {
    this.#shapes.delete(id);
    const el = this.#shapeElMap.get(id);
    if (el?.parentNode) el.parentNode.removeChild(el);
    this.#shapeElMap.delete(id);
    if (this.#selectedId === id) {
      this.#selectedId = null;
      this.#refreshHandles();
    }
  }

  setResultPolygons(polys) {
    this.#resultPolys = polys || [];
    this.#rebuildResultLayer();
  }

  selectShape(id) {
    this.#selectedId = id;
    for (const [sid, g] of this.#shapeElMap) {
      g.classList.toggle("concept-shape--selected", sid === id);
    }
    this.#refreshHandles();
  }

  resize() {
    this.#repaint();
    this.#reshapeAll();
  }

  // ── rendering ──────────────────────────────────────────────────────────────

  #repaint() {
    const w = this.#wrap.clientWidth  - 24;
    const h = this.#wrap.clientHeight - 24;
    if (w <= 0 || h <= 0) return;
    this.#svg.setAttribute("width",   w);
    this.#svg.setAttribute("height",  h);
    this.#svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    this.#toSvg   = buildTransform(this.#bbox, w, h);
    this.#toWorld = buildInverseTransform(this.#bbox, w, h);

    while (this.#svg.firstChild) this.#svg.removeChild(this.#svg.firstChild);

    const viewport = svgEl("g");
    this.#viewportG = viewport;
    this.#applyViewportTransform();

    this.#gridLayerEl   = this.#buildGridLayer();
    this.#shapesLayerEl = svgEl("g", { id: "layer-concept-shapes" });
    this.#resultLayerEl = svgEl("g", { id: "layer-concept-result" });
    this.#drawLayerEl   = svgEl("g", { id: "layer-concept-draw" });
    viewport.appendChild(this.#gridLayerEl);
    viewport.appendChild(this.#shapesLayerEl);
    viewport.appendChild(this.#resultLayerEl);
    viewport.appendChild(this.#drawLayerEl);

    // Handles, center marker, and overlay live outside the viewport so they
    // stay fixed-size regardless of zoom level.
    this.#handlesLayerEl = svgEl("g", { id: "layer-concept-handles" });
    this.#centerLayerEl  = svgEl("g", { id: "layer-concept-center", "pointer-events": "none" });
    this.#overlayLayerEl = svgEl("g", { id: "layer-concept-overlay" });

    this.#svg.appendChild(viewport);
    this.#svg.appendChild(this.#handlesLayerEl);
    this.#svg.appendChild(this.#centerLayerEl);
    this.#svg.appendChild(this.#overlayLayerEl);
    this.#refreshCenterMarker();
  }

  #reshapeAll() {
    if (!this.#shapesLayerEl || !this.#toSvg) return;
    while (this.#shapesLayerEl.firstChild) this.#shapesLayerEl.removeChild(this.#shapesLayerEl.firstChild);
    this.#shapeElMap.clear();
    for (const shape of this.#shapes.values()) {
      const g = this.#renderShapeEl(shape);
      this.#shapeElMap.set(shape.id, g);
      this.#shapesLayerEl.appendChild(g);
    }
    this.#rebuildResultLayer();
    this.#refreshHandles();
    this.#refreshCenterMarker();
  }

  #buildGridLayer() {
    const g = svgEl("g", { id: "layer-concept-grid", "pointer-events": "none" });
    if (!this.#toSvg) return g;
    const [minX, maxX, minZ, maxZ] = this.#bbox;
    const step  = 16;
    const startX = Math.floor(minX / step) * step;
    const startZ = Math.floor(minZ / step) * step;
    for (let x = startX; x <= maxX; x += step) {
      const p1 = this.#toSvg(x, minZ), p2 = this.#toSvg(x, maxZ);
      g.appendChild(svgEl("line", {
        x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y,
        stroke: x === 0 ? "#334155" : "#1e293b",
        "stroke-width": x === 0 ? "0.8" : "0.3",
      }));
    }
    for (let z = startZ; z <= maxZ; z += step) {
      const p1 = this.#toSvg(minX, z), p2 = this.#toSvg(maxX, z);
      g.appendChild(svgEl("line", {
        x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y,
        stroke: z === 0 ? "#334155" : "#1e293b",
        "stroke-width": z === 0 ? "0.8" : "0.3",
      }));
    }
    return g;
  }

  #renderShapeEl(shape) {
    const isAdd  = shape.operation !== "subtract";
    const fill   = isAdd ? ADD_FILL  : SUB_FILL;
    const stroke = isAdd ? ADD_STROKE : SUB_STROKE;

    const g = svgEl("g", { class: "concept-shape", "data-id": shape.id });

    if (shape.type === "rectangle") {
      const p1 = this.#toSvg(shape.min_x, shape.min_z);
      const p2 = this.#toSvg(shape.max_x, shape.max_z);
      g.appendChild(svgEl("rect", {
        x: Math.min(p1.x, p2.x), y: Math.min(p1.y, p2.y),
        width: Math.abs(p2.x - p1.x), height: Math.abs(p2.y - p1.y),
        fill, stroke, "stroke-width": "1.2", "fill-opacity": "0.30",
        "vector-effect": "non-scaling-stroke",
      }));
    } else if (shape.type === "circle") {
      const p1 = this.#toSvg(shape.center_x - shape.radius, shape.center_z - shape.radius);
      const p2 = this.#toSvg(shape.center_x + shape.radius, shape.center_z + shape.radius);
      g.appendChild(svgEl("ellipse", {
        cx: (p1.x + p2.x) / 2, cy: (p1.y + p2.y) / 2,
        rx: Math.abs(p2.x - p1.x) / 2, ry: Math.abs(p2.y - p1.y) / 2,
        fill, stroke, "stroke-width": "1.2", "fill-opacity": "0.30",
        "vector-effect": "non-scaling-stroke",
      }));
    } else if (shape.type === "polygon") {
      const d = shape.vertices.map(([x, z], i) => {
        const p = this.#toSvg(x, z);
        return (i === 0 ? "M" : "L") + `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
      }).join(" ") + " Z";
      g.appendChild(svgEl("path", {
        d, fill, stroke, "stroke-width": "1.2", "fill-opacity": "0.30",
        "fill-rule": "evenodd", "vector-effect": "non-scaling-stroke",
      }));
    }

    g.style.cursor = "pointer";
    g.addEventListener("click", (e) => {
      if (this.#activeTool !== null) return;
      e.stopPropagation();   // prevent canvas click from deselecting immediately after
      this.#callbacks.onShapeSelected?.(shape.id);
    });

    return g;
  }

  #rebuildResultLayer() {
    if (!this.#resultLayerEl || !this.#toSvg) return;
    while (this.#resultLayerEl.firstChild) this.#resultLayerEl.removeChild(this.#resultLayerEl.firstChild);
    for (const poly of this.#resultPolys) {
      if (!poly?.exterior?.length) continue;
      this.#resultLayerEl.appendChild(svgEl("path", {
        d: polyToPath(poly, this.#toSvg),
        fill: RES_FILL, stroke: RES_STROKE,
        "stroke-width": "1.5", "fill-opacity": "0.18",
        "fill-rule": "evenodd", "vector-effect": "non-scaling-stroke",
        "pointer-events": "none",
      }));
    }
  }

  // ── handles (screen-space, outside viewport) ───────────────────────────────

  /** Convert a base-SVG point to screen pixel coordinates. */
  #toScreen(svgX, svgY) {
    return { x: svgX * this.#scale + this.#panX, y: svgY * this.#scale + this.#panY };
  }

  #refreshHandles() {
    if (!this.#handlesLayerEl) return;
    while (this.#handlesLayerEl.firstChild) this.#handlesLayerEl.removeChild(this.#handlesLayerEl.firstChild);
    if (!this.#selectedId || !this.#toSvg) return;
    const shape = this.#shapes.get(this.#selectedId);
    if (!shape) return;

    if (shape.type === "rectangle") {
      this.#renderRectHandles(shape);
    } else if (shape.type === "polygon") {
      this.#renderVertexHandles(shape);
    }
  }

  #renderRectHandles(shape) {
    const p1 = this.#toSvg(shape.min_x, shape.min_z);
    const p2 = this.#toSvg(shape.max_x, shape.max_z);
    const s1 = this.#toScreen(p1.x, p1.y);
    const s2 = this.#toScreen(p2.x, p2.y);
    const b = {
      l:  Math.min(s1.x, s2.x),
      r:  Math.max(s1.x, s2.x),
      t:  Math.min(s1.y, s2.y),
      b:  Math.max(s1.y, s2.y),
    };
    b.mx = (b.l + b.r) / 2;
    b.my = (b.t + b.b) / 2;

    for (const hd of HANDLE_DEFS) {
      const [hx, hy] = hd.pos(b);
      const h = svgEl("rect", {
        x: hx - HANDLE_HALF, y: hy - HANDLE_HALF,
        width: HANDLE_HALF * 2, height: HANDLE_HALF * 2,
        fill: "#0f172a", stroke: "#94a3b8", "stroke-width": "1",
        style: `cursor:${hd.cursor}`,
      });
      const { xf, zf } = hd;
      h.addEventListener("mousedown", (e) => {
        if (e.button !== 0) return;
        e.stopPropagation();
        this.#rectResizeState = { shapeId: shape.id, xf, zf };
        this.#svg.style.cursor = hd.cursor;
        this.#clickWasDrag = true;
      });
      this.#handlesLayerEl.appendChild(h);
    }
  }

  #renderVertexHandles(shape) {
    shape.vertices.forEach(([wx, wz], idx) => {
      const svgPt = this.#toSvg(wx, wz);
      const sp = this.#toScreen(svgPt.x, svgPt.y);
      const h = svgEl("rect", {
        x: sp.x - VERTEX_HALF, y: sp.y - VERTEX_HALF,
        width: VERTEX_HALF * 2, height: VERTEX_HALF * 2,
        fill: "#0f172a", stroke: "#94a3b8", "stroke-width": "1",
        style: "cursor:move",
      });
      h.addEventListener("mousedown", (e) => {
        if (e.button !== 0) return;
        e.stopPropagation();
        this.#vertexDragState = { shapeId: shape.id, vertexIdx: idx };
        this.#svg.style.cursor = "move";
        this.#clickWasDrag = true;
      });
      this.#handlesLayerEl.appendChild(h);
    });
  }

  // ── draw tools ─────────────────────────────────────────────────────────────

  #opFill()   { return this.#activeOperation === "subtract" ? SUB_FILL   : ADD_FILL; }
  #opStroke() { return this.#activeOperation === "subtract" ? SUB_STROKE : ADD_STROKE; }

  // Rectangle ─────────────────────────────────────────────────────────────────

  #startRectDraw(bx, bz) {
    const preview = svgEl("rect", {
      fill: this.#opFill(), stroke: this.#opStroke(),
      "stroke-width": "1", "fill-opacity": "0.22",
      "stroke-dasharray": "5 3",
      "vector-effect": "non-scaling-stroke",
      x: 0, y: 0, width: 0, height: 0,
    });
    this.#drawLayerEl.appendChild(preview);
    this.#drawState = { type: "rectangle", startBx: bx, startBz: bz, currentBx: bx, currentBz: bz, preview };
  }

  #updateRectPreview(bx, bz) {
    const { startBx, startBz, preview } = this.#drawState;
    this.#drawState.currentBx = bx;
    this.#drawState.currentBz = bz;
    const minX = Math.min(startBx, bx), maxX = Math.max(startBx, bx) + 1;
    const minZ = Math.min(startBz, bz), maxZ = Math.max(startBz, bz) + 1;
    const p1 = this.#toSvg(minX, minZ), p2 = this.#toSvg(maxX, maxZ);
    preview.setAttribute("x",      Math.min(p1.x, p2.x));
    preview.setAttribute("y",      Math.min(p1.y, p2.y));
    preview.setAttribute("width",  Math.abs(p2.x - p1.x));
    preview.setAttribute("height", Math.abs(p2.y - p1.y));
  }

  #completeRectDraw() {
    const { startBx, startBz, currentBx, currentBz, preview } = this.#drawState;
    preview?.parentNode?.removeChild(preview);
    this.#drawState = null;
    const minX = Math.min(startBx, currentBx), maxX = Math.max(startBx, currentBx) + 1;
    const minZ = Math.min(startBz, currentBz), maxZ = Math.max(startBz, currentBz) + 1;
    if (maxX - minX < 1 || maxZ - minZ < 1) return;
    this.#callbacks.onShapeCreated?.({
      type: "rectangle", operation: this.#activeOperation,
      min_x: minX, max_x: maxX, min_z: minZ, max_z: maxZ,
    });
  }

  // Circle ────────────────────────────────────────────────────────────────────

  #startCircleDraw(bx, bz) {
    const p = this.#toSvg(bx, bz);
    const dot = svgEl("rect", {
      x: p.x - VERTEX_HALF, y: p.y - VERTEX_HALF,
      width: VERTEX_HALF * 2, height: VERTEX_HALF * 2,
      fill: "#94a3b8", "pointer-events": "none",
    });
    const preview = svgEl("ellipse", {
      fill: this.#opFill(), stroke: this.#opStroke(),
      "stroke-width": "1", "fill-opacity": "0.22", "stroke-dasharray": "5 3",
      "vector-effect": "non-scaling-stroke",
      cx: p.x, cy: p.y, rx: 0, ry: 0,
    });
    this.#drawLayerEl.appendChild(preview);
    this.#drawLayerEl.appendChild(dot);
    this.#drawState = { type: "circle", centerX: bx, centerZ: bz, currentRadius: 0, preview, dot };
  }

  #updateCirclePreview(bx, bz) {
    const { centerX, centerZ, preview } = this.#drawState;
    const r = Math.max(1, Math.round(Math.hypot(bx - centerX, bz - centerZ)));
    this.#drawState.currentRadius = r;
    const p1 = this.#toSvg(centerX - r, centerZ - r);
    const p2 = this.#toSvg(centerX + r, centerZ + r);
    preview.setAttribute("cx", (p1.x + p2.x) / 2);
    preview.setAttribute("cy", (p1.y + p2.y) / 2);
    preview.setAttribute("rx", Math.abs(p2.x - p1.x) / 2);
    preview.setAttribute("ry", Math.abs(p2.y - p1.y) / 2);
  }

  #completeCircleDraw(bx, bz) {
    const { centerX, centerZ, preview, dot } = this.#drawState;
    preview?.parentNode?.removeChild(preview);
    dot?.parentNode?.removeChild(dot);
    this.#drawState = null;
    const radius = Math.max(1, Math.round(Math.hypot(bx - centerX, bz - centerZ)));
    this.#callbacks.onShapeCreated?.({
      type: "circle", operation: this.#activeOperation,
      center_x: centerX, center_z: centerZ, radius,
    });
  }

  // Polygon ───────────────────────────────────────────────────────────────────

  #startPolygonDraw(bx, bz) {
    const p = this.#toSvg(bx, bz);
    const firstDot = this.#makePolyDot(p.x, p.y, true);
    const previewLine = svgEl("line", {
      x1: p.x, y1: p.y, x2: p.x, y2: p.y,
      stroke: "#94a3b8", "stroke-width": "1", "stroke-dasharray": "4 3",
      "pointer-events": "none", "vector-effect": "non-scaling-stroke",
    });
    this.#drawLayerEl.appendChild(previewLine);
    this.#drawLayerEl.appendChild(firstDot);
    this.#drawState = {
      type: "polygon",
      vertices: [[bx, bz]],
      dots:  [firstDot],
      lines: [],
      previewLine,
    };
  }

  #addPolygonVertex(bx, bz) {
    const ds = this.#drawState;
    const prev = ds.vertices[ds.vertices.length - 1];
    const p1 = this.#toSvg(prev[0], prev[1]);
    const p2 = this.#toSvg(bx, bz);

    const seg = svgEl("line", {
      x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y,
      stroke: "#94a3b8", "stroke-width": "1",
      "pointer-events": "none", "vector-effect": "non-scaling-stroke",
    });
    // Insert before the preview line so it stays below the dashed cursor line
    this.#drawLayerEl.insertBefore(seg, ds.previewLine);
    ds.lines.push(seg);

    const dot = this.#makePolyDot(p2.x, p2.y, false);
    this.#drawLayerEl.insertBefore(dot, ds.previewLine);
    ds.dots.push(dot);

    ds.vertices.push([bx, bz]);

    ds.previewLine.setAttribute("x1", p2.x);
    ds.previewLine.setAttribute("y1", p2.y);
    ds.previewLine.setAttribute("x2", p2.x);
    ds.previewLine.setAttribute("y2", p2.y);
  }

  #updatePolygonPreview(bx, bz) {
    if (!this.#drawState?.previewLine) return;
    const p = this.#toSvg(bx, bz);
    this.#drawState.previewLine.setAttribute("x2", p.x);
    this.#drawState.previewLine.setAttribute("y2", p.y);
  }

  #closePolygon() {
    const saved = this.#drawState;
    this.#drawState = null;
    // Clean up preview elements
    for (const el of [...(saved.dots || []), ...(saved.lines || []), saved.previewLine]) {
      el?.parentNode?.removeChild(el);
    }
    if (saved.vertices.length < 3) return;
    this.#callbacks.onShapeCreated?.({
      type: "polygon", operation: this.#activeOperation,
      vertices: saved.vertices,
    });
  }

  #makePolyDot(sx, sy, isFirst) {
    return svgEl("rect", {
      x: sx - VERTEX_HALF, y: sy - VERTEX_HALF,
      width: VERTEX_HALF * 2, height: VERTEX_HALF * 2,
      fill: isFirst ? "#f59e0b" : "#94a3b8",
      stroke: "#0f172a", "stroke-width": "0.8",
      "pointer-events": "none", "vector-effect": "non-scaling-stroke",
    });
  }

  // Lasso ─────────────────────────────────────────────────────────────────────

  #startLassoDraw(bx, bz) {
    const previewPath = svgEl("path", {
      fill: this.#opFill(), stroke: this.#opStroke(),
      "stroke-width": "1", "fill-opacity": "0.22",
      "stroke-dasharray": "5 3",
      "fill-rule": "evenodd",
      "vector-effect": "non-scaling-stroke",
    });
    this.#drawLayerEl.appendChild(previewPath);
    this.#drawState = { type: "lasso", vertices: [[bx, bz]], previewPath };
  }

  #addLassoPoint(bx, bz) {
    const { vertices } = this.#drawState;
    const last = vertices[vertices.length - 1];
    if (bx === last[0] && bz === last[1]) return;  // same block — skip
    vertices.push([bx, bz]);
    this.#updateLassoPreview();
  }

  #updateLassoPreview() {
    const { vertices, previewPath } = this.#drawState;
    if (vertices.length < 2) return;
    const d = vertices.map(([x, z], i) => {
      const p = this.#toSvg(x, z);
      return (i === 0 ? "M" : "L") + `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
    }).join(" ") + " Z";
    previewPath.setAttribute("d", d);
  }

  #completeLassoDraw() {
    const { vertices, previewPath } = this.#drawState;
    previewPath?.parentNode?.removeChild(previewPath);
    this.#drawState = null;
    if (vertices.length < 3) return;
    this.#callbacks.onShapeCreated?.({
      type: "polygon", operation: this.#activeOperation,
      vertices,
    });
  }

  #cancelDraw() {
    if (!this.#drawState) return;
    const ds = this.#drawState;
    this.#drawState = null;
    for (const el of [ds.preview, ds.previewPath, ds.previewLine, ds.dot,
                      ...(ds.dots || []), ...(ds.lines || [])]) {
      el?.parentNode?.removeChild(el);
    }
  }

  // ── viewport transform ─────────────────────────────────────────────────────

  #applyViewportTransform() {
    if (!this.#viewportG) return;
    this.#viewportG.setAttribute(
      "transform", `matrix(${this.#scale},0,0,${this.#scale},${this.#panX},${this.#panY})`
    );
    this.#refreshHandles();
    this.#refreshCenterMarker();
  }

  #refreshCenterMarker() {
    if (!this.#centerLayerEl || !this.#toSvg) return;
    while (this.#centerLayerEl.firstChild)
      this.#centerLayerEl.removeChild(this.#centerLayerEl.firstChild);

    const svgPt = this.#toSvg(this.#centerX, this.#centerZ);
    const sx    = svgPt.x * this.#scale + this.#panX;
    const sy    = svgPt.y * this.#scale + this.#panY;
    const arm   = 10;
    const color = "#a78bfa";

    this.#centerLayerEl.appendChild(svgEl("line", {
      x1: sx - arm, y1: sy, x2: sx + arm, y2: sy,
      stroke: color, "stroke-width": "1",
    }));
    this.#centerLayerEl.appendChild(svgEl("line", {
      x1: sx, y1: sy - arm, x2: sx, y2: sy + arm,
      stroke: color, "stroke-width": "1",
    }));
    this.#centerLayerEl.appendChild(svgEl("circle", {
      cx: sx, cy: sy, r: 4,
      fill: "none", stroke: color, "stroke-width": "1.5",
    }));
  }

  #clientToSvg(clientX, clientY) {
    const r = this.#svg.getBoundingClientRect();
    return {
      x: (clientX - r.left - this.#panX) / this.#scale,
      y: (clientY - r.top  - this.#panY) / this.#scale,
    };
  }

  #clientToBlock(clientX, clientY) {
    if (!this.#toWorld) return null;
    const sp = this.#clientToSvg(clientX, clientY);
    const w  = this.#toWorld(sp.x, sp.y);
    return { bx: Math.floor(w.x), bz: Math.floor(w.z) };
  }

  #refreshCursor() {
    if (this.#activeTool === null)      this.#svg.style.cursor = "default";
    else if (this.#activeTool === "move") this.#svg.style.cursor = "grab";
    else                                this.#svg.style.cursor = "crosshair";
  }

  // ── events ─────────────────────────────────────────────────────────────────

  #setupEvents() {
    // Zoom
    this.#svg.addEventListener("wheel", (e) => {
      e.preventDefault();
      if (!this.#viewportG) return;
      const factor   = e.deltaY < 0 ? ZOOM_FACTOR : 1 / ZOOM_FACTOR;
      const newScale = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, this.#scale * factor));
      const r  = this.#svg.getBoundingClientRect();
      const mx = e.clientX - r.left, my = e.clientY - r.top;
      this.#panX  = mx - (mx - this.#panX) * (newScale / this.#scale);
      this.#panY  = my - (my - this.#panY) * (newScale / this.#scale);
      this.#scale = newScale;
      this.#applyViewportTransform();
      this.#callbacks.onZoom?.(this.#scale);
    }, { passive: false });

    // Mousedown on canvas
    this.#svg.addEventListener("mousedown", (e) => {
      if (!this.#viewportG) return;

      if (e.button === 1) {
        e.preventDefault();
        this.#midPanning = true;
        this.#didPan     = false;
        this.#panAnchor  = { x: e.clientX, y: e.clientY, panX: this.#panX, panY: this.#panY };
        return;
      }
      if (e.button !== 0) return;

      const blk = this.#clientToBlock(e.clientX, e.clientY);
      if (!blk) return;
      const { bx, bz } = blk;

      if (this.#activeTool === "rectangle") {
        this.#startRectDraw(bx, bz);
        this.#clickWasDrag = true;
        return;
      }

      if (this.#activeTool === "lasso") {
        this.#startLassoDraw(bx, bz);
        this.#clickWasDrag = true;
        return;
      }

      if (this.#activeTool === "circle") {
        if (!this.#drawState) {
          this.#startCircleDraw(bx, bz);
        } else {
          this.#completeCircleDraw(bx, bz);
        }
        this.#clickWasDrag = true;
        return;
      }

      if (this.#activeTool === "polygon") {
        if (!this.#drawState) {
          this.#startPolygonDraw(bx, bz);
        } else {
          // Close if within 2 blocks of first vertex and have ≥3 verts
          const [fx, fz] = this.#drawState.vertices[0];
          if (Math.abs(bx - fx) <= 2 && Math.abs(bz - fz) <= 2
              && this.#drawState.vertices.length >= 3) {
            this.#closePolygon();
          } else {
            this.#addPolygonVertex(bx, bz);
          }
        }
        this.#clickWasDrag = true;
        return;
      }

      // Pan (move tool only) / select
      this.#clickWasDrag = false;
      if (this.#activeTool === "move") {
        this.#isPanning = true;
        this.#didPan    = false;
        this.#panAnchor = { x: e.clientX, y: e.clientY, panX: this.#panX, panY: this.#panY };
      }
    });

    // Double-click to close polygon
    this.#svg.addEventListener("dblclick", (e) => {
      if (this.#activeTool !== "polygon" || !this.#drawState) return;
      e.stopPropagation();
      const ds = this.#drawState;
      // The second click of the dblclick already added a duplicate vertex; remove it
      if (ds.vertices.length > 1) {
        const last = ds.vertices[ds.vertices.length - 1];
        const prev = ds.vertices[ds.vertices.length - 2];
        if (last[0] === prev[0] && last[1] === prev[1]) {
          ds.vertices.pop();
          const dot  = ds.dots.pop();  dot?.parentNode?.removeChild(dot);
          const line = ds.lines.pop(); line?.parentNode?.removeChild(line);
        }
      }
      this.#closePolygon();
    });

    // Click — deselect if clicking empty canvas
    this.#svg.addEventListener("click", (e) => {
      if (this.#clickWasDrag) { this.#clickWasDrag = false; return; }
      if (this.#activeTool === null) {
        this.#callbacks.onShapeSelected?.(null);
      }
    });

    // Mousemove — coordinate display and draw previews only
    this.#svg.addEventListener("mousemove", (e) => {
      if ((this.#isPanning || this.#midPanning) && this.#panAnchor) {
        const dx = e.clientX - this.#panAnchor.x;
        const dy = e.clientY - this.#panAnchor.y;
        if (!this.#didPan && (Math.abs(dx) > 3 || Math.abs(dy) > 3)) this.#didPan = true;
        if (this.#didPan) {
          this.#panX = this.#panAnchor.panX + dx;
          this.#panY = this.#panAnchor.panY + dy;
          this.#applyViewportTransform();
          this.#svg.style.cursor = "grabbing";
        }
        return;
      }

      const blk = this.#clientToBlock(e.clientX, e.clientY);
      if (!blk) return;
      const { bx, bz } = blk;

      if (this.#drawState?.type === "rectangle") this.#updateRectPreview(bx, bz);
      if (this.#drawState?.type === "circle")    this.#updateCirclePreview(bx, bz);
      if (this.#drawState?.type === "polygon")   this.#updatePolygonPreview(bx, bz);
      if (this.#drawState?.type === "lasso")     this.#addLassoPoint(bx, bz);

      this.#callbacks.onCoords?.(bx, bz);
    });

    this.#svg.addEventListener("mouseleave", () => {
      this.#callbacks.onCoords?.(null, null);
    });

    // Window mouseup — end rectangle draw, end drag states
    window.addEventListener("mouseup", (e) => {
      if (e.button === 1) {
        this.#midPanning = false; this.#panAnchor = null; this.#didPan = false;
        this.#refreshCursor();
        return;
      }
      if (e.button !== 0) return;

      if (this.#drawState?.type === "lasso") {
        this.#completeLassoDraw();
        return;
      }

      if (this.#activeTool === "rectangle" && this.#drawState) {
        this.#completeRectDraw();
        return;
      }

      if (this.#rectResizeState) {
        this.#rectResizeState = null;
        this.#clickWasDrag = true;
        this.#refreshCursor();
        this.#refreshHandles();
        return;
      }

      if (this.#vertexDragState) {
        const { shapeId } = this.#vertexDragState;
        this.#vertexDragState = null;
        this.#refreshCursor();
        this.#refreshHandles();
        const shape = this.#shapes.get(shapeId);
        if (shape) this.#callbacks.onShapeUpdated?.(shape);
        return;
      }

      if (this.#isPanning) this.#clickWasDrag = this.#didPan;
      this.#isPanning = false;
      this.#didPan    = false;
      this.#refreshCursor();
    });

    // Window mousemove — lasso tracking + vertex drag + rect resize outside SVG
    window.addEventListener("mousemove", (e) => {
      if (!this.#rectResizeState && !this.#vertexDragState
          && this.#drawState?.type !== "lasso") return;
      const blk = this.#clientToBlock(e.clientX, e.clientY);
      if (!blk) return;
      const { bx, bz } = blk;

      if (this.#drawState?.type === "lasso") {
        this.#addLassoPoint(bx, bz);
        return;
      }

      if (this.#vertexDragState) {
        const { shapeId, vertexIdx } = this.#vertexDragState;
        const shape = this.#shapes.get(shapeId);
        if (shape?.type === "polygon") {
          shape.vertices[vertexIdx] = [bx, bz];
          this.updateShape(shape);
          this.#callbacks.onShapeUpdated?.(shape);
        }
        return;
      }

      if (this.#rectResizeState) {
        const { shapeId, xf, zf } = this.#rectResizeState;
        const shape = this.#shapes.get(shapeId);
        if (shape?.type === "rectangle") {
          if (xf) shape[xf] = xf === "max_x" ? bx + 1 : bx;
          if (zf) shape[zf] = zf === "max_z" ? bz + 1 : bz;
          // Keep min < max (1-block minimum)
          if (shape.min_x >= shape.max_x) {
            if (xf === "min_x") shape.min_x = shape.max_x - 1;
            else                shape.max_x = shape.min_x + 1;
          }
          if (shape.min_z >= shape.max_z) {
            if (zf === "min_z") shape.min_z = shape.max_z - 1;
            else                shape.max_z = shape.min_z + 1;
          }
          this.updateShape(shape);
          this.#callbacks.onShapeUpdated?.(shape);
        }
      }
    });

    // Keyboard shortcuts
    document.addEventListener("keydown", (e) => {
      if (["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
      if (e.key === "Escape") this.#cancelDraw();
      if ((e.key === "Delete" || e.key === "Backspace") && this.#selectedId) {
        this.#callbacks.onShapeDeleted?.(this.#selectedId);
      }
    });
  }
}
