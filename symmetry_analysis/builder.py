"""
Builder for symmetry analysis results.

Analyzes the geometric layout of a map from islands.json
to determine which global symmetry types are present (mirror, 180° rotation,
90° rotation).  Works purely from island geometry — does not require XML.

Team assignment and intra-team symmetry detection require XML data and live
in map_analysis.team_assignment (called during the assembly step).

Coordinate convention:
    - Bounding box: (min_x, max_x, min_z, max_z)
    - Block at integer (x, z) occupies [x, x+1) x [z, z+1), centroid at (x+0.5, z+0.5)
    - Map center is computed from bounding box midpoint in block-centroid space
"""

import json
import numpy as np

from symmetry_analysis.datatypes import SymmetryResult


# ---------------------------------------------------------------------------
# Center classification
# ---------------------------------------------------------------------------

def classify_center(bbox: tuple[float, float, float, float]) -> dict:
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

def _build_canonical_pairs(islands: list[dict]) -> list[tuple[dict, dict]]:
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
    a: dict, b: dict,
    center_x: float, center_z: float,
    tolerance: float = 2.0,
) -> list[str]:
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

def _reflect_polygon_x(poly_coords: list[list[float]], center_x: float) -> np.ndarray:
    """Reflect polygon coordinates across x = center_x."""
    pts = np.array(poly_coords)
    pts[:, 0] = 2 * center_x - pts[:, 0]
    return pts


def _reflect_polygon_z(poly_coords: list[list[float]], center_z: float) -> np.ndarray:
    """Reflect polygon coordinates across z = center_z."""
    pts = np.array(poly_coords)
    pts[:, 1] = 2 * center_z - pts[:, 1]
    return pts


def _rotate_polygon_180(poly_coords: list[list[float]], cx: float, cz: float) -> np.ndarray:
    """Rotate polygon coordinates 180 degrees around (cx, cz)."""
    pts = np.array(poly_coords)
    pts[:, 0] = 2 * cx - pts[:, 0]
    pts[:, 1] = 2 * cz - pts[:, 1]
    return pts


def _rotate_polygon_90(poly_coords: list[list[float]], cx: float, cz: float) -> np.ndarray:
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
    islands: list[dict],
    center_x: float,
    center_z: float,
    transform_name: str,
    iou_threshold: float = 0.85,
) -> tuple[float, list[dict]]:
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
# Geometric pair-support helpers
# ---------------------------------------------------------------------------

def _apply_transform_center(
    x: float, z: float,
    transform_type: str,
    center_x: float, center_z: float,
) -> tuple[float, float]:
    """Return the expected partner position for a given point under *transform_type*."""
    if transform_type == 'mirror_x':
        return 2.0 * center_x - x, z
    elif transform_type == 'mirror_z':
        return x, 2.0 * center_z - z
    elif transform_type == 'rot_180':
        return 2.0 * center_x - x, 2.0 * center_z - z
    elif transform_type == 'rot_90':
        return center_x + (z - center_z), center_z - (x - center_x)
    elif transform_type == 'rot_270':
        return center_x - (z - center_z), center_z + (x - center_x)
    else:
        return x, z



def _geometric_pair_support(
    islands: list[dict],
    transform_type: str,
    center_x: float,
    center_z: float,
    tolerance: float = 3.0,
) -> tuple[int, int]:
    """Compute (supporting, total) pairs using geometry-based island assignment.

    Replaces all-combinations counting for groups of identical-area islands.
    Handles two cases that the old counting cannot:

    1. Groups of 4+ identical islands (e.g. four 300-block corner islands that
       form two rot_180 pairs).  All-combinations produces C(4,2)=6 candidates
       of which only 2 have the right transform → pair_support = 2/6 ≈ 0.33.
       Geometric assignment finds the 2 correct pairs → pair_support = 2/2 = 1.0.

    2. Self-symmetric islands that lie on the symmetry axis (e.g. wintertime
       center-line islands under mirror_x).  They map to themselves; the old code
       tried to pair them with each other and failed.  Here they are detected by
       dist(transform(center), center) < tolerance and counted as automatically
       satisfied without consuming a partner slot.

    Groups of any even size are supported; odd-sized groups treat the leftover
    island as unsupported.
    """
    from collections import defaultdict

    by_area: dict[int, list[dict]] = defaultdict(list)
    for isl in islands:
        by_area[isl['area']].append(isl)

    supporting = 0
    total = 0

    for _area, group in by_area.items():
        self_sym = []
        needs_partner = []
        for isl in group:
            ix, iz = isl['center']
            ex, ez = _apply_transform_center(ix, iz, transform_type, center_x, center_z)
            if ((ex - ix) ** 2 + (ez - iz) ** 2) ** 0.5 < tolerance:
                self_sym.append(isl)
            else:
                needs_partner.append(isl)

        # Self-symmetric islands: each is its own "pair" → fully supported
        for _ in self_sym:
            supporting += 1
            total += 1

        n = len(needs_partner)
        if n == 0:
            continue
        if n == 1:
            total += 1          # lone island with no partner → unsupported
            continue

        # Greedy geometric pairing for n >= 2
        n_pairs = n // 2
        total += n_pairs
        if n % 2 == 1:
            total += 1          # odd island out → unsupported

        unassigned = list(range(n))
        paired = 0
        while len(unassigned) >= 2:
            i = unassigned[0]
            ix, iz = needs_partner[i]['center']
            ex, ez = _apply_transform_center(ix, iz, transform_type, center_x, center_z)

            best_j = None
            best_dist = float('inf')
            for j in unassigned[1:]:
                bx, bz = needs_partner[j]['center']
                d = ((ex - bx) ** 2 + (ez - bz) ** 2) ** 0.5
                if d < best_dist:
                    best_dist = d
                    best_j = j

            unassigned.remove(i)
            if best_j is not None and best_dist < tolerance:
                unassigned.remove(best_j)
                paired += 1
            # Island i is unsupported if no partner within tolerance;
            # it has already been counted in total via n_pairs.

        supporting += paired

    return supporting, total


# ---------------------------------------------------------------------------
# Island pair transform aggregation
# ---------------------------------------------------------------------------

def _aggregate_pair_transforms(
    islands: list[dict],
    center_x: float,
    center_z: float,
    tolerance: float = 3.0,
) -> dict:
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
    islands: list[dict],
    center_x: float,
    center_z: float,
    pair_analysis: dict,
) -> list[dict]:
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

    GROUP_IOU_THRESHOLD = 0.85

    # First pass: compute polygon IoU for all candidates
    ious = {}
    for sym_type, _ in candidates:
        iou, _ = _verify_polygon_symmetry(islands, center_x, center_z, sym_type)
        ious[sym_type] = iou

    # Second pass: compute group-aware pair support and confidence
    results = []
    for sym_type, description in candidates:
        iou = ious[sym_type]

        if sym_type == "rot_90":
            # rot_90 forms cycles of 4, not pairs — keep compatible-set counting.
            # Must have both rot_90 and rot_270 present.
            if counts.get("rot_90", 0) == 0 or counts.get("rot_270", 0) == 0:
                pair_support = 0.0
            else:
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

        else:
            # rot_180 / mirror_x / mirror_z: use geometry-based assignment.
            #
            # All-combinations counting under-counts when there are groups of 4+
            # identical-area islands (only 2 of C(4,2)=6 pairs have the right
            # transform → pair_support ≈ 0.33 for a perfectly symmetric map).
            # Geometric assignment finds the N/2 correct pairs directly.
            #
            # Islands that lie on the symmetry axis (self-symmetric) are
            # automatically satisfied and don't penalise pair_support.
            sup, tot = _geometric_pair_support(
                islands, sym_type, center_x, center_z
            )
            pair_support = sup / tot if tot > 0 else 0.0

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
# Main entry point
# ---------------------------------------------------------------------------


def detect_symmetry_from_data(data: dict) -> SymmetryResult:
    """Run geometric symmetry analysis from pre-parsed island data.

    Accepts a dict with the same structure as islands.json:
        - bounding_box: [min_x, max_x, min_z, max_z]
        - islands: list of island dicts (id, area, center, simplified_polygon)
        - map_name: str (optional, defaults to "Unknown")

    Detects global symmetry types (mirror, rotation) from island pair
    geometry. Does NOT include team assignment or intra-team symmetry —
    those are assembly-layer concerns handled by assemble_map() in
    map_analysis.pipeline.

    Returns:
        SymmetryResult with: map_name, center, pair_analysis, global_symmetry
    """
    bbox = data["bounding_box"]
    islands = data["islands"]
    map_name = data.get("map_name", "Unknown")

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

    return SymmetryResult(
        map_name=map_name,
        center=center_info,
        pair_analysis=pair_analysis,
        global_symmetry=global_symmetries,
    )


def detect_symmetry(islands_path: str) -> SymmetryResult:
    """Run geometric symmetry analysis on a map from its islands.json.

    Reads the JSON file at islands_path and delegates to
    detect_symmetry_from_data. Prefer passing data directly via
    detect_symmetry_from_data to avoid the disk round-trip.

    Args:
        islands_path: Path to islands.json

    Returns:
        SymmetryResult with: map_name, center, pair_analysis, global_symmetry
    """
    with open(islands_path, "r") as f:
        data = json.load(f)
    return detect_symmetry_from_data(data)
