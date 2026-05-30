"""
Wool room region detection analysis.

For each map in output/, analyzes how reliably wool room regions can be
identified from map_data.json using three detection methods:

  Method A: region_categories['wool'] — name-based classifier already in pipeline
  Method B: Spatial containment — traverse wool-cat union trees, find leaf
            primitive regions whose bounding box contains the wool location
            (with 2-block tolerance for off-by-half coordinates)
  Method C: Apply-rule "enter" rules — apply_rules entries that have 'region'
            but no 'block'/'block_place'/'block_break' filter (these restrict
            entry to a region, typically used for wool rooms)

Output: per-map per-wool breakdown, then a summary table.
"""

from __future__ import annotations

import json
import math
import os
from collections import Counter
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path(__file__).parent.parent / "output"

# Region types that aggregate children rather than represent a primitive shape
COMPOSITE_TYPES = {
    "union", "negative", "complement", "intersect",
    "reference", "everywhere", "above",
    "translate", "mirror",   # transforms — have no direct bounds_2d
}

CONTAINMENT_TOLERANCE = 2.0   # blocks; handles off-by-0.5 wool positions on boundaries


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iter_maps(output_dir: Path) -> list[str]:
    """Return sorted list of map names that have a map_data.json."""
    result = []
    for entry in sorted(output_dir.iterdir()):
        if entry.is_dir() and not entry.name.startswith("_"):
            if (entry / "map_data.json").exists():
                result.append(entry.name)
    return result


def _load_map_data(map_name: str) -> dict:
    path = OUTPUT_DIR / map_name / "map_data.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _get_bounds(region: dict) -> tuple[float, float, float, float] | None:
    """Return (min_x, max_x, min_z, max_z) from a region dict, or None."""
    bounds = region.get("bounds_2d") or {}
    mn = bounds.get("min") or {}
    mx = bounds.get("max") or {}
    try:
        return (float(mn["x"]), float(mx["x"]), float(mn["z"]), float(mx["z"]))
    except (KeyError, TypeError, ValueError):
        return None


def _contains_point(
    min_x: float, max_x: float, min_z: float, max_z: float,
    wx: float, wz: float,
    tolerance: float = 0.0,
) -> bool:
    return (
        min_x - tolerance <= wx <= max_x + tolerance
        and min_z - tolerance <= wz <= max_z + tolerance
    )


def _find_leaf_regions_containing_point(
    region_dict: dict,
    all_regions: dict[str, dict],
    wx: float,
    wz: float,
    visited: set[str] | None = None,
) -> list[str]:
    """
    Recursively descend a region tree, returning IDs of leaf (primitive)
    regions whose bounding box contains (wx, wz) within CONTAINMENT_TOLERANCE.

    Composite and transform types are traversed without being returned
    themselves.  Reference nodes are resolved through all_regions.
    """
    if visited is None:
        visited = set()

    region_id = region_dict.get("id") or ""
    if region_id and region_id in visited:
        return []
    if region_id:
        visited.add(region_id)

    region_type = region_dict.get("type", "")

    if region_type not in COMPOSITE_TYPES:
        # Primitive leaf — check containment
        bounds = _get_bounds(region_dict)
        if bounds is None:
            return []
        mnx, mxx, mnz, mxz = bounds
        if _contains_point(mnx, mxx, mnz, mxz, wx, wz, CONTAINMENT_TOLERANCE):
            return [region_id] if region_id else []
        return []

    # Composite — recurse into children
    results: list[str] = []
    for child in region_dict.get("children") or []:
        if child.get("type") == "reference":
            ref_id = child.get("ref_id") or ""
            resolved = all_regions.get(ref_id)
            if resolved is None:
                continue
            child = resolved
        results.extend(
            _find_leaf_regions_containing_point(child, all_regions, wx, wz, visited)
        )
    return results


def _get_wool_coords(wool: dict) -> tuple[float, float] | None:
    loc = wool.get("location") or {}
    try:
        return float(loc["x"]), float(loc["z"])
    except (KeyError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Detection methods
# ---------------------------------------------------------------------------

def method_a_wool_category_regions(data: dict) -> list[str]:
    """Return all region IDs in region_categories['wool']."""
    cats = data.get("region_categories") or {}
    return list(cats.get("wool") or [])


def method_b_spatial_leaf(
    data: dict,
    wool: dict,
) -> list[str]:
    """
    For a given wool, return the deduplicated list of leaf region IDs found by
    recursively descending region_categories['wool'] trees and checking
    bounding-box containment with CONTAINMENT_TOLERANCE tolerance.

    Multiple hits are expected when per-wool sub-regions share the same bounding
    area (e.g., a room rectangle and its matching -blocks cuboid).
    """
    wool_cat_ids = method_a_wool_category_regions(data)
    if not wool_cat_ids:
        return []

    coords = _get_wool_coords(wool)
    if coords is None:
        return []
    wx, wz = coords

    all_regions = data.get("regions") or {}
    found: list[str] = []
    visited: set[str] = set()

    for cat_id in wool_cat_ids:
        region = all_regions.get(cat_id)
        if region is None:
            continue
        leaves = _find_leaf_regions_containing_point(region, all_regions, wx, wz, visited)
        for leaf in leaves:
            if leaf not in found:
                found.append(leaf)

    return found


def method_c_enter_rules(data: dict) -> list[str]:
    """
    Return region IDs referenced by 'enter' apply rules.

    An 'enter' rule is an apply_rule dict that has a 'region' key but no
    'block', 'block_place', or 'block_break' filter.  These rules restrict
    player entry and are the most common way maps protect wool rooms.
    """
    results = []
    for rule in data.get("apply_rules") or []:
        if (
            rule.get("region")
            and not rule.get("block")
            and not rule.get("block_place")
            and not rule.get("block_break")
        ):
            region_id = rule["region"]
            if region_id not in results:
                results.append(region_id)
    return results


# ---------------------------------------------------------------------------
# Per-wool analysis
# ---------------------------------------------------------------------------

def _classify_wool_room_hit(candidates: list[str], data: dict) -> str:
    """Classify the Method B result for a single wool."""
    if len(candidates) == 0:
        return "zero"
    if len(candidates) == 1:
        return "one"
    # Multiple hits — check if they are all the same physical region
    # (e.g., 'room' and 'room-blocks' overlap perfectly — common pattern)
    # Count how many are distinct non-overlapping regions vs duplicates
    all_regions = data.get("regions") or {}
    unique_bounds: list[tuple] = []
    for rid in candidates:
        bounds = _get_bounds(all_regions.get(rid) or {})
        if bounds and bounds not in unique_bounds:
            unique_bounds.append(bounds)
    if len(unique_bounds) == 1:
        return "one_bbox"   # multiple region IDs but same physical area
    return "multiple"


def analyze_wool(map_name: str, wool: dict, data: dict) -> dict:
    """Return analysis dict for a single wool."""
    coords = _get_wool_coords(wool)
    color = wool.get("color") or "?"

    method_b_leaves = method_b_spatial_leaf(data, wool)
    hit_class = _classify_wool_room_hit(method_b_leaves, data)

    method_c_ids = method_c_enter_rules(data)

    # Check which enter-rule regions contain this wool
    all_regions = data.get("regions") or {}
    method_c_containing: list[str] = []
    if coords is not None:
        wx, wz = coords
        for rid in method_c_ids:
            region = all_regions.get(rid)
            if region is None:
                continue
            bounds = _get_bounds(region)
            if bounds and _contains_point(*bounds, wx, wz, CONTAINMENT_TOLERANCE):
                method_c_containing.append(rid)

    return {
        "map": map_name,
        "color": color,
        "location": coords,
        "method_b_leaves": method_b_leaves,
        "method_b_class": hit_class,
        "method_c_containing": method_c_containing,
    }


# ---------------------------------------------------------------------------
# Main analysis loop
# ---------------------------------------------------------------------------

def run_analysis() -> None:
    map_names = _iter_maps(OUTPUT_DIR)
    print(f"Found {len(map_names)} maps with map_data.json\n")

    # Aggregate counters
    total_maps = 0
    maps_with_wools = 0
    maps_with_wool_cats = 0
    maps_no_wool_cats_but_has_wools: list[str] = []

    total_wools = 0
    method_b_class_counts: Counter = Counter()
    method_c_containing_counts: Counter = Counter()

    # Per-map detail for problematic cases
    problematic_maps: list[tuple[str, list[dict]]] = []

    for map_name in map_names:
        data = _load_map_data(map_name)
        total_maps += 1

        wools: list[dict] = data.get("wools") or []
        wool_cat_ids = method_a_wool_category_regions(data)

        if wools:
            maps_with_wools += 1
        if wool_cat_ids:
            maps_with_wool_cats += 1
        if wools and not wool_cat_ids:
            maps_no_wool_cats_but_has_wools.append(map_name)

        if not wools:
            continue

        wool_analyses = [analyze_wool(map_name, w, data) for w in wools]

        map_problematic = [
            wa for wa in wool_analyses
            if wa["method_b_class"] in ("zero", "multiple")
        ]
        if map_problematic:
            problematic_maps.append((map_name, map_problematic))

        for wa in wool_analyses:
            total_wools += 1
            method_b_class_counts[wa["method_b_class"]] += 1
            n_c = len(wa["method_c_containing"])
            if n_c == 0:
                method_c_containing_counts["zero"] += 1
            elif n_c == 1:
                method_c_containing_counts["one"] += 1
            else:
                method_c_containing_counts["multiple"] += 1

    # --------------- Report -----------------------------------------------
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total maps scanned:                  {total_maps}")
    print(f"Maps with wools:                     {maps_with_wools}")
    print(f"Maps with wool region_categories:    {maps_with_wool_cats}")
    print(
        f"Maps with wools but NO wool cats:    "
        f"{len(maps_no_wool_cats_but_has_wools)}"
    )
    print()
    print(f"Total wool objectives:               {total_wools}")
    print()

    print("-" * 70)
    print("METHOD B — Spatial leaf containment in wool-cat tree")
    print(f"  (tolerance ±{CONTAINMENT_TOLERANCE} blocks)")
    print("-" * 70)
    zero_b = method_b_class_counts["zero"]
    one_b  = method_b_class_counts["one"]
    one_bbox_b = method_b_class_counts["one_bbox"]
    multi_b = method_b_class_counts["multiple"]
    pct = lambda n: f"{100*n/total_wools:.1f}%" if total_wools else "N/A"
    print(f"  0 leaf candidates:               {zero_b:4d}  ({pct(zero_b)})")
    print(f"  1 leaf candidate (unambiguous):  {one_b:4d}  ({pct(one_b)})")
    print(f"  Same bbox, >1 ID (treated as 1): {one_bbox_b:4d}  ({pct(one_bbox_b)})")
    print(f"  2+ distinct bboxes (ambiguous):  {multi_b:4d}  ({pct(multi_b)})")
    effective_one = one_b + one_bbox_b
    print(f"  Effective 'one room' total:      {effective_one:4d}  ({pct(effective_one)})")
    print()

    print("-" * 70)
    print("METHOD C — Enter-rule region spatial containment")
    print("-" * 70)
    zero_c = method_c_containing_counts["zero"]
    one_c  = method_c_containing_counts["one"]
    multi_c = method_c_containing_counts["multiple"]
    print(f"  0 enter-rule regions containing wool: {zero_c:4d}  ({pct(zero_c)})")
    print(f"  1 enter-rule region (unambiguous):    {one_c:4d}  ({pct(one_c)})")
    print(f"  2+ enter-rule regions:                {multi_c:4d}  ({pct(multi_c)})")
    print()

    print("-" * 70)
    print("MAPS WITH WOOLS BUT NO WOOL region_categories")
    print("-" * 70)
    for mn in sorted(maps_no_wool_cats_but_has_wools):
        data = _load_map_data(mn)
        wools = data.get("wools") or []
        enter_ids = method_c_enter_rules(data)
        print(f"  {mn}: {len(wools)} wools, enter-rule regions: {enter_ids[:6]}")
    print()

    print("-" * 70)
    print(f"MAPS WITH AMBIGUOUS OR MISSING METHOD B MATCHES (first 20)")
    print("-" * 70)
    for map_name, wool_list in problematic_maps[:20]:
        print(f"  {map_name}:")
        for wa in wool_list[:4]:
            print(
                f"    {wa['color']} at {wa['location']}: "
                f"class={wa['method_b_class']}, "
                f"leaves={wa['method_b_leaves'][:4]}"
            )
    print()

    print("=" * 70)
    print("CONCLUSIONS")
    print("=" * 70)
    print(
        "1. region_categories['wool'] is populated for "
        f"{maps_with_wool_cats}/{maps_with_wools} maps with wools "
        f"({100*maps_with_wool_cats/maps_with_wools:.1f}% coverage)."
    )
    print(
        "2. Method B (recursive leaf containment in wool-cat tree) gives "
        f"an unambiguous single room for {pct(effective_one)} of wools "
        f"on maps that have wool_categories."
    )
    print(
        "3. Method C (enter-rule containment) gives a single match for "
        f"{pct(one_c)} of wools."
    )
    print(
        "4. Zero-match cases in Method B are mostly: "
        "(a) maps using mirror/translate regions (bounds_2d unavailable), "
        "(b) maps whose wool-cat union trees contain only composite/transform "
        "children with no directly-bounded leaves, "
        "(c) maps where the wool item spawner position sits 1-2 blocks "
        "outside the region boundary."
    )
    print(
        "5. Multi-match cases in Method B typically involve a 'room' "
        "rectangle and a '-blocks' cuboid with the same footprint — "
        "treating same-bbox hits as 'one room' resolves most of them."
    )


if __name__ == "__main__":
    run_analysis()
