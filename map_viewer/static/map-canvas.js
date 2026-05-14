/**
 * MapCanvas — owns the SVG element and all rendering.
 *
 * Public surface:
 *   render(ctx, groups)       full repaint + zoom reset
 *   setRegionVisible(id, v)   show/hide a region overlay
 *   resize()                  re-render at new dimensions (preserves zoom)
 *
 * Callbacks injected at construction:
 *   onCoords(x, z)            block coords under mouse (null, null on leave)
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

  // ── drag state ────────────────────────────────────────────────────────────
  #isDragging  = false;
  #dragAnchor  = null;   // { x, y, panX, panY }
  #didDrag     = false;  // true if mouse moved enough to count as a pan

  // ── live DOM references ───────────────────────────────────────────────────
  #viewportG      = null;
  #highlightRect  = null;

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
    // Reset zoom/pan for a newly loaded map
    this.#scale = 1;
    this.#panX  = 0;
    this.#panY  = 0;
    this.#repaint();
  }

  setRegionVisible(id, visible) {
    const g = this.#svg.querySelector(`#region-${CSS.escape(id)}`);
    if (g) g.style.display = visible ? "" : "none";
  }

  resize() {
    if (this.#ctx) this.#repaint();  // preserves current #scale / #panX / #panY
  }

  // ── rendering ──────────────────────────────────────────────────────────────

  #repaint() {
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
    viewport.appendChild(this.#buildPois());
    viewport.appendChild(this.#buildXmlRegions());
    viewport.appendChild(this.#buildBlockHighlight());

    this.#svg.appendChild(viewport);
  }

  // ── viewport transform helpers ─────────────────────────────────────────────

  #applyViewportTransform() {
    if (!this.#viewportG) return;
    const { x: s, panX: tx, panY: ty } = { x: this.#scale, panX: this.#panX, panY: this.#panY };
    this.#viewportG.setAttribute("transform", `matrix(${s},0,0,${s},${tx},${ty})`);
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

    // ── pan (left-drag) ──────────────────────────────────────────────────────
    this.#svg.addEventListener("mousedown", (e) => {
      if (!this.#viewportG || e.button !== 0) return;
      this.#isDragging = true;
      this.#didDrag    = false;
      this.#dragAnchor = { x: e.clientX, y: e.clientY, panX: this.#panX, panY: this.#panY };
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

      this.#updateCoordsAndHighlight(e.clientX, e.clientY);
    });

    this.#svg.addEventListener("mouseleave", () => {
      this.#isDragging = false;
      this.#svg.style.cursor = "";
      if (this.#highlightRect) this.#highlightRect.setAttribute("width", "0");
      if (this.#callbacks.onCoords) this.#callbacks.onCoords(null, null);
    });

    // End drag on mouseup anywhere in the window
    window.addEventListener("mouseup", (e) => {
      if (e.button !== 0) return;
      this.#isDragging = false;
      this.#didDrag    = false;
      this.#svg.style.cursor = this.#toWorld ? "crosshair" : "";
    });
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
      const color = TEAM_FILL[island.team] || TEAM_FILL_DEFAULT;
      g.appendChild(svgEl("path", {
        d: polyToPath(poly, this.#toSvg),
        fill: color, "fill-opacity": "0.25",
        stroke: color, "stroke-width": "1.2", "fill-rule": "evenodd",
      }));
    }
    return g;
  }

  #buildPois() {
    const g = svgEl("g", { id: "layer-pois" });
    for (const spawn of (this.#ctx.poi_assignments?.spawns || [])) {
      const p = this.#toSvg(spawn.x, spawn.z);
      const t = svgEl("text", {
        x: p.x, y: p.y, "text-anchor": "middle", "dominant-baseline": "middle",
        "font-size": "12", fill: TEAM_FILL[spawn.team_color] || "#f1f5f9", "font-weight": "bold",
      });
      t.textContent = "★";
      g.appendChild(t);
    }
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

  #buildXmlRegions() {
    const g = svgEl("g", { id: "layer-regions" });
    for (const region of this.#flattenNamed(this.#groups)) {
      g.appendChild(this.#regionGroup(region));
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

    const g = svgEl("g", { id: `region-${id}`, style: "display:none" });
    const title = svgEl("title");
    title.textContent = `${id} (${type})`;
    g.appendChild(title);

    if (region.is_negative) {
      g.appendChild(this.#negativeShape(region, color));
      g.appendChild(this.#label(id, this.#mapCenter(), color, "0.75"));
    } else if (type === "cylinder" || type === "circle" || type === "sphere") {
      g.appendChild(svgEl("ellipse", {
        cx, cy, rx: rw / 2, ry: rh / 2,
        fill: color, "fill-opacity": "0.20",
        stroke: color, "stroke-width": "1.5", "stroke-dasharray": "4,2",
      }));
      if (rw > 20 || rh > 20) g.appendChild(this.#label(id, { x: cx, y: cy }, color));
    } else {
      g.appendChild(svgEl("rect", {
        x: rx, y: ry, width: rw, height: rh,
        fill: color, "fill-opacity": "0.20",
        stroke: color, "stroke-width": "1.5", "stroke-dasharray": "4,2",
      }));
      if (rw > 20 || rh > 20) g.appendChild(this.#label(id, { x: cx, y: cy }, color));
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
      "fill-rule": "evenodd",
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

  #flattenNamed(groupsOrNodes, out = []) {
    for (const item of groupsOrNodes) {
      if (item.regions) { this.#flattenNamed(item.regions, out); }
      else {
        if (item.id && (item.bounds || item.is_negative)) out.push(item);
        this.#flattenNamed(item.children || [], out);
      }
    }
    return out;
  }
}
