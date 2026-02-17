"""
Builder for symmetry analysis results.

Analyzes the geometric layout of a map from map_context.json to determine
which symmetry types are present (mirror, 180° rotation, 90° rotation),
both globally and within each team's territory.

Coordinate convention:
    - Bounding box: (min_x, max_x, min_z, max_z)
    - Block at integer (x, z) occupies [x, x+1) x [z, z+1), centroid at (x+0.5, z+0.5)
    - Map center is computed from bounding box midpoint in block-centroid space
"""

import json
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Center classification
# ---------------------------------------------------------------------------

def classify_center(bbox: Tuple[float, float, float, float]) -> Dict:
    """Classify the geometric map center based on bounding box dimensions.

    In Minecraft's block coordinate system, a block at integer (x, z) occupies
    the area [x, x+1) x [z, z+1).  The bounding box stores min/max block indices,
    so the full extent is [min_x, max_x+1) x [min_z, max_z+1).

    The center type depends on whether each dimension spans an odd or even
    number of blocks:
        - odd x odd   -> single block center
        - even x odd  -> 2x1 center line (horizontal)
        - odd x even  -> 1x2 center line (vertical)
        - even x even -> 2x2 center area

    Returns dict with keys: center_x, center_z, type, description, blocks
    """
    min_x, max_x, min_z, max_z = bbox
    # max_x/max_z in bbox are already +1 from the raw block coords
    # (see build_map_context: max + 1), so width = max_x - min_x
    width_x = max_x - min_x
    width_z = max_z - min_z

    center_x = (min_x + max_x) / 2.0
    center_z = (min_z + max_z) / 2.0

    odd_x = (int(width_x) % 2 == 1)
    odd_z = (int(width_z) % 2 == 1)

    if odd_x and odd_z:
        center_type = "single_block"
        description = "Single block center"
        # The center block index
        bx = int(center_x - 0.5)
        bz = int(center_z - 0.5)
        blocks = [(bx, bz)]
    elif not odd_x and odd_z:
        center_type = "2x1_line"
        description = "2x1 center line (along X axis)"
        bx1 = int(center_x - 1)
        bx2 = int(center_x)
        bz = int(center_z - 0.5)
        blocks = [(bx1, bz), (bx2, bz)]
    elif odd_x and not odd_z:
        center_type = "1x2_line"
        description = "1x2 center line (along Z axis)"
        bx = int(center_x - 0.5)
        bz1 = int(center_z - 1)
        bz2 = int(center_z)
        blocks = [(bx, bz1), (bx, bz2)]
    else:
        center_type = "2x2_area"
        description = "2x2 center area"
        bx1 = int(center_x - 1)
        bx2 = int(center_x)
        bz1 = int(center_z - 1)
        bz2 = int(center_z)
        blocks = [(bx1, bz1), (bx2, bz1), (bx1, bz2), (bx2, bz2)]

    return {
        "center_x": center_x,
        "center_z": center_z,
        "type": center_type,
        "description": description,
        "blocks": blocks,
        "map_width_x": int(width_x),
        "map_width_z": int(width_z),
    }


# ---------------------------------------------------------------------------
# Island pairing via canonical keys
# ---------------------------------------------------------------------------

def _build_canonical_pairs(islands: List[Dict]) -> List[Tuple[Dict, Dict]]:
    """Group islands by area to find potential symmetric pairs.

    Islands with the same area are candidates for symmetric pairing.
    Returns list of (island_a, island_b) tuples.
    """
    from collections import defaultdict
    by_area = defaultdict(list)
    for isl in islands:
        by_area[isl["area"]].append(isl)

    pairs = []
    for area, group in by_area.items():
        if len(group) == 2:
            pairs.append((group[0], group[1]))
        elif len(group) == 4:
            # For 4-team maps: pair all combinations
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    pairs.append((group[i], group[j]))
    return pairs


# ---------------------------------------------------------------------------
# Transform detection between two islands
# ---------------------------------------------------------------------------

def _detect_pair_transform(
    a: Dict, b: Dict,
    center_x: float, center_z: float,
    tolerance: float = 2.0,
) -> List[str]:
    """Detect which global transforms map island A's center to island B's center.

    Tests:
        - mirror_x: reflection across the vertical axis (x = center_x)
        - mirror_z: reflection across the horizontal axis (z = center_z)
        - rot_180:  180-degree rotation around (center_x, center_z)
        - rot_90:   90-degree rotation around (center_x, center_z)

    Returns list of transform names that match within tolerance.
    """
    ax, az = a["center"]
    bx, bz = b["center"]

    transforms = []

    # Mirror across X = center_x: (x, z) -> (2*cx - x, z)
    mx = 2 * center_x - ax
    mz = az
    if abs(mx - bx) < tolerance and abs(mz - bz) < tolerance:
        transforms.append("mirror_x")

    # Mirror across Z = center_z: (x, z) -> (x, 2*cz - z)
    mx = ax
    mz = 2 * center_z - az
    if abs(mx - bx) < tolerance and abs(mz - bz) < tolerance:
        transforms.append("mirror_z")

    # 180-degree rotation: (x, z) -> (2*cx - x, 2*cz - z)
    rx = 2 * center_x - ax
    rz = 2 * center_z - az
    if abs(rx - bx) < tolerance and abs(rz - bz) < tolerance:
        transforms.append("rot_180")

    # 90-degree rotation: (x, z) -> (cx + (z - cz), cz - (x - cx))
    # = (cx + az - cz, cz - ax + cx)
    r90x = center_x + (az - center_z)
    r90z = center_z - (ax - center_x)
    if abs(r90x - bx) < tolerance and abs(r90z - bz) < tolerance:
        transforms.append("rot_90")

    # 270-degree rotation (= 90 CW): (x, z) -> (cx - (z - cz), cz + (x - cx))
    r270x = center_x - (az - center_z)
    r270z = center_z + (ax - center_x)
    if abs(r270x - bx) < tolerance and abs(r270z - bz) < tolerance:
        transforms.append("rot_270")

    return transforms


# ---------------------------------------------------------------------------
# Polygon-based symmetry verification
# ---------------------------------------------------------------------------

def _reflect_polygon_x(poly_coords: List[List[float]], center_x: float) -> np.ndarray:
    """Reflect polygon coordinates across x = center_x."""
    pts = np.array(poly_coords)
    pts[:, 0] = 2 * center_x - pts[:, 0]
    return pts


def _reflect_polygon_z(poly_coords: List[List[float]], center_z: float) -> np.ndarray:
    """Reflect polygon coordinates across z = center_z."""
    pts = np.array(poly_coords)
    pts[:, 1] = 2 * center_z - pts[:, 1]
    return pts


def _rotate_polygon_180(poly_coords: List[List[float]], cx: float, cz: float) -> np.ndarray:
    """Rotate polygon coordinates 180 degrees around (cx, cz)."""
    pts = np.array(poly_coords)
    pts[:, 0] = 2 * cx - pts[:, 0]
    pts[:, 1] = 2 * cz - pts[:, 1]
    return pts


def _rotate_polygon_90(poly_coords: List[List[float]], cx: float, cz: float) -> np.ndarray:
    """Rotate polygon coordinates 90 degrees CCW around (cx, cz)."""
    pts = np.array(poly_coords)
    dx = pts[:, 0] - cx
    dz = pts[:, 1] - cz
    new_pts = np.empty_like(pts)
    new_pts[:, 0] = cx + dz
    new_pts[:, 1] = cz - dx
    return new_pts


def _polygon_iou(poly_a_coords, poly_b_coords) -> float:
    """Compute IoU (Intersection over Union) between two polygons using Shapely.

    Returns 0.0 on any error or degenerate geometry.
    """
    try:
        from shapely.geometry import Polygon
        from shapely.validation import make_valid

        pa = Polygon(poly_a_coords)
        pb = Polygon(poly_b_coords)

        if not pa.is_valid:
            pa = make_valid(pa)
        if not pb.is_valid:
            pb = make_valid(pb)

        if pa.is_empty or pb.is_empty:
            return 0.0

        intersection = pa.intersection(pb).area
        union = pa.union(pb).area

        if union < 1e-6:
            return 0.0
        return intersection / union
    except Exception:
        return 0.0


def _verify_polygon_symmetry(
    islands: List[Dict],
    center_x: float,
    center_z: float,
    transform_name: str,
    iou_threshold: float = 0.85,
) -> Tuple[float, List[Dict]]:
    """Verify a symmetry type using polygon geometry (IoU).

    Applies the specified transform to all island polygons and checks
    whether the transformed set matches the original set.

    Returns (average_iou, list of per-pair match details).
    """
    # Collect all polygons with their island IDs
    polys = []
    for isl in islands:
        sp = isl.get("simplified_polygon")
        if sp and sp.get("exterior"):
            polys.append({
                "island_id": isl["id"],
                "exterior": sp["exterior"],
                "area": isl["area"],
                "center": isl["center"],
            })

    if not polys:
        return 0.0, []

    # Build Shapely polygons for originals
    from shapely.geometry import Polygon, MultiPolygon
    from shapely.validation import make_valid
    from shapely.ops import unary_union

    original_shapes = []
    for p in polys:
        try:
            shape = Polygon(p["exterior"])
            if not shape.is_valid:
                shape = make_valid(shape)
            if not shape.is_empty:
                original_shapes.append(shape)
        except Exception:
            continue

    if not original_shapes:
        return 0.0, []

    original_union = unary_union(original_shapes)

    # Transform all polygons
    transformed_shapes = []
    for p in polys:
        ext = p["exterior"]
        if transform_name == "mirror_x":
            t_ext = _reflect_polygon_x(ext, center_x).tolist()
        elif transform_name == "mirror_z":
            t_ext = _reflect_polygon_z(ext, center_z).tolist()
        elif transform_name == "rot_180":
            t_ext = _rotate_polygon_180(ext, center_x, center_z).tolist()
        elif transform_name in ("rot_90", "rot_270"):
            if transform_name == "rot_90":
                t_ext = _rotate_polygon_90(ext, center_x, center_z).tolist()
            else:
                # 270 = three 90s
                coords = _rotate_polygon_90(ext, center_x, center_z)
                coords = _rotate_polygon_90(coords.tolist(), center_x, center_z)
                t_ext = _rotate_polygon_90(coords.tolist(), center_x, center_z).tolist()
        else:
            continue

        try:
            shape = Polygon(t_ext)
            if not shape.is_valid:
                shape = make_valid(shape)
            if not shape.is_empty:
                transformed_shapes.append(shape)
        except Exception:
            continue

    if not transformed_shapes:
        return 0.0, []

    transformed_union = unary_union(transformed_shapes)

    # Compute IoU of the whole-map polygon sets
    try:
        intersection = original_union.intersection(transformed_union).area
        union_area = original_union.union(transformed_union).area
        if union_area < 1e-6:
            return 0.0, []
        global_iou = intersection / union_area
    except Exception:
        return 0.0, []

    return global_iou, []


# ---------------------------------------------------------------------------
# Island pair transform aggregation
# ---------------------------------------------------------------------------

def _aggregate_pair_transforms(
    islands: List[Dict],
    center_x: float,
    center_z: float,
    tolerance: float = 3.0,
) -> Dict:
    """Aggregate observed transforms across all canonical island pairs.

    Returns dict with:
        - pairs: list of pair info dicts
        - transform_counts: {transform_name: count}
        - total_pairs: number of pairs analyzed
    """
    pairs = _build_canonical_pairs(islands)

    transform_counts = {}
    pair_details = []

    for a, b in pairs:
        transforms = _detect_pair_transform(a, b, center_x, center_z, tolerance)
        for t in transforms:
            transform_counts[t] = transform_counts.get(t, 0) + 1

        pair_details.append({
            "island_a": a["id"],
            "island_b": b["id"],
            "area": a["area"],
            "transforms": transforms,
        })

    return {
        "pairs": pair_details,
        "transform_counts": transform_counts,
        "total_pairs": len(pairs),
    }


# ---------------------------------------------------------------------------
# Global symmetry detection
# ---------------------------------------------------------------------------

def _detect_global_symmetry(
    islands: List[Dict],
    center_x: float,
    center_z: float,
    pair_analysis: Dict,
) -> List[Dict]:
    """Detect global symmetry types combining pair transforms and polygon IoU.

    Pair support is computed with symmetry-group awareness:
      - rot_180 = mirror_x ∘ mirror_z, so when both mirrors have high IoU,
        mirror pairs also count as rot_180 evidence.
      - rot_90 implies rot_180 (and rot_270 is its inverse), so rot_180
        pairs also count as rot_90 evidence when IoU confirms.

    Returns list of detected symmetry dicts, each with:
        - type: symmetry type name
        - pair_support: fraction of pairs supporting this transform
        - polygon_iou: IoU of full map polygon under this transform
        - confidence: combined confidence score
    """
    n_pairs = pair_analysis["total_pairs"]
    counts = pair_analysis["transform_counts"]
    pairs = pair_analysis["pairs"]

    candidates = [
        ("mirror_x", "Mirror across vertical axis (X = center)"),
        ("mirror_z", "Mirror across horizontal axis (Z = center)"),
        ("rot_180", "180-degree rotational symmetry"),
        ("rot_90", "90-degree rotational symmetry"),
    ]

    # First pass: compute polygon IoU for all candidates
    ious = {}
    for sym_type, _ in candidates:
        iou, _ = _verify_polygon_symmetry(islands, center_x, center_z, sym_type)
        ious[sym_type] = iou

    GROUP_IOU_THRESHOLD = 0.85

    # Second pass: compute group-aware pair support and confidence
    results = []
    for sym_type, description in candidates:
        iou = ious[sym_type]

        if sym_type == "rot_90":
            # Must have both rot_90 and rot_270 present
            if counts.get("rot_90", 0) == 0 or counts.get("rot_270", 0) == 0:
                pair_support = 0.0
            else:
                # rot_270 is the inverse, rot_180 is rot_90 applied twice
                compatible = {"rot_90", "rot_270"}
                if ious.get("rot_180", 0) >= GROUP_IOU_THRESHOLD:
                    compatible.add("rot_180")
                if (ious.get("mirror_x", 0) >= GROUP_IOU_THRESHOLD and
                        ious.get("mirror_z", 0) >= GROUP_IOU_THRESHOLD):
                    compatible.update(["mirror_x", "mirror_z"])
                supporting = sum(
                    1 for p in pairs if compatible & set(p["transforms"])
                )
                pair_support = supporting / n_pairs if n_pairs > 0 else 0.0

        elif sym_type == "rot_180":
            # mirror_x + mirror_z = rot_180, so mirror pairs are evidence
            compatible = {"rot_180"}
            if (ious.get("mirror_x", 0) >= GROUP_IOU_THRESHOLD and
                    ious.get("mirror_z", 0) >= GROUP_IOU_THRESHOLD):
                compatible.update(["mirror_x", "mirror_z"])
            supporting = sum(
                1 for p in pairs if compatible & set(p["transforms"])
            )
            pair_support = supporting / n_pairs if n_pairs > 0 else 0.0

        else:
            # mirror_x / mirror_z: count direct matches only
            pair_count = counts.get(sym_type, 0)
            pair_support = pair_count / n_pairs if n_pairs > 0 else 0.0

        # Combined confidence: weighted average of pair and polygon signals
        if n_pairs > 0:
            confidence = 0.4 * pair_support + 0.6 * iou
        else:
            confidence = iou

        results.append({
            "type": sym_type,
            "description": description,
            "pair_support": round(pair_support, 3),
            "polygon_iou": round(iou, 4),
            "confidence": round(confidence, 3),
            "detected": confidence >= 0.60,
        })

    return results


# ---------------------------------------------------------------------------
# Intra-team symmetry
# ---------------------------------------------------------------------------

def _determine_intra_axis(
    primary_global: Dict,
    team_island: Dict,
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
        # The team's spawn island sits on one side of center.
        # Determine which coordinate has the larger offset from center —
        # that's the axis separating teams, so the perpendicular is the
        # intra-team axis.
        tc = team_island["center"]
        dx = abs(tc[0] - center_x)
        dz = abs(tc[1] - center_z)
        return "mirror_x" if dz > dx else "mirror_z"
    if gtype == "rot_90":
        # For 4-team maps the intra-team axis depends on team position.
        tc = team_island["center"]
        dx = abs(tc[0] - center_x)
        dz = abs(tc[1] - center_z)
        return "mirror_x" if dz > dx else "mirror_z"

    return None


def _split_polygon_along_axis(
    exterior: List[List[float]],
    axis: str,
    axis_value: float,
    center_info: Dict,
) -> Tuple[Optional[object], Optional[object]]:
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
    big = max(abs(bounds[2] - bounds[0]), abs(bounds[3] - bounds[1])) + 100

    # Determine if the axis dimension is odd (center line through a block)
    center_type = center_info["type"]
    if axis == "mirror_x":
        odd_on_axis = (center_type in ("single_block", "1x2_line"))
    else:
        odd_on_axis = (center_type in ("single_block", "2x1_line"))

    if odd_on_axis:
        # Exclude the center column/row (1-block wide strip)
        # For mirror_x: exclude x in [floor(axis_value), floor(axis_value)+1]
        # For mirror_z: exclude z in [floor(axis_value), floor(axis_value)+1]
        strip_lo = int(np.floor(axis_value))
        strip_hi = strip_lo + 1
        if axis == "mirror_x":
            neg_clip = box(bounds[0] - 1, bounds[1] - 1, strip_lo, bounds[3] + 1)
            pos_clip = box(strip_hi, bounds[1] - 1, bounds[2] + 1, bounds[3] + 1)
        else:
            neg_clip = box(bounds[0] - 1, bounds[1] - 1, bounds[2] + 1, strip_lo)
            pos_clip = box(bounds[0] - 1, strip_hi, bounds[2] + 1, bounds[3] + 1)
    else:
        # Clean split at axis_value (falls between two block columns)
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
    team_islands: List[Dict],
    axis: str,
    axis_value: float,
    center_info: Dict,
) -> Tuple[float, str]:
    """Verify intra-team symmetry by splitting all territory polygons along
    the axis and comparing the two halves via IoU.

    The negative half is reflected across the axis, then compared to the
    positive half.

    Returns (iou, axis_name).
    """
    from shapely.ops import unary_union
    from shapely.validation import make_valid

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

    # Reflect the negative half to overlay the positive half
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


def _reflect_shapely_geom_x(geom, center_x: float):
    """Reflect a Shapely geometry across x = center_x.

    Maps x → 2·center_x − x, keeps z unchanged.
    """
    from shapely import affinity
    # Affine matrix [a, b, d, e, xoff, yoff]: x' = a*x + b*y + xoff
    return affinity.affine_transform(geom, [-1, 0, 0, 1, 2 * center_x, 0])


def _reflect_shapely_geom_z(geom, center_z: float):
    """Reflect a Shapely geometry across z = center_z.

    Maps z → 2·center_z − z, keeps x unchanged.
    (z is the y-coordinate in Shapely's 2D plane.)
    """
    from shapely import affinity
    return affinity.affine_transform(geom, [1, 0, 0, -1, 0, 2 * center_z])


def _assign_islands_to_teams(
    islands: List[Dict],
    teams: List[Dict],
    center_x: float,
    center_z: float,
    primary_global: Dict,
) -> Dict[str, List[Dict]]:
    """Assign islands to teams by explicit team field or proximity to spawns."""
    team_islands = {t["id"]: [] for t in teams}
    assigned_ids = set()

    # Explicit team assignment
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


def _check_canonical_coverage(
    islands: List[Dict],
    teams: List[Dict],
    team_islands: Dict[str, List[Dict]],
) -> List[Dict]:
    """Check that each team gets exactly 1 island from each canonical group.

    For rot_90 (4-team) maps, intra-team mirror symmetry is not meaningful
    because island shapes are abstract and team territories don't form
    neat axis-aligned quadrants.  Instead we verify that the rotational
    symmetry correctly distributes one island from each canonical group
    to every team.

    Canonical groups are identified by area (islands with the same area
    share a canonical D4 shape).  Only groups whose size equals the number
    of teams are considered (one island per team expected).
    """
    from collections import defaultdict

    n_teams = len(teams)

    # Build canonical groups by area
    area_groups = defaultdict(list)
    for isl in islands:
        area_groups[isl["area"]].append(isl["id"])

    # Keep groups that have exactly n_teams members
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


def _detect_intra_team_symmetry(
    islands: List[Dict],
    center_x: float,
    center_z: float,
    center_info: Dict,
    global_symmetries: List[Dict],
    teams: List[Dict],
) -> List[Dict]:
    """Detect symmetry within each team's territory.

    Strategy depends on global symmetry type:

    - rot_90 (typically 4 teams): Check canonical coverage — each team
      should receive exactly 1 island from each canonical group.  Mirror-
      split is not attempted because island shapes are abstract and team
      territories don't form neat axis-aligned quadrants.

    - rot_180 / mirror (typically 2 teams): Split each team's territory
      along the intra-team axis and compare the two halves via polygon
      IoU.  The split respects the center type (even = clean split,
      odd = exclude center column/row).

    Returns list of per-team symmetry results.
    """
    if not teams:
        return []

    detected = [s for s in global_symmetries if s["detected"]]
    if not detected:
        return []

    primary = max(detected, key=lambda s: s["confidence"])

    # Assign islands to teams
    team_islands = _assign_islands_to_teams(
        islands, teams, center_x, center_z, primary,
    )

    # --- rot_90: canonical coverage instead of mirror split ---
    if primary["type"] == "rot_90":
        return _check_canonical_coverage(islands, teams, team_islands)

    # --- 2-team maps: mirror split ---
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
        intra_axis = _determine_intra_axis(
            primary, spawn_island, center_x, center_z,
        )

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


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def detect_symmetry(map_context_path: str) -> Dict:
    """Run full symmetry analysis on a map from its map_context.json.

    Args:
        map_context_path: Path to map_context.json

    Returns:
        Dict with complete symmetry analysis results.
    """
    with open(map_context_path, "r") as f:
        ctx = json.load(f)

    bbox = ctx["bounding_box"]
    islands = ctx["islands"]
    teams = ctx.get("teams", [])

    # Step 1: Classify center
    center_info = classify_center(tuple(bbox))
    center_x = center_info["center_x"]
    center_z = center_info["center_z"]

    # Step 2: Aggregate pair transforms
    pair_analysis = _aggregate_pair_transforms(islands, center_x, center_z)

    # Step 3: Detect global symmetry
    global_symmetries = _detect_global_symmetry(
        islands, center_x, center_z, pair_analysis,
    )

    # Step 4: Detect intra-team symmetry
    intra_team = _detect_intra_team_symmetry(
        islands, center_x, center_z, center_info, global_symmetries, teams,
    )

    return {
        "map_name": ctx.get("map_name", "Unknown"),
        "center": center_info,
        "pair_analysis": pair_analysis,
        "global_symmetry": global_symmetries,
        "intra_team_symmetry": intra_team,
    }
