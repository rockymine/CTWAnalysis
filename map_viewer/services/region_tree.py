from __future__ import annotations

_NEUTRAL = "#64748b"

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
    if base_cat == "wool":
        return "monument" if region_type == "block" else "wool_room"
    if base_cat == "spawn":
        return "spawn_point" if region_type == "point" else "spawn_area"
    return base_cat


def collect_named_child_ids(region: dict, out: set[str]) -> None:
    for child in region.get("children", []):
        child_id = child.get("id") or ""
        if child_id:
            out.add(child_id)
        collect_named_child_ids(child, out)


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
    if region_type == "half":
        origin = region.get("origin") or {}
        normal = region.get("normal") or {}
        return {
            "origin_x": origin.get("x"), "origin_y": origin.get("y"), "origin_z": origin.get("z"),
            "normal_x": normal.get("x"), "normal_y": normal.get("y"), "normal_z": normal.get("z"),
        }
    if region_type == "mirror":
        origin = region.get("origin") or {}
        normal = region.get("normal") or {}
        return {
            "origin_x": origin.get("x"), "origin_y": origin.get("y"), "origin_z": origin.get("z"),
            "normal_x": normal.get("x"), "normal_y": normal.get("y"), "normal_z": normal.get("z"),
        }
    if region_type == "translate":
        offset = region.get("offset") or {}
        return {
            "offset_x": offset.get("x"), "offset_y": offset.get("y"), "offset_z": offset.get("z"),
        }
    return None


def _encode_node(region: dict, parent_id: str = "", index: int = 0) -> dict:
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
    raw_source = region.get("source")
    source_node = _encode_node(raw_source) if raw_source else None
    return {
        "id": region_id,
        "type": region_type,
        "label": label,
        "color": _NEUTRAL,
        "bounds": _encode_bounds(region),
        "coords": _encode_coords(region),
        "is_negative": region_type == "negative",
        "synthetic_id": not bool(xml_id),
        "children": children,
        "source": source_node,
    }


def encode_region_tree_categorized(
    regions_dict: dict,
    categories_dict: dict,
) -> list[dict]:
    """Return root regions grouped into thematic categories for the browser."""
    id_to_category: dict[str, str] = {}
    for cat in _CATEGORY_ORDER:
        for region_id in categories_dict.get(cat, []):
            id_to_category.setdefault(region_id, cat)
    for cat, ids in categories_dict.items():
        for region_id in ids:
            id_to_category.setdefault(region_id, cat)

    named_child_ids: set[str] = set()
    for region in regions_dict.values():
        collect_named_child_ids(region, named_child_ids)

    root_nodes = [
        _encode_node(region)
        for region_id, region in regions_dict.items()
        if region_id not in named_child_ids
    ]

    groups: dict[str, list[dict]] = {}
    for node in root_nodes:
        base_cat = id_to_category.get(node["id"], "other")
        cat = _refine_category(base_cat, node["type"])
        groups.setdefault(cat, []).append(node)

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


def _walk_embedded_regions(container: list):
    """Yield each embedded region dict found in spawns/wools/observer_spawn items."""
    for item in container:
        embedded = item.get("region") or item.get("monument")
        if embedded:
            yield from _walk_region_recursive(embedded)


def _walk_region_recursive(region: dict):
    yield region
    for child in region.get("children", []):
        yield from _walk_region_recursive(child)


def patch_embedded_region(container: list, region_id: str, new_bounds_2d: dict) -> None:
    """Update bounds_2d on any embedded region copy whose id matches region_id."""
    for r in _walk_embedded_regions(container):
        if r.get("id") == region_id:
            r["bounds_2d"] = new_bounds_2d


def patch_all_embedded_regions(data: dict, region_id: str, new_bounds_2d: dict) -> None:
    """Propagate a bounds_2d change to all embedded copies in spawns, wools, and observer_spawn."""
    patch_embedded_region(data.get("spawns", []), region_id, new_bounds_2d)
    patch_embedded_region(data.get("wools",  []), region_id, new_bounds_2d)
    if obs := data.get("observer_spawn"):
        patch_embedded_region([obs], region_id, new_bounds_2d)


def rename_embedded_region(container: list, old_id: str, new_id: str) -> None:
    """Rename id field on any embedded region copy whose id matches old_id."""
    for r in _walk_embedded_regions(container):
        if r.get("id") == old_id:
            r["id"] = new_id


def collect_region_subtree_ids(regions: dict, region_id: str) -> list[str]:
    """Return region_id and all descendant ids found in regions (depth-first)."""
    result = [region_id]
    for child in regions.get(region_id, {}).get("children", []):
        child_id = child.get("id")
        if child_id and child_id in regions:
            result.extend(collect_region_subtree_ids(regions, child_id))
    return result


def remove_inline_children(regions: dict, ids_to_remove: set[str]) -> None:
    """Remove inline child entries matching ids_to_remove from all regions' children arrays."""
    for region in regions.values():
        children = region.get("children")
        if isinstance(children, list):
            region["children"] = [c for c in children if c.get("id") not in ids_to_remove]


def rename_in_children(region: dict, old_id: str, new_id: str) -> None:
    """Recursively update id in a composite region's children array."""
    for child in region.get("children", []):
        if child.get("id") == old_id:
            child["id"] = new_id
        rename_in_children(child, old_id, new_id)


def find_parent_of_child(
    regions: dict,
    target_id: str,
) -> tuple[dict, dict, int] | None:
    """Search all regions recursively for a child with *target_id*.

    Returns ``(parent_dict, child_dict, child_index)`` so the caller can splice
    the child back in (restore) or build an undo snapshot.  Returns ``None`` if
    the id is not found as a nested child.
    """
    def _walk(region: dict) -> tuple[dict, dict, int] | None:
        for i, child in enumerate(region.get("children", [])):
            if child.get("id") == target_id:
                return region, child, i
            result = _walk(child)
            if result is not None:
                return result
        return None

    for region in regions.values():
        result = _walk(region)
        if result is not None:
            return result
    return None


def find_child_region(regions_dict: dict, target_sid: str) -> dict | None:
    """Find a region by synthetic id, searching recursively through children.

    Synthetic ids mirror _encode_node logic:
      named region   → its own xml id
      anonymous child at index i of parent with sid P → f"{P}__{i}"
    Returns the mutable child dict so the caller can update it in-place.
    """
    def _walk(region: dict, region_sid: str) -> dict | None:
        for i, child in enumerate(region.get("children", [])):
            child_xml_id = child.get("id", "")
            child_sid = child_xml_id if child_xml_id else f"{region_sid}__{i}"
            if child_sid == target_sid:
                return child
            result = _walk(child, child_sid)
            if result is not None:
                return result
        return None

    for rid, region in regions_dict.items():
        region_sid = region.get("id", "") or rid
        result = _walk(region, region_sid)
        if result is not None:
            return result
    return None