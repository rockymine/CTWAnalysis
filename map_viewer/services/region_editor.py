from __future__ import annotations

from map_viewer.services.regions import apply_coord_update, build_region_dict, build_union_bounds
from map_viewer.services.region_tree import (
    collect_region_subtree_ids,
    find_child_region,
    find_parent_of_child,
    patch_all_embedded_regions,
    remove_inline_children,
    rename_embedded_region,
    rename_in_children,
)


class RegionEditorError(Exception):
    pass


class RegionNotFound(RegionEditorError):
    pass


class RegionConflict(RegionEditorError):
    pass


class InvalidRegionPayload(RegionEditorError):
    pass


SUPPORTED_CREATE_TYPES = {"rectangle", "cuboid", "point", "block", "cylinder", "circle"}


def create_region(data: dict, payload: dict) -> dict:
    """Create a new region and register it in data.

    Returns {"id": region_id}.
    Raises InvalidRegionPayload on bad input, RegionConflict on id clash.
    """
    region_type = payload.get("type", "rectangle")
    if region_type not in SUPPORTED_CREATE_TYPES:
        raise InvalidRegionPayload(f"unsupported type '{region_type}'")

    regions = data.setdefault("regions", {})

    region_id = (payload.get("id") or "").strip()
    if not region_id:
        prefix = region_type if region_type != "rectangle" else "region"
        i = 1
        while f"{prefix}_{i}" in regions:
            i += 1
        region_id = f"{prefix}_{i}"
    elif region_id in regions:
        raise RegionConflict(f"id {region_id!r} already in use")

    try:
        new_region = build_region_dict(region_type, payload, region_id)
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidRegionPayload(f"Missing or invalid field: {exc}") from exc

    regions[region_id] = new_region
    category = payload.get("category", "other")
    data.setdefault("region_categories", {}).setdefault(category, []).append(region_id)
    return {"id": region_id}


def group_regions(data: dict, payload: dict) -> dict:
    """Wrap a set of existing regions in a new union region.

    Returns {"id": union_id, "bounds": {min_x, min_z, max_x, max_z}}.
    Raises InvalidRegionPayload, RegionNotFound, RegionConflict.
    """
    child_ids = [str(cid) for cid in payload.get("child_ids", [])]
    if len(child_ids) < 2:
        raise InvalidRegionPayload("at least 2 regions required")

    regions = data.setdefault("regions", {})

    missing = [cid for cid in child_ids if cid not in regions]
    if missing:
        raise RegionNotFound(f"unknown region(s): {missing}")

    union_id = (payload.get("id") or "").strip()
    if not union_id:
        i = 1
        while f"union_{i}" in regions:
            i += 1
        union_id = f"union_{i}"
    elif union_id in regions:
        raise RegionConflict(f"id {union_id!r} already in use")

    children = [regions[cid] for cid in child_ids]
    bounds_2d, min_x, min_z, max_x, max_z = build_union_bounds(children)

    regions[union_id] = {
        "id": union_id,
        "type": "union",
        "children": children,
        **({"bounds_2d": bounds_2d} if bounds_2d else {}),
    }
    data.setdefault("region_categories", {}).setdefault("other", []).append(union_id)
    return {
        "id": union_id,
        "bounds": {"min_x": min_x, "min_z": min_z, "max_x": max_x, "max_z": max_z},
    }


def remove_from_group(data: dict, region_id: str, payload: dict) -> dict:
    """Remove one child from a union without deleting it.

    The child stays in the top-level regions dict and becomes a visible root.
    Returns {}.
    Raises InvalidRegionPayload, RegionNotFound.
    """
    child_id = str(payload.get("child_id", "")).strip()
    if not child_id:
        raise InvalidRegionPayload("child_id required")
    regions = data.get("regions", {})
    region = regions.get(region_id)
    if region is None:
        raise RegionNotFound(f"region {region_id!r} not found")
    if region.get("type") != "union":
        raise InvalidRegionPayload(f"region {region_id!r} is not a union")
    children = region.get("children", [])
    idx = next((i for i, c in enumerate(children) if c.get("id") == child_id), None)
    if idx is None:
        raise RegionNotFound(f"child {child_id!r} not found in union {region_id!r}")
    children.pop(idx)
    # Ensure the child is visible as a root in case it was never in region_categories
    cats = data.get("region_categories", {})
    if not any(child_id in cat_list for cat_list in cats.values()):
        cats.setdefault("other", []).append(child_id)
    return {}


def set_base_child(data: dict, region_id: str, payload: dict) -> dict:
    """Move a named child to index 0 of a complement's children array.

    Returns {}.
    Raises InvalidRegionPayload, RegionNotFound.
    """
    child_id = str(payload.get("child_id", "")).strip()
    if not child_id:
        raise InvalidRegionPayload("child_id required")
    regions = data.get("regions", {})
    region = regions.get(region_id)
    if region is None:
        raise RegionNotFound(f"region {region_id!r} not found")
    if region.get("type") != "complement":
        raise InvalidRegionPayload(f"region {region_id!r} is not a complement")
    children = region.get("children", [])
    idx = next((i for i, c in enumerate(children) if c.get("id") == child_id), None)
    if idx is None:
        raise RegionNotFound(f"child {child_id!r} not found in complement {region_id!r}")
    if idx != 0:
        children.insert(0, children.pop(idx))
    return {}


def ungroup_region(data: dict, payload: dict) -> dict:
    """Dissolve a union: remove it and expose its children as top-level regions.

    Returns {"child_ids": [...]}.
    Raises InvalidRegionPayload, RegionNotFound.
    """
    region_id = str(payload.get("region_id", "")).strip()
    if not region_id:
        raise InvalidRegionPayload("region_id required")

    regions = data.get("regions", {})
    if region_id not in regions:
        raise RegionNotFound(f"region {region_id!r} not found")

    union = regions[region_id]
    if union.get("type") != "union":
        raise InvalidRegionPayload(f"region {region_id!r} is not a union")

    children = union.get("children", [])
    child_ids = []
    for child in children:
        child_id = (child.get("id") or "").strip()
        if not child_id:
            i = 1
            while f"region_{i}" in regions:
                i += 1
            child_id = f"region_{i}"
            child["id"] = child_id
        if child_id not in regions:
            regions[child_id] = child
        child_ids.append(child_id)

    del regions[region_id]
    for cat_list in data.get("region_categories", {}).values():
        if region_id in cat_list:
            cat_list.remove(region_id)
            break

    return {"child_ids": child_ids}


def delete_region(data: dict, region_id: str) -> dict:
    """Remove a region (top-level or inline child) from data.

    Returns a snapshot dict suitable for passing to restore_region.
    Raises RegionNotFound if region_id cannot be located anywhere.
    """
    regions = data.get("regions", {})

    if region_id in regions:
        subtree_ids = collect_region_subtree_ids(regions, region_id)

        category = "other"
        for cat_name, cat_list in data.get("region_categories", {}).items():
            if region_id in cat_list:
                category = cat_name
                break

        region_entries = {rid: regions[rid] for rid in subtree_ids if rid in regions}

        subtree_set = set(subtree_ids)
        for rid in subtree_ids:
            regions.pop(rid, None)
        for cat_list in data.get("region_categories", {}).values():
            cat_list[:] = [rid for rid in cat_list if rid not in subtree_set]
        remove_inline_children(regions, subtree_set)

        return {
            "snapshot": {
                "root_id":        region_id,
                "category":       category,
                "region_entries": region_entries,
            },
        }

    found = find_parent_of_child(regions, region_id)
    if found is None:
        raise RegionNotFound(f"region {region_id!r} not found")

    parent_dict, child_dict, child_index = found
    remove_inline_children(regions, {region_id})
    return {
        "snapshot": {
            "root_id":        region_id,
            "category":       None,
            "parent_id":      parent_dict.get("id"),
            "child_index":    child_index,
            "region_entries": {region_id: child_dict},
        },
    }


def restore_region(data: dict, snapshot: dict) -> dict:
    """Restore a previously deleted region from its snapshot.

    Returns {"id": root_id}.
    Raises InvalidRegionPayload on malformed snapshot, RegionNotFound if the
    parent is missing, RegionConflict if target ids are already occupied.
    """
    root_id        = snapshot.get("root_id", "")
    category       = snapshot.get("category", "other")
    region_entries = snapshot.get("region_entries", {})

    if not root_id or not region_entries:
        raise InvalidRegionPayload("invalid snapshot")

    regions = data.setdefault("regions", {})

    parent_id = snapshot.get("parent_id")
    if parent_id is not None:
        parent_dict = regions.get(parent_id)
        if parent_dict is None:
            raise RegionNotFound(f"parent region {parent_id!r} not found")
        child_dict  = region_entries.get(root_id)
        child_index = snapshot.get("child_index", 0)
        children = parent_dict.setdefault("children", [])
        children.insert(child_index, child_dict)
        return {"id": root_id}

    conflicts = [rid for rid in region_entries if rid in regions]
    if conflicts:
        raise RegionConflict(f"id(s) already in use: {conflicts}")

    regions.update(region_entries)
    data.setdefault("region_categories", {}).setdefault(category, []).append(root_id)
    return {"id": root_id}


def patch_region(data: dict, region_id: str, payload: dict) -> dict:
    """Apply id rename, bounds, and/or coords update to a region.

    Returns {"bounds": {min_x, min_z, max_x, max_z}} when bounds changed,
    otherwise {}.
    Raises InvalidRegionPayload on empty payload, RegionNotFound, RegionConflict.
    """
    bounds = payload.get("bounds") if isinstance(payload.get("bounds"), dict) else None
    coords = payload.get("coords") if isinstance(payload.get("coords"), dict) else None
    if not payload.get("id") and bounds is None and coords is None:
        raise InvalidRegionPayload("provide 'id', 'bounds', or 'coords'")

    regions = data.get("regions", {})

    region = regions.get(region_id)
    is_top_level = region is not None
    if not is_top_level:
        region = find_child_region(regions, region_id)
        if region is None:
            raise RegionNotFound(f"region {region_id!r} not found")

    if is_top_level:
        new_id = (payload.get("id") or "").strip()
        if new_id and new_id != region_id:
            if new_id in regions:
                raise RegionConflict(f"id {new_id!r} already in use")
            regions[new_id] = regions.pop(region_id)
            regions[new_id]["id"] = new_id
            for cat_list in data.get("region_categories", {}).values():
                for i, rid in enumerate(cat_list):
                    if rid == region_id:
                        cat_list[i] = new_id
            for r in regions.values():
                rename_in_children(r, region_id, new_id)
            for container_key in ("spawns", "wools"):
                rename_embedded_region(data.get(container_key, []), region_id, new_id)
            obs = data.get("observer_spawn")
            if obs:
                rename_embedded_region([obs], region_id, new_id)
            region_id = new_id
            region = regions[region_id]

    updated_bounds_2d = None
    if bounds:
        updated_bounds_2d = {
            "min": {"x": bounds["min_x"], "z": bounds["min_z"]},
            "max": {"x": bounds["max_x"], "z": bounds["max_z"]},
        }
        region["bounds_2d"] = updated_bounds_2d
        if is_top_level:
            patch_all_embedded_regions(data, region_id, updated_bounds_2d)

    if coords:
        region_type = region.get("type", "")
        updated_bounds_2d = apply_coord_update(region, region_type, coords)
        if updated_bounds_2d and is_top_level:
            patch_all_embedded_regions(data, region_id, updated_bounds_2d)

    if updated_bounds_2d:
        b = updated_bounds_2d
        return {"bounds": {
            "min_x": b["min"]["x"], "min_z": b["min"]["z"],
            "max_x": b["max"]["x"], "max_z": b["max"]["z"],
        }}
    return {}
