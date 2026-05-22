import { buildTransform, svgEl as makeEl } from "./transform.js";

const SYMMETRY_COLOR   = "#a855f7";  // purple-500
const SYMMETRY_SKIPPED = 0.25;

export class OverviewCanvas {
  #svg;
  #wrap;
  #ctx          = null;
  #toSvg        = null;
  #blockLayerEl    = null;
  #symmetryLayerEl = null;
  #blockData    = null;
  #showBlocks   = true;
  #symmetryData = null;
  #symmetryStatus = null;

  constructor(svgElement, wrapEl) {
    this.#svg  = svgElement;
    this.#wrap = wrapEl;
  }

  render(ctx) {
    this.#ctx   = ctx;
    this.#toSvg = null;
    while (this.#svg.firstChild) this.#svg.removeChild(this.#svg.firstChild);
    this.#build();
  }

  loadBlockLayer(data) {
    this.#blockData = data;
    if (this.#blockLayerEl && this.#toSvg) this.#renderBlocks();
  }

  setBlocksVisible(visible) {
    this.#showBlocks = visible;
    if (this.#blockLayerEl)
      this.#blockLayerEl.style.display = visible ? "" : "none";
  }

  /**
   * Draw purple symmetry dot + axis line.
   * @param {object|null} symmetryData  Full symmetry.json object, or null.
   * @param {string|null} status        "confirmed" | "skipped" | null
   */
  setSymmetryOverlay(symmetryData, status) {
    this.#symmetryData   = symmetryData;
    this.#symmetryStatus = status;
    if (!this.#symmetryLayerEl || !this.#toSvg) return;
    this.#renderSymmetry();
  }

  resize() {
    if (!this.#ctx || !this.#wrap.clientWidth) return;
    this.#build();
  }

  // ── private ──────────────────────────────────────────────────────────────

  #build() {
    while (this.#svg.firstChild) this.#svg.removeChild(this.#svg.firstChild);
    const svgW = this.#wrap.clientWidth  || 400;
    const svgH = this.#wrap.clientHeight || 400;
    this.#svg.setAttribute("viewBox", `0 0 ${svgW} ${svgH}`);
    this.#svg.setAttribute("width",   svgW);
    this.#svg.setAttribute("height",  svgH);

    this.#toSvg = buildTransform(this.#ctx.bounding_box, svgW, svgH);

    const viewportG = makeEl("g", { id: "ov-viewport" });
    this.#blockLayerEl    = makeEl("g", { id: "ov-layer-blocks" });
    this.#symmetryLayerEl = makeEl("g", { id: "ov-layer-symmetry" });

    viewportG.appendChild(this.#blockLayerEl);
    viewportG.appendChild(this.#symmetryLayerEl);
    this.#svg.appendChild(viewportG);

    if (this.#blockData) this.#renderBlocks();
    this.#blockLayerEl.style.display = this.#showBlocks ? "" : "none";
    if (this.#symmetryData) this.#renderSymmetry();
  }

  #renderBlocks() {
    const blockData = this.#blockData;
    const { xs, zs, colors, min_x, min_z, max_x, max_z } = blockData;
    const imgW = max_x - min_x + 1;
    const imgH = max_z - min_z + 1;

    const offscreen = document.createElement("canvas");
    offscreen.width  = imgW;
    offscreen.height = imgH;
    const ctx2d  = offscreen.getContext("2d");
    const pixels = ctx2d.createImageData(imgW, imgH);
    const data   = pixels.data;

    for (let idx = 0; idx < xs.length; idx++) {
      const rgb       = parseInt(colors[idx].slice(1), 16);
      const pixelIdx  = ((zs[idx] - min_z) * imgW + (xs[idx] - min_x)) * 4;
      data[pixelIdx]     = (rgb >> 16) & 0xff;
      data[pixelIdx + 1] = (rgb >> 8)  & 0xff;
      data[pixelIdx + 2] =  rgb        & 0xff;
      data[pixelIdx + 3] = 255;
    }
    ctx2d.putImageData(pixels, 0, 0);

    const p1  = this.#toSvg(min_x,     min_z);
    const p2  = this.#toSvg(max_x + 1, max_z + 1);
    const img = makeEl("image");
    img.setAttribute("href",            offscreen.toDataURL("image/png"));
    img.setAttribute("x",               Math.min(p1.x, p2.x));
    img.setAttribute("y",               Math.min(p1.y, p2.y));
    img.setAttribute("width",           Math.abs(p2.x - p1.x));
    img.setAttribute("height",          Math.abs(p2.y - p1.y));
    img.setAttribute("pointer-events",  "none");
    img.style.imageRendering = "pixelated";

    while (this.#blockLayerEl.firstChild)
      this.#blockLayerEl.removeChild(this.#blockLayerEl.firstChild);
    this.#blockLayerEl.appendChild(img);
  }

  #renderSymmetry() {
    while (this.#symmetryLayerEl.firstChild)
      this.#symmetryLayerEl.removeChild(this.#symmetryLayerEl.firstChild);

    const { center, global_symmetry } = this.#symmetryData;
    if (!center) return;

    const opacity = this.#symmetryStatus === "skipped" ? SYMMETRY_SKIPPED : 1.0;
    const [minX, maxX, minZ, maxZ] = this.#ctx.bounding_box;

    // Primary = highest-confidence detected symmetry
    const primary = [...global_symmetry]
      .filter(entry => entry.detected)
      .sort((entryA, entryB) => entryB.confidence - entryA.confidence)[0];

    if (primary) {
      const centerX = center.center_x;
      const centerZ = center.center_z;
      let lineStart, lineEnd;

      if (primary.type === "mirror_x") {
        lineStart = this.#toSvg(centerX, minZ);
        lineEnd   = this.#toSvg(centerX, maxZ);
      } else if (primary.type === "mirror_z") {
        lineStart = this.#toSvg(minX, centerZ);
        lineEnd   = this.#toSvg(maxX, centerZ);
      }

      if (lineStart && lineEnd) {
        this.#symmetryLayerEl.appendChild(makeEl("line", {
          x1: lineStart.x, y1: lineStart.y,
          x2: lineEnd.x,   y2: lineEnd.y,
          stroke:               SYMMETRY_COLOR,
          "stroke-width":       "1.5",
          "stroke-dasharray":   "6 3",
          opacity,
        }));
      }
    }

    // Center dot (rendered on top of axis line)
    const centerPt = this.#toSvg(center.center_x, center.center_z);
    this.#symmetryLayerEl.appendChild(makeEl("circle", {
      cx: centerPt.x, cy: centerPt.y, r: 5,
      fill:           SYMMETRY_COLOR,
      stroke:         "#fff",
      "stroke-width": "1.5",
      opacity,
    }));
  }
}
