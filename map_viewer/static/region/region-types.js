export const TYPE_ICON = {
  point:      lucide.Dot,
  block:      lucide.Square,
  rectangle:  lucide.RectangleHorizontal,
  cuboid:     lucide.Box,
  cylinder:   lucide.Cylinder,
  circle:     lucide.Circle,
  sphere:     lucide.Globe,
  complement: lucide.SquaresSubtract,
  union:      lucide.SquaresUnite,
  negative:   lucide.SquareSquare,
  intersect:  lucide.SquaresIntersect,
  reference:  lucide.SquareArrowOutUpRight,
  mirror:     lucide.SquareSplitHorizontal,
  half:       lucide.ArrowsUpFromLine,
  translate:  lucide.Move3d,
};

/**
 * Recompute 2D canvas bounds from updated coords.
 * Returns {min_x, max_x, min_z, max_z} or null when type has no 2D footprint.
 */
export function deriveBoundsFromCoords(type, coords) {
  if (type === "cylinder") {
    const bx = coords.base_x ?? 0, bz = coords.base_z ?? 0, r = coords.radius ?? 0;
    return { min_x: bx - r, max_x: bx + r, min_z: bz - r, max_z: bz + r };
  }
  if (type === "circle") {
    const cx = coords.center_x ?? 0, cz = coords.center_z ?? 0, r = coords.radius ?? 0;
    return { min_x: cx - r, max_x: cx + r, min_z: cz - r, max_z: cz + r };
  }
  if (type === "sphere") {
    const ox = coords.origin_x ?? 0, oz = coords.origin_z ?? 0, r = coords.radius ?? 0;
    return { min_x: ox - r, max_x: ox + r, min_z: oz - r, max_z: oz + r };
  }
  if (type === "block") {
    const x = coords.x ?? 0, z = coords.z ?? 0;
    return { min_x: x, max_x: x + 1, min_z: z, max_z: z + 1 };
  }
  if (type === "point") {
    const x = coords.x ?? 0, z = coords.z ?? 0;
    return { min_x: x - 0.5, max_x: x + 0.5, min_z: z - 0.5, max_z: z + 0.5 };
  }
  // cuboid Y-only, above — no 2D footprint change
  return null;
}

/**
 * Drawable tool descriptor — each entry describes one toolbar tool in the
 * Regions (and potentially future) activities.
 *
 * drawMode:
 *   "drag"    — click + drag to define a bounding rectangle (rectangle, cuboid)
 *   "radial"  — click center then click/move to set radius (cylinder, circle)
 *   "click"   — single click places the region (point, block)
 *
 * key          — lowercase keyboard shortcut character
 * toggleOff    — when true, clicking the already-active button returns to "move"
 *                (rectangle toggles off; other types do not)
 *
 * Adding a new drawable type only requires:
 *   1. An entry here in DRAW_TOOLS (and a TYPE_ICON entry above)
 *   2. A case in RegionsActivity.#buildCreatePayload / #buildNewNode
 *   3. A radial/click/drag branch in MapCanvas (if it's a new drawMode)
 *   4. A circle case in app.py create_region (backend)
 *   5. An HTML button with id="tool-<type>"
 */
export const COMPOUND_TYPES = new Set([
  "union", "complement", "intersect", "negative",
  "mirror", "translate", "half",
]);

export const DRAW_TOOLS = {
  rectangle: { key: "r", toggleOff: true,  drawMode: "drag"   },
  cuboid:    { key: "c", toggleOff: false, drawMode: "drag"   },
  cylinder:  { key: "y", toggleOff: false, drawMode: "radial" },
  circle:    { key: "o", toggleOff: false, drawMode: "radial" },
  point:     { key: "p", toggleOff: false, drawMode: "click"  },
  block:     { key: "b", toggleOff: false, drawMode: "click"  },
};

export function typeIcon(type, isSynthetic, cssClass = "region-type-icon") {
  const iconData = TYPE_ICON[type] ?? lucide.HelpCircle;
  const el = document.createElement("div");
  el.className = cssClass;
  if (isSynthetic) el.classList.add("region-type-icon--synthetic");
  if (type) el.title = type.charAt(0).toUpperCase() + type.slice(1);
  el.appendChild(lucide.createElement(iconData, { width: 14, height: 14, "stroke-width": "2" }));
  return el;
}
