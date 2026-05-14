"""Convert map_data.json region dicts into a render-ready hierarchy for the browser."""

from __future__ import annotations

_BLUE = "#3b82f6"
_RED = "#ef4444"
_YELLOW = "#f1c40f"
_NEUTRAL = "#94a3b8"

# Canonical category order and display labels.
_CATEGORY_ORDER = ["spawn", "wool", "monument", "build", "other"]
_CATEGORY_LABELS = {
    "spawn":    "Spawns",
    "wool":     "Wool",
    "monument": "Monuments",
    "build":    "Build",
    "other":    "Other",
}


def _region_color(region_id: str) -> str:
    lower = region_id.lower()
    if "blue" in lower:
        return _BLUE
    if "red" in lower:
        return _RED
    if "wool" in lower or "monument" in lower:
        return _YELLOW
    return _NEUTRAL


def _encode_bounds(region: dict) -> dict | None:
    bounds_2d = region.get("bounds_2d")
    if not bounds_2d:
        return None
    mn = bounds_2d.get("min", {})
    mx = bounds_2d.get("max", {})
    if "x" not in mn or "z" not in mn:
        return None
    return {"min_x": mn["x"], "min_z": mn["z"], "max_x": mx["x"], "max_z": mx["z"]}


def _encode_node(region: dict, parent_id: str = "", index: int = 0) -> dict:
    """Recursively encode a region dict (with optional children) into a tree node.

    Anonymous children (those with no ``id`` in the XML) receive a synthetic
    deterministic id of the form ``{parent_id}__{index}`` so the browser can
    create a uniquely addressable SVG group and checkbox for each one.  The
    displayed ``label`` is kept as ``[type]`` to make clear it has no XML name.

    ``is_negative`` is set for complement regions so the frontend renders them
    as map-bbox-minus-children rather than drawing the bounds directly.
    """
    xml_id = region.get("id") or ""
    region_type = region.get("type", "unknown")

    # Assign a synthetic id for anonymous nodes so they are selectable
    region_id = xml_id if xml_id else (f"{parent_id}__{index}" if parent_id else f"__anon_{index}")
    label = xml_id if xml_id else f"[{region_type}]"

    children = [
        _encode_node(child, parent_id=region_id, index=i)
        for i, child in enumerate(region.get("children", []))
    ]
    return {
        "id": region_id,
        "type": region_type,
        "label": label,
        "color": _region_color(xml_id),  # color based on XML id; anon nodes get neutral
        "bounds": _encode_bounds(region),
        "is_negative": region_type == "negative",
        "synthetic_id": not bool(xml_id),  # True when id was generated, not from XML
        "children": children,
    }


def _collect_named_child_ids(region: dict, out: set[str]) -> None:
    """Recursively collect all non-empty child IDs under a region."""
    for child in region.get("children", []):
        child_id = child.get("id") or ""
        if child_id:
            out.add(child_id)
        _collect_named_child_ids(child, out)


def encode_region_tree_categorized(
    regions_dict: dict,
    categories_dict: dict,
) -> list[dict]:
    """Return root regions grouped into thematic categories.

    Each entry in the returned list:
      {"name": category_name, "label": display_label, "regions": [tree nodes]}

    Category order follows ``_CATEGORY_ORDER``; any categories present in
    ``categories_dict`` but not in that list are appended at the end.
    Regions absent from all categories land in "other".  Empty groups are
    omitted from the output.

    Root regions are top-level regions not referenced as a named child by any
    other top-level region — same rule as ``encode_region_tree``.
    """
    # Build id → first-matching category lookup (priority follows _CATEGORY_ORDER)
    id_to_category: dict[str, str] = {}
    for cat in _CATEGORY_ORDER:
        for region_id in categories_dict.get(cat, []):
            id_to_category.setdefault(region_id, cat)
    # Any extra categories not in the canonical order
    for cat, ids in categories_dict.items():
        for region_id in ids:
            id_to_category.setdefault(region_id, cat)

    # Find root nodes (not referenced as named children by anyone else)
    named_child_ids: set[str] = set()
    for region in regions_dict.values():
        _collect_named_child_ids(region, named_child_ids)

    root_nodes = [
        _encode_node(region)
        for region_id, region in regions_dict.items()
        if region_id not in named_child_ids
    ]

    # Group root nodes by category
    groups: dict[str, list[dict]] = {}
    for node in root_nodes:
        cat = id_to_category.get(node["id"], "other")
        groups.setdefault(cat, []).append(node)

    # Emit in canonical order, then any extra categories, skipping empty groups
    seen = set(_CATEGORY_ORDER)
    ordered_cats = _CATEGORY_ORDER + [c for c in groups if c not in seen]
    return [
        {
            "name": cat,
            "label": _CATEGORY_LABELS.get(cat, cat.title()),
            "regions": groups[cat],
        }
        for cat in ordered_cats
        if cat in groups
    ]
