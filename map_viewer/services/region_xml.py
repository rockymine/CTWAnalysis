"""Serialize map_data.json region dicts to XML."""

from __future__ import annotations

from map_viewer.services.region_tree import collect_named_child_ids

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
        return (
            f'{pad}<cylinder{id_attr}'
            f' base="{_fmt(base.get("x"), base.get("y"), base.get("z"))}"'
            f' radius="{_fmt_num(region.get("radius"))}"'
            f' height="{_fmt_num(region.get("height"))}"/>'
        )

    if region_type == "circle":
        center = region.get("center") or {}
        return (
            f'{pad}<circle{id_attr}'
            f' center="{_fmt(center.get("x"), center.get("z"))}"'
            f' radius="{_fmt_num(region.get("radius"))}"/>'
        )

    if region_type == "sphere":
        origin = region.get("origin") or {}
        return (
            f'{pad}<sphere{id_attr}'
            f' origin="{_fmt(origin.get("x"), origin.get("y"), origin.get("z"))}"'
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
        collect_named_child_ids(region, named_child_ids)

    roots = [r for rid, r in regions_dict.items() if rid not in named_child_ids]
    lines = ["<regions>"] + [_region_to_xml(r, indent=1) for r in roots] + ["</regions>"]
    return "\n".join(lines)
