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

    Synthetic ids mirror region_encoder._encode_node logic:
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