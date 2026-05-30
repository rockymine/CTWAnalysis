/**
 * concept-geometry.js — Boolean island computation for the concept tool.
 *
 * Converts primitive shapes to polygons, runs union/difference via
 * polygon-clipping, and returns connected-component islands.
 *
 * Pure helper functions (shapeToRing, circleToRing, shapeCentroid,
 * pointInRing) are also exported for testing via Node.js.
 */

import polygonClipping from "https://cdn.jsdelivr.net/npm/polygon-clipping@0.15.7/+esm";

// Number of vertices used to approximate a circle outline.
const CIRCLE_POINTS = 64;

const ISLAND_COLORS = [
  "#4ade80", "#60a5fa", "#f472b6", "#fb923c",
  "#a78bfa", "#34d399", "#facc15", "#f87171",
];

// ── Shape → ring conversion ───────────────────────────────────────────────────

/**
 * Convert a shape to a closed coordinate ring [[x,z], ...].
 * The last point equals the first (polygon-clipping requirement).
 */
export function shapeToRing(shape) {
  if (shape.type === "rectangle") {
    const { min_x, max_x, min_z, max_z } = shape;
    return [
      [min_x, min_z], [max_x, min_z],
      [max_x, max_z], [min_x, max_z],
      [min_x, min_z],
    ];
  }
  if (shape.type === "circle") {
    return circleToRing(shape.center_x, shape.center_z, shape.radius);
  }
  if (shape.type === "polygon") {
    if (shape.vertices.length < 3) return [];
    const ring = shape.vertices.map(([x, z]) => [x, z]);
    ring.push(ring[0]);
    return ring;
  }
  throw new Error(`Unknown shape type: ${shape.type}`);
}

/**
 * Approximate a circle as a block-snapped polygon ring.
 * Each point is rounded to the nearest integer block coordinate.
 */
export function circleToRing(cx, cz, radius, nPoints = CIRCLE_POINTS) {
  const points = [];
  for (let i = 0; i < nPoints; i++) {
    const angle = (2 * Math.PI * i) / nPoints;
    points.push([
      Math.round(cx + radius * Math.cos(angle)),
      Math.round(cz + radius * Math.sin(angle)),
    ]);
  }
  points.push(points[0]);
  return points;
}

/** Wrap a ring as a polygon-clipping MultiPolygon: [ [ ring ] ] */
function ringToMultiPoly(ring) {
  return [[ring]];
}

/** Convert a shape to a polygon-clipping MultiPolygon. */
export function shapeToMultiPoly(shape) {
  return ringToMultiPoly(shapeToRing(shape));
}

// ── Centroid + point-in-polygon ───────────────────────────────────────────────

/** Return the [x, z] centroid of a shape. */
export function shapeCentroid(shape) {
  if (shape.type === "rectangle") {
    return [
      (shape.min_x + shape.max_x) / 2,
      (shape.min_z + shape.max_z) / 2,
    ];
  }
  if (shape.type === "circle") {
    return [shape.center_x, shape.center_z];
  }
  if (shape.type === "polygon") {
    const n = shape.vertices.length;
    const sumX = shape.vertices.reduce((s, [x]) => s + x, 0);
    const sumZ = shape.vertices.reduce((s, [, z]) => s + z, 0);
    return [sumX / n, sumZ / n];
  }
  return [0, 0];
}

/**
 * Ray-casting point-in-polygon test for a single ring [[x,z],...].
 * Returns true if (px, pz) is inside the ring.
 */
export function pointInRing(px, pz, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, zi] = ring[i];
    const [xj, zj] = ring[j];
    if ((zi > pz) !== (zj > pz) &&
        px < (xj - xi) * (pz - zi) / (zj - zi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

/**
 * Test if (px, pz) is inside an island polygon {exterior, holes}.
 * Returns true if inside exterior and not inside any hole.
 */
export function pointInIsland(px, pz, island) {
  if (!pointInRing(px, pz, island.exterior)) return false;
  return !island.holes.some(hole => pointInRing(px, pz, hole));
}

// ── Main computation ──────────────────────────────────────────────────────────

/**
 * Compute islands from the given list of shapes.
 *
 * Returns:
 *   {
 *     islands: [{ id, name, color, exterior, holes, shapeIds }],
 *     addUnion: MultiPolygon of the add-only union (for subtract assignment),
 *     newIslandCount: number of islands in this result (used for warning detection),
 *   }
 */
export function computeIslands(shapes) {
  const normalAddShapes    = shapes.filter(s => s.operation !== "subtract" && !s.override);
  const overrideAddShapes  = shapes.filter(s => s.operation !== "subtract" && s.override);
  const normalSubShapes    = shapes.filter(s => s.operation === "subtract" && !s.override);
  const overrideSubShapes  = shapes.filter(s => s.operation === "subtract" && s.override);

  if (normalAddShapes.length === 0 && overrideAddShapes.length === 0) {
    return { islands: [], addUnion: [], overrideAddUnion: [], newIslandCount: 0 };
  }

  // Step 1: union normal add shapes.
  let normalUnion = [];
  if (normalAddShapes.length > 0) {
    try {
      const polys = normalAddShapes.map(shapeToMultiPoly);
      normalUnion = polygonClipping.union(polys[0], ...polys.slice(1));
    } catch (err) {
      console.warn("polygon-clipping union error:", err);
    }
  }

  // Step 2: normal subtract shapes carve into the normal union only.
  let afterNormalSub = normalUnion;
  if (normalSubShapes.length > 0 && normalUnion.length > 0) {
    try {
      const subPolys = normalSubShapes.map(shapeToMultiPoly);
      afterNormalSub = polygonClipping.difference(normalUnion, ...subPolys);
    } catch (err) {
      console.warn("polygon-clipping difference error:", err);
    }
  }

  // Step 3: override add shapes union in after normal subtraction — immune to normal subtracts.
  let afterOverrideAdd = afterNormalSub;
  if (overrideAddShapes.length > 0) {
    try {
      const overridePolys = overrideAddShapes.map(shapeToMultiPoly);
      afterOverrideAdd = afterNormalSub.length > 0
        ? polygonClipping.union(afterNormalSub, ...overridePolys)
        : polygonClipping.union(overridePolys[0], ...overridePolys.slice(1));
    } catch (err) {
      console.warn("polygon-clipping override-add union error:", err);
    }
  }

  // Step 4: override subtract shapes cut last — they carve through everything,
  // including override add shapes.
  let result = afterOverrideAdd;
  if (overrideSubShapes.length > 0 && afterOverrideAdd.length > 0) {
    try {
      const overrideSubPolys = overrideSubShapes.map(shapeToMultiPoly);
      result = polygonClipping.difference(afterOverrideAdd, ...overrideSubPolys);
    } catch (err) {
      console.warn("polygon-clipping override-subtract difference error:", err);
    }
  }

  const islands = result.map((poly, i) => ({
    id:       `isl_${i}`,
    name:     `Island ${i + 1}`,
    color:    ISLAND_COLORS[i % ISLAND_COLORS.length],
    exterior: poly[0],
    holes:    poly.slice(1),
    shapeIds: [],
  }));

  return {
    islands,
    addUnion:         normalUnion,      // normal-add union — for normal shape assignment
    overrideAddUnion: afterOverrideAdd, // state before override subtracts — for override subtract assignment
    newIslandCount:   islands.length,
  };
}

/** Centroid of a polygon ring [[x,z],...] (last point == first). */
function ringCentroid(ring) {
  const n = ring.length - 1;
  let sumX = 0, sumZ = 0;
  for (let i = 0; i < n; i++) { sumX += ring[i][0]; sumZ += ring[i][1]; }
  return [sumX / n, sumZ / n];
}

/**
 * Assign each shape to island(s) and populate island.shapeIds.
 *
 * Uses polygon intersection rather than centroid tests so that:
 * - Add shapes whose centroid falls in a carved void are still correctly placed.
 * - Subtract shapes that span multiple islands appear under all affected islands.
 * - Override add shapes (immune to subtract) are placed via direct final-island
 *   intersection rather than via the normal add-union component map.
 *
 * Strategy:
 *   1. Map each final island back to the normal-add-union component it came from.
 *   2. For normal add shapes: find the one normal-add-union component they intersect;
 *      assign to the matching final island(s).  If a subtract split one component into
 *      several final islands, use a secondary intersection check to pick the right one(s).
 *   3. For subtract shapes: find every normal-add-union component they intersect; assign
 *      to all corresponding final islands.
 *   4. For override add shapes: intersect directly against the final island polygons
 *      (they were unioned in after normal subtraction, so the normal-add-union map doesn't apply).
 *   5. For override subtract shapes: intersect against the overrideAddUnion (the state after
 *      step 3, before override subtracts) to find which islands they carved from.
 */
export function assignShapesToIslands(shapes, islands, addUnion, overrideAddUnion) {
  if (islands.length === 0) return;

  // Pre-build island MultiPolygons for intersection tests.
  const islandPolys = islands.map(isl => [[isl.exterior, ...isl.holes]]);

  // Map final islands to their source normal-add-union component (−1 if none).
  const islandToNormalIdx = islands.map(isl => {
    if (addUnion.length === 0) return -1;
    const [cx, cz] = ringCentroid(isl.exterior);
    for (let j = 0; j < addUnion.length; j++) {
      if (pointInRing(cx, cz, addUnion[j][0])) return j;
    }
    return -1;
  });

  // Map final islands to their source override-add-union component (−1 if none).
  const islandToOverrideAddIdx = islands.map(isl => {
    if (!overrideAddUnion?.length) return -1;
    const [cx, cz] = ringCentroid(isl.exterior);
    for (let j = 0; j < overrideAddUnion.length; j++) {
      if (pointInRing(cx, cz, overrideAddUnion[j][0])) return j;
    }
    return -1;
  });

  for (const shape of shapes) {
    const shapePoly = shapeToMultiPoly(shape);
    const toAssign  = new Set();

    if (shape.operation === "subtract" && !shape.override) {
      // Normal subtract: assign to islands from normal-add-union components it touches.
      for (let j = 0; j < addUnion.length; j++) {
        let hits = false;
        try { hits = polygonClipping.intersection(shapePoly, [addUnion[j]]).length > 0; } catch { /* skip */ }
        if (!hits) continue;
        for (let i = 0; i < islands.length; i++) {
          if (islandToNormalIdx[i] === j) toAssign.add(i);
        }
      }
    } else if (shape.operation === "subtract" && shape.override) {
      // Override subtract: cuts last — assign to islands from override-add-union components it touches.
      for (let j = 0; j < (overrideAddUnion?.length ?? 0); j++) {
        let hits = false;
        try { hits = polygonClipping.intersection(shapePoly, [overrideAddUnion[j]]).length > 0; } catch { /* skip */ }
        if (!hits) continue;
        for (let i = 0; i < islands.length; i++) {
          if (islandToOverrideAddIdx[i] === j) toAssign.add(i);
        }
      }
    } else if (shape.override) {
      // Override add: unioned in after normal subtraction — intersect directly against final islands.
      for (let i = 0; i < islands.length; i++) {
        let hits = false;
        try { hits = polygonClipping.intersection(shapePoly, islandPolys[i]).length > 0; } catch { /* skip */ }
        if (hits) toAssign.add(i);
      }
    } else {
      // Normal add: assign to every normal-add-union component it overlaps.
      // No break — a self-intersecting shape (e.g. figure-eight lasso) is
      // decomposed into multiple disjoint components by polygon-clipping, so
      // the shape must be credited to all of them.  For simple shapes this loop
      // still only ever finds one matching component (components are disjoint).
      for (let j = 0; j < addUnion.length; j++) {
        let hits = false;
        try { hits = polygonClipping.intersection(shapePoly, [addUnion[j]]).length > 0; } catch { /* skip */ }
        if (!hits) continue;

        const peers = islands.reduce((acc, _, i) => {
          if (islandToNormalIdx[i] === j) acc.push(i);
          return acc;
        }, []);

        if (peers.length === 1) {
          toAssign.add(peers[0]);
        } else {
          // A subtract split this component into multiple final islands —
          // check which ones this add shape actually overlaps.
          for (const i of peers) {
            let sub = false;
            try { sub = polygonClipping.intersection(shapePoly, islandPolys[i]).length > 0; } catch { /* skip */ }
            if (sub) toAssign.add(i);
          }
        }
      }
    }

    for (const i of toAssign) islands[i].shapeIds.push(shape.id);
  }
}
