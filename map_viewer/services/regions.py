from typing import Optional


def apply_coord_update(region: dict, region_type: str, coords: dict) -> dict | None:
    """Update raw geometry fields on *region* from *coords* and recompute bounds_2d.

    Returns the new bounds_2d dict, or None if the type has no 2D footprint change
    (cuboid Y-only edits, above).
    """
    def _bounds(min_x: float, min_z: float, max_x: float, max_z: float) -> dict:
        return {"min": {"x": min_x, "z": min_z}, "max": {"x": max_x, "z": max_z}}

    if region_type == "cuboid":
        if "min_y" in coords:
            region["min_y"] = coords["min_y"]
        if "max_y" in coords:
            region["max_y"] = coords["max_y"]
        return None  # only Y changed; 2D bounds stay the same

    if region_type == "cylinder":
        if "base_x" in coords:
            region.setdefault("base", {})["x"] = coords["base_x"]
        if "base_y" in coords:
            region.setdefault("base", {})["y"] = coords["base_y"]
        if "base_z" in coords:
            region.setdefault("base", {})["z"] = coords["base_z"]
        if "radius" in coords:
            region["radius"] = coords["radius"]
        if "height" in coords:
            region["height"] = coords["height"]
        base = region.get("base", {})
        bx, bz = base.get("x", 0), base.get("z", 0)
        r = float(region.get("radius", 0))
        new_bounds = _bounds(bx - r, bz - r, bx + r, bz + r)
        region["bounds_2d"] = new_bounds
        return new_bounds

    if region_type == "circle":
        if "center_x" in coords:
            region.setdefault("center", {})["x"] = coords["center_x"]
        if "center_z" in coords:
            region.setdefault("center", {})["z"] = coords["center_z"]
        if "radius" in coords:
            region["radius"] = coords["radius"]
        center = region.get("center", {})
        cx, cz = center.get("x", 0), center.get("z", 0)
        r = float(region.get("radius", 0))
        new_bounds = _bounds(cx - r, cz - r, cx + r, cz + r)
        region["bounds_2d"] = new_bounds
        return new_bounds

    if region_type == "sphere":
        if "origin_x" in coords:
            region.setdefault("origin", {})["x"] = coords["origin_x"]
        if "origin_y" in coords:
            region.setdefault("origin", {})["y"] = coords["origin_y"]
        if "origin_z" in coords:
            region.setdefault("origin", {})["z"] = coords["origin_z"]
        if "radius" in coords:
            region["radius"] = coords["radius"]
        origin = region.get("origin", {})
        ox, oz = origin.get("x", 0), origin.get("z", 0)
        r = float(region.get("radius", 0))
        new_bounds = _bounds(ox - r, oz - r, ox + r, oz + r)
        region["bounds_2d"] = new_bounds
        return new_bounds

    if region_type in ("block", "point"):
        pos = region.setdefault("position", {})
        if "x" in coords:
            pos["x"] = coords["x"]
        if "y" in coords:
            pos["y"] = coords["y"]
        if "z" in coords:
            pos["z"] = coords["z"]
        px, pz = pos.get("x", 0), pos.get("z", 0)
        if region_type == "block":
            new_bounds = _bounds(px, pz, px + 1, pz + 1)
        else:
            new_bounds = _bounds(px - 0.5, pz - 0.5, px + 0.5, pz + 0.5)
        region["bounds_2d"] = new_bounds
        return new_bounds

    if region_type == "above":
        if "y" in coords:
            region["y"] = coords["y"]
        return None  # above has no 2D footprint

    return None


def resolve_region_bounds(
    data: dict,
    region_id: Optional[str],
) -> Optional[tuple[float, float, float, float]]:
    """Return (min_x, min_z, max_x, max_z) for *region_id* from *data['regions']*.

    Returns None if region_id is absent or the region has no bounds_2d.
    """
    if not region_id:
        return None
    region = data.get("regions", {}).get(region_id)
    if region is None:
        return None
    bounds = region.get("bounds_2d")
    if not bounds:
        return None
    return (
        bounds["min"]["x"],
        bounds["min"]["z"],
        bounds["max"]["x"],
        bounds["max"]["z"],
    )
