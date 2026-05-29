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
  const addShapes = shapes.filter(s => s.operation !== "subtract");
  const subShapes = shapes.filter(s => s.operation === "subtract");

  if (addShapes.length === 0) {
    return { islands: [], addUnion: [], newIslandCount: 0 };
  }

  // Union all add shapes
  let addUnion;
  try {
    const addPolys = addShapes.map(shapeToMultiPoly);
    addUnion = polygonClipping.union(addPolys[0], ...addPolys.slice(1));
  } catch (err) {
    console.warn("polygon-clipping union error:", err);
    return { islands: [], addUnion: [], newIslandCount: 0 };
  }

  // Subtract all subtract shapes from the union
  let result = addUnion;
  if (subShapes.length > 0) {
    try {
      const subPolys = subShapes.map(shapeToMultiPoly);
      result = polygonClipping.difference(addUnion, ...subPolys);
    } catch (err) {
      console.warn("polygon-clipping difference error:", err);
      // Keep the union — subtraction failed, ignore it
    }
  }

  // Each polygon in the MultiPolygon is a separate connected island
  const islands = result.map((poly, i) => ({
    id:       `isl_${i}`,
    name:     `Island ${i + 1}`,
    color:    ISLAND_COLORS[i % ISLAND_COLORS.length],
    exterior: poly[0],
    holes:    poly.slice(1),
    shapeIds: [],
  }));

  return { islands, addUnion, newIslandCount: islands.length };
}

/**
 * Assign each shape to an island and populate island.shapeIds.
 *
 * Add shapes: centroid tested against final computed islands.
 * Subtract shapes: centroid tested against the add-only union polygons.
 */
export function assignShapesToIslands(shapes, islands, addUnion) {
  // Build add-union islands (temporary, for subtract assignment)
  const addIslands = addUnion.map((poly, i) => ({
    id: `add_${i}`, exterior: poly[0], holes: poly.slice(1),
  }));

  for (const shape of shapes) {
    const [cx, cz] = shapeCentroid(shape);

    if (shape.operation !== "subtract") {
      // Use exterior-only check: a shape whose centroid falls inside the exterior
      // contributed to that island even if a hole was later carved through it.
      for (const island of islands) {
        if (pointInRing(cx, cz, island.exterior)) {
          island.shapeIds.push(shape.id);
          break;
        }
      }
    } else {
      // Subtract shapes: their centroid may be inside the hole they carved.
      // Check the final island exterior only (ignoring holes) so we still
      // assign them to the island they subtracted from.
      let assigned = false;
      for (const island of islands) {
        if (pointInRing(cx, cz, island.exterior)) {
          island.shapeIds.push(shape.id);
          assigned = true;
          break;
        }
      }
      // Fallback: check add-union exterior in case the subtract shape is
      // entirely outside the final islands (e.g. it subtracted everything away).
      if (!assigned) {
        for (let i = 0; i < addIslands.length; i++) {
          if (pointInRing(cx, cz, addIslands[i].exterior) && i < islands.length) {
            islands[i].shapeIds.push(shape.id);
            break;
          }
        }
      }
    }
  }
}
