/**
 * Tests for concept-geometry.js pure functions + integration.
 *
 * Run with:  node map_viewer/static/tests/concept-geometry.test.mjs
 *
 * Pure functions (shapeToRing, circleToRing, shapeCentroid, pointInRing,
 * pointInIsland) are inlined here so tests work without a browser CDN import.
 * Integration tests use the npm polygon-clipping package directly.
 */

import assert from "node:assert/strict";
import polygonClipping from "polygon-clipping";

// ── Inline pure functions (mirrors concept-geometry.js) ──────────────────────

const CIRCLE_POINTS = 64;

function shapeToRing(shape) {
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
    const ring = shape.vertices.map(([x, z]) => [x, z]);
    ring.push(ring[0]);
    return ring;
  }
  throw new Error(`Unknown shape type: ${shape.type}`);
}

function circleToRing(cx, cz, radius, nPoints = CIRCLE_POINTS) {
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

function shapeToMultiPoly(shape) {
  return [[shapeToRing(shape)]];
}

function shapeCentroid(shape) {
  if (shape.type === "rectangle") {
    return [(shape.min_x + shape.max_x) / 2, (shape.min_z + shape.max_z) / 2];
  }
  if (shape.type === "circle") {
    return [shape.center_x, shape.center_z];
  }
  if (shape.type === "polygon") {
    const n = shape.vertices.length;
    return [
      shape.vertices.reduce((s, [x]) => s + x, 0) / n,
      shape.vertices.reduce((s, [, z]) => s + z, 0) / n,
    ];
  }
  return [0, 0];
}

function pointInRing(px, pz, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, zi] = ring[i], [xj, zj] = ring[j];
    if ((zi > pz) !== (zj > pz) &&
        px < (xj - xi) * (pz - zi) / (zj - zi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

function pointInIsland(px, pz, island) {
  if (!pointInRing(px, pz, island.exterior)) return false;
  return !island.holes.some(h => pointInRing(px, pz, h));
}

// ── Test helpers ─────────────────────────────────────────────────────────────

let passed = 0, failed = 0;
function test(name, fn) {
  try {
    fn();
    console.log(`  ✓ ${name}`);
    passed++;
  } catch (err) {
    console.error(`  ✗ ${name}`);
    console.error(`    ${err.message}`);
    failed++;
  }
}

function approxEqual(a, b, tolerance = 0.5) {
  return Math.abs(a - b) <= tolerance;
}

// ── shapeToRing ───────────────────────────────────────────────────────────────

console.log("\nshapeToRing");

test("rectangle ring has 5 points (closed)", () => {
  const ring = shapeToRing({ type: "rectangle", min_x: 0, max_x: 10, min_z: 0, max_z: 5 });
  assert.equal(ring.length, 5);
  assert.deepEqual(ring[0], ring[4]); // closed
});

test("rectangle ring corners are correct", () => {
  const ring = shapeToRing({ type: "rectangle", min_x: -5, max_x: 5, min_z: -3, max_z: 3 });
  assert.deepEqual(ring[0], [-5, -3]);
  assert.deepEqual(ring[1], [5, -3]);
  assert.deepEqual(ring[2], [5, 3]);
  assert.deepEqual(ring[3], [-5, 3]);
});

test("polygon ring closes itself", () => {
  const ring = shapeToRing({
    type: "polygon",
    vertices: [[0, 0], [10, 0], [5, 10]],
  });
  assert.equal(ring.length, 4);
  assert.deepEqual(ring[0], ring[3]);
});

// ── circleToRing ──────────────────────────────────────────────────────────────

console.log("\ncircleToRing");

test("circle ring has nPoints+1 entries (closed)", () => {
  const ring = circleToRing(0, 0, 10);
  assert.equal(ring.length, CIRCLE_POINTS + 1);
  assert.deepEqual(ring[0], ring[CIRCLE_POINTS]);
});

test("circle ring points are approximately on the circle", () => {
  const cx = 5, cz = 5, r = 20;
  const ring = circleToRing(cx, cz, r);
  for (const [x, z] of ring.slice(0, -1)) {
    const dist = Math.hypot(x - cx, z - cz);
    assert.ok(approxEqual(dist, r, 1.5), `Point [${x},${z}] dist=${dist.toFixed(2)} not near r=${r}`);
  }
});

test("circle ring is block-snapped (integer coords)", () => {
  const ring = circleToRing(3, 7, 15);
  for (const [x, z] of ring) {
    assert.equal(x, Math.round(x));
    assert.equal(z, Math.round(z));
  }
});

// ── shapeCentroid ─────────────────────────────────────────────────────────────

console.log("\nshapeCentroid");

test("rectangle centroid", () => {
  const [cx, cz] = shapeCentroid({ type: "rectangle", min_x: 0, max_x: 10, min_z: 0, max_z: 20 });
  assert.equal(cx, 5);
  assert.equal(cz, 10);
});

test("circle centroid equals center", () => {
  const [cx, cz] = shapeCentroid({ type: "circle", center_x: 7, center_z: -3, radius: 5 });
  assert.equal(cx, 7);
  assert.equal(cz, -3);
});

test("polygon centroid is average of vertices", () => {
  const [cx, cz] = shapeCentroid({ type: "polygon", vertices: [[0, 0], [6, 0], [0, 6]] });
  assert.equal(cx, 2);
  assert.equal(cz, 2);
});

// ── pointInRing ───────────────────────────────────────────────────────────────

console.log("\npointInRing");

const squareRing = [[0,0],[10,0],[10,10],[0,10],[0,0]];

test("center point is inside square ring", () => {
  assert.ok(pointInRing(5, 5, squareRing));
});

test("point outside square ring", () => {
  assert.ok(!pointInRing(15, 5, squareRing));
});

test("point on boundary edge (corner case — either result is acceptable)", () => {
  // Boundary behavior is undefined; just ensure no crash
  pointInRing(0, 0, squareRing);
});

// ── Integration: polygon-clipping union + difference ─────────────────────────

console.log("\nintegration (polygon-clipping)");

test("union of two overlapping rectangles gives one island", () => {
  const shapeA = { type: "rectangle", operation: "add", min_x: 0, max_x: 10, min_z: 0, max_z: 10 };
  const shapeB = { type: "rectangle", operation: "add", min_x: 5, max_x: 15, min_z: 0, max_z: 10 };
  const result = polygonClipping.union(shapeToMultiPoly(shapeA), shapeToMultiPoly(shapeB));
  assert.equal(result.length, 1, "Should be one connected polygon");
});

test("union of two disconnected rectangles gives two islands", () => {
  const shapeA = { type: "rectangle", operation: "add", min_x: 0, max_x: 5, min_z: 0, max_z: 5 };
  const shapeB = { type: "rectangle", operation: "add", min_x: 20, max_x: 25, min_z: 20, max_z: 25 };
  const result = polygonClipping.union(shapeToMultiPoly(shapeA), shapeToMultiPoly(shapeB));
  assert.equal(result.length, 2, "Should be two disconnected polygons");
});

test("difference creates a hole (donut)", () => {
  const outer = { type: "rectangle", operation: "add",      min_x: 0, max_x: 20, min_z: 0, max_z: 20 };
  const inner = { type: "rectangle", operation: "subtract", min_x: 5, max_x: 15, min_z: 5, max_z: 15 };
  const addUnion = polygonClipping.union(shapeToMultiPoly(outer));
  const result   = polygonClipping.difference(addUnion, shapeToMultiPoly(inner));
  assert.equal(result.length, 1, "Still one polygon");
  assert.equal(result[0].length, 2, "Outer ring + one hole ring");
});

test("subtract shape that doesn't overlap leaves result unchanged", () => {
  const outer = { type: "rectangle", operation: "add",      min_x: 0,  max_x: 10, min_z: 0,  max_z: 10 };
  const far   = { type: "rectangle", operation: "subtract", min_x: 50, max_x: 60, min_z: 50, max_z: 60 };
  const addUnion = polygonClipping.union(shapeToMultiPoly(outer));
  const result   = polygonClipping.difference(addUnion, shapeToMultiPoly(far));
  assert.equal(result.length, 1);
  // Area should be unchanged (10×10 = 100)
  const ring = result[0][0];
  const minX = Math.min(...ring.map(p => p[0]));
  const maxX = Math.max(...ring.map(p => p[0]));
  assert.equal(maxX - minX, 10);
});

test("bridge add shape connects two disconnected islands into one", () => {
  const left   = { type: "rectangle", operation: "add", min_x: 0,  max_x: 5,  min_z: 0, max_z: 5 };
  const right  = { type: "rectangle", operation: "add", min_x: 15, max_x: 20, min_z: 0, max_z: 5 };
  const bridge = { type: "rectangle", operation: "add", min_x: 5,  max_x: 15, min_z: 1, max_z: 4 };
  const result = polygonClipping.union(
    shapeToMultiPoly(left), shapeToMultiPoly(right), shapeToMultiPoly(bridge)
  );
  assert.equal(result.length, 1, "Bridge should merge into one island");
});

// ── pointInIsland ─────────────────────────────────────────────────────────────

console.log("\npointInIsland");

test("point in donut exterior but not hole is inside island", () => {
  const donut = {
    exterior: [[0,0],[20,0],[20,20],[0,20],[0,0]],
    holes: [[[5,5],[15,5],[15,15],[5,15],[5,5]]],
  };
  assert.ok(pointInIsland(2, 2, donut));   // in exterior, not in hole
});

test("point in donut hole is NOT inside island", () => {
  const donut = {
    exterior: [[0,0],[20,0],[20,20],[0,20],[0,0]],
    holes: [[[5,5],[15,5],[15,15],[5,15],[5,5]]],
  };
  assert.ok(!pointInIsland(10, 10, donut)); // inside the hole
});

// ── assignShapesToIslands ─────────────────────────────────────────────────────

console.log("\nassignShapesToIslands");

function assignShapesToIslands(shapes, islands, addUnion) {
  const addIslands = addUnion.map(poly => ({ exterior: poly[0], holes: poly.slice(1) }));
  for (const shape of shapes) {
    const [cx, cz] = shapeCentroid(shape);
    if (shape.operation !== "subtract") {
      // Exterior-only: centroid inside the exterior means the shape contributed
      // to this island even if a hole was later carved through its centroid.
      for (const island of islands) {
        if (pointInRing(cx, cz, island.exterior)) { island.shapeIds.push(shape.id); break; }
      }
    } else {
      let assigned = false;
      for (const island of islands) {
        if (pointInRing(cx, cz, island.exterior)) { island.shapeIds.push(shape.id); assigned = true; break; }
      }
      if (!assigned) {
        for (let i = 0; i < addIslands.length; i++) {
          if (pointInRing(cx, cz, addIslands[i].exterior) && i < islands.length) {
            islands[i].shapeIds.push(shape.id); break;
          }
        }
      }
    }
  }
}

test("subtract shape inside a hole is still assigned to its island", () => {
  const outer  = { id: "s1", type: "rectangle", operation: "add",      min_x: 0, max_x: 20, min_z: 0, max_z: 20 };
  const hole   = { id: "s2", type: "rectangle", operation: "subtract", min_x: 5, max_x: 15, min_z: 5, max_z: 15 };
  const addPoly = polygonClipping.union([[[[0,0],[20,0],[20,20],[0,20],[0,0]]]]);
  const result  = polygonClipping.difference(addPoly, [[[[5,5],[15,5],[15,15],[5,15],[5,5]]]]);
  const islands = result.map((poly, i) => ({ id: `isl_${i}`, exterior: poly[0], holes: poly.slice(1), shapeIds: [] }));
  assignShapesToIslands([outer, hole], islands, addPoly);
  assert.equal(islands[0].shapeIds.length, 2, "Both add and subtract shapes should be assigned to Island 1");
  assert.ok(islands[0].shapeIds.includes("s2"), "Subtract shape should be assigned despite being in the hole");
});

test("add shape assigned by centroid to correct island", () => {
  const left  = { id: "s1", type: "rectangle", operation: "add", min_x: 0,  max_x: 5,  min_z: 0, max_z: 5 };
  const right = { id: "s2", type: "rectangle", operation: "add", min_x: 20, max_x: 25, min_z: 0, max_z: 5 };
  const addPoly = polygonClipping.union(shapeToMultiPoly(left), shapeToMultiPoly(right));
  const islands = addPoly.map((poly, i) => ({ id: `isl_${i}`, exterior: poly[0], holes: poly.slice(1), shapeIds: [] }));
  assignShapesToIslands([left, right], islands, addPoly);
  assert.equal(islands.length, 2);
  assert.equal(islands[0].shapeIds.length, 1);
  assert.equal(islands[1].shapeIds.length, 1);
});

// ── Summary ───────────────────────────────────────────────────────────────────

console.log(`\n${passed + failed} tests: ${passed} passed, ${failed} failed\n`);
if (failed > 0) process.exit(1);
