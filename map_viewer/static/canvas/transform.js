/**
 * Pure coordinate-math and SVG-element helpers.
 * No state, no DOM queries — safe to import anywhere.
 */

const PAD = 20;

/**
 * Build a world→SVG transform from a map bounding box.
 * Returns a function (worldX, worldZ) → {x, y} in SVG pixels.
 * @param {[number,number,number,number]} bbox  [minX, maxX, minZ, maxZ]
 */
export function buildTransform(bbox, svgW, svgH) {
  const [minX, maxX, minZ, maxZ] = bbox;
  const worldW = maxX - minX, worldH = maxZ - minZ;
  const drawW = svgW - 2 * PAD, drawH = svgH - 2 * PAD;
  const scale = Math.min(drawW / worldW, drawH / worldH);
  const offX = PAD + (drawW - worldW * scale) / 2;
  const offY = PAD + (drawH - worldH * scale) / 2;
  return (wx, wz) => ({
    x: offX + (wx - minX) * scale,
    y: offY + (wz - minZ) * scale,
  });
}

/**
 * Invert a transform: SVG pixel → approximate world coords.
 * Useful for mouse-click → world-coord conversion in the editor.
 */
export function buildInverseTransform(bbox, svgW, svgH) {
  const [minX, maxX, minZ, maxZ] = bbox;
  const worldW = maxX - minX, worldH = maxZ - minZ;
  const drawW = svgW - 2 * PAD, drawH = svgH - 2 * PAD;
  const scale = Math.min(drawW / worldW, drawH / worldH);
  const offX = PAD + (drawW - worldW * scale) / 2;
  const offY = PAD + (drawH - worldH * scale) / 2;
  return (px, py) => ({
    x: (px - offX) / scale + minX,
    z: (py - offY) / scale + minZ,
  });
}

/** Create an SVG element with given attributes and optional children. */
export function svgEl(tag, attrs = {}, children = []) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  for (const ch of children) el.appendChild(ch);
  return el;
}

/** Convert a polygon ring [[x,z],...] to an SVG path segment string. */
export function ringToPath(ring, toSvg) {
  return ring.map(([x, z], i) => {
    const p = toSvg(x, z);
    return (i === 0 ? "M" : "L") + `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
  }).join(" ") + " Z";
}

/** Convert a polygon {exterior, holes} to a compound SVG path string. */
export function polyToPath(poly, toSvg) {
  let d = ringToPath(poly.exterior, toSvg);
  for (const hole of (poly.holes || [])) d += " " + ringToPath(hole, toSvg);
  return d;
}

/**
 * Clip a convex polygon against a half-plane using Sutherland-Hodgman.
 * Keeps vertices where: nx*(x - ox) + nz*(z - oz) >= 0
 *
 * @param {Array<[number,number]>} poly  Input vertices [[x,z],...]
 * @param {number} ox  Plane origin x
 * @param {number} oz  Plane origin z
 * @param {number} nx  Plane normal x component
 * @param {number} nz  Plane normal z component
 * @returns {Array<[number,number]>}  Clipped vertices (may be empty)
 */
export function clipHalfPlane(poly, ox, oz, nx, nz) {
  if (poly.length === 0) return [];
  const dist  = ([x, z]) => nx * (x - ox) + nz * (z - oz);
  const cross = ([x1, z1], [x2, z2]) => {
    const d1 = nx * (x1 - ox) + nz * (z1 - oz);
    const d2 = nx * (x2 - ox) + nz * (z2 - oz);
    const t  = d1 / (d1 - d2);
    return [x1 + t * (x2 - x1), z1 + t * (z2 - z1)];
  };
  const out = [];
  const n   = poly.length;
  for (let i = 0; i < n; i++) {
    const curr = poly[i], prev = poly[(i - 1 + n) % n];
    const cIn  = dist(curr) >= 0, pIn = dist(prev) >= 0;
    if (cIn) { if (!pIn) out.push(cross(prev, curr)); out.push(curr); }
    else if (pIn) out.push(cross(prev, curr));
  }
  return out;
}

/** Convert a bounds {min_x, min_z, max_x, max_z} to an SVG path ring. */
export function boundsToRingPath(bounds, toSvg) {
  const { min_x, min_z, max_x, max_z } = bounds;
  return ringToPath(
    [[min_x, min_z], [max_x, min_z], [max_x, max_z], [min_x, max_z]],
    toSvg,
  );
}
