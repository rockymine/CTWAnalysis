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
    'L_shape':   '#8e44ad',   # purple
    'fork':      '#d35400',   # orange
    'rugged':    '#c0392b',   # dark red / coral
    'linear':    '#16a085',   # teal
    'blob':      '#95a5a6',   # gray
}

_ALL_TYPES: list[str] = list(_TYPE_COLORS)


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
    hole_ratio: float         # hole_count / area
    bbox_width: float         # canonical bounding box width  (x extent)
    bbox_height: float        # canonical bounding box height (z extent)
    area: int                 # island block count
    perimeter: float          # polygon exterior perimeter in world units
    bbox_fill_ratio: float    # area / (bbox_width × bbox_height) — 1.0 = perfect rectangle
    rugosity: float           # perimeter / bbox_perimeter — 1.0 = rectangle, >1.0 = jagged
    # Tier B — skeleton-derived (Optional — see docstring)
    skeleton_endpoint_count: Optional[int]
    skeleton_junction_count: Optional[int]
    skeleton_total_length: Optional[float]
    skeleton_topology: Optional[str]   # 'line' | 'tree' | 'mesh' | 'none' | None


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
    """

    canonical_key: str
    island_type: str             # one of _ALL_TYPES
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


def _polygon_area_shoelace(exterior: list[list[float]]) -> float:
    """Shoelace formula area of a simple polygon."""
    pts = np.asarray(exterior, dtype=float)
    if len(pts) < 3:
        return 0.0
    x, y = pts[:, 0], pts[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


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

    return IslandFeatures(
        canonical_key=canonical_key,
        aspect_ratio=round(aspect_ratio, 4),
        compactness=round(compactness, 4),
        convexity=round(convexity, 4),
        pca_elongation=round(pca_elongation, 4),
        pca_angle_deg=round(pca_angle_deg, 2),
        hole_ratio=round(hole_ratio, 6),
        bbox_width=round(bbox_width, 2),
        bbox_height=round(bbox_height, 2),
        area=int(area),
        perimeter=round(perimeter, 2),
        bbox_fill_ratio=round(bbox_fill_ratio, 4),
        rugosity=round(rugosity, 4),
        skeleton_endpoint_count=skel_endpoint_count,
        skeleton_junction_count=skel_junction_count,
        skeleton_total_length=skel_total_length,
        skeleton_topology=skel_topology,
    )


# ---------------------------------------------------------------------------
# Public API — classification
# ---------------------------------------------------------------------------


def classify_island(features: IslandFeatures) -> str:
    """Apply geometry-first rule cascade and return the island_type string.

    Rules are applied in priority order; the first match wins.
    Skeleton features (Tier B) are used only where available — all rules
    degrade gracefully when skeleton data is absent.

    Rule cascade
    ------------
    1. square      bbox_fill_ratio ≥ 0.85 AND aspect_ratio ≤ 1.3 AND convexity ≥ 0.85
    2. rectangle   bbox_fill_ratio ≥ 0.85 AND aspect_ratio > 1.3 AND convexity ≥ 0.85
    3. circle      aspect_ratio ≤ 1.35 AND convexity ≥ 0.88
                   (fill < 0.85 guaranteed here since square/rect already fired for fill ≥ 0.85)
    4. L_shape     skeleton available AND junctions == 1 AND convexity < 0.82
    5. fork        skeleton available AND junctions ≥ 2 AND convexity < 0.70
    6. rugged      rugosity ≥ 1.2 (perimeter noticeably larger than bbox perimeter)
    7. linear      aspect_ratio ≥ 2.5
    8. blob        (default)

    Design notes
    ------------
    - square/rectangle: fill ≥ 0.85 selects only truly rectangular platforms
    - circle: fill < 0.85 is implicit since rules 1/2 already fired; catches round blobs
      whose convexity is ≥ 0.88 (very smooth outline) and aspect_ratio ≤ 1.35
    - fork vs rugged: fork has deep concave gaps (convexity < 0.70); rugged has many
      surface irregularities without deep concavity (convexity ≥ 0.70 but rugosity ≥ 1.2)
    """
    # Rule 1: square — tight rectangular fill, near-square
    if (features.bbox_fill_ratio >= 0.85
            and features.aspect_ratio <= 1.3
            and features.convexity >= 0.85):
        return 'square'

    # Rule 2: rectangle — tight rectangular fill, elongated
    if (features.bbox_fill_ratio >= 0.85
            and features.aspect_ratio > 1.3
            and features.convexity >= 0.85):
        return 'rectangle'

    # Rule 3: circle — round/oval shape (fill < 0.85 guaranteed here).
    # High convexity (≥ 0.88) and low aspect ratio together select smooth, round islands.
    if features.aspect_ratio <= 1.35 and features.convexity >= 0.88:
        return 'circle'

    # Rules 4 & 5: branching shapes — require skeleton data
    junction_count = features.skeleton_junction_count
    if junction_count is not None:
        # Rule 4: L_shape — single junction, concave (one corner/bend)
        if junction_count == 1 and features.convexity < 0.82:
            return 'L_shape'

        # Rule 5: fork — multiple junctions, strongly concave (T/Y/H/complex arm).
        # Threshold 0.70 separates deep-branching forks (convexity 0.48-0.67 in practice)
        # from moderately-irregular shapes better captured by the rugged rule.
        if junction_count >= 2 and features.convexity < 0.70:
            return 'fork'

    # Rule 6: rugged — polygon perimeter noticeably larger than bbox perimeter.
    # Captures irregular/jagged shapes not caught by the fork rule (convexity ≥ 0.70).
    if features.rugosity >= 1.2:
        return 'rugged'

    # Rule 7: linear — elongated corridor
    if features.aspect_ratio >= 2.5:
        return 'linear'

    # Rule 8: blob (default)
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
# Public API — main entry point
# ---------------------------------------------------------------------------


def profile_islands(
    map_context: dict,
    map_graph: dict,
    base_grid_size: int,
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

    profiles: list[IslandProfile] = []
    for canonical_key, group_islands in sorted(groups.items()):
        # Use the first island as the canonical representative for feature extraction
        representative = group_islands[0]
        island_id = representative['id']
        raw_island_ids = sorted(isl['id'] for isl in group_islands)

        graph_dict = graph_by_id.get(island_id)
        features = extract_island_features(canonical_key, representative, graph_dict)
        island_type = classify_island(features)
        raster_strategy = build_raster_strategy(island_type, features, base_grid_size)

        profiles.append(IslandProfile(
            canonical_key=canonical_key,
            island_type=island_type,
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
            'raw_island_ids': profile.raw_island_ids,
            'features': {
                'canonical_key': feat.canonical_key,
                'aspect_ratio': feat.aspect_ratio,
                'compactness': feat.compactness,
                'convexity': feat.convexity,
                'pca_elongation': feat.pca_elongation,
                'pca_angle_deg': feat.pca_angle_deg,
                'hole_ratio': feat.hole_ratio,
                'bbox_width': feat.bbox_width,
                'bbox_height': feat.bbox_height,
                'area': feat.area,
                'perimeter': feat.perimeter,
                'bbox_fill_ratio': feat.bbox_fill_ratio,
                'rugosity': feat.rugosity,
                'skeleton_endpoint_count': feat.skeleton_endpoint_count,
                'skeleton_junction_count': feat.skeleton_junction_count,
                'skeleton_total_length': feat.skeleton_total_length,
                'skeleton_topology': feat.skeleton_topology,
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
                hole_ratio=feat_d['hole_ratio'],
                bbox_width=feat_d['bbox_width'],
                bbox_height=feat_d['bbox_height'],
                area=feat_d.get('area', 0),
                perimeter=feat_d.get('perimeter', 0.0),
                bbox_fill_ratio=feat_d.get('bbox_fill_ratio', 0.0),
                rugosity=feat_d.get('rugosity', 0.0),
                skeleton_endpoint_count=feat_d.get('skeleton_endpoint_count'),
                skeleton_junction_count=feat_d.get('skeleton_junction_count'),
                skeleton_total_length=feat_d.get('skeleton_total_length'),
                skeleton_topology=feat_d.get('skeleton_topology'),
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
                    alpha=0.7, label='square/rect (fill≥0.85)')
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
