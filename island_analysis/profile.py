"""Island spatial profiling: feature extraction, classification, and visualization.

Computes shape and topology features for each *canonical* island shape and
classifies it into one of six spatial types.  Observer islands
(is_observer_island=True) are excluded from all profiling.

Pipeline integration
--------------------
Called as a non-blocking Stage 8 in map_analysis/pipeline.py after
map_context.json and map_graph.json have been written.

Data sources
------------
- map_context.json: polygon geometry, bounding box, semantic flags, canonical_key
- map_graph.json:   per-island skeleton nodes/edges (optional Tier B features)

Output
------
island_profiles.json: list of IslandProfile objects (one per canonical shape)
island_profiles.png:  per-map two-panel visualization (optional, via --plot)
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
from scipy.spatial import ConvexHull

logger = logging.getLogger('ctw')

# ---------------------------------------------------------------------------
# Type colour palette (consistent across all profile plots)
# ---------------------------------------------------------------------------

_TYPE_COLORS: dict[str, str] = {
    'square':    '#27ae60',   # green
    'rectangle': '#2980b9',   # blue
    'circle':    '#e74c3c',   # red
    'donut':     '#1abc9c',   # cyan/teal
    'shard':     '#f39c12',   # amber
    'L_shape':   '#8e44ad',   # purple
    'Z_shape':   '#e67e22',   # dark orange
    'plus':      '#3498db',   # light blue
    'fork':      '#d35400',   # orange
    'rugged':    '#c0392b',   # dark red / coral
    'linear':    '#16a085',   # teal
    'blob':      '#95a5a6',   # gray
}

_ALL_TYPES: list[str] = list(_TYPE_COLORS)

# Per-type primary sort metric for mosaic ordering.
# Tuple: (feature_attr, descending).  Higher-descending = "most characteristic" first.
_TYPE_SORT_METRIC: dict[str, tuple[str, bool]] = {
    'square':    ('bbox_fill_ratio', True),   # most box-filling first
    'rectangle': ('bbox_fill_ratio', True),   # most box-filling first
    'circle':    ('convexity',       True),   # smoothest / most convex first
    'donut':     ('bbox_fill_ratio', False),  # most ring-like (lowest fill) first
    'shard':     ('convexity',       True),   # most convex / sharpest points first
    'L_shape':   ('convexity',       False),  # most concave (most L-like) first
    'Z_shape':   ('aspect_ratio',    True),   # most elongated first
    'plus':      ('convexity',       False),  # most arm-like (most concave) first
    'fork':      ('convexity',       False),  # most concave (most branched) first
    'rugged':    ('rugosity',        True),   # highest perimeter ratio first
    'linear':    ('aspect_ratio',    True),   # most elongated first
    'blob':      ('compactness',     True),   # most compact blobs first
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class IslandFeatures:
    """Raw numeric features for one canonical island shape.

    Tier A features (aspect_ratio … hole_ratio) are derived purely from the
    polygon stored in map_context.json and are always present.

    Tier B features (skeleton_*) come from map_graph.json skeleton data and
    may be None when:
      - the island has no skeleton (too small, or skeletonization failed)
      - the skeleton is unreliable (ring/donut topology — high hole_ratio
        combined with low compactness distorts the skeleton into a ring trace)
    """

    canonical_key: str
    # Tier A — polygon-derived (always available)
    aspect_ratio: float       # max(w, h) / max(min(w, h), 1) — elongation proxy
    compactness: float        # 4π·area / perimeter² — circle = 1.0
    convexity: float          # area / convex_hull_area — 1.0 = fully convex
    pca_elongation: float     # sqrt(λ₁/λ₂) from PCA of exterior vertices
    pca_angle_deg: float      # principal axis angle, degrees (−180 .. 180)
    hole_count: int           # number of interior polygon rings (holes)
    hole_ratio: float         # hole_count / area
    bbox_width: float         # canonical bounding box width  (x extent)
    bbox_height: float        # canonical bounding box height (z extent)
    area: int                 # island block count
    perimeter: float          # polygon exterior perimeter in world units
    bbox_fill_ratio: float    # area / (bbox_width × bbox_height) — 1.0 = perfect rectangle
    rugosity: float           # perimeter / bbox_perimeter — 1.0 = rectangle, >1.0 = jagged
    circle_fit_residual: float  # algebraic circle fit: RMS deviation / radius — 0 = perfect circle
    ellipse_residual: float     # PCA-normalised radial residual — 0 = perfect axis-aligned ellipse
    # Tier B — skeleton-derived (Optional — see docstring)
    skeleton_endpoint_count: Optional[int]
    skeleton_junction_count: Optional[int]
    skeleton_total_length: Optional[float]
    skeleton_topology: Optional[str]   # 'line' | 'tree' | 'mesh' | 'none' | None
    skeleton_path_bends: Optional[int] # direction changes in line-topology path (L=1, Z=2+, straight=0)
    # Tier A extended — bounding-box negative space
    bbox_cutout_count: Optional[int]      # qualifying rectangular corner cutouts (L=1, Z=2)
    bbox_cutout_min_fill: Optional[float] # min fill ratio among those cutouts
    bbox_cutout_coverage: Optional[float] # corner area / total negative space (1.0 = clean L/Z)
    # Tier A extended — point symmetry
    has_point_symmetry: bool = False      # block set maps to itself under 180° rotation about bbox centre


@dataclass
class IslandRasterStrategy:
    """Per-island rasterization hints derived from classification.

    grid_size_override replaces the map-level adaptive grid size for cells
    that belong to this island.  None means use the map-level default.

    alignment_angle_deg stores the island's principal axis angle (from
    pca_angle_deg) for *future* use with a rotated-grid rasterizer; the
    current axis-aligned rasterizer ignores this value.
    """

    grid_size_override: Optional[int]
    alignment_angle_deg: Optional[float]
    anchor_x: Optional[float]
    anchor_z: Optional[float]


@dataclass
class IslandProfile:
    """Classification result for one canonical island shape.

    raw_island_ids lists all raw island ids in the map that share this
    canonical shape (i.e. are rotations/reflections of each other).

    island_type is the *effective* profile — either the algorithm output or an
    override from island_profile_overrides.json.  auto_profile always holds
    the algorithm-computed type; when no override is active both fields are equal.
    """

    canonical_key: str
    island_type: str             # effective profile (override-applied); one of _ALL_TYPES
    auto_profile: str            # algorithm-computed profile before any overrides
    raw_island_ids: list[int]    # all island ids with this canonical_key
    features: IslandFeatures
    raster_strategy: IslandRasterStrategy


# ---------------------------------------------------------------------------
# Internal feature helpers
# ---------------------------------------------------------------------------


def _polygon_perimeter(exterior: list[list[float]]) -> float:
    """Compute the perimeter of a closed polygon from its vertex list."""
    if len(exterior) < 2:
        return 0.0
    pts = np.asarray(exterior, dtype=float)
    diffs = np.diff(pts, axis=0)
    # Close the ring
    close = pts[0] - pts[-1]
    return float(np.sum(np.hypot(diffs[:, 0], diffs[:, 1])) + math.hypot(close[0], close[1]))


def _convex_hull_area(exterior: list[list[float]]) -> float:
    """Compute convex hull area of a polygon exterior ring."""
    pts = np.asarray(exterior, dtype=float)
    if len(pts) < 3:
        return 0.0
    try:
        hull = ConvexHull(pts)
        return float(hull.volume)   # 'volume' is area in 2D
    except Exception:
        return 0.0


def _pca_of_polygon(exterior: list[list[float]]) -> tuple[float, float]:
    """PCA of polygon exterior vertices.

    Returns (elongation_ratio, principal_angle_deg) where:
      elongation_ratio = sqrt(λ₁ / max(λ₂, ε))  (λ₁ ≥ λ₂)
      principal_angle_deg = angle of the dominant eigenvector in degrees
    """
    pts = np.asarray(exterior, dtype=float)
    if len(pts) < 2:
        return 1.0, 0.0
    cov = np.cov(pts.T)
    if cov.ndim < 2:
        return 1.0, 0.0
    try:
        eigenvalues, eigenvectors = np.linalg.eigh(cov)
        # eigh returns ascending order; largest eigenvalue is last
        dominant = eigenvectors[:, -1]
        angle_deg = float(math.degrees(math.atan2(float(dominant[1]), float(dominant[0]))))
        lam1 = max(float(eigenvalues[-1]), 1e-9)
        lam2 = max(float(eigenvalues[0]), 1e-9)
        elongation = math.sqrt(lam1 / lam2)
    except Exception:
        return 1.0, 0.0
    return elongation, angle_deg


def _skeleton_topology(
    junction_count: int,
    endpoint_count: int,
    edge_count: int,
) -> str:
    """Classify skeleton topology from node/edge counts."""
    if junction_count == 0 and endpoint_count == 0:
        return 'none'
    if junction_count == 0 and endpoint_count == 2:
        return 'line'
    if edge_count > (junction_count + endpoint_count - 1):
        return 'mesh'
    return 'tree'


def _rdp_simplify(pts: np.ndarray, epsilon: float) -> np.ndarray:
    """Ramer-Douglas-Peucker path simplification.

    Recursively collapses path segments whose interior points deviate less than
    *epsilon* from the straight line between their endpoints.  Returns a
    reduced array of waypoints that preserves genuine corners.
    """
    if len(pts) < 3:
        return pts

    start, end = pts[0], pts[-1]
    line_vec = end - start
    line_len = float(np.linalg.norm(line_vec))

    if line_len < 1e-9:
        return np.array([pts[0], pts[-1]])

    # Perpendicular distance of each interior point from the start→end line
    perp = pts - start
    proj_scalar = perp @ line_vec / (line_len ** 2)
    proj_pts = start + np.outer(proj_scalar, line_vec)
    dists = np.linalg.norm(pts - proj_pts, axis=1)

    max_idx = int(np.argmax(dists))
    max_dist = dists[max_idx]

    if max_dist < epsilon:
        return np.array([pts[0], pts[-1]])

    left = _rdp_simplify(pts[: max_idx + 1], epsilon)
    right = _rdp_simplify(pts[max_idx:], epsilon)
    return np.vstack([left[:-1], right])


def _skeleton_path_bends(
    edge_pixels: dict | list,
    epsilon: float = 2.0,
    min_turn_deg: float = 40.0,
) -> int:
    """Count major direction changes in a line-topology skeleton path.

    Only meaningful when skeleton_topology == 'line' (0 junctions, 2 endpoints,
    1 edge).  Uses RDP simplification to collapse near-straight sub-paths (so
    single diagonal corner pixels don't produce phantom bends), then counts
    consecutive segment pairs whose angle difference exceeds *min_turn_deg*.

    Returns
    -------
    0   straight path (linear / shard / straight rectangle)
    1   single bend (L-shape — one ~90° corner)
    2+  two or more bends (Z / S / staircase)
    """
    # Extract the single edge's pixel list
    pixel_path: list = []
    if isinstance(edge_pixels, dict):
        for edge_entry in edge_pixels.values():
            pixel_path = (
                edge_entry.get('pixels', []) if isinstance(edge_entry, dict) else edge_entry
            )
            break
    else:
        for edge_entry in edge_pixels:
            pixel_path = (
                edge_entry.get('pixels', []) if isinstance(edge_entry, dict) else edge_entry
            )
            break

    if len(pixel_path) < 4:
        return 0

    pts = np.array(pixel_path, dtype=float)
    simplified = _rdp_simplify(pts, epsilon)

    if len(simplified) < 3:
        return 0

    diffs = np.diff(simplified, axis=0)
    angles = np.degrees(np.arctan2(diffs[:, 1], diffs[:, 0]))

    bends = 0
    for i in range(1, len(angles)):
        delta = abs(angles[i] - angles[i - 1])
        if delta > 180.0:
            delta = 360.0 - delta
        if delta > min_turn_deg:
            bends += 1

    return bends


def _polygon_area_shoelace(exterior: list[list[float]]) -> float:
    """Shoelace formula area of a simple polygon."""
    pts = np.asarray(exterior, dtype=float)
    if len(pts) < 3:
        return 0.0
    x, y = pts[:, 0], pts[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def _circle_fit_residual(exterior: list[list[float]]) -> float:
    """Algebraic least-squares circle fit.  Returns normalised RMS residual.

    Solves Ax + Bz + C = -(x² + z²) for the best-fit circle centre and
    radius, then returns RMS(|dist_i - r_fit|) / r_fit.

    Near 0  → points lie close to a circle.
    ~0.15+  → angular / diamond shape.

    Robust choice for near-square bounding boxes (aspect_ratio ≤ 1.2):
    a Minecraft diamond with fill ≈ 0.5 produces values ~0.15–0.30,
    while a genuine Minecraft circle produces values < 0.06.
    """
    pts = np.asarray(exterior, dtype=float)
    if len(pts) < 3:
        return 1.0
    x, z = pts[:, 0], pts[:, 1]
    A_mat = np.column_stack([x, z, np.ones(len(x))])
    b_vec = -(x ** 2 + z ** 2)
    coeffs, _, _, _ = np.linalg.lstsq(A_mat, b_vec, rcond=None)
    A, B, C = coeffs
    cx, cz = -A / 2.0, -B / 2.0
    r_sq = cx ** 2 + cz ** 2 - C
    if r_sq <= 0:
        return 1.0
    r = math.sqrt(r_sq)
    dists = np.sqrt((x - cx) ** 2 + (z - cz) ** 2)
    rms = math.sqrt(float(np.mean((dists - r) ** 2)))
    return float(rms / r)


def _ellipse_residual(exterior: list[list[float]]) -> float:
    """PCA-normalised radial residual — measures how well the polygon fits an
    axis-aligned ellipse.

    Steps:
      1. Centre the points.
      2. Rotate to the principal-component axes.
      3. Scale each axis by 1/sqrt(eigenvalue) → map the best-fit ellipse to
         a unit circle in this normalised space.
      4. Return RMS(|r_i - r_mean|) / r_mean in the normalised space.

    Near 0  → shape is close to an ellipse (or circle).
    ~0.10+  → shape has corners / flat sides that deviate from an ellipse.

    Preferred over circle_fit_residual for elongated shapes (aspect > 1.2)
    because it accounts for the axis ratio before measuring roundness.
    """
    pts = np.asarray(exterior, dtype=float)
    if len(pts) < 3:
        return 1.0
    centroid = pts.mean(axis=0)
    centered = pts - centroid
    cov = np.cov(centered.T)
    if cov.ndim < 2:
        return 1.0
    try:
        eigenvalues, eigenvectors = np.linalg.eigh(cov)
    except np.linalg.LinAlgError:
        return 1.0
    eigenvalues = np.maximum(eigenvalues, 1e-9)
    rotated = centered @ eigenvectors
    scaled = rotated / np.sqrt(eigenvalues)
    radii = np.linalg.norm(scaled, axis=1)
    r_mean = float(radii.mean())
    if r_mean < 1e-9:
        return 1.0
    rms = math.sqrt(float(np.mean((radii - r_mean) ** 2)))
    return float(rms / r_mean)


def _bbox_corner_cutout_count(
    exterior: list[list[float]],
    holes: list[list[list[float]]],
    island_area: float,
) -> tuple[int, float]:
    """Count approximately-rectangular corner cutouts in the bounding box.

    Computes (bounding_box − island_polygon) using Shapely and analyses each
    connected negative-space region.  A region qualifies as a "corner cutout"
    when it:
      (a) touches exactly two *adjacent* (non-opposite) edges of the global
          bounding box, and
      (b) has a bbox_fill_ratio ≥ 0.65 — i.e. is itself approximately
          rectangular.

    Corner piece fill values for reference shapes:
      perfect rectangle cut  ≈ 1.00
      noisy rectangle cut    ≈ 0.80 – 0.95
      L with rounded corner  ≈ 0.70
      circle-corner sliver   ≈ 0.21   (excluded by threshold)

    coverage_ratio is the key discriminator between genuine L/Z shapes and
    other shapes (sickles, boomerangs) that happen to leave one empty corner:
      clean L/Z: all negative space sits in the corner(s) → coverage ≈ 0.9–1.0
      sickle:    corner is only part of the negative space  → coverage ≈ 0.3–0.6

    Returns
    -------
    (count, min_fill, coverage_ratio) where:
      count          : number of qualifying corner cutout regions
      min_fill       : minimum fill ratio among those regions (1.0 if count == 0)
      coverage_ratio : sum(qualifying corner areas) / total negative space area
    """
    try:
        from shapely.geometry import Polygon as ShapelyPolygon
        from shapely.geometry import box as shapely_box
    except ImportError:
        return 0, 1.0, 0.0

    if len(exterior) < 3:
        return 0, 1.0, 0.0

    pts = np.asarray(exterior, dtype=float)
    min_x, min_z = pts.min(axis=0)
    max_x, max_z = pts.max(axis=0)

    if (max_x - min_x) < 1 or (max_z - min_z) < 1:
        return 0, 1.0, 0.0

    bbox_geom = shapely_box(min_x, min_z, max_x, max_z)
    hole_rings = [ring for ring in holes if len(ring) >= 3]
    try:
        island_poly = ShapelyPolygon(exterior, hole_rings)
        if not island_poly.is_valid:
            island_poly = island_poly.buffer(0)
        negative = bbox_geom.difference(island_poly)
    except Exception:
        return 0, 1.0, 0.0

    if negative.is_empty:
        return 0, 1.0, 0.0

    components = list(negative.geoms) if hasattr(negative, 'geoms') else [negative]

    # Ignore slivers smaller than 2 % of the island area
    min_component_area = max(1.0, island_area * 0.02)
    # Edge-touch tolerance: 2 % of the shorter bbox dimension
    eps = max(0.5, min(max_x - min_x, max_z - min_z) * 0.02)

    corner_count = 0
    min_fill = 1.0
    total_corner_area = 0.0
    total_negative_area = float(negative.area)

    for comp in components:
        if comp.area < min_component_area:
            continue

        bounds = comp.bounds  # (minx, minz, maxx, maxz)
        comp_bbox_area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
        if comp_bbox_area < 1e-6:
            continue

        comp_fill = float(comp.area / comp_bbox_area)

        # Which global bbox edges does this component reach?
        touches_left   = bounds[0] <= min_x + eps
        touches_right  = bounds[2] >= max_x - eps
        touches_bottom = bounds[1] <= min_z + eps
        touches_top    = bounds[3] >= max_z - eps

        edge_count = sum([touches_left, touches_right, touches_bottom, touches_top])
        is_opposite = (touches_left and touches_right) or (touches_bottom and touches_top)

        # Corner: exactly 2 adjacent (non-opposite) edges
        is_corner = (edge_count == 2) and not is_opposite

        if is_corner and comp_fill >= 0.68:
            corner_count += 1
            min_fill = min(min_fill, comp_fill)
            total_corner_area += float(comp.area)

    if total_negative_area > 1e-6:
        coverage_ratio = total_corner_area / total_negative_area
    else:
        coverage_ratio = 0.0

    return corner_count, min_fill, coverage_ratio


# ---------------------------------------------------------------------------
# Point-symmetry helper
# ---------------------------------------------------------------------------


def _check_point_symmetry(exterior: list, bbox: list) -> bool:
    """Return True if the island block set has 180° rotational (point) symmetry.

    The rotation centre is the bounding-box midpoint:
        cx = (min_x + max_x) / 2
        cz = (min_z + max_z) / 2

    This is always one of the four valid centre types:
        1×1  — cx half-integer, cz half-integer  (odd width, odd height)
        2×1  — cx integer,      cz half-integer  (even width, odd height)
        1×2  — cx half-integer, cz integer       (odd width, even height)
        2×2  — cx integer,      cz integer       (even width, even height)

    For any of these, 2*cx − x and 2*cz − z map integers to integers, so the
    rotated positions land back on valid block indices.
    """
    from shapely.geometry import Polygon, Point

    if len(exterior) < 3:
        return False

    min_x, max_x, min_z, max_z = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
    cx = (min_x + max_x) / 2.0
    cz = (min_z + max_z) / 2.0

    shapely_poly = Polygon(exterior)
    blocks: frozenset[tuple[int, int]] = frozenset(
        (x, z)
        for x in range(int(min_x), int(max_x))
        for z in range(int(min_z), int(max_z))
        if shapely_poly.contains(Point(x + 0.5, z + 0.5))
    )
    if not blocks:
        return False

    # Rotate block centres (x+0.5, z+0.5) about (cx, cz), then convert back to
    # block index: x' = (2*cx - (x+0.5)) - 0.5 = 2*cx - x - 1.
    rotated: frozenset[tuple[int, int]] = frozenset(
        (int(round(2.0 * cx - x - 1.0)), int(round(2.0 * cz - z - 1.0)))
        for x, z in blocks
    )
    return rotated == blocks


# ---------------------------------------------------------------------------
# Public API — feature extraction
# ---------------------------------------------------------------------------


def extract_island_features(
    canonical_key: str,
    island_dict: dict,
    graph_dict: Optional[dict],
) -> IslandFeatures:
    """Compute all features for one canonical island representative.

    Parameters
    ----------
    canonical_key:
        The canonical key string for this island shape.
    island_dict:
        One island entry from map_context.json['islands'].  Used for polygon
        geometry, bounding box, area, and hole_count.
    graph_dict:
        Matching island entry from map_graph.json['islands'] (matched by
        island_id), or None if skeleton data is unavailable.
    """
    poly = island_dict.get('simplified_polygon') or {}
    exterior = poly.get('exterior') or []
    area = island_dict.get('area', 1)
    hole_count = island_dict.get('hole_count', 0)
    bbox = island_dict.get('bounding_box', [0, 0, 0, 0])  # [min_x, max_x, min_z, max_z]

    # Bounding box dimensions
    bbox_width = float(bbox[1] - bbox[0])
    bbox_height = float(bbox[3] - bbox[2])

    # Tier A features
    long_side = max(bbox_width, bbox_height)
    short_side = max(min(bbox_width, bbox_height), 1.0)
    aspect_ratio = long_side / short_side

    perimeter = _polygon_perimeter(exterior)
    if perimeter > 0:
        compactness = 4.0 * math.pi * area / (perimeter ** 2)
    else:
        compactness = 0.0

    hull_area = _convex_hull_area(exterior)
    if hull_area > 0:
        poly_area = _polygon_area_shoelace(exterior)
        convexity = min(poly_area / hull_area, 1.0)
    else:
        convexity = 1.0

    pca_elongation, pca_angle_deg = _pca_of_polygon(exterior)

    hole_ratio = hole_count / max(area, 1)

    bbox_area = max(bbox_width * bbox_height, 1.0)
    bbox_fill_ratio = area / bbox_area

    bbox_perimeter = 2.0 * (bbox_width + bbox_height)
    rugosity = perimeter / max(bbox_perimeter, 1.0)

    # Tier B features (skeleton — Optional)
    skel_endpoint_count: Optional[int] = None
    skel_junction_count: Optional[int] = None
    skel_total_length: Optional[float] = None
    skel_topology: Optional[str] = None
    skel_path_bends: Optional[int] = None

    if graph_dict is not None:
        skeleton = graph_dict.get('skeleton')
        if skeleton is not None:
            nodes = skeleton.get('nodes') or []
            edges_list = skeleton.get('edges') or []
            edge_pixels = skeleton.get('edge_pixels') or []

            endpoint_count = sum(1 for n in nodes if n.get('type') == 'endpoint')
            junction_count = sum(1 for n in nodes if n.get('type') == 'junction')
            edge_count = len(edges_list)

            # Total skeleton length: sum of Euclidean distances along edge pixel paths.
            # edge_pixels is a dict: {str_edge_id: {'src': int, 'dst': int, 'pixels': [[x,z],...]}}
            total_length = 0.0
            pixel_paths = (
                edge_pixels.values()
                if isinstance(edge_pixels, dict)
                else edge_pixels
            )
            for edge_entry in pixel_paths:
                pixel_path = (
                    edge_entry.get('pixels', [])
                    if isinstance(edge_entry, dict)
                    else edge_entry
                )
                if len(pixel_path) >= 2:
                    pts = np.asarray(pixel_path, dtype=float)
                    diffs = np.diff(pts, axis=0)
                    total_length += float(np.sum(np.hypot(diffs[:, 0], diffs[:, 1])))

            skel_endpoint_count = endpoint_count
            skel_junction_count = junction_count
            skel_total_length = round(total_length, 2)
            skel_topology = _skeleton_topology(junction_count, endpoint_count, edge_count)

            # Path bend count — only meaningful for line topology (1 edge, 2 endpoints)
            skel_path_bends: Optional[int] = None
            if skel_topology == 'line' and edge_pixels:
                skel_path_bends = _skeleton_path_bends(edge_pixels)

    # Bounding-box corner cutout analysis (for L_shape / Z_shape detection)
    holes = poly.get('holes') or []
    cutout_count, cutout_min_fill, cutout_coverage = _bbox_corner_cutout_count(
        exterior, holes, float(area)
    )

    # Point-symmetry check (for circle / ellipse gate)
    has_point_symmetry = _check_point_symmetry(exterior, bbox)

    return IslandFeatures(
        canonical_key=canonical_key,
        aspect_ratio=round(aspect_ratio, 4),
        compactness=round(compactness, 4),
        convexity=round(convexity, 4),
        pca_elongation=round(pca_elongation, 4),
        pca_angle_deg=round(pca_angle_deg, 2),
        hole_count=int(hole_count),
        hole_ratio=round(hole_ratio, 6),
        bbox_width=round(bbox_width, 2),
        bbox_height=round(bbox_height, 2),
        area=int(area),
        perimeter=round(perimeter, 2),
        bbox_fill_ratio=round(bbox_fill_ratio, 4),
        rugosity=round(rugosity, 4),
        circle_fit_residual=round(_circle_fit_residual(exterior), 4),
        ellipse_residual=round(_ellipse_residual(exterior), 4),
        skeleton_endpoint_count=skel_endpoint_count,
        skeleton_junction_count=skel_junction_count,
        skeleton_total_length=skel_total_length,
        skeleton_topology=skel_topology,
        skeleton_path_bends=skel_path_bends,
        bbox_cutout_count=cutout_count if cutout_count > 0 else None,
        bbox_cutout_min_fill=round(cutout_min_fill, 4) if cutout_count > 0 else None,
        bbox_cutout_coverage=round(cutout_coverage, 4) if cutout_count > 0 else None,
        has_point_symmetry=has_point_symmetry,
    )


# ---------------------------------------------------------------------------
# Public API — classification
# ---------------------------------------------------------------------------


def classify_island(features: IslandFeatures) -> str:
    """Apply skeleton-informed rule cascade and return the island_type string.

    Rules are applied in priority order; the first match wins.
    Skeleton features (Tier B) are used where available — most rules degrade
    gracefully when skeleton data is absent.

    Rule cascade
    ------------
    1.   square      bbox_fill_ratio == 1.0 AND aspect_ratio ≤ 1.3
    2.   rectangle   bbox_fill_ratio == 1.0 AND aspect_ratio > 1.3
    3.   donut       hole_count == 1 AND convexity ≥ 0.92 AND rugosity ≤ 1.1
                     (exactly one enclosed air pocket with a smooth outer ring)
    4.   circle      convexity ≥ 0.88 AND hole_count == 0 AND has_point_symmetry AND
                     (aspect ≤ 1.2 AND circle_fit_residual < 0.12
                      OR aspect > 1.2 AND ellipse_residual < 0.10 AND bbox_fill_ratio ≥ 0.72)
                     (circle or ellipse: smooth solid shape with 180° rotational symmetry)
    4.5  L_shape     bbox_cutout_count == 1 AND bbox_cutout_coverage >= 0.70
                     (one rectangular corner cutout accounting for ≥ 70 % of negative space)
    4.6  Z_shape     bbox_cutout_count == 2 AND bbox_cutout_coverage >= 0.70
                     (two rectangular corner cutouts, together ≥ 70 % of negative space)
    5.   shard       topo == 'line' AND convexity ≥ 0.87 AND NOT round
                     (smooth two-pointed diamond/lens/tear — poor elliptic fit or low fill)
    6.   plus        topo == 'tree' AND junctions == 1 AND endpoints ≥ 3
                     (T / Y / + / star: one central branch point, ≥ 3 arms)
    7.   fork        junctions ≥ 2 AND convexity < 0.70
                     (complex multi-branching, deep concavity)
    8.   L_shape     topo == 'line' AND path_bends == 1
                     (fallback: line skeleton with one ~90° direction change)
    9.   Z_shape     topo == 'line' AND path_bends ≥ 2
                     (fallback: line skeleton with two+ direction changes)
    10.  rugged      rugosity ≥ 1.2
    11.  linear      aspect_ratio ≥ 2.5
    12.  blob        (default)

    Design notes
    ------------
    - square/rectangle: fill == 1.0 requires a literally perfect rectangle (no missing corners)
    - donut: hole_count == 1 (not ≥ 1) — a genuine ring has exactly one interior void.
      hole_count > 1 indicates structural complexity (e.g. a ring whose blocks don't
      fully close, producing multiple separate air pockets) rather than a simple donut.
      convexity ≥ 0.92 and rugosity ≤ 1.1 ensure the outer ring is smooth — any rugged
      or forked island can enclose a small gap without being ring-shaped.
      Reference examples: kingdom (0.988, 0.993), ouroboros (0.944, 1.058),
      pineium_ctw (0.952, 1.000).
    - shard: convexity ≥ 0.87 — captures diamond/tear shapes with convexity as low as
      0.882 (ad1f82ab) without false-positives, because the residual/fill gate now acts
      as the primary circle-vs-shard discriminator.  Earlier value of 0.93 was set when
      the residual check was absent; shapes with conv 0.87–0.93 and poor fit are
      genuine shards (cb5874e2=0.923, 3855d0e3=0.919, de43e1a0=0.890, 296006fc=0.895).
    - circle vs shard: a circle/ellipse fits an elliptic curve (low residual, high fill);
      a shard has flat sides/sharp tips that deviate from an ellipse.
      For near-square shapes (aspect ≤ 1.2), circle_fit_residual is the discriminator:
        circles < 0.12 (6eb91fd7=0.110, e15af4ee=0.101 — small WorldEdit cylinders)
        shards ≥ 0.12 (cb5874e2=0.146, 238aa276=0.246, fd4f5230=0.161)
      For elongated shapes (aspect > 1.2), ellipse_residual alone is insufficient
      because tear/shard shapes can have low ell_res; bbox_fill_ratio provides the
      second gate:  a true ellipse fills π/4 ≈ 0.785 of its bounding box;
      shards/tears fill ≤ 0.70 (296006fc=0.697, de43e1a0=0.619, ad1f82ab=0.600).
      Threshold 0.72 sits in the observed gap between ellipses (≥ 0.77) and shards.
    - plus vs fork: plus has exactly one junction (the centre) with ≥ 3 endpoints;
      fork has two or more junctions indicating a more complex branching network
    - L_shape / Z_shape require path_bends, which is only computed for topo='line';
      shapes without skeleton data degrade to rugged/linear/blob
    - fork vs rugged: fork has deep concave gaps (convexity < 0.70); rugged has many
      surface irregularities without deep concavity
    """
    # Rule 1: square — perfect rectangular fill, near-square
    if (features.bbox_fill_ratio == 1.0
            and features.aspect_ratio <= 1.3):
        return 'square'

    # Rule 2: rectangle — perfect rectangular fill, elongated
    if (features.bbox_fill_ratio == 1.0
            and features.aspect_ratio > 1.3):
        return 'rectangle'

    # Rule 3: donut — ring/annular shape with exactly one enclosed interior air pocket.
    # hole_count == 1: a true donut has a single interior void (the hole in the ring).
    #   hole_count > 1 → structurally complex island (e.g. multiple enclosed pockets
    #   from an irregular block arrangement), not a simple ring — must be excluded.
    # convexity ≥ 0.92 and rugosity ≤ 1.1: the outer boundary must be smooth.
    #   Any rugged or forked island can enclose a small gap (hole_count ≥ 1) without
    #   being ring-shaped; these produce low convexity and high rugosity.
    if (features.hole_count == 1
            and features.convexity >= 0.92
            and features.rugosity <= 1.1):
        return 'donut'

    # Rule 4: circle / ellipse — smooth solid curved shape with a good elliptic fit.
    #
    # Two residuals measure fit quality depending on aspect ratio:
    #   aspect ≤ 1.2  →  circle_fit_residual  (algebraic circle; best for near-square)
    #   aspect > 1.2  →  ellipse_residual + bbox_fill_ratio  (handles elongation)
    #
    # Thresholds derive from verified examples:
    #   circles: a6d59506=0.032, e23c5e30=0.046, 6eb91fd7=0.110, e15af4ee=0.101
    #   shards:  fd4f5230=0.161, cb5874e2=0.146, 238aa276=0.246  (all ≥ 0.12)
    #   ellipses (ell_res): 696bce97=0.072, 5e5e0548=0.072, 5e666a93=0.094  (all < 0.10)
    #   elongated fill: ellipses ≥ 0.77 (5e666a93=0.771); shards < 0.70 (296006fc=0.697)
    #
    # No topology constraint: Minecraft pixelated circles often get 'line' skeleton
    # topology because the staircase approximation slightly elongates the shape.
    if features.convexity >= 0.88 and features.hole_count == 0 and features.has_point_symmetry:
        if features.aspect_ratio <= 1.2:
            is_round = features.circle_fit_residual < 0.12
        else:
            is_round = (features.ellipse_residual < 0.10
                        and features.bbox_fill_ratio >= 0.72)
        if is_round:
            return 'circle'

    # Rule 4.5: L_shape via bbox-cutout — a rectangle with exactly one rectangular
    # corner removed.  Fires before the shard rule so that angular L shapes are not
    # intercepted by the line-topology shard gate.
    # coverage_ratio >= 0.70: the qualifying corner(s) must account for ≥ 70 % of
    # the total negative space; this rejects sickles/boomerangs whose empty corner
    # represents only a fraction of their bounding-box gap.
    if (features.bbox_cutout_count == 1
            and (features.bbox_cutout_coverage or 0.0) >= 0.70):
        return 'L_shape'

    # Rule 4.6: Z_shape via bbox-cutout — a rectangle with two rectangular corner
    # cuts on opposite sides (Z / S staircase form).
    if (features.bbox_cutout_count == 2
            and (features.bbox_cutout_coverage or 0.0) >= 0.70):
        return 'Z_shape'

    # Rule 5: shard — smooth two-pointed shape (diamond, rhombus, lens, tear).
    # Requires line topology (two skeleton endpoints, no junctions), convexity ≥ 0.87,
    # and a POOR elliptic fit (exact logical complement of the circle rule above).
    # convexity ≥ 0.87: captures tear/diamond shapes down to ad1f82ab=0.882.
    #   The residual/fill gate is the primary circle-vs-shard discriminator; convexity
    #   only excludes clearly irregular shapes from the shard category.
    # shard_not_round is the logical complement of is_round in Rule 4.
    if features.skeleton_topology == 'line' and features.convexity >= 0.87:
        if features.aspect_ratio <= 1.2:
            shard_not_round = features.circle_fit_residual >= 0.12
        else:
            shard_not_round = (features.ellipse_residual >= 0.10
                               or features.bbox_fill_ratio < 0.72)
        if shard_not_round:
            return 'shard'

    # Rules 6 & 7: branching shapes — require skeleton data
    junction_count = features.skeleton_junction_count
    endpoint_count = features.skeleton_endpoint_count
    if junction_count is not None and endpoint_count is not None:
        # Rule 6: plus — one central junction with three or more arms (T, Y, +, star)
        if junction_count == 1 and endpoint_count >= 3:
            return 'plus'

        # Rule 7: fork — multiple junctions, strongly concave (complex branching).
        if junction_count >= 2 and features.convexity < 0.70:
            return 'fork'

    # Rules 8 & 9: bent-path shapes — require line topology with path_bends
    if (features.skeleton_topology == 'line'
            and features.skeleton_path_bends is not None):
        # Rule 8: L_shape — single 90°-ish bend in an otherwise straight path
        if features.skeleton_path_bends == 1:
            return 'L_shape'

        # Rule 9: Z_shape — two or more direction changes (Z, S, staircase)
        if features.skeleton_path_bends >= 2:
            return 'Z_shape'

    # Rule 10: rugged — polygon perimeter noticeably larger than bbox perimeter.
    if features.rugosity >= 1.2:
        return 'rugged'

    # Rule 11: linear — elongated corridor
    if features.aspect_ratio >= 2.5:
        return 'linear'

    # Rule 12: blob (default)
    return 'blob'


def build_raster_strategy(
    island_type: str,
    features: IslandFeatures,
    base_grid_size: int,
) -> IslandRasterStrategy:
    """Derive rasterization hints from island type and features.

    The alignment_angle_deg value (from pca_angle_deg) is stored for future
    use with a rotated-grid rasterizer but is NOT yet applied by the current
    axis-aligned GridBase rasterizer.
    """
    grid_size_override: Optional[int] = None
    alignment_angle_deg: Optional[float] = None
    anchor_x: Optional[float] = None
    anchor_z: Optional[float] = None

    if island_type == 'rectangle':
        # Store principal axis angle for future rotated-grid support
        alignment_angle_deg = features.pca_angle_deg
    elif island_type == 'linear':
        # Store principal axis angle for future rotated-grid support
        alignment_angle_deg = features.pca_angle_deg
    elif island_type in ('fork', 'rugged'):
        # Complex internal structure — finer grid improves path coverage
        grid_size_override = max(2, base_grid_size // 2)

    return IslandRasterStrategy(
        grid_size_override=grid_size_override,
        alignment_angle_deg=alignment_angle_deg,
        anchor_x=anchor_x,
        anchor_z=anchor_z,
    )


# ---------------------------------------------------------------------------
# Override file helpers
# ---------------------------------------------------------------------------


def load_override_data(path: Path) -> dict[str, dict[str, str]]:
    """Load full override data: canonical_key → {profile, note}.

    Handles both the old flat format (key → profile_str) and the current
    rich format (key → {profile, note}).  Old-format files are migrated
    on read (the note field is initialised to "").  Returns an empty dict
    if the file is absent or unreadable.
    """
    if not path.exists():
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            return {}
        result: dict[str, dict[str, str]] = {}
        for key, value in raw.items():
            if not isinstance(key, str):
                continue
            if isinstance(value, str):
                # Old flat format — migrate: profile present, no note yet
                result[key] = {'profile': value, 'note': ''}
            elif isinstance(value, dict):
                result[key] = {
                    'profile': str(value.get('profile', '')),
                    'note':    str(value.get('note', '')),
                }
        return result
    except Exception as exc:
        logger.warning('island profiling: failed to load overrides %s: %s', path, exc)
        return {}


def save_override_data(path: Path, data: dict[str, dict[str, str]]) -> None:
    """Persist full override data (profiles + notes) to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(dict(sorted(data.items())), fh, indent=2)


def load_overrides(path: Path) -> dict[str, str]:
    """Return canonical_key → profile string for use by the classification pipeline.

    Ignores entries that have a note but no profile override.
    """
    return {
        key: entry['profile']
        for key, entry in load_override_data(path).items()
        if entry.get('profile')
    }


def save_overrides(path: Path, overrides: dict[str, str]) -> None:
    """Write profile-only overrides, preserving existing notes.

    Entries present in *overrides* are upserted; entries absent from *overrides*
    are removed only if they also have no note.
    """
    existing = load_override_data(path)
    new_data: dict[str, dict[str, str]] = {}

    # Keep entries from existing that have a note but are not in the new overrides
    for key, entry in existing.items():
        if key not in overrides and entry.get('note'):
            new_data[key] = {'profile': '', 'note': entry['note']}

    # Upsert every entry from overrides
    for key, profile in overrides.items():
        note = existing.get(key, {}).get('note', '')
        new_data[key] = {'profile': profile, 'note': note}

    save_override_data(path, new_data)


# ---------------------------------------------------------------------------
# Public API — main entry point
# ---------------------------------------------------------------------------


def profile_islands(
    map_context: dict,
    map_graph: dict,
    base_grid_size: int,
    overrides: Optional[dict[str, str]] = None,
) -> list[IslandProfile]:
    """Profile all canonical island shapes in a map.

    Skips islands where is_observer_island=True.
    Groups playable islands by canonical_key.
    Returns one IslandProfile per unique canonical shape.

    Parameters
    ----------
    map_context:
        Parsed map_context.json dict.
    map_graph:
        Parsed map_graph.json dict.
    base_grid_size:
        Map-level adaptive grid size (used to derive per-island overrides).
    overrides:
        Optional dict mapping canonical_key → profile label.  When provided,
        the effective island_type is replaced by the override; auto_profile
        still records the algorithm-computed classification.
    """
    all_islands = map_context.get('islands', [])

    # Filter out non-playable islands
    playable = [isl for isl in all_islands if not isl.get('is_observer_island', False)]
    if not playable:
        logger.debug('  island profiling: no playable islands found')
        return []

    # Index skeleton data from map_graph.json by island_id
    graph_by_id: dict[int, dict] = {
        entry['island_id']: entry
        for entry in map_graph.get('islands', [])
    }

    # Group playable islands by canonical_key
    groups: dict[str, list[dict]] = {}
    for isl in playable:
        key = isl.get('canonical_key')
        if key is None:
            # Fallback: treat each island as its own canonical group using its id
            key = f'_solo_{isl["id"]}'
        groups.setdefault(key, []).append(isl)

    active_overrides: dict[str, str] = overrides or {}

    profiles: list[IslandProfile] = []
    for canonical_key, group_islands in sorted(groups.items()):
        # Use the first island as the canonical representative for feature extraction
        representative = group_islands[0]
        island_id = representative['id']
        raw_island_ids = sorted(isl['id'] for isl in group_islands)

        graph_dict = graph_by_id.get(island_id)
        features = extract_island_features(canonical_key, representative, graph_dict)
        auto_profile = classify_island(features)
        island_type = active_overrides.get(canonical_key, auto_profile)
        raster_strategy = build_raster_strategy(island_type, features, base_grid_size)

        profiles.append(IslandProfile(
            canonical_key=canonical_key,
            island_type=island_type,
            auto_profile=auto_profile,
            raw_island_ids=raw_island_ids,
            features=features,
            raster_strategy=raster_strategy,
        ))

    _log_profile_summary(profiles)
    return profiles


def _log_profile_summary(profiles: list[IslandProfile]) -> None:
    """Log a one-line breakdown of island types."""
    counts: dict[str, int] = {}
    for profile in profiles:
        counts[profile.island_type] = counts.get(profile.island_type, 0) + 1
    summary = ', '.join(f'{t}={counts[t]}' for t in _ALL_TYPES if t in counts)
    logger.debug('  island profiling: %d canonical shapes (%s)', len(profiles), summary)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def save_profiles(profiles: list[IslandProfile], output_path: Path) -> None:
    """Serialize profiles to island_profiles.json."""
    data = []
    for profile in profiles:
        feat = profile.features
        strat = profile.raster_strategy
        data.append({
            'canonical_key': profile.canonical_key,
            'island_type': profile.island_type,
            'auto_profile': profile.auto_profile,
            'raw_island_ids': profile.raw_island_ids,
            'features': {
                'canonical_key': feat.canonical_key,
                'aspect_ratio': feat.aspect_ratio,
                'compactness': feat.compactness,
                'convexity': feat.convexity,
                'pca_elongation': feat.pca_elongation,
                'pca_angle_deg': feat.pca_angle_deg,
                'hole_count': feat.hole_count,
                'hole_ratio': feat.hole_ratio,
                'bbox_width': feat.bbox_width,
                'bbox_height': feat.bbox_height,
                'area': feat.area,
                'perimeter': feat.perimeter,
                'bbox_fill_ratio': feat.bbox_fill_ratio,
                'rugosity': feat.rugosity,
                'circle_fit_residual': feat.circle_fit_residual,
                'ellipse_residual': feat.ellipse_residual,
                'skeleton_endpoint_count': feat.skeleton_endpoint_count,
                'skeleton_junction_count': feat.skeleton_junction_count,
                'skeleton_total_length': feat.skeleton_total_length,
                'skeleton_topology': feat.skeleton_topology,
                'skeleton_path_bends': feat.skeleton_path_bends,
                'bbox_cutout_count': feat.bbox_cutout_count,
                'bbox_cutout_min_fill': feat.bbox_cutout_min_fill,
                'bbox_cutout_coverage': feat.bbox_cutout_coverage,
                'has_point_symmetry': feat.has_point_symmetry,
            },
            'raster_strategy': {
                'grid_size_override': strat.grid_size_override,
                'alignment_angle_deg': strat.alignment_angle_deg,
                'anchor_x': strat.anchor_x,
                'anchor_z': strat.anchor_z,
            },
        })
    with open(output_path, 'w', encoding='utf-8') as fh:
        json.dump({'profiles': data}, fh, indent=2)


def load_profiles(output_path: Path) -> Optional[list[IslandProfile]]:
    """Load island_profiles.json. Returns None if file is absent or unreadable."""
    if not output_path.exists():
        return None
    try:
        with open(output_path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        profiles = []
        for entry in data.get('profiles', []):
            feat_d = entry['features']
            strat_d = entry['raster_strategy']
            features = IslandFeatures(
                canonical_key=feat_d['canonical_key'],
                aspect_ratio=feat_d['aspect_ratio'],
                compactness=feat_d['compactness'],
                convexity=feat_d['convexity'],
                pca_elongation=feat_d['pca_elongation'],
                pca_angle_deg=feat_d['pca_angle_deg'],
                hole_count=feat_d.get('hole_count', 0),
                hole_ratio=feat_d['hole_ratio'],
                bbox_width=feat_d['bbox_width'],
                bbox_height=feat_d['bbox_height'],
                area=feat_d.get('area', 0),
                perimeter=feat_d.get('perimeter', 0.0),
                bbox_fill_ratio=feat_d.get('bbox_fill_ratio', 0.0),
                rugosity=feat_d.get('rugosity', 0.0),
                circle_fit_residual=feat_d.get('circle_fit_residual', 1.0),
                ellipse_residual=feat_d.get('ellipse_residual', 1.0),
                skeleton_endpoint_count=feat_d.get('skeleton_endpoint_count'),
                skeleton_junction_count=feat_d.get('skeleton_junction_count'),
                skeleton_total_length=feat_d.get('skeleton_total_length'),
                skeleton_topology=feat_d.get('skeleton_topology'),
                skeleton_path_bends=feat_d.get('skeleton_path_bends'),
                bbox_cutout_count=feat_d.get('bbox_cutout_count'),
                bbox_cutout_min_fill=feat_d.get('bbox_cutout_min_fill'),
                bbox_cutout_coverage=feat_d.get('bbox_cutout_coverage'),
                has_point_symmetry=feat_d.get('has_point_symmetry', False),
            )
            raster_strategy = IslandRasterStrategy(
                grid_size_override=strat_d.get('grid_size_override'),
                alignment_angle_deg=strat_d.get('alignment_angle_deg'),
                anchor_x=strat_d.get('anchor_x'),
                anchor_z=strat_d.get('anchor_z'),
            )
            profiles.append(IslandProfile(
                canonical_key=entry['canonical_key'],
                island_type=entry['island_type'],
                auto_profile=entry.get('auto_profile', entry['island_type']),
                raw_island_ids=entry['raw_island_ids'],
                features=features,
                raster_strategy=raster_strategy,
            ))
        return profiles
    except Exception as exc:
        logger.warning('  island profiling: failed to load %s: %s', output_path, exc)
        return None


# ---------------------------------------------------------------------------
# Per-map visualization
# ---------------------------------------------------------------------------


def plot_island_profiles(
    map_context: dict,
    profiles: list[IslandProfile],
    output_path: str,
) -> None:
    """Two-panel per-map profile visualization.

    Left panel: Map canvas with island outlines filled by type color.
                Each island polygon is labeled with its canonical_key (8 chars).
    Right panel: Feature scatter — aspect_ratio (x) vs compactness (y),
                 bubble size proportional to area, colored by type.
    """
    from common.visualization.map_primitives import draw_build_region, draw_island_outlines

    # Build lookup from island_id -> profile
    profile_by_id: dict[int, IslandProfile] = {}
    for profile in profiles:
        for island_id in profile.raw_island_ids:
            profile_by_id[island_id] = profile

    fig, (ax_map, ax_scatter) = plt.subplots(1, 2, figsize=(18, 9))
    map_name = map_context.get('map_name', '')
    fig.suptitle(f'Island Profiles — {map_name}', fontsize=14, fontweight='bold')

    # ── Left panel: map canvas ─────────────────────────────────────────────
    ax_map.set_aspect('equal')
    ax_map.invert_yaxis()
    ax_map.set_title('Island types (world view)', fontsize=11)

    build_region = map_context.get('build_region')
    if build_region:
        draw_build_region(ax_map, build_region)

    for island in map_context.get('islands', []):
        if island.get('is_observer_island', False):
            continue
        island_id = island['id']
        profile = profile_by_id.get(island_id)
        color = _TYPE_COLORS.get(profile.island_type, '#cccccc') if profile else '#cccccc'

        poly = island.get('simplified_polygon') or {}
        exterior = poly.get('exterior') or []
        holes = poly.get('holes') or []
        if len(exterior) >= 3:
            from matplotlib.patches import PathPatch
            from matplotlib.path import Path as MplPath
            verts = list(exterior) + [exterior[0]]
            codes = [MplPath.MOVETO] + [MplPath.LINETO] * (len(exterior) - 1) + [MplPath.CLOSEPOLY]
            for hole in holes:
                if len(hole) >= 3:
                    verts += list(hole) + [hole[0]]
                    codes += [MplPath.MOVETO] + [MplPath.LINETO] * (len(hole) - 1) + [MplPath.CLOSEPOLY]
            path = MplPath(verts, codes)
            patch = PathPatch(path, facecolor=color, alpha=0.55, edgecolor='#333333',
                              linewidth=0.7, zorder=2)
            ax_map.add_patch(patch)

        # Label at island center with canonical_key abbreviation
        cx, cz = island.get('center', [0, 0])
        key_label = (profile.canonical_key[:8] if profile else '?')
        ax_map.text(cx, cz, key_label, fontsize=5, ha='center', va='center',
                    color='#111111', zorder=3, clip_on=True)

    ax_map.autoscale_view()
    ax_map.set_xlabel('World X')
    ax_map.set_ylabel('World Z')

    # ── Right panel: feature scatter ───────────────────────────────────────
    ax_scatter.set_title('rugosity vs compactness', fontsize=11)
    ax_scatter.set_xlabel('Rugosity (perimeter / bbox perimeter)')
    ax_scatter.set_ylabel('Compactness')

    plotted_types: set[str] = set()
    for profile in profiles:
        feat = profile.features
        color = _TYPE_COLORS.get(profile.island_type, '#cccccc')
        bubble_size = max(20, min(800, feat.area / 5))
        ax_scatter.scatter(
            feat.rugosity, feat.compactness,
            s=bubble_size, c=color, alpha=0.75, edgecolors='#333333', linewidths=0.5,
            zorder=3,
        )
        ax_scatter.annotate(
            profile.canonical_key[:8],
            (feat.rugosity, feat.compactness),
            fontsize=5, ha='left', va='bottom', color='#333333',
        )
        plotted_types.add(profile.island_type)

    # Threshold reference lines
    ax_scatter.axvline(1.2, color='#c0392b', linestyle='--', linewidth=0.7,
                       alpha=0.5, label='rugged threshold (rugosity=1.2)')
    ax_scatter.axhline(0.88, color='#e74c3c', linestyle='--', linewidth=0.7,
                       alpha=0.5, label='circle threshold (convexity=0.88)')

    # Legend
    legend_patches = [
        mpatches.Patch(facecolor=_TYPE_COLORS[t], edgecolor='#333333',
                       linewidth=0.5, label=t)
        for t in _ALL_TYPES if t in plotted_types
    ]
    ax_scatter.legend(handles=legend_patches, fontsize=7, loc='upper right')

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    plt.savefig(output_path, dpi=120, bbox_inches='tight')
    plt.close(fig)
    logger.debug('  island profiling: saved %s', output_path)


# ---------------------------------------------------------------------------
# Cross-map visualization helpers (called from ctw/commands/maps.py)
# ---------------------------------------------------------------------------


def plot_profile_landscape(
    all_profiles: list[tuple[str, IslandProfile]],
    feature_x: str,
    feature_y: str,
    output_path: str,
) -> None:
    """Cross-map scatter: all canonical islands from all maps on feature axes.

    Parameters
    ----------
    all_profiles:
        List of (map_slug, IslandProfile) tuples from all available maps.
    feature_x, feature_y:
        Attribute names on IslandFeatures to use as scatter axes.
        Defaults used by CLI: 'aspect_ratio' and 'compactness'.
    output_path:
        Destination PNG path.
    """
    fig, ax = plt.subplots(figsize=(14, 10))
    ax.set_title(f'Island landscape — {feature_x} vs {feature_y}', fontsize=13)
    ax.set_xlabel(feature_x.replace('_', ' ').title())
    ax.set_ylabel(feature_y.replace('_', ' ').title())

    plotted_types: set[str] = set()
    for map_slug, profile in all_profiles:
        feat = profile.features
        x_val = getattr(feat, feature_x, None)
        y_val = getattr(feat, feature_y, None)
        if x_val is None or y_val is None:
            continue
        color = _TYPE_COLORS.get(profile.island_type, '#cccccc')
        ax.scatter(x_val, y_val, s=60, c=color, alpha=0.7,
                   edgecolors='#555555', linewidths=0.4, zorder=3)
        ax.annotate(
            f'{map_slug[:6]}\n{profile.canonical_key[:6]}',
            (x_val, y_val), fontsize=4, ha='left', va='bottom', color='#333333',
        )
        plotted_types.add(profile.island_type)

    # Threshold reference lines for known axes
    if feature_x == 'aspect_ratio':
        ax.axvline(2.5, color='#16a085', linestyle='--', linewidth=0.7,
                   alpha=0.5, label='linear threshold (AR=2.5)')
    if feature_x == 'rugosity':
        ax.axvline(1.5, color='#c0392b', linestyle='--', linewidth=0.7,
                   alpha=0.5, label='rugged threshold (rugosity=1.5)')
    if feature_y == 'compactness':
        ax.axhline(0.65, color='#e74c3c', linestyle='--', linewidth=0.7,
                   alpha=0.5, label='circle threshold (comp=0.65)')

    legend_patches = [
        mpatches.Patch(facecolor=_TYPE_COLORS[t], edgecolor='#555555',
                       linewidth=0.5, label=t)
        for t in _ALL_TYPES if t in plotted_types
    ]
    ax.legend(handles=legend_patches, fontsize=8, loc='upper right')

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    plt.savefig(output_path, dpi=130, bbox_inches='tight')
    plt.close(fig)
    logger.info('Saved landscape plot: %s', output_path)


def plot_profile_mosaic(
    all_profiles: list[tuple[str, IslandProfile, dict]],
    island_type_filter: Optional[str],
    output_path_template: str,
) -> list[str]:
    """Island shape mosaic grouped by type.

    Each cell shows one canonical island polygon at normalized scale,
    labeled with map_slug + canonical_key.

    Parameters
    ----------
    all_profiles:
        List of (map_slug, IslandProfile, island_dict) tuples where
        island_dict is the representative island entry from map_context.json.
    island_type_filter:
        If set, only render islands of this type; otherwise render all types.
    output_path_template:
        Path with '{type}' placeholder.  e.g. 'output/images/island_mosaic_{type}.png'

    Returns
    -------
    List of output file paths written.
    """
    # Group by type
    by_type: dict[str, list[tuple[str, IslandProfile, dict]]] = {}
    for map_slug, profile, island_dict in all_profiles:
        if island_type_filter and profile.island_type != island_type_filter:
            continue
        by_type.setdefault(profile.island_type, []).append((map_slug, profile, island_dict))

    output_files: list[str] = []
    for island_type, entries in by_type.items():
        n = len(entries)
        if n == 0:
            continue

        # Sort by primary metric (most characteristic first), then map_slug alphabetically.
        sort_attr, sort_desc = _TYPE_SORT_METRIC.get(island_type, ('compactness', True))
        entries.sort(key=lambda entry: (
            -getattr(entry[1].features, sort_attr) if sort_desc
            else getattr(entry[1].features, sort_attr),
            entry[0],   # map_slug as alphabetical tie-breaker
        ))

        cols = min(6, n)
        rows = math.ceil(n / cols)
        fig, axes = plt.subplots(rows, cols, figsize=(cols * 2.5, rows * 2.5))
        fig.suptitle(f'Island mosaic — {island_type} ({n} shapes)', fontsize=13, fontweight='bold')

        # Flatten axes grid
        if rows == 1 and cols == 1:
            axes_flat = [axes]
        elif rows == 1 or cols == 1:
            axes_flat = list(axes.flat if hasattr(axes, 'flat') else axes)
        else:
            axes_flat = list(axes.flat)

        color = _TYPE_COLORS.get(island_type, '#cccccc')

        for idx, (map_slug, profile, island_dict) in enumerate(entries):
            ax = axes_flat[idx]
            ax.set_aspect('equal')
            ax.axis('off')

            poly = island_dict.get('simplified_polygon') or {}
            exterior = poly.get('exterior') or []
            holes = poly.get('holes') or []

            if len(exterior) >= 3:
                pts = np.asarray(exterior, dtype=float)
                # Normalize to unit square centered at origin
                min_xy = pts.min(axis=0)
                max_xy = pts.max(axis=0)
                scale = max(np.ptp(pts, axis=0).max(), 1.0)
                pts_n = (pts - min_xy) / scale

                from matplotlib.patches import PathPatch
                from matplotlib.path import Path as MplPath
                verts = list(pts_n) + [pts_n[0]]
                codes = [MplPath.MOVETO] + [MplPath.LINETO] * (len(pts_n) - 1) + [MplPath.CLOSEPOLY]
                for hole in holes:
                    if len(hole) >= 3:
                        h_pts = (np.asarray(hole, dtype=float) - min_xy) / scale
                        verts += list(h_pts) + [h_pts[0]]
                        codes += [MplPath.MOVETO] + [MplPath.LINETO] * (len(h_pts) - 1) + [MplPath.CLOSEPOLY]
                path = MplPath(verts, codes)
                patch = PathPatch(path, facecolor=color, alpha=0.6, edgecolor='#333333',
                                  linewidth=0.8)
                ax.add_patch(patch)
                ax.set_xlim(-0.05, 1.05)
                ax.set_ylim(-0.05, 1.05)
                ax.invert_yaxis()

            label = f'{map_slug[:8]}\n{profile.canonical_key[:8]}'
            ax.set_title(label, fontsize=5.5, pad=2)

        # Hide unused axes
        for idx in range(len(entries), len(axes_flat)):
            axes_flat[idx].axis('off')

        out_path = output_path_template.replace('{type}', island_type)
        plt.tight_layout()
        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
        plt.savefig(out_path, dpi=130, bbox_inches='tight')
        plt.close(fig)
        output_files.append(out_path)
        logger.info('Saved mosaic: %s', out_path)

    return output_files


def plot_feature_distributions(
    all_profiles: list[tuple[str, IslandProfile]],
    output_path: str,
) -> None:
    """Feature distribution histograms across all canonical islands from all maps.

    Plots one histogram per numeric feature, stacked by island type.
    Helps choose and validate classification thresholds empirically.
    """
    numeric_features: list[tuple[str, str]] = [
        ('bbox_fill_ratio', 'BBox Fill Ratio'),
        ('rugosity',        'Rugosity'),
        ('aspect_ratio',    'Aspect Ratio'),
        ('compactness',     'Compactness'),
        ('convexity',       'Convexity'),
        ('pca_elongation',  'PCA Elongation'),
    ]

    fig, axes = plt.subplots(1, len(numeric_features), figsize=(5 * len(numeric_features), 5))
    fig.suptitle('Island feature distributions (all maps)', fontsize=13, fontweight='bold')

    # Collect per-type data
    type_data: dict[str, dict[str, list[float]]] = {
        t: {fname: [] for fname, _ in numeric_features}
        for t in _ALL_TYPES
    }
    for _map_slug, profile in all_profiles:
        feat = profile.features
        island_type = profile.island_type
        if island_type not in type_data:
            continue
        for fname, _ in numeric_features:
            val = getattr(feat, fname, None)
            if val is not None:
                type_data[island_type][fname].append(float(val))

    for col_idx, (fname, flabel) in enumerate(numeric_features):
        ax = axes[col_idx]
        ax.set_title(flabel, fontsize=10)
        ax.set_xlabel(flabel)
        if col_idx == 0:
            ax.set_ylabel('Count')

        all_vals = [v for t in _ALL_TYPES for v in type_data[t][fname]]
        if not all_vals:
            continue

        bin_min = min(all_vals)
        bin_max = max(all_vals)
        bins = np.linspace(bin_min, bin_max, 25)

        bottom = np.zeros(len(bins) - 1)
        for island_type in _ALL_TYPES:
            vals = type_data[island_type][fname]
            if not vals:
                continue
            counts, _ = np.histogram(vals, bins=bins)
            ax.bar(
                bins[:-1], counts, width=np.diff(bins),
                bottom=bottom, color=_TYPE_COLORS[island_type],
                alpha=0.85, align='edge', label=island_type,
            )
            bottom += counts

    # Add threshold lines corresponding to classification rules
    axes[0].axvline(0.85, color='#2980b9', linestyle='--', linewidth=1.0,
                    alpha=0.7, label='square/rect (fill=1.0)')
    axes[1].axvline(1.2, color='#c0392b', linestyle='--', linewidth=1.0,
                    alpha=0.7, label='rugged (rugosity≥1.2)')
    axes[2].axvline(2.5, color='#16a085', linestyle='--', linewidth=1.0,
                    alpha=0.7, label='linear (AR≥2.5)')
    axes[4].axvline(0.88, color='#e74c3c', linestyle='--', linewidth=1.0,
                    alpha=0.7, label='circle (convexity≥0.88)')

    legend_patches = [
        mpatches.Patch(facecolor=_TYPE_COLORS[t], edgecolor='#555555',
                       linewidth=0.5, label=t)
        for t in _ALL_TYPES
    ]
    axes[-1].legend(handles=legend_patches, fontsize=7, loc='upper right',
                    bbox_to_anchor=(1.0, 1.0))

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    plt.savefig(output_path, dpi=130, bbox_inches='tight')
    plt.close(fig)
    logger.info('Saved distribution plot: %s', output_path)
