"""Convert map_data.json region dicts into a render-ready hierarchy for the browser."""

from __future__ import annotations

_NEUTRAL = "#64748b"   # slate gray  — default region color

# Canonical category order and display labels.
# wool+block → monument; wool+other → wool_room
# spawn+point → spawn_point; spawn+other → spawn_area
# The original "monument" category in region_categories is always empty in practice.
_CATEGORY_ORDER = ["spawn_area", "spawn_point", "wool_room", "monument", "build", "other"]
_CATEGORY_LABELS = {
    "spawn_area":  "Spawn Areas",
    "spawn_point": "Spawn Points",
    "wool_room":   "Wool Rooms",
    "monument":    "Monuments",
    "build":       "Build",
    "other":       "Other",
}


def _refine_category(base_cat: str, region_type: str) -> str:
    """Refine coarse XML categories into semantically distinct groups."""
    if base_cat == "wool":
        return "monument" if region_type == "block" else "wool_room"
    if base_cat == "spawn":
        return "spawn_point" if region_type == "point" else "spawn_area"
    return base_cat



def _encode_bounds(region: dict) -> dict | None:
    bounds_2d = region.get("bounds_2d")
    if not bounds_2d:
        return None
    mn = bounds_2d.get("min", {})
    mx = bounds_2d.get("max", {})
    if "x" not in mn or "z" not in mn:
        return None
    min_x, min_z = mn["x"], mn["z"]
    max_x, max_z = mx["x"], mx["z"]
    # Older map_data.json files store min==max (zero area) for block and point.
    # Expand here so existing outputs display correctly without a pipeline re-run.
    # block: index (x,z) occupies [x, x+1] × [z, z+1]  → max += 1
    # point: continuous coord — shown as 1×1 square centred on it → ±0.5
    region_type = region.get("type")
    if max_x == min_x and max_z == min_z:
        if region_type == "block":
            max_x = min_x + 1
            max_z = min_z + 1
        elif region_type == "point":
            min_x -= 0.5
            min_z -= 0.5
            max_x += 0.5
            max_z += 0.5
    return {"min_x": min_x, "min_z": min_z, "max_x": max_x, "max_z": max_z}


def _encode_coords(region: dict) -> dict | None:
    """Extract type-specific coordinates needed to reconstruct the XML element.

    Returns a flat dict of the fields that cannot be derived from bounds_2d
    (e.g. y-coordinates, radius, height). 2D coordinates for rectangle and
    cuboid are also included so the viewer can round-trip them to XML even
    before the region has been rendered to bounds_2d.
    """
    region_type = region.get("type")
    if region_type == "rectangle":
        return {k: region.get(k) for k in ("min_x", "min_z", "max_x", "max_z")}
    if region_type == "cuboid":
        return {k: region.get(k) for k in ("min_x", "min_y", "min_z", "max_x", "max_y", "max_z")}
    if region_type == "cylinder":
        base = region.get("base") or {}
        return {
            "base_x": base.get("x"), "base_y": base.get("y"), "base_z": base.get("z"),
            "radius": region.get("radius"), "height": region.get("height"),
        }
    if region_type == "circle":
        center = region.get("center") or {}
        return {"center_x": center.get("x"), "center_z": center.get("z"), "radius": region.get("radius")}
    if region_type == "sphere":
        origin = region.get("origin") or {}
        return {
            "origin_x": origin.get("x"), "origin_y": origin.get("y"), "origin_z": origin.get("z"),
            "radius": region.get("radius"),
        }
    if region_type in ("block", "point"):
        pos = region.get("position") or {}
        return {"x": pos.get("x"), "y": pos.get("y"), "z": pos.get("z")}
    if region_type == "reference":
        return {"ref_id": region.get("ref_id", "")}
    return None


def _encode_node(region: dict, parent_id: str = "", index: int = 0) -> dict:
    """Recursively encode a region dict (with optional children) into a tree node.

    All regions and their composite children have ids baked into map_data.json by
    the pipeline (``inject_anonymous_region_ids``), so ``xml_id`` is always
    non-empty for up-to-date JSON.  Reference-type nodes override their label to
    show ``→ target`` regardless, since that is more informative than the
    synthetic id string.

    ``is_negative`` is set for complement regions so the frontend renders them
    as map-bbox-minus-children rather than drawing the bounds directly.
    """
    xml_id = region.get("id") or ""
    region_type = region.get("type", "unknown")

    region_id = xml_id
    label = xml_id
    if region_type == "reference":
        label = f"→ {region.get('ref_id', '?')}"

    children = [
        _encode_node(child, parent_id=region_id, index=i)
        for i, child in enumerate(region.get("children", []))
    ]
    return {
        "id": region_id,
        "type": region_type,
        "label": label,
        "color": _NEUTRAL,
        "bounds": _encode_bounds(region),
        "coords": _encode_coords(region),
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


_COMPOSITE_TYPES = {"union", "negative", "complement", "intersect"}


def _fmt_num(n: object) -> str:
    if n is None:
        return "?"
    if n == "oo" or n == "-oo":
        return str(n)
    if isinstance(n, float) and n.is_integer():
        return str(int(n))
    return str(n)


def _fmt(*nums: object) -> str:
    return ",".join(_fmt_num(n) for n in nums)


def _region_to_xml(region: dict, indent: int = 0) -> str:
    """Recursively convert a region dict from map_data.json to an XML element string.

    X/Z coordinates are taken from ``bounds_2d`` (updated by the PATCH endpoint).
    Y, radius, and height come from the original type-specific fields.
    """
    pad = "  " * indent
    region_type = region.get("type", "unknown")
    xml_id = region.get("id") or ""
    id_attr = f' id="{xml_id}"' if xml_id else ""

    bounds = region.get("bounds_2d") or {}
    b_min = bounds.get("min", {})
    b_max = bounds.get("max", {})
    min_x, min_z = b_min.get("x"), b_min.get("z")
    max_x, max_z = b_max.get("x"), b_max.get("z")

    if region_type in _COMPOSITE_TYPES:
        children_xml = [_region_to_xml(c, indent + 1) for c in region.get("children", [])]
        if children_xml:
            inner = "\n".join(children_xml)
            return f"{pad}<{region_type}{id_attr}>\n{inner}\n{pad}</{region_type}>"
        return f"{pad}<{region_type}{id_attr}/>"

    if region_type == "rectangle":
        return f'{pad}<rectangle{id_attr} min="{_fmt(min_x, min_z)}" max="{_fmt(max_x, max_z)}"/>'

    if region_type == "cuboid":
        return (
            f'{pad}<cuboid{id_attr}'
            f' min="{_fmt(min_x, region.get("min_y"), min_z)}"'
            f' max="{_fmt(max_x, region.get("max_y"), max_z)}"/>'
        )

    if region_type == "cylinder":
        base = region.get("base") or {}
        cx = (min_x + max_x) / 2 if min_x is not None and max_x is not None else base.get("x")
        cz = (min_z + max_z) / 2 if min_z is not None and max_z is not None else base.get("z")
        return (
            f'{pad}<cylinder{id_attr}'
            f' base="{_fmt(cx, base.get("y"), cz)}"'
            f' radius="{_fmt_num(region.get("radius"))}"'
            f' height="{_fmt_num(region.get("height"))}"/>'
        )

    if region_type == "circle":
        center = region.get("center") or {}
        cx = (min_x + max_x) / 2 if min_x is not None and max_x is not None else center.get("x")
        cz = (min_z + max_z) / 2 if min_z is not None and max_z is not None else center.get("z")
        return (
            f'{pad}<circle{id_attr}'
            f' center="{_fmt(cx, cz)}"'
            f' radius="{_fmt_num(region.get("radius"))}"/>'
        )

    if region_type == "sphere":
        origin = region.get("origin") or {}
        cx = (min_x + max_x) / 2 if min_x is not None and max_x is not None else origin.get("x")
        cz = (min_z + max_z) / 2 if min_z is not None and max_z is not None else origin.get("z")
        return (
            f'{pad}<sphere{id_attr}'
            f' origin="{_fmt(cx, origin.get("y"), cz)}"'
            f' radius="{_fmt_num(region.get("radius"))}"/>'
        )

    if region_type in ("block", "point"):
        pos = region.get("position") or {}
        coords = _fmt(pos.get("x"), pos.get("y"), pos.get("z"))
        return f"{pad}<{region_type}{id_attr}>{coords}</{region_type}>"

    if region_type == "reference":
        ref_id = region.get("ref_id", "")
        return f'{pad}<region id="{ref_id}"/>'

    return f"{pad}<!-- unknown type: {region_type} -->"


def regions_to_xml(regions_dict: dict) -> str:
    """Serialise a map_data.json regions dict to a ``<regions>`` XML block."""
    named_child_ids: set[str] = set()
    for region in regions_dict.values():
        _collect_named_child_ids(region, named_child_ids)

    roots = [r for rid, r in regions_dict.items() if rid not in named_child_ids]
    lines = ["<regions>"] + [_region_to_xml(r, indent=1) for r in roots] + ["</regions>"]
    return "\n".join(lines)



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

    # Group root nodes by (refined) category
    groups: dict[str, list[dict]] = {}
    for node in root_nodes:
        base_cat = id_to_category.get(node["id"], "other")
        cat = _refine_category(base_cat, node["type"])
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
