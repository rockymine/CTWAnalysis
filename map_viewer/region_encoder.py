"""Convert map_data.json region dicts into render-ready structures for the browser."""

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


def encode_regions(regions_dict: dict) -> list[dict]:
    """Convert map_data.json regions dict to a list of render-ready dicts.

    Each output dict has:
      id, type, label, color, bounds {min_x, min_z, max_x, max_z}

    Regions without bounds_2d are silently skipped.
    """
    result: list[dict] = []
    for region_id, region in regions_dict.items():
        bounds_2d = region.get("bounds_2d")
        if not bounds_2d:
            continue
        mn = bounds_2d.get("min", {})
        mx = bounds_2d.get("max", {})
        if "x" not in mn or "z" not in mn:
            continue
        result.append({
            "id": region_id,
            "type": region.get("type", "unknown"),
            "label": region_id,
            "color": _region_color(region_id),
            "bounds": {
                "min_x": mn["x"],
                "min_z": mn["z"],
                "max_x": mx["x"],
                "max_z": mx["z"],
            },
        })
    return result
