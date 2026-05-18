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

export function typeIcon(type, isSynthetic, cssClass = "region-type-icon") {
  const iconData = TYPE_ICON[type] ?? lucide.HelpCircle;
  const el = document.createElement("div");
  el.className = cssClass;
  if (isSynthetic) el.classList.add("region-type-icon--synthetic");
  if (type) el.title = type.charAt(0).toUpperCase() + type.slice(1);
  el.appendChild(lucide.createElement(iconData, { width: 14, height: 14, "stroke-width": "2" }));
  return el;
}
