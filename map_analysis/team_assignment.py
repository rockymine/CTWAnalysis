"""Team assignment and intra-team symmetry detection.

These are assembly-layer concerns: they combine island geometry (from the
islands step) with XML team/spawn data (from the xml step) to assign
islands to teams and verify intra-team symmetry.

They live here — not in symmetry_analysis — because they require XML data
(teams, spawns) which is a Layer 4 input unavailable during the pure
geometry steps.

Public API:
    assign_islands_to_teams(islands, teams, center_x, center_z, primary_global)
    detect_intra_team_symmetry(islands, center_x, center_z, center_info,
                               global_symmetries, teams)
"""

import numpy as np
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Shapely geometry helpers (used by intra-team polygon splitting)
# ---------------------------------------------------------------------------

def _reflect_shapely_geom_x(geom: Any, center_x: float) -> Any:
    """Reflect a Shapely geometry across x = center_x."""
    from shapely import affinity
    return affinity.affine_transform(geom, [-1, 0, 0, 1, 2 * center_x, 0])


def _reflect_shapely_geom_z(geom: Any, center_z: float) -> Any:
    """Reflect a Shapely geometry across z = center_z.

    Maps z → 2·center_z − z, keeps x unchanged.
    (z is the y-coordinate in Shapely's 2D plane.)
    """
    from shapely import affinity
    return affinity.affine_transform(geom, [1, 0, 0, -1, 0, 2 * center_z])


# ---------------------------------------------------------------------------
# Intra-team axis determination
# ---------------------------------------------------------------------------

def _determine_intra_axis(
    primary_global: dict,
    team_island: dict,
    center_x: float,
    center_z: float,
) -> Optional[str]:
    """Determine the intra-team symmetry axis from the global symmetry type.

    The intra-team axis is the axis that runs *through* each team's territory,
    perpendicular to the axis that *separates* the teams.

    For a 2-team map with:
      - mirror_z (teams separated by Z=center): intra axis is mirror_x
      - mirror_x (teams separated by X=center): intra axis is mirror_z
      - rot_180:  use the team's spawn center to decide which axis is
                  the splitting axis (perpendicular to the team offset)

    Returns "mirror_x" or "mirror_z", or None if undetermined.
    """
    gtype = primary_global["type"]

    if gtype == "mirror_z":
        return "mirror_x"
    if gtype == "mirror_x":
        return "mirror_z"
    if gtype == "rot_180":
        tc = team_island["center"]
        dx = abs(tc[0] - center_x)
        dz = abs(tc[1] - center_z)
        return "mirror_x" if dz > dx else "mirror_z"
    if gtype == "rot_90":
        tc = team_island["center"]
        dx = abs(tc[0] - center_x)
        dz = abs(tc[1] - center_z)
        return "mirror_x" if dz > dx else "mirror_z"

    return None


# ---------------------------------------------------------------------------
# Intra-team polygon splitting and IoU verification
# ---------------------------------------------------------------------------

def _split_polygon_along_axis(
    exterior: list[list[float]],
    axis: str,
    axis_value: float,
    center_info: dict,
) -> tuple[Any, Any]:
    """Split a polygon into two halves along a symmetry axis.

    For even dimensions (2x2 or 2x1/1x2 along this axis) the split falls
    cleanly between two block columns — no ambiguity.

    For odd dimensions (single_block or 2x1/1x2 across this axis) the split
    goes through the center column.  We exclude the center column from both
    halves to keep them equal-sized.

    Args:
        exterior: polygon exterior coordinates
        axis: "mirror_x" (split at x = axis_value) or "mirror_z"
        axis_value: the coordinate value of the split line
        center_info: center classification dict (type, map_width_x, map_width_z)

    Returns:
        (neg_half, pos_half) — Shapely geometries, or (None, None) on failure.
    """
    from shapely.geometry import Polygon, box
    from shapely.validation import make_valid

    try:
        poly = Polygon(exterior)
        if not poly.is_valid:
            poly = make_valid(poly)
        if poly.is_empty:
            return None, None
    except Exception:
        return None, None

    bounds = poly.bounds  # (minx, minz, maxx, maxz)

    center_type = center_info["type"]
    if axis == "mirror_x":
        odd_on_axis = (center_type in ("single_block", "1x2_line"))
    else:
        odd_on_axis = (center_type in ("single_block", "2x1_line"))

    if odd_on_axis:
        strip_lo = int(np.floor(axis_value))
        strip_hi = strip_lo + 1
        if axis == "mirror_x":
            neg_clip = box(bounds[0] - 1, bounds[1] - 1, strip_lo, bounds[3] + 1)
            pos_clip = box(strip_hi, bounds[1] - 1, bounds[2] + 1, bounds[3] + 1)
        else:
            neg_clip = box(bounds[0] - 1, bounds[1] - 1, bounds[2] + 1, strip_lo)
            pos_clip = box(bounds[0] - 1, strip_hi, bounds[2] + 1, bounds[3] + 1)
    else:
        if axis == "mirror_x":
            neg_clip = box(bounds[0] - 1, bounds[1] - 1, axis_value, bounds[3] + 1)
            pos_clip = box(axis_value, bounds[1] - 1, bounds[2] + 1, bounds[3] + 1)
        else:
            neg_clip = box(bounds[0] - 1, bounds[1] - 1, bounds[2] + 1, axis_value)
            pos_clip = box(bounds[0] - 1, axis_value, bounds[2] + 1, bounds[3] + 1)

    try:
        neg_half = poly.intersection(neg_clip)
        pos_half = poly.intersection(pos_clip)
        if neg_half.is_empty:
            neg_half = None
        if pos_half.is_empty:
            pos_half = None
        return neg_half, pos_half
    except Exception:
        return None, None


def _verify_intra_team_symmetry(
    team_islands: list[dict],
    axis: str,
    axis_value: float,
    center_info: dict,
) -> tuple[float, str]:
    """Verify intra-team symmetry by splitting all territory polygons along
    the axis and comparing the two halves via IoU.

    Returns (iou, axis_name).
    """
    from shapely.ops import unary_union

    neg_parts = []
    pos_parts = []

    for isl in team_islands:
        sp = isl.get("simplified_polygon")
        if not sp or not sp.get("exterior"):
            continue
        neg, pos = _split_polygon_along_axis(
            sp["exterior"], axis, axis_value, center_info,
        )
        if neg is not None:
            neg_parts.append(neg)
        if pos is not None:
            pos_parts.append(pos)

    if not neg_parts or not pos_parts:
        return 0.0, axis

    neg_union = unary_union(neg_parts)
    pos_union = unary_union(pos_parts)

    try:
        if axis == "mirror_x":
            reflected = _reflect_shapely_geom_x(neg_union, axis_value)
        else:
            reflected = _reflect_shapely_geom_z(neg_union, axis_value)

        if reflected.is_empty or pos_union.is_empty:
            return 0.0, axis

        intersection = reflected.intersection(pos_union).area
        union_area = reflected.union(pos_union).area
        if union_area < 1e-6:
            return 0.0, axis
        return intersection / union_area, axis
    except Exception:
        return 0.0, axis


# ---------------------------------------------------------------------------
# Canonical coverage check (rot_90 / 4-team maps)
# ---------------------------------------------------------------------------

def _check_canonical_coverage(
    islands: list[dict],
    teams: list[dict],
    team_islands: dict[str, list[dict]],
) -> list[dict]:
    """Check that each team gets exactly 1 island from each canonical group.

    For rot_90 (4-team) maps, intra-team mirror symmetry is not meaningful
    because island shapes are abstract and team territories don't form
    neat axis-aligned quadrants.  Instead we verify that the rotational
    symmetry correctly distributes one island from each canonical group
    to every team.
    """
    from collections import defaultdict

    n_teams = len(teams)

    area_groups = defaultdict(list)
    for isl in islands:
        area_groups[isl["area"]].append(isl["id"])

    canonical_groups = {
        area: set(ids) for area, ids in area_groups.items()
        if len(ids) == n_teams
    }

    total_groups = len(canonical_groups)

    results = []
    for team in teams:
        tid = team["id"]
        t_islands = team_islands.get(tid, [])
        t_ids = {isl["id"] for isl in t_islands}

        covered = 0
        for area, group_ids in canonical_groups.items():
            if len(t_ids & group_ids) == 1:
                covered += 1

        coverage = covered / total_groups if total_groups > 0 else 0.0

        results.append({
            "team": tid,
            "island_count": len(t_islands),
            "island_ids": [i["id"] for i in t_islands],
            "symmetry_detected": coverage >= 1.0,
            "check_type": "canonical_coverage",
            "canonical_groups": total_groups,
            "groups_covered": covered,
            "best_iou": round(coverage, 4),
            "detail": f"Canonical coverage: {covered}/{total_groups} groups",
        })

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assign_islands_to_teams(
    islands: list[dict],
    teams: list[dict],
    center_x: float,
    center_z: float,
    primary_global: dict,
) -> dict[str, list[dict]]:
    """Assign island dicts to teams by explicit team field or geometric fallback.

    First pass: islands that already have a "team" field (set by XML POI
    annotation) are assigned directly.

    Second pass: remaining islands are assigned by proximity to spawn centers
    (3+ teams) or by which side of the symmetry axis they fall on (2 teams).

    Args:
        islands: list of island dicts (same format as islands.json / map_context.json)
        teams: list of team dicts with at least an "id" key
        center_x, center_z: map center coordinates
        primary_global: primary global symmetry dict (keys: "type", ...)

    Returns:
        Dict mapping team_id → list of island dicts.
    """
    team_islands = {t["id"]: [] for t in teams}
    assigned_ids = set()

    # Explicit team assignment from XML POI annotation
    for isl in islands:
        if isl.get("team"):
            team_islands.setdefault(isl["team"], []).append(isl)
            assigned_ids.add(isl["id"])

    unassigned = [isl for isl in islands if isl["id"] not in assigned_ids]

    if len(teams) >= 3:
        spawn_centers = {}
        for isl in islands:
            if isl.get("team") and isl.get("has_spawn"):
                spawn_centers[isl["team"]] = isl["center"]
        for isl in unassigned:
            if not spawn_centers:
                break
            ix, iz = isl["center"]
            best_team = min(
                spawn_centers,
                key=lambda t: (ix - spawn_centers[t][0]) ** 2
                            + (iz - spawn_centers[t][1]) ** 2,
            )
            team_islands[best_team].append(isl)
    elif primary_global["type"] == "rot_180" and len(teams) == 2:
        team_ids = [t["id"] for t in teams]
        for isl in unassigned:
            iz = isl["center"][1]
            if iz < center_z:
                team_islands[team_ids[0]].append(isl)
            else:
                team_islands[team_ids[1]].append(isl)
    elif primary_global["type"] in ("mirror_x", "mirror_z"):
        team_ids = [t["id"] for t in teams]
        for isl in unassigned:
            if primary_global["type"] == "mirror_z":
                val = isl["center"][1]
                ref = center_z
            else:
                val = isl["center"][0]
                ref = center_x
            if val < ref:
                team_islands[team_ids[0]].append(isl)
            elif val > ref:
                team_islands[team_ids[1]].append(isl)

    return team_islands


def detect_intra_team_symmetry(
    islands: list[dict],
    center_x: float,
    center_z: float,
    center_info: dict,
    global_symmetries: list[dict],
    teams: list[dict],
) -> list[dict]:
    """Detect symmetry within each team's territory.

    Strategy depends on global symmetry type:

    - rot_90 (typically 4 teams): Check canonical coverage — each team
      should receive exactly 1 island from each canonical group.

    - rot_180 / mirror (typically 2 teams): Split each team's territory
      along the intra-team axis and compare the two halves via polygon IoU.

    Returns list of per-team symmetry result dicts.
    """
    if not teams:
        return []

    detected = [s for s in global_symmetries if s["detected"]]
    if not detected:
        return []

    primary = max(detected, key=lambda s: s["confidence"])

    team_islands = assign_islands_to_teams(
        islands, teams, center_x, center_z, primary,
    )

    if primary["type"] == "rot_90":
        return _check_canonical_coverage(islands, teams, team_islands)

    results = []
    for team in teams:
        tid = team["id"]
        t_islands = team_islands.get(tid, [])
        if not t_islands:
            results.append({
                "team": tid,
                "island_count": 0,
                "island_ids": [],
                "symmetry_detected": False,
                "detail": "No islands assigned to team",
            })
            continue

        spawn_island = next(
            (i for i in t_islands if i.get("has_spawn")), t_islands[0],
        )
        intra_axis = _determine_intra_axis(primary, spawn_island, center_x, center_z)

        if intra_axis is None:
            results.append({
                "team": tid,
                "island_count": len(t_islands),
                "island_ids": [i["id"] for i in t_islands],
                "symmetry_detected": False,
                "detail": "Could not determine intra-team axis",
            })
            continue

        axis_value = center_x if intra_axis == "mirror_x" else center_z

        iou, axis_name = _verify_intra_team_symmetry(
            t_islands, intra_axis, axis_value, center_info,
        )

        results.append({
            "team": tid,
            "island_count": len(t_islands),
            "island_ids": [i["id"] for i in t_islands],
            "check_type": "mirror_split",
            "intra_axis": intra_axis,
            "axis_value": axis_value,
            "symmetry_detected": iou >= 0.60,
            "best_symmetry_type": intra_axis,
            "best_iou": round(iou, 4),
        })

    return results
