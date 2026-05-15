/**
 * MapCanvas — owns the SVG element and all rendering.
 *
 * Public surface:
 *   render(ctx, groups)            full repaint + zoom reset
 *   setSelectedRegions(ids)        show overlays only for the given id set
 *   resize()                       re-render at new dimensions (preserves zoom)
 *   showAnchors(node)              highlight anchor blocks for focused region
 *   clearAnchors()                 remove anchor highlights
 *   setPoisVisible(v)              toggle spawn/wool POI markers
 *   setBuildVisible(v)             toggle build region overlay
 *
 * Callbacks injected at construction:
 *   onCoords(x, z)                 block coords under mouse (null, null on leave)
 *   onCanvasClick(node | null)     region hit under click, or null for empty space
 *   onRegionDraw(bounds)           rectangle draw completed: {min_x,min_z,max_x,max_z}
 *   onBoundsChange(node, bounds)   live update during canvas resize drag
 *   onBoundsSave(node, bounds)     persist after canvas resize drag ends
 */

import { buildTransform, buildInverseTransform, svgEl,
         ringToPath, polyToPath, boundsToRingPath } from "./transform.js";

const TEAM_FILL         = { blue: "#3b82f6", red: "#ef4444" };
const TEAM_FILL_DEFAULT = "#6b7280";
const WOOL_COLORS = {
  orange: "#f97316", pink: "#ec4899", lime: "#84cc16", yellow: "#eab308",
  cyan: "#06b6d4", purple: "#a855f7", white: "#f1f5f9", light_blue: "#38bdf8",
  magenta: "#d946ef", gray: "#9ca3af", black: "#374151", brown: "#92400e",
  green: "#22c55e", red: "#ef4444", blue: "#3b82f6",
};

const ZOOM_FACTOR = 1.15;
const ZOOM_MIN    = 0.5;
const ZOOM_MAX    = 200;

const HANDLE_SIZE = 7;
const HANDLE_DEFS = [
  { key: "nw", pos: sb => [sb.left,  sb.top   ], cursor: "nw-resize" },
  { key: "n",  pos: sb => [sb.midX,  sb.top   ], cursor: "n-resize"  },
  { key: "ne", pos: sb => [sb.right, sb.top   ], cursor: "ne-resize" },
  { key: "w",  pos: sb => [sb.left,  sb.midY  ], cursor: "w-resize"  },
  { key: "e",  pos: sb => [sb.right, sb.midY  ], cursor: "e-resize"  },
  { key: "sw", pos: sb => [sb.left,  sb.bottom], cursor: "sw-resize" },
  { key: "s",  pos: sb => [sb.midX,  sb.bottom], cursor: "s-resize"  },
  { key: "se", pos: sb => [sb.right, sb.bottom], cursor: "se-resize" },
];
const COMPOSITE_TYPES  = new Set(["union", "intersect", "negative", "complement"]);
const RESIZABLE_TYPES  = new Set(["rectangle", "cuboid"]);

export class MapCanvas {
  #svg;
  #wrap;
  #ctx    = null;
  #groups = [];
  #toSvg  = null;
  #toWorld = null;
  #callbacks;

  // ── zoom / pan state ──────────────────────────────────────────────────────
  #scale = 1;
  #panX  = 0;
  #panY  = 0;

  // ── drag / click state ───────────────────────────────────────────────────
  #isDragging   = false;
  #dragAnchor   = null;   // { x, y, panX, panY }
  #didDrag      = false;  // true if mouse moved enough to count as a pan
  #clickWasDrag = false;  // latched in mouseup, consumed in click handler

  // ── live DOM references ───────────────────────────────────────────────────
  #regionGroupMap = new Map();  // id → SVG <g> for fast setSelectedRegions
  #shapeMap       = new Map();  // id → { shape, type } for live bound updates
  #nodeMap        = new Map();  // id → node object, for hit-testing (includes addRegion nodes)
  #viewportG      = null;
  #overlayLayer   = null;  // outside viewport — fixed-size labels at screen coords
  #highlightRect  = null;
  #anchorLayer    = null;
  #buildLayerEl   = null;
  #spawnLayerEl   = null;
  #woolLayerEl    = null;
  #regionsLayerEl = null;  // <g id="layer-regions"> for addRegion()
  #drawLayerEl    = null;  // <g id="layer-draw"> for draw-tool preview

  // ── draw tool state ───────────────────────────────────────────────────────
  #activeTool  = null;  // null | "rectangle"
  #drawState   = null;  // null | { startBx, startBz, currentBx, currentBz, previewRect, anchor1, anchor2 }

  // ── resize state ──────────────────────────────────────────────────────────
  #resizeState = null;  // null | { node, xField, zField, cursor }

  // ── region visibility / selection ─────────────────────────────────────────
  #visibilityMap      = new Map();  // id → false means hidden; absent = visible
  #currentSelectedIds = new Set();

  // ── layer visibility state (persists across resize) ───────────────────────
  #showPois     = false;
  #showBuild    = false;
  #selectedNode = null;

  constructor(svgEl, wrapEl, callbacks = {}) {
    this.#svg       = svgEl;
    this.#wrap      = wrapEl;
    this.#callbacks = callbacks;
    this.#setupEvents();
  }

  // ── public API ─────────────────────────────────────────────────────────────

  render(ctx, groups) {
    this.#ctx    = ctx;
    this.#groups = groups;
    this.#selectedNode = null;
    this.#regionGroupMap.clear();
    this.#shapeMap.clear();
    this.#nodeMap.clear();
    this.#visibilityMap.clear();
    this.#currentSelectedIds.clear();
    // Reset zoom/pan for a newly loaded map
    this.#scale = 1;
    this.#panX  = 0;
    this.#panY  = 0;
    this.#repaint();
  }

  /** Highlight the anchor blocks and show the name/dimensions overlay for a region. */
  showAnchors(node) {
    this.#selectedNode = node;
    if (this.#anchorLayer) {
      while (this.#anchorLayer.firstChild) this.#anchorLayer.removeChild(this.#anchorLayer.firstChild);
      this.#renderAnchors();
    }
    this.#updateOverlay();
  }

  /** Remove anchor highlights and overlay. */
  clearAnchors() {
    this.#selectedNode = null;
    if (this.#anchorLayer) {
      while (this.#anchorLayer.firstChild) this.#anchorLayer.removeChild(this.#anchorLayer.firstChild);
    }
    this.#updateOverlay();
  }

  setPoisVisible(v) {
    this.#showPois = v;
    if (this.#spawnLayerEl) this.#spawnLayerEl.style.display = v ? "" : "none";
    if (this.#woolLayerEl)  this.#woolLayerEl.style.display  = v ? "" : "none";
  }

  setBuildVisible(v) {
    this.#showBuild = v;
    if (this.#buildLayerEl) this.#buildLayerEl.style.display = v ? "" : "none";
  }

  /**
   * Update selection. Selected regions get a solid thick outline; unselected
   * regions revert to dashed. A region selected while hidden is shown temporarily
   * (it hides again when deselected).
   */
  setSelectedRegions(ids) {
    this.#currentSelectedIds = new Set(ids);
    for (const id of this.#regionGroupMap.keys()) this.#refreshRegionDisplay(id);
  }

  /**
   * Persistently show or hide a region. Hidden regions are invisible unless
   * currently selected.
   */
  setRegionVisible(id, visible) {
    if (visible) this.#visibilityMap.delete(id);
    else         this.#visibilityMap.set(id, false);
    this.#refreshRegionDisplay(id);
  }

  /**
   * Apply new bounds to a region node in-place and refresh its SVG shape,
   * anchor blocks, and overlay — without a full repaint.
   */
  updateRegionBounds(node, newBounds) {
    Object.assign(node.bounds, newBounds);

    const entry = this.#shapeMap.get(node.id);
    if (entry && this.#toSvg) {
      const { min_x, min_z, max_x, max_z } = node.bounds;
      const p1 = this.#toSvg(min_x, min_z);
      const p2 = this.#toSvg(max_x, max_z);
      if (["cylinder", "circle", "sphere"].includes(entry.type)) {
        const cx = (p1.x + p2.x) / 2, cy = (p1.y + p2.y) / 2;
        const rw = Math.abs(p2.x - p1.x), rh = Math.abs(p2.y - p1.y);
        entry.shape.setAttribute("cx", cx);
        entry.shape.setAttribute("cy", cy);
        entry.shape.setAttribute("rx", rw / 2);
        entry.shape.setAttribute("ry", rh / 2);
      } else {
        entry.shape.setAttribute("x",      Math.min(p1.x, p2.x));
        entry.shape.setAttribute("y",      Math.min(p1.y, p2.y));
        entry.shape.setAttribute("width",  Math.abs(p2.x - p1.x));
        entry.shape.setAttribute("height", Math.abs(p2.y - p1.y));
      }
    }

    if (this.#selectedNode?.id === node.id) {
      if (this.#anchorLayer) {
        while (this.#anchorLayer.firstChild) this.#anchorLayer.removeChild(this.#anchorLayer.firstChild);
        this.#renderAnchors();
      }
      this.#updateOverlay();
    }
  }

  /** Activate or deactivate a draw tool. Cancels any in-progress draw. */
  setActiveTool(tool) {
    this.#cancelDraw();
    this.#activeTool = tool;
  }

  /** Add a freshly-created region to the canvas without a full repaint. */
  addRegion(node) {
    if (!this.#regionsLayerEl || !this.#toSvg) return;
    const regionG = this.#regionGroup(node);
    this.#regionGroupMap.set(node.id, regionG);
    this.#nodeMap.set(node.id, node);
    this.#regionsLayerEl.appendChild(regionG);
  }

  /** Remove a region from the canvas entirely (called on delete). */
  removeRegion(id) {
    const g = this.#regionGroupMap.get(id);
    if (g?.parentNode) g.parentNode.removeChild(g);
    this.#regionGroupMap.delete(id);
    this.#shapeMap.delete(id);
    this.#nodeMap.delete(id);
    this.#visibilityMap.delete(id);
    this.#currentSelectedIds.delete(id);
    if (this.#selectedNode?.id === id) {
      this.#selectedNode = null;
      this.#updateOverlay();
    }
  }

  /** Update canvas maps when a region is renamed (node.id already mutated). */
  renameNode(oldId, newId) {
    const g = this.#regionGroupMap.get(oldId);
    if (g) {
      this.#regionGroupMap.delete(oldId);
      this.#regionGroupMap.set(newId, g);
      g.setAttribute("id", `region-${newId}`);
      const titleEl = g.querySelector("title");
      if (titleEl) {
        const type = titleEl.textContent.replace(/^.*\(/, "").replace(/\)$/, "");
        titleEl.textContent = `${newId} (${type})`;
      }
    }
    const shape = this.#shapeMap.get(oldId);
    if (shape) {
      this.#shapeMap.delete(oldId);
      this.#shapeMap.set(newId, shape);
    }
    const node = this.#nodeMap.get(oldId);
    if (node) {
      this.#nodeMap.delete(oldId);
      this.#nodeMap.set(newId, node);
    }
    // Migrate visibility / selection state
    if (this.#visibilityMap.has(oldId)) {
      this.#visibilityMap.set(newId, this.#visibilityMap.get(oldId));
      this.#visibilityMap.delete(oldId);
    }
    if (this.#currentSelectedIds.has(oldId)) {
      this.#currentSelectedIds.delete(oldId);
      this.#currentSelectedIds.add(newId);
    }
  }

  resize() {
    if (this.#ctx) this.#repaint();  // preserves current #scale / #panX / #panY
  }

  // ── rendering ──────────────────────────────────────────────────────────────

  #repaint() {
    this.#cancelDraw();
    const w = this.#wrap.clientWidth  - 24;
    const h = this.#wrap.clientHeight - 24;
    this.#svg.setAttribute("width",   w);
    this.#svg.setAttribute("height",  h);
    this.#svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    this.#toSvg   = buildTransform(this.#ctx.bounding_box, w, h);
    this.#toWorld = buildInverseTransform(this.#ctx.bounding_box, w, h);

    while (this.#svg.firstChild) this.#svg.removeChild(this.#svg.firstChild);

    // All layers live inside the viewport group so one transform handles zoom+pan.
    const viewport = svgEl("g");
    this.#viewportG = viewport;
    this.#applyViewportTransform();

    viewport.appendChild(this.#buildBuildRegion());
    viewport.appendChild(this.#buildIslands());
    viewport.appendChild(this.#buildSpawnLayer());
    viewport.appendChild(this.#buildWoolLayer());
    viewport.appendChild(this.#buildXmlRegions());
    viewport.appendChild(this.#buildAnchorLayer());
    viewport.appendChild(this.#buildDrawLayer());
    viewport.appendChild(this.#buildBlockHighlight());

    // Overlay sits outside the viewport group so its text stays fixed-size at
    // any zoom level. Positions are computed in SVG screen coords.
    const overlayG = svgEl("g", { id: "layer-overlay" });
    this.#overlayLayer = overlayG;

    this.#svg.appendChild(viewport);
    this.#svg.appendChild(overlayG);
    this.#updateOverlay();
  }

  // ── viewport transform helpers ─────────────────────────────────────────────

  #applyViewportTransform() {
    if (!this.#viewportG) return;
    const { x: s, panX: tx, panY: ty } = { x: this.#scale, panX: this.#panX, panY: this.#panY };
    this.#viewportG.setAttribute("transform", `matrix(${s},0,0,${s},${tx},${ty})`);
    this.#updateOverlay();
  }

  /** Convert a mouse event's client position to pre-zoom SVG coordinates. */
  #clientToSvg(clientX, clientY) {
    const rect = this.#svg.getBoundingClientRect();
    return {
      x: (clientX - rect.left  - this.#panX) / this.#scale,
      y: (clientY - rect.top - this.#panY) / this.#scale,
    };
  }

  // ── event wiring (called once from constructor) ────────────────────────────

  #setupEvents() {
    // ── zoom ────────────────────────────────────────────────────────────────
    this.#svg.addEventListener("wheel", (e) => {
      if (!this.#viewportG) return;
      e.preventDefault();
      const factor = e.deltaY < 0 ? ZOOM_FACTOR : 1 / ZOOM_FACTOR;
      const newScale = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, this.#scale * factor));
      const rect = this.#svg.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      // Keep the world point under the mouse stationary
      this.#panX = mx - (mx - this.#panX) * (newScale / this.#scale);
      this.#panY = my - (my - this.#panY) * (newScale / this.#scale);
      this.#scale = newScale;
      this.#applyViewportTransform();
    }, { passive: false });

    // ── pan (left-drag) / click ──────────────────────────────────────────────
    this.#svg.addEventListener("mousedown", (e) => {
      if (!this.#viewportG || e.button !== 0) return;
      if (this.#activeTool === "rectangle") {
        if (!this.#toWorld) return;
        const svgPt = this.#clientToSvg(e.clientX, e.clientY);
        const world = this.#toWorld(svgPt.x, svgPt.y);
        this.#startDraw(Math.floor(world.x), Math.floor(world.z));
        return;
      }
      this.#clickWasDrag = false;  // reset for each new gesture
      this.#isDragging = true;
      this.#didDrag    = false;
      this.#dragAnchor = { x: e.clientX, y: e.clientY, panX: this.#panX, panY: this.#panY };
    });

    // Canvas click: latch wasDrag (set in mouseup which fires first), then hit-test
    this.#svg.addEventListener("click", (e) => {
      if (this.#clickWasDrag) return;
      this.#handleCanvasClick(e.clientX, e.clientY);
    });

    // ── mouse move: pan + coordinate tracking + block highlight ─────────────
    this.#svg.addEventListener("mousemove", (e) => {
      if (this.#isDragging && this.#dragAnchor) {
        const dx = e.clientX - this.#dragAnchor.x;
        const dy = e.clientY - this.#dragAnchor.y;
        if (!this.#didDrag && (Math.abs(dx) > 3 || Math.abs(dy) > 3)) this.#didDrag = true;
        if (this.#didDrag) {
          this.#panX = this.#dragAnchor.panX + dx;
          this.#panY = this.#dragAnchor.panY + dy;
          this.#applyViewportTransform();
          this.#svg.style.cursor = "grabbing";
        }
      }

      if (this.#activeTool === "rectangle" && this.#drawState && this.#toWorld) {
        const svgPt = this.#clientToSvg(e.clientX, e.clientY);
        const world = this.#toWorld(svgPt.x, svgPt.y);
        this.#updateDrawPreview(Math.floor(world.x), Math.floor(world.z));
      }

      this.#updateCoordsAndHighlight(e.clientX, e.clientY);
    });

    this.#svg.addEventListener("mouseleave", () => {
      this.#isDragging = false;
      this.#svg.style.cursor = "";
      if (this.#highlightRect) this.#highlightRect.setAttribute("width", "0");
      if (this.#callbacks.onCoords) this.#callbacks.onCoords(null, null);
    });

    // End drag on mouseup anywhere in the window; latch drag state before reset
    window.addEventListener("mouseup", (e) => {
      if (e.button !== 0) return;
      if (this.#activeTool === "rectangle" && this.#drawState) {
        this.#completeDraw();
        return;
      }
      if (this.#resizeState) {
        const { node } = this.#resizeState;
        this.#resizeState = null;
        this.#clickWasDrag = true;  // prevent the click event from deselecting
        this.#svg.style.cursor = this.#toWorld ? "crosshair" : "";
        if (this.#callbacks.onBoundsSave) this.#callbacks.onBoundsSave(node, node.bounds);
        this.#updateOverlay();
        return;
      }
      this.#clickWasDrag = this.#didDrag;
      this.#isDragging = false;
      this.#didDrag    = false;
      this.#svg.style.cursor = this.#toWorld ? "crosshair" : "";
    });

    // Window-level mousemove for resize (mouse may leave the SVG mid-drag)
    window.addEventListener("mousemove", (e) => {
      if (!this.#resizeState) return;
      this.#doResize(e.clientX, e.clientY);
    });
  }

  #handleCanvasClick(clientX, clientY) {
    if (this.#activeTool) return;
    if (!this.#toWorld || !this.#callbacks.onCanvasClick) return;
    const svgPt = this.#clientToSvg(clientX, clientY);
    const world = this.#toWorld(svgPt.x, svgPt.y);

    // Only hit-test visible regions; hidden ones can't be clicked on the canvas
    const candidates = [...this.#nodeMap.values()]
      .filter(r => r.bounds && !r.is_negative
               && this.#visibilityMap.get(r.id) !== false
               && this.#pointInRegion(world, r));
    candidates.sort((a, b) => this.#regionArea(a) - this.#regionArea(b));
    this.#callbacks.onCanvasClick(candidates[0] ?? null);
  }

  #pointInRegion({ x, z }, region) {
    const { min_x, min_z, max_x, max_z } = region.bounds;
    const isCircular = ["cylinder", "circle", "sphere"].includes(region.type);
    if (isCircular) {
      const cx = (min_x + max_x) / 2, cz = (min_z + max_z) / 2;
      const rx = (max_x - min_x) / 2, rz = (max_z - min_z) / 2;
      if (rx === 0 || rz === 0) return false;
      return ((x - cx) / rx) ** 2 + ((z - cz) / rz) ** 2 <= 1;
    }
    return x >= min_x && x <= max_x && z >= min_z && z <= max_z;
  }

  #regionArea(region) {
    const { min_x, min_z, max_x, max_z } = region.bounds;
    return (max_x - min_x) * (max_z - min_z);
  }

  #updateCoordsAndHighlight(clientX, clientY) {
    if (!this.#toWorld || !this.#toSvg) return;
    const svgPt = this.#clientToSvg(clientX, clientY);
    const world = this.#toWorld(svgPt.x, svgPt.y);
    const bx = Math.floor(world.x);
    const bz = Math.floor(world.z);

    // Move highlight rect to the block under the cursor
    if (this.#highlightRect) {
      const p1 = this.#toSvg(bx,     bz);
      const p2 = this.#toSvg(bx + 1, bz + 1);
      this.#highlightRect.setAttribute("x",      Math.min(p1.x, p2.x));
      this.#highlightRect.setAttribute("y",      Math.min(p1.y, p2.y));
      this.#highlightRect.setAttribute("width",  Math.abs(p2.x - p1.x));
      this.#highlightRect.setAttribute("height", Math.abs(p2.y - p1.y));
    }

    if (this.#callbacks.onCoords) this.#callbacks.onCoords(bx, bz);
  }

  // ── layer builders ─────────────────────────────────────────────────────────

  #buildBlockHighlight() {
    this.#highlightRect = svgEl("rect", {
      x: 0, y: 0, width: 0, height: 0,
      fill: "white", "fill-opacity": "0.06",
      stroke: "white", "stroke-opacity": "0.4", "stroke-width": "1",
      "vector-effect": "non-scaling-stroke",
      "pointer-events": "none",
    });
    return this.#highlightRect;
  }

  #buildBuildRegion() {
    const g = svgEl("g", { id: "layer-build" });
    this.#buildLayerEl = g;
    if (!this.#showBuild) g.style.display = "none";
    for (const poly of (this.#ctx.build_region?.buildable_void || [])) {
      g.appendChild(svgEl("path", {
        d: polyToPath(poly, this.#toSvg),
        fill: "#22c55e", "fill-opacity": "0.10",
        stroke: "#22c55e", "stroke-width": "0.8", "stroke-opacity": "0.4",
        "fill-rule": "evenodd",
      }));
    }
    return g;
  }

  #buildIslands() {
    const g = svgEl("g", { id: "layer-islands" });
    for (const island of (this.#ctx.islands || [])) {
      const poly = island.simplified_polygon;
      if (!poly?.exterior?.length) continue;
      const color = TEAM_FILL_DEFAULT;
      g.appendChild(svgEl("path", {
        d: polyToPath(poly, this.#toSvg),
        fill: color, "fill-opacity": "0.25",
        stroke: color, "stroke-width": "1.2", "fill-rule": "evenodd",
      }));
    }
    return g;
  }

  #buildSpawnLayer() {
    const g = svgEl("g", { id: "layer-spawns" });
    this.#spawnLayerEl = g;
    if (!this.#showPois) g.style.display = "none";
    for (const spawn of (this.#ctx.poi_assignments?.spawns || [])) {
      const p = this.#toSvg(spawn.x, spawn.z);
      const t = svgEl("text", {
        x: p.x, y: p.y, "text-anchor": "middle", "dominant-baseline": "middle",
        "font-size": "12", fill: TEAM_FILL[spawn.team_color] || "#f1f5f9", "font-weight": "bold",
      });
      t.textContent = "★";
      g.appendChild(t);
    }
    return g;
  }

  #buildWoolLayer() {
    const g = svgEl("g", { id: "layer-wools" });
    this.#woolLayerEl = g;
    if (!this.#showPois) g.style.display = "none";
    for (const wool of (this.#ctx.poi_assignments?.wools || [])) {
      const p = this.#toSvg(wool.x, wool.z);
      const t = svgEl("text", {
        x: p.x, y: p.y, "text-anchor": "middle", "dominant-baseline": "middle",
        "font-size": "11", fill: WOOL_COLORS[wool.color] || "#f1c40f",
      });
      t.textContent = "◆";
      g.appendChild(t);
    }
    return g;
  }

  #buildAnchorLayer() {
    const g = svgEl("g", { id: "layer-anchors" });
    this.#anchorLayer = g;
    this.#renderAnchors();
    return g;
  }

  #updateOverlay() {
    if (!this.#overlayLayer) return;
    while (this.#overlayLayer.firstChild) this.#overlayLayer.removeChild(this.#overlayLayer.firstChild);

    const node = this.#selectedNode;
    if (!node?.bounds || node.is_negative || !this.#toSvg) return;

    const { min_x, min_z, max_x, max_z } = node.bounds;
    const color = node.color || "#94a3b8";

    // Convert base SVG coordinates to screen coordinates within the SVG element
    const p1b   = this.#toSvg(min_x, min_z);
    const p2b   = this.#toSvg(max_x, max_z);
    const toScr = (bx, by) => ({ x: bx * this.#scale + this.#panX, y: by * this.#scale + this.#panY });
    const s1    = toScr(p1b.x, p1b.y);
    const s2    = toScr(p2b.x, p2b.y);
    const left  = Math.min(s1.x, s2.x);
    const right = Math.max(s1.x, s2.x);
    const top   = Math.min(s1.y, s2.y);
    const bottom = Math.max(s1.y, s2.y);
    const mid   = (left + right) / 2;

    // ── name above top-left ──────────────────────────────────────────────────
    const maxChars  = 36;
    const labelText = node.label.length > maxChars
      ? node.label.slice(0, maxChars - 1) + "…"
      : node.label;
    const nameEl = svgEl("text", {
      x: left, y: top - 5,
      "text-anchor": "start", "dominant-baseline": "alphabetic",
      "font-size": "11", "font-family": "ui-monospace, monospace",
      fill: color, "pointer-events": "none",
    });
    nameEl.textContent = labelText;
    this.#overlayLayer.appendChild(nameEl);

    // ── dimensions badge below bottom-center ─────────────────────────────────
    const fmtDim = (v) => Number.isInteger(v) ? String(v) : v.toFixed(1);
    const dimText = `${fmtDim(max_x - min_x)} × ${fmtDim(max_z - min_z)}`;

    const FONT_SZ   = 10;
    const PAD_X     = 6;
    const PAD_Y     = 3;
    const pillH     = FONT_SZ + PAD_Y * 2;
    const pillW     = dimText.length * (FONT_SZ * 0.6) + PAD_X * 2;
    const pillX     = mid - pillW / 2;
    const pillY     = bottom + 5;

    this.#overlayLayer.appendChild(svgEl("rect", {
      x: pillX, y: pillY, width: pillW, height: pillH, rx: 3,
      fill: color, "fill-opacity": "0.85", "pointer-events": "none",
    }));
    const dimEl = svgEl("text", {
      x: mid, y: pillY + PAD_Y + FONT_SZ - 1,
      "text-anchor": "middle", "dominant-baseline": "auto",
      "font-size": FONT_SZ, "font-family": "ui-monospace, monospace",
      fill: "#0f172a", "font-weight": "600", "pointer-events": "none",
    });
    dimEl.textContent = dimText;
    this.#overlayLayer.appendChild(dimEl);

    // ── resize handles (rectangle / cuboid only, non-synthetic) ─────────────
    if (!node.synthetic_id && RESIZABLE_TYPES.has(node.type)) {
      this.#renderHandles(node);
    }
  }

  #renderAnchors() {
    const node = this.#selectedNode;
    if (!node?.bounds || !this.#toSvg || node.is_negative || COMPOSITE_TYPES.has(node.type)) return;

    const { min_x, min_z, max_x, max_z } = node.bounds;
    const color = node.color || "#ffffff";
    const isCircular = ["cylinder", "circle", "sphere"].includes(node.type);

    if (isCircular) {
      const cx = (min_x + max_x) / 2, cz = (min_z + max_z) / 2;
      this.#anchorLayer.appendChild(this.#anchorBlock(Math.floor(cx), Math.floor(cz), color));
    } else {
      const bMinX = Math.floor(min_x),      bMinZ = Math.floor(min_z);
      const bMaxX = Math.ceil(max_x) - 1,   bMaxZ = Math.ceil(max_z) - 1;
      this.#anchorLayer.appendChild(this.#anchorBlock(bMinX, bMinZ, color));
      if (bMaxX !== bMinX || bMaxZ !== bMinZ) {
        this.#anchorLayer.appendChild(this.#anchorBlock(bMaxX, bMaxZ, color));
      }
    }
  }

  #anchorBlock(bx, bz, color) {
    const p1 = this.#toSvg(bx,     bz);
    const p2 = this.#toSvg(bx + 1, bz + 1);
    return svgEl("rect", {
      x: Math.min(p1.x, p2.x), y: Math.min(p1.y, p2.y),
      width:  Math.abs(p2.x - p1.x),
      height: Math.abs(p2.y - p1.y),
      fill: color, "fill-opacity": "0.5",
      stroke: color, "stroke-width": "2",
      "vector-effect": "non-scaling-stroke",
      "pointer-events": "none",
    });
  }

  #buildXmlRegions() {
    this.#regionGroupMap.clear();
    this.#shapeMap.clear();
    this.#nodeMap.clear();
    const g = svgEl("g", { id: "layer-regions" });
    this.#regionsLayerEl = g;
    for (const region of this.#flattenNamed(this.#groups)) {
      const regionG = this.#regionGroup(region);
      this.#regionGroupMap.set(region.id, regionG);
      this.#nodeMap.set(region.id, region);
      g.appendChild(regionG);
    }
    return g;
  }

  #regionGroup(region) {
    const { id, type, color, bounds } = region;
    const p1 = bounds ? this.#toSvg(bounds.min_x, bounds.min_z) : null;
    const p2 = bounds ? this.#toSvg(bounds.max_x, bounds.max_z) : null;
    const rx = p1 ? Math.min(p1.x, p2.x) : 0, ry = p1 ? Math.min(p1.y, p2.y) : 0;
    const rw = p1 ? Math.abs(p2.x - p1.x) : 0, rh = p1 ? Math.abs(p2.y - p1.y) : 0;
    const cx = p1 ? (p1.x + p2.x) / 2 : 0, cy = p1 ? (p1.y + p2.y) / 2 : 0;

    const g = svgEl("g", { id: `region-${id}` });
    const title = svgEl("title");
    title.textContent = `${id} (${type})`;
    g.appendChild(title);

    if (region.is_negative) {
      g.appendChild(this.#negativeShape(region, color));
      g.appendChild(this.#label(id, this.#mapCenter(), color, "0.75"));
    } else if (type === "cylinder" || type === "circle" || type === "sphere") {
      const shape = svgEl("ellipse", {
        cx, cy, rx: rw / 2, ry: rh / 2,
        fill: color, "fill-opacity": "0.20",
        stroke: color, "stroke-width": "1.5", "stroke-dasharray": "4,2",
        "vector-effect": "non-scaling-stroke",
      });
      g.appendChild(shape);
      this.#shapeMap.set(id, { shape, type });
    } else {
      const shape = svgEl("rect", {
        x: rx, y: ry, width: rw, height: rh,
        fill: color, "fill-opacity": "0.20",
        stroke: color, "stroke-width": "1.5", "stroke-dasharray": "4,2",
        "vector-effect": "non-scaling-stroke",
      });
      g.appendChild(shape);
      this.#shapeMap.set(id, { shape, type });
    }
    return g;
  }

  #negativeShape(region, color) {
    const [minX, maxX, minZ, maxZ] = this.#ctx.bounding_box;
    let d = boundsToRingPath({ min_x: minX, min_z: minZ, max_x: maxX, max_z: maxZ }, this.#toSvg);
    for (const child of (region.children || [])) {
      if (child.bounds) d += " " + boundsToRingPath(child.bounds, this.#toSvg);
    }
    return svgEl("path", {
      d, fill: color, "fill-opacity": "0.12",
      stroke: color, "stroke-width": "1.5", "stroke-dasharray": "6,3",
      "fill-rule": "evenodd", "vector-effect": "non-scaling-stroke",
    });
  }

  #mapCenter() {
    const [minX, maxX, minZ, maxZ] = this.#ctx.bounding_box;
    const a = this.#toSvg(minX, minZ), b = this.#toSvg(maxX, maxZ);
    return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  }

  #label(id, pos, color, opacity = "0.9") {
    const el = svgEl("text", {
      x: pos.x, y: pos.y, "text-anchor": "middle", "dominant-baseline": "middle",
      "font-size": "9", fill: color, "fill-opacity": opacity, "pointer-events": "none",
    });
    el.textContent = id.length > 24 ? id.slice(0, 22) + "…" : id;
    return el;
  }

  // ── region display ────────────────────────────────────────────────────────

  #refreshRegionDisplay(id) {
    const g = this.#regionGroupMap.get(id);
    if (!g) return;
    const isSelected = this.#currentSelectedIds.has(id);
    const isVisible  = this.#visibilityMap.get(id) !== false;
    g.style.display  = (isVisible || isSelected) ? "" : "none";
    const entry = this.#shapeMap.get(id);
    if (!entry) return;
    if (isSelected) {
      entry.shape.setAttribute("stroke-width",    "2.5");
      entry.shape.setAttribute("fill-opacity",    "0.22");
      entry.shape.removeAttribute("stroke-dasharray");
    } else {
      entry.shape.setAttribute("stroke-width",    "1.5");
      entry.shape.setAttribute("fill-opacity",    "0.20");
      entry.shape.setAttribute("stroke-dasharray", "4,2");
    }
  }

  // ── resize helpers ─────────────────────────────────────────────────────────

  /** Compute screen-space bounding box and axis-orientation flags for a node. */
  #screenBounds(node) {
    if (!node?.bounds || !this.#toSvg) return null;
    const { min_x, min_z, max_x, max_z } = node.bounds;
    const toScr = (bx, by) => ({ x: bx * this.#scale + this.#panX, y: by * this.#scale + this.#panY });
    const p1b = this.#toSvg(min_x, min_z);
    const p2b = this.#toSvg(max_x, max_z);
    const s1  = toScr(p1b.x, p1b.y);
    const s2  = toScr(p2b.x, p2b.y);
    return {
      left:       Math.min(s1.x, s2.x),
      right:      Math.max(s1.x, s2.x),
      top:        Math.min(s1.y, s2.y),
      bottom:     Math.max(s1.y, s2.y),
      midX:       (s1.x + s2.x) / 2,
      midY:       (s1.y + s2.y) / 2,
      leftIsMinX: p1b.x <= p2b.x,
      topIsMinZ:  p1b.y <= p2b.y,
    };
  }

  /** Map a handle key to the bounds field(s) it controls, accounting for axis orientation. */
  #handleFields(key, sb) {
    const leftF  = sb.leftIsMinX ? "min_x" : "max_x";
    const rightF = sb.leftIsMinX ? "max_x" : "min_x";
    const topF   = sb.topIsMinZ  ? "min_z" : "max_z";
    const botF   = sb.topIsMinZ  ? "max_z" : "min_z";
    return {
      nw: { xField: leftF,  zField: topF  },
      n:  { xField: null,   zField: topF  },
      ne: { xField: rightF, zField: topF  },
      w:  { xField: leftF,  zField: null  },
      e:  { xField: rightF, zField: null  },
      sw: { xField: leftF,  zField: botF  },
      s:  { xField: null,   zField: botF  },
      se: { xField: rightF, zField: botF  },
    }[key];
  }

  /** Append 8 interactive resize handles to the overlay layer for a node. */
  #renderHandles(node) {
    const sb = this.#screenBounds(node);
    if (!sb) return;
    const hs    = HANDLE_SIZE / 2;
    const color = node.color || "#94a3b8";
    for (const h of HANDLE_DEFS) {
      const [cx, cy] = h.pos(sb);
      const el = svgEl("rect", {
        x: cx - hs, y: cy - hs, width: HANDLE_SIZE, height: HANDLE_SIZE, rx: 1,
        fill: "#1e293b", stroke: color, "stroke-width": "1.5",
        cursor: h.cursor,
      });
      el.addEventListener("mousedown", (e) => {
        if (e.button !== 0) return;
        e.stopPropagation();
        e.preventDefault();
        const fields = this.#handleFields(h.key, this.#screenBounds(node));
        this.#resizeState = { node, ...fields, cursor: h.cursor };
        this.#svg.style.cursor = h.cursor;
      });
      this.#overlayLayer.appendChild(el);
    }
  }

  /** Update bounds during a resize drag and fire the live-update callback. */
  #doResize(clientX, clientY) {
    if (!this.#resizeState || !this.#toWorld) return;
    const { node, xField, zField } = this.#resizeState;
    const svgPt = this.#clientToSvg(clientX, clientY);
    const world = this.#toWorld(svgPt.x, svgPt.y);
    const nb    = { ...node.bounds };
    if (xField) nb[xField] = Math.round(world.x);
    if (zField) nb[zField] = Math.round(world.z);
    // Enforce minimum 1-block size
    if (xField && nb.max_x - nb.min_x < 1)
      nb[xField] = xField === "max_x" ? nb.min_x + 1 : nb.max_x - 1;
    if (zField && nb.max_z - nb.min_z < 1)
      nb[zField] = zField === "max_z" ? nb.min_z + 1 : nb.max_z - 1;
    if (this.#callbacks.onBoundsChange) this.#callbacks.onBoundsChange(node, nb);
  }

  #buildDrawLayer() {
    const g = svgEl("g", { id: "layer-draw" });
    this.#drawLayerEl = g;
    return g;
  }

  // ── draw tool helpers ──────────────────────────────────────────────────────

  /** Compute world-extent bounds from two block indices (order-independent). */
  #boundsFromBlocks(b1x, b1z, b2x, b2z) {
    return {
      min_x: Math.min(b1x, b2x),
      min_z: Math.min(b1z, b2z),
      max_x: Math.max(b1x, b2x) + 1,
      max_z: Math.max(b1z, b2z) + 1,
    };
  }

  /** Reposition a previously-created anchor block element. */
  #moveAnchorBlock(el, bx, bz) {
    const p1 = this.#toSvg(bx,     bz);
    const p2 = this.#toSvg(bx + 1, bz + 1);
    el.setAttribute("x",      Math.min(p1.x, p2.x));
    el.setAttribute("y",      Math.min(p1.y, p2.y));
    el.setAttribute("width",  Math.abs(p2.x - p1.x));
    el.setAttribute("height", Math.abs(p2.y - p1.y));
  }

  #startDraw(bx, bz) {
    if (!this.#drawLayerEl || !this.#toSvg) return;
    const color       = "#94a3b8";
    const previewRect = svgEl("rect", {
      x: 0, y: 0, width: 0, height: 0,
      fill: color, "fill-opacity": "0.12",
      stroke: color, "stroke-width": "1.5", "stroke-dasharray": "4,2",
      "vector-effect": "non-scaling-stroke", "pointer-events": "none",
    });
    const anchor1 = this.#anchorBlock(bx, bz, color);
    const anchor2 = this.#anchorBlock(bx, bz, color);
    this.#drawLayerEl.appendChild(previewRect);
    this.#drawLayerEl.appendChild(anchor1);
    this.#drawLayerEl.appendChild(anchor2);
    this.#drawState = { startBx: bx, startBz: bz, currentBx: bx, currentBz: bz,
                        previewRect, anchor1, anchor2 };
    this.#updateDrawPreview(bx, bz);
  }

  #updateDrawPreview(bx, bz) {
    if (!this.#drawState || !this.#toSvg) return;
    this.#drawState.currentBx = bx;
    this.#drawState.currentBz = bz;
    const { startBx, startBz, previewRect, anchor1, anchor2 } = this.#drawState;
    const { min_x, min_z, max_x, max_z } = this.#boundsFromBlocks(startBx, startBz, bx, bz);

    const p1 = this.#toSvg(min_x, min_z);
    const p2 = this.#toSvg(max_x, max_z);
    previewRect.setAttribute("x",      Math.min(p1.x, p2.x));
    previewRect.setAttribute("y",      Math.min(p1.y, p2.y));
    previewRect.setAttribute("width",  Math.abs(p2.x - p1.x));
    previewRect.setAttribute("height", Math.abs(p2.y - p1.y));

    this.#moveAnchorBlock(anchor1, min_x,     min_z);
    this.#moveAnchorBlock(anchor2, max_x - 1, max_z - 1);
  }

  #completeDraw() {
    if (!this.#drawState) return;
    const { startBx, startBz, currentBx, currentBz } = this.#drawState;
    const bounds = this.#boundsFromBlocks(startBx, startBz, currentBx, currentBz);
    this.#cancelDraw();
    if (this.#callbacks.onRegionDraw) this.#callbacks.onRegionDraw(bounds);
  }

  #cancelDraw() {
    if (!this.#drawState) return;
    const { previewRect, anchor1, anchor2 } = this.#drawState;
    for (const el of [previewRect, anchor1, anchor2]) {
      if (el.parentNode) el.parentNode.removeChild(el);
    }
    this.#drawState = null;
  }

  #flattenNamed(groupsOrNodes, out = []) {
    for (const item of groupsOrNodes) {
      if (item.regions) { this.#flattenNamed(item.regions, out); }
      else {
        if (item.id && !COMPOSITE_TYPES.has(item.type) && item.bounds) out.push(item);
        this.#flattenNamed(item.children || [], out);
      }
    }
    return out;
  }
}
