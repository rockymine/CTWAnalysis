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

export function typeIcon(type, isSynthetic, cssClass = "region-type-icon") {
  const iconData = TYPE_ICON[type] ?? lucide.HelpCircle;
  const el = document.createElement("div");
  el.className = cssClass;
  if (isSynthetic) el.classList.add("region-type-icon--synthetic");
  if (type) el.title = type.charAt(0).toUpperCase() + type.slice(1);
  el.appendChild(lucide.createElement(iconData, { width: 14, height: 14, "stroke-width": "2" }));
  return el;
}
