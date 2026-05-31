/**
 * Polygon simplification utilities.
 *
 * polygonArea(vertices)           — signed shoelace area in block units
 * visvalingamWhyatt(verts, tol)   — simplify polygon to remove vertices whose
 *                                   effective triangle area is below `tol`
 */

function triArea([ax, az], [bx, bz], [cx, cz]) {
  return Math.abs((bx - ax) * (cz - az) - (cx - ax) * (bz - az)) / 2;
}

export function polygonArea(vertices) {
  const n = vertices.length;
  let sum = 0;
  for (let i = 0, j = n - 1; i < n; j = i++) {
    sum += vertices[j][0] * vertices[i][1] - vertices[i][0] * vertices[j][1];
  }
  return Math.abs(sum) / 2;
}

/**
 * Visvalingam–Whyatt simplification.
 * Removes vertices whose triangle area (formed with their two neighbours) is
 * below `minArea`, smallest first, until no candidate remains or ≤3 verts left.
 *
 * @param {[number,number][]} vertices
 * @param {number}            minArea  triangle-area threshold in blocks²
 * @returns {[number,number][]} simplified vertex array (≥3 entries)
 */
export function visvalingamWhyatt(vertices, minArea) {
  const n = vertices.length;
  if (n <= 3) return vertices.slice();

  // Doubly-linked index list for O(1) neighbour removal
  const prev = vertices.map((_, i) => (i === 0 ? n - 1 : i - 1));
  const next = vertices.map((_, i) => (i === n - 1 ? 0 : i + 1));
  const area = new Float64Array(n);
  const gone = new Uint8Array(n);

  const recompute = (i) => {
    area[i] = triArea(vertices[prev[i]], vertices[i], vertices[next[i]]);
  };
  for (let i = 0; i < n; i++) recompute(i);

  let remaining = n;

  while (remaining > 3) {
    // Find vertex with the smallest effective area
    let minIdx = -1, minA = Infinity;
    for (let i = 0; i < n; i++) {
      if (!gone[i] && area[i] < minA) { minA = area[i]; minIdx = i; }
    }

    if (minIdx === -1 || minA >= minArea) break;

    // Remove it and relink neighbours
    const p = prev[minIdx], q = next[minIdx];
    next[p] = q;
    prev[q] = p;
    gone[minIdx] = 1;
    remaining--;

    recompute(p);
    recompute(q);
  }

  const result = [];
  for (let i = 0; i < n; i++) if (!gone[i]) result.push(vertices[i]);
  return result;
}
