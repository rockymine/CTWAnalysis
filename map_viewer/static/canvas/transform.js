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

/** Convert a bounds {min_x, min_z, max_x, max_z} to an SVG path ring. */
export function boundsToRingPath(bounds, toSvg) {
  const { min_x, min_z, max_x, max_z } = bounds;
  return ringToPath(
    [[min_x, min_z], [max_x, min_z], [max_x, max_z], [min_x, max_z]],
    toSvg,
  );
}
