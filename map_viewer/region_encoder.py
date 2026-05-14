"""Convert map_data.json region dicts into a render-ready hierarchy for the browser."""

from __future__ import annotations

_BLUE = "#3b82f6"
_RED = "#ef4444"
_YELLOW = "#f1c40f"
_NEUTRAL = "#94a3b8"


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


def _encode_node(region: dict) -> dict:
    """Recursively encode a region dict (with optional children) into a tree node.

    Anonymous children (empty id) are encoded with a generated label and no
    SVG id so the frontend skips them in the SVG layer but still shows them in
    the sidebar.
    """
    region_id = region.get("id") or ""
    region_type = region.get("type", "unknown")
    label = region_id if region_id else f"[{region_type}]"
    children = [_encode_node(child) for child in region.get("children", [])]
    return {
        "id": region_id,
        "type": region_type,
        "label": label,
        "color": _region_color(region_id),
        "bounds": _encode_bounds(region),
        "children": children,
    }


def _collect_named_child_ids(region: dict, out: set[str]) -> None:
    """Recursively collect all non-empty child IDs under a region."""
    for child in region.get("children", []):
        child_id = child.get("id") or ""
        if child_id:
            out.add(child_id)
        _collect_named_child_ids(child, out)


def encode_region_tree(regions_dict: dict) -> list[dict]:
    """Return a hierarchy of root regions from map_data.json's regions dict.

    Root regions are top-level regions that are not referenced as a named child
    by any other top-level region.  Children that are also top-level entries
    appear only under their parent in the tree (not duplicated at the root).
    """
    named_child_ids: set[str] = set()
    for region in regions_dict.values():
        _collect_named_child_ids(region, named_child_ids)

    return [
        _encode_node(region)
        for region_id, region in regions_dict.items()
        if region_id not in named_child_ids
    ]
