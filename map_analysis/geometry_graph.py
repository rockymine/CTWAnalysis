"""Geometry-derived navigation graph from GridBase cell adjacency.

Builds a 4-connected adjacency graph from a GridBase — one node per
rasterized grid cell, edges between face-adjacent cells.  No player data
is required.  This graph captures the theoretical maximum connectivity of
the map geometry and can be used as a geometry-only navigation graph or
as a seed for build_traffic_graph().

An alternative adaptive builder is also provided:
    build_adaptive_geometry_graph() — symmetric hex-grid sampling with
    Delaunay triangulation edges, giving approximately equidistant nodes
    that respect the full polygon geometry rather than a fixed cell size.

Node and edge schema is identical to the traffic graph so that all
downstream consumers (build_traffic_topology, plot_traffic_graph, etc.)
work without modification.

Typical usage (CLI):
    python ctw.py maps geometry-graph --map tumbleweed
    python ctw.py maps geometry-graph --map tumbleweed --adaptive-nodes

Output:
    output/<map_slug>/geometry_graph.json
    output/<map_slug>/adaptive_graph.json   (--adaptive-nodes)
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Optional

import numpy as np
from shapely import STRtree
from shapely import points as shp_points
from shapely.geometry import Polygon

from map_analysis.grid_base import GridBase

logger = logging.getLogger("ctw")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build_geometry_graph(
    grid_base: GridBase,
    wool_pois: Optional[list[dict]] = None,
) -> dict:
    """Build a 4-connected adjacency graph from GridBase cells.

    Each cell in grid_base becomes a node.  Edges connect cells that
    differ by exactly grid_size in x or z (face-adjacent in the grid).
    Wool and spawn anchors are injected as fixed nodes following the same
    logic as build_traffic_graph step 7.

    Parameters
    ----------
    grid_base:
        Rasterized map geometry produced by rasterize_map_polygons().
    wool_pois:
        Override list of wool anchor dicts.  When None, grid_base.wool_pois
        is used (map_context positions).  Pass a DB-sourced list (e.g. from
        _load_wool_pois_from_db) for more accurate wool placement.
        Each dict must have keys: poi_type, coords, team, poi_color, island_id.

    Returns
    -------
    Plain dict in the same schema as traffic_graph.json, plus
    ``"source": "geometry"`` to distinguish it from a data-driven graph.
    Node occupation is 0 for all geometry-derived nodes (no player data).
    Edge transitions is 1 for all adjacency edges.
    """
    grid_size = grid_base.grid_size
    valid_cell_set = grid_base.valid_cell_set
    cell_island_id = grid_base.cell_island_id

    # ── 1. Assign node IDs (sorted for deterministic output) ──────────────
    sorted_cells = sorted(valid_cell_set)
    cell_to_node: dict[tuple[int, int], int] = {
        cell: node_id for node_id, cell in enumerate(sorted_cells)
    }

    # ── 2. Build 4-connected edges ─────────────────────────────────────────
    # Check only the two positive-direction neighbours to avoid double-counting.
    edges: list[dict] = []
    for cx, cz in sorted_cells:
        for ncx, ncz in ((cx + grid_size, cz), (cx, cz + grid_size)):
            if (ncx, ncz) in valid_cell_set:
                src = cell_to_node[(cx, cz)]
                dst = cell_to_node[(ncx, ncz)]
                edges.append({"src": src, "dst": dst, "transitions": 1})

    # ── 3. Serialise base nodes ────────────────────────────────────────────
    nodes: list[dict] = []
    for (cx, cz), node_id in sorted(cell_to_node.items(), key=lambda kv: kv[1]):
        nodes.append({
            "node_id":    node_id,
            "cx":         cx,
            "cz":         cz,
            "coords":     [cx + grid_size / 2.0, cz + grid_size / 2.0],
            "occupation": 0,
            "island_id":  cell_island_id.get((cx, cz)),
            "poi_type":   None,
            "poi_color":  None,
            "team":       None,
            "fixed":      False,
        })

    # ── 4. Inject wool and spawn anchor nodes ──────────────────────────────
    # Mirrors build_traffic_graph step 7: annotate existing cell nodes or
    # create new fixed nodes connected to their 3 nearest neighbours.
    poi_sources: list[dict] = list(
        wool_pois if wool_pois is not None else grid_base.wool_pois
    ) + list(grid_base.spawn_pois)

    # Build node lookup by id for annotation
    node_by_id: dict[int, dict] = {n["node_id"]: n for n in nodes}
    next_id = len(nodes)
    # Keep edge_list mutable for synthetic POI edges
    extra_edges: list[dict] = []

    for poi in poi_sources:
        coords = poi.get("coords")
        if not coords:
            continue
        fx, fz = float(coords[0]), float(coords[1])
        fcx = int(fx // grid_size * grid_size)
        fcz = int(fz // grid_size * grid_size)

        if (fcx, fcz) in cell_to_node:
            # Annotate the existing node
            nid = cell_to_node[(fcx, fcz)]
            node = node_by_id[nid]
            node["poi_type"]  = poi.get("poi_type")
            node["poi_color"] = poi.get("poi_color")
            node["team"]      = poi.get("team")
            node["fixed"]     = True
        else:
            # Create a new fixed node for this anchor
            new_node: dict = {
                "node_id":    next_id,
                "cx":         fcx,
                "cz":         fcz,
                "coords":     [fx, fz],
                "occupation": 0,
                "island_id":  poi.get("island_id"),
                "poi_type":   poi.get("poi_type"),
                "poi_color":  poi.get("poi_color"),
                "team":       poi.get("team"),
                "fixed":      True,
            }
            nodes.append(new_node)
            node_by_id[next_id] = new_node
            cell_to_node[(fcx, fcz)] = next_id

            # Connect to 3 nearest existing nodes by Euclidean distance
            existing = [
                (cx, cz)
                for (cx, cz) in cell_to_node
                if (cx, cz) != (fcx, fcz)
            ]
            if existing:
                existing_arr = np.array(
                    [[cx + grid_size / 2, cz + grid_size / 2] for cx, cz in existing]
                )
                center = np.array([fx, fz])
                dists = np.linalg.norm(existing_arr - center, axis=1)
                k = min(3, len(dists))
                for nbr_idx in np.argsort(dists)[:k]:
                    nbr_cx, nbr_cz = existing[int(nbr_idx)]
                    nbr_id = cell_to_node.get((nbr_cx, nbr_cz))
                    if nbr_id is not None and nbr_id != next_id:
                        src_id = min(next_id, nbr_id)
                        dst_id = max(next_id, nbr_id)
                        extra_edges.append({
                            "src": src_id,
                            "dst": dst_id,
                            "transitions": 1,
                        })
            next_id += 1

    all_edges = edges + extra_edges

    graph = {
        "source":             "geometry",
        "map_slug":           grid_base.map_slug,
        "grid_size":          grid_size,
        "cell_count":         len(sorted_cells),
        # Presence of these keys keeps plot_traffic_graph() happy (it uses them
        # for title/subtitle formatting and guards against missing values).
        "match_count":        0,
        "position_count":     0,
        "player_count":       0,
        "total_playtime_min": None,
        "nodes":              nodes,
        "edges":              all_edges,
    }

    logger.info(
        "Geometry graph '%s': %d nodes, %d edges  (grid_size=%d)",
        grid_base.map_slug, len(nodes), len(all_edges), grid_size,
    )
    return graph


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def save_geometry_graph(graph: dict, path: Path) -> None:
    """Write geometry graph dict to path as indented JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(graph, fh, indent=2)
    logger.debug("Saved geometry graph → %s", path)


# ---------------------------------------------------------------------------
# Adaptive (experimental): symmetric hex-grid sampling + Delaunay edges
# ---------------------------------------------------------------------------


def build_adaptive_geometry_graph(
    grid_base: GridBase,
    map_context: dict,
    n_target: int = 300,
    wool_pois: Optional[list[dict]] = None,
    symmetry_info: Optional[dict] = None,
) -> dict:
    """Build a geometry-aware node graph using symmetric hex-grid sampling.

    Experimental alternative to build_geometry_graph().  Instead of a fixed
    N×N grid, places nodes on a hexagonal lattice anchored at the map centre
    and clipped to the union of all playable polygons (islands + build regions).
    Connectivity is derived from Delaunay triangulation; edges that
    significantly cross void territory are pruned.

    Symmetry enforcement removes candidate points whose mirror counterparts
    did not survive the polygon containment check (polygon simplification can
    introduce floating-point asymmetries at boundaries).  The enforcement
    strategy is derived from ``symmetry_info`` if supplied; if absent, all
    of mirror_x, mirror_z, and rot_180 are enforced as a conservative default.

    Parameters
    ----------
    grid_base:
        Provides map_slug, wool_pois, spawn_pois.  Grid geometry is not used.
    map_context:
        Parsed map_context.json — source of raw polygon geometry and map_center.
    n_target:
        Approximate target node count.  Hex-grid spacing is derived from
        ``sqrt(2 * playable_area / (sqrt(3) * n_target))``.  Actual count
        depends on polygon coverage.
    wool_pois:
        Override wool anchor list (same semantics as build_geometry_graph).
    symmetry_info:
        Parsed symmetry.json dict (from ``output/<map>/symmetry.json``).
        When provided, only detected symmetry types are enforced on the node
        set.  When None, mirror_x, mirror_z, and rot_180 are all enforced.

    Returns
    -------
    Plain dict with the same schema as traffic_graph.json plus
    ``"source": "adaptive"``.  ``grid_size`` is None (no fixed cell size).
    """
    try:
        from scipy.spatial import Delaunay as _Delaunay  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "build_adaptive_geometry_graph requires scipy. "
            "Install with: pip install scipy"
        ) from exc

    from shapely.ops import unary_union as _unary_union
    from shapely.geometry import Point as _Point

    map_slug = grid_base.map_slug

    # ── 1. Build playable polygon (islands ∪ build regions) ───────────────
    polys: list[Polygon] = []
    for isl in map_context.get("islands", []):
        poly_data = isl.get("simplified_polygon") or {}
        exterior = poly_data.get("exterior", [])
        if len(exterior) < 3:
            continue
        holes = [h for h in poly_data.get("holes", []) if len(h) >= 3]
        try:
            poly = Polygon(exterior, holes)
            if poly.is_valid:
                polys.append(poly)
        except Exception:
            pass

    build_region = map_context.get("build_region")
    if build_region:
        for poly_data in build_region.get("buildable_void", []):
            exterior = poly_data.get("exterior", [])
            if len(exterior) < 3:
                continue
            holes = [h for h in poly_data.get("holes", []) if len(h) >= 3]
            try:
                poly = Polygon(exterior, holes)
                if poly.is_valid:
                    polys.append(poly)
            except Exception:
                pass

    if not polys:
        logger.warning(
            "build_adaptive_geometry_graph('%s'): no polygons found; "
            "returning empty graph",
            map_slug,
        )
        return {
            "source": "adaptive", "map_slug": map_slug, "grid_size": None,
            "cell_count": 0, "match_count": 0, "position_count": 0,
            "player_count": 0, "total_playtime_min": None,
            "nodes": [], "edges": [],
        }

    playable = _unary_union(polys)
    if not playable.is_valid:
        playable = playable.buffer(0)

    # ── 2. Hex grid anchored at both symmetry axes ────────────────────────
    # Spacing formula: hex cell area = (sqrt(3)/2) * spacing²
    # → spacing = sqrt(2 * polygon_area / (sqrt(3) * n_target))
    raw_center = map_context.get("map_center", [0, 0])
    axis_x = float(raw_center[0])
    axis_z = float(raw_center[1])
    area = float(playable.area)
    spacing = math.sqrt(2.0 * area / (math.sqrt(3) * max(n_target, 1)))
    row_height = spacing * math.sqrt(3) / 2.0

    minx, miny, maxx, maxy = playable.bounds

    _R = 6   # rounding precision (decimal places) used throughout

    def _row_candidates(z: float, row_parity: int) -> list[tuple[float, float]]:
        """Return x-symmetric candidate points for one row at height z.

        All coordinates are rounded to _R decimal places so that mirror-point
        lookups in inside_set produce exact matches despite floating-point
        accumulation in the loop counters.
        """
        pts: list[tuple[float, float]] = []
        x_off = 0.0 if row_parity == 0 else spacing / 2.0
        # Right side (including axis point for even rows)
        x = axis_x + x_off
        while x <= maxx + spacing:
            pts.append((round(x, _R), round(z, _R)))
            x += spacing
        # Left side (mirror; for odd rows x_off > 0 so the right side
        # already skips axis_x, meaning axis_x - x_off is the first left pt)
        x = axis_x - x_off - (0.0 if x_off > 0 else spacing)
        while x >= minx - spacing:
            pts.append((round(x, _R), round(z, _R)))
            x -= spacing
        return pts

    # Generate rows upward from axis_z, then mirror downward.  Row k going
    # up has parity k%2; row k going down mirrors row k up, so same parity
    # → same x-structure → z-symmetry is structurally guaranteed.
    candidates: list[tuple[float, float]] = []
    row = 0
    y = axis_z
    while y <= maxy + row_height:
        candidates.extend(_row_candidates(y, row % 2))
        row += 1
        y += row_height
    row = 1
    y = axis_z - row_height
    while y >= miny - row_height:
        candidates.extend(_row_candidates(y, row % 2))
        row += 1
        y -= row_height

    if not candidates:
        logger.warning(
            "build_adaptive_geometry_graph('%s'): no candidate grid points generated",
            map_slug,
        )
        return build_geometry_graph(grid_base, wool_pois=wool_pois)

    # ── 3. Bulk containment via STRtree ───────────────────────────────────
    cand_arr = np.array(candidates)
    pts_geom = shp_points(cand_arr[:, 0], cand_arr[:, 1])

    if hasattr(playable, "geoms"):
        tree_polys: list = list(playable.geoms)
    else:
        tree_polys = [playable]
    play_tree = STRtree(tree_polys)
    result = play_tree.query(pts_geom, predicate="within")
    inside_mask = np.zeros(len(candidates), dtype=bool)
    if result.shape[1] > 0:
        inside_mask[result[0]] = True

    # ── 3b. Enforce detected symmetry ────────────────────────────────────
    # The hex grid is structurally symmetric around (axis_x, axis_z), but
    # the polygon `within` check is strict — a boundary point and its mirror
    # may disagree due to floating-point imprecision in the simplified polygon
    # vertices.  Fix: keep a point only if all mirrors for each detected
    # symmetry type are also inside.
    #
    # Symmetry types considered:
    #   mirror_x  — reflect across vertical axis (x = axis_x)
    #   mirror_z  — reflect across horizontal axis (z = axis_z)
    #   rot_180   — 180° rotation around map centre
    #
    # If symmetry_info is not supplied, all three are enforced (conservative).
    if symmetry_info is not None:
        detected = {
            entry["type"]
            for entry in symmetry_info.get("global_symmetry", [])
            if entry.get("detected", False)
        }
    else:
        detected = {"mirror_x", "mirror_z", "rot_180"}

    do_mirror_x = "mirror_x" in detected
    do_mirror_z = "mirror_z" in detected
    do_rot_180  = "rot_180"  in detected

    # All coordinates are pre-rounded to _R dp; mirror coords are rounded the
    # same way so dict lookups match regardless of floating-point path.
    inside_set: frozenset[tuple[float, float]] = frozenset(
        (float(cand_arr[i, 0]), float(cand_arr[i, 1]))
        for i in range(len(candidates))
        if inside_mask[i]
    )
    sym_mask = np.zeros(len(candidates), dtype=bool)
    for i in range(len(candidates)):
        if not inside_mask[i]:
            continue
        px = float(cand_arr[i, 0])
        pz = float(cand_arr[i, 1])
        mx = round(2.0 * axis_x - px, _R)
        mz = round(2.0 * axis_z - pz, _R)
        on_x_axis = abs(mx - px) < 1e-9
        on_z_axis = abs(mz - pz) < 1e-9

        keep = True
        if do_mirror_x:
            keep = keep and (on_x_axis or (mx, pz) in inside_set)
        if do_mirror_z:
            keep = keep and (on_z_axis or (px, mz) in inside_set)
        if do_rot_180:
            keep = keep and ((on_x_axis and on_z_axis) or (mx, mz) in inside_set)
        if keep:
            sym_mask[i] = True

    inside_arr = cand_arr[sym_mask]

    if len(inside_arr) == 0:
        logger.warning(
            "build_adaptive_geometry_graph('%s'): zero points survived containment check",
            map_slug,
        )
        return build_geometry_graph(grid_base, wool_pois=wool_pois)

    # ── 4. Assign island_id to each point ─────────────────────────────────
    island_polys: list[tuple[int, Polygon]] = []
    for isl in map_context.get("islands", []):
        poly_data = isl.get("simplified_polygon") or {}
        exterior = poly_data.get("exterior", [])
        if len(exterior) < 3:
            continue
        holes = [h for h in poly_data.get("holes", []) if len(h) >= 3]
        try:
            poly = Polygon(exterior, holes)
            if poly.is_valid:
                island_polys.append((isl["id"], poly))
        except Exception:
            pass

    island_id_arr: list[Optional[int]] = [None] * len(inside_arr)
    if island_polys:
        isl_tree = STRtree([p for _, p in island_polys])
        isl_ids = [iid for iid, _ in island_polys]
        pts_in = shp_points(inside_arr[:, 0], inside_arr[:, 1])
        res2 = isl_tree.query(pts_in, predicate="within")
        if res2.shape[1] > 0:
            for pi, gi in zip(res2[0], res2[1]):
                if island_id_arr[int(pi)] is None:
                    island_id_arr[int(pi)] = isl_ids[int(gi)]

    # ── 5. Build node list ─────────────────────────────────────────────────
    nodes: list[dict] = []
    for idx in range(len(inside_arr)):
        px, pz = float(inside_arr[idx, 0]), float(inside_arr[idx, 1])
        nodes.append({
            "node_id":    idx,
            "cx":         round(px),
            "cz":         round(pz),
            "coords":     [px, pz],
            "occupation": 0,
            "island_id":  island_id_arr[idx],
            "poi_type":   None,
            "poi_color":  None,
            "team":       None,
            "fixed":      False,
        })

    # ── 6. Delaunay triangulation + void-crossing edge pruning ────────────
    edges: list[dict] = []
    if len(inside_arr) >= 3:
        tri = _Delaunay(inside_arr)
        seen_edges: set[tuple[int, int]] = set()
        # Max edge length guard: reject edges longer than 2.5× spacing
        # (these connect nodes across wide void gaps in the triangulation hull)
        max_edge_len_sq = (spacing * 2.5) ** 2
        for simplex in tri.simplices:
            for i, j in ((0, 1), (1, 2), (0, 2)):
                a, b = int(simplex[i]), int(simplex[j])
                if a > b:
                    a, b = b, a
                if (a, b) in seen_edges:
                    continue
                seen_edges.add((a, b))
                pa, pb = inside_arr[a], inside_arr[b]
                # Fast length guard (avoids shapely for obviously bad edges)
                dx, dz = float(pa[0] - pb[0]), float(pa[1] - pb[1])
                if dx * dx + dz * dz > max_edge_len_sq:
                    continue
                # Sample 4 interior points along the edge; prune if any is
                # outside the playable polygon (edge crosses void)
                inside_edge = True
                for k in (1, 2, 3, 4):
                    t = k / 5.0
                    mx = pa[0] * (1 - t) + pb[0] * t
                    mz = pa[1] * (1 - t) + pb[1] * t
                    if not playable.contains(_Point(mx, mz)):
                        inside_edge = False
                        break
                if inside_edge:
                    edges.append({"src": a, "dst": b, "transitions": 1})

    # ── 7. Inject wool and spawn anchor nodes ──────────────────────────────
    poi_sources: list[dict] = list(
        wool_pois if wool_pois is not None else grid_base.wool_pois
    ) + list(grid_base.spawn_pois)

    node_by_id: dict[int, dict] = {n["node_id"]: n for n in nodes}
    next_id = len(nodes)
    extra_edges: list[dict] = []

    pts_arr = np.array([[n["coords"][0], n["coords"][1]] for n in nodes]) if nodes else np.empty((0, 2))

    for poi in poi_sources:
        coords = poi.get("coords")
        if not coords or len(pts_arr) == 0:
            continue
        fx, fz = float(coords[0]), float(coords[1])
        dists = np.linalg.norm(pts_arr - np.array([fx, fz]), axis=1)
        nearest_idx = int(np.argmin(dists))

        if dists[nearest_idx] < spacing * 0.6:
            # Annotate the closest existing node
            node = node_by_id[nearest_idx]
            node["poi_type"]  = poi.get("poi_type")
            node["poi_color"] = poi.get("poi_color")
            node["team"]      = poi.get("team")
            node["fixed"]     = True
        else:
            # New fixed node connected to 3 nearest
            new_node: dict = {
                "node_id":    next_id,
                "cx":         round(fx),
                "cz":         round(fz),
                "coords":     [fx, fz],
                "occupation": 0,
                "island_id":  poi.get("island_id"),
                "poi_type":   poi.get("poi_type"),
                "poi_color":  poi.get("poi_color"),
                "team":       poi.get("team"),
                "fixed":      True,
            }
            nodes.append(new_node)
            node_by_id[next_id] = new_node
            for nbr_idx in np.argsort(dists)[:min(3, len(dists))]:
                nbr_id = int(nbr_idx)
                src_id = min(next_id, nbr_id)
                dst_id = max(next_id, nbr_id)
                extra_edges.append({"src": src_id, "dst": dst_id, "transitions": 1})
            next_id += 1

    all_edges = edges + extra_edges

    graph = {
        "source":             "adaptive",
        "map_slug":           map_slug,
        "grid_size":          None,
        "cell_count":         len(inside_arr),
        "match_count":        0,
        "position_count":     0,
        "player_count":       0,
        "total_playtime_min": None,
        "nodes":              nodes,
        "edges":              all_edges,
    }

    logger.info(
        "Adaptive geometry graph '%s': %d nodes, %d edges  "
        "(target=%d, spacing=%.1f)",
        map_slug, len(nodes), len(all_edges), n_target, spacing,
    )
    return graph


# ---------------------------------------------------------------------------
# Contour (experimental): boundary-first shell sampling + hex fill
# ---------------------------------------------------------------------------


def _sample_ring(ring: Any, spacing: float) -> list[tuple[float, float]]:
    """Sample a Shapely ring at approximately *spacing* arc-length intervals."""
    length = ring.length
    if length < 1e-6:
        return []
    n = max(1, round(length / spacing))
    step = length / n
    return [(ring.interpolate(k * step).x, ring.interpolate(k * step).y)
            for k in range(n)]


def _contour_shells(
    polygon: Polygon,
    spacing: float,
    shell_gap: float,
) -> list[tuple[float, float]]:
    """Sample concentric eroded shells of *polygon*.

    Iterates: sample exterior ring → erode by *shell_gap* → repeat.
    Stops when the remaining geometry is too small to yield a perimeter
    sample.  Handles MultiPolygon fragments produced by erosion.
    """
    pts: list[tuple[float, float]] = []
    current: Any = polygon
    while current is not None and not current.is_empty:
        pieces: list[Polygon] = (
            list(current.geoms) if hasattr(current, "geoms") else [current]
        )
        sampled_any = False
        for piece in pieces:
            if piece.is_empty or piece.area < (spacing * 0.4) ** 2:
                continue
            pts.extend(_sample_ring(piece.exterior, spacing))
            sampled_any = True
        if not sampled_any:
            break
        next_shell: Any = current.buffer(-shell_gap)
        if not next_shell.is_valid:
            next_shell = next_shell.buffer(0)
        current = next_shell
    return pts


def build_contour_geometry_graph(
    grid_base: GridBase,
    map_context: dict,
    wool_pois: Optional[list[dict]] = None,
    symmetry_info: Optional[dict] = None,
) -> dict:
    """Build a geometry graph with boundary-first (contour shell) node placement.

    Experimental alternative to the adaptive hex-grid builder.  Island
    polygons are sampled in concentric eroded shells — outermost boundary
    first, working inward — giving denser coverage at island edges where
    combat near the void occurs.  The build region is filled with a hex
    grid anchored at the map centre (same approach as adaptive).

    Spacing is taken directly from ``grid_base.grid_size`` so node density
    is consistent with the regular geometry graph for the same map.

    Symmetry is enforced by explicitly adding the mirror of every generated
    node under each detected symmetry transform, then relying on
    containment + deduplication to clean up.  This guarantees a symmetric
    output without tolerance tuning, and never discards edge nodes.

    Parameters
    ----------
    grid_base:
        Provides map_slug, grid_size, wool_pois, spawn_pois.
    map_context:
        Parsed map_context.json — polygon geometry and map_center.
    wool_pois:
        Override wool anchor list (same semantics as other graph builders).
    symmetry_info:
        Parsed symmetry.json dict.  When None, all symmetry types are enforced.

    Returns
    -------
    Plain dict with the same schema as traffic_graph.json plus
    ``"source": "contour"``.  ``grid_size`` is None (no fixed cell size).
    """
    try:
        from scipy.spatial import Delaunay as _Delaunay, cKDTree as _cKDTree
    except ImportError as exc:
        raise ImportError(
            "build_contour_geometry_graph requires scipy. "
            "Install with: pip install scipy"
        ) from exc

    from shapely.ops import unary_union as _unary_union
    from shapely.geometry import Point as _Point

    map_slug = grid_base.map_slug
    # Use the same spacing as the grid mode for consistent node density.
    spacing = float(grid_base.grid_size)
    shell_gap = spacing * math.sqrt(3) / 2.0   # hex row height

    # ── 1. Build island and build-region polygon lists ─────────────────────
    island_polys: list[tuple[int, Polygon]] = []
    for isl in map_context.get("islands", []):
        poly_data = isl.get("simplified_polygon") or {}
        exterior = poly_data.get("exterior", [])
        if len(exterior) < 3:
            continue
        holes = [h for h in poly_data.get("holes", []) if len(h) >= 3]
        try:
            poly = Polygon(exterior, holes)
            if poly.is_valid:
                island_polys.append((isl["id"], poly))
        except Exception:
            pass

    build_polys: list[Polygon] = []
    build_region = map_context.get("build_region")
    if build_region:
        for poly_data in build_region.get("buildable_void", []):
            exterior = poly_data.get("exterior", [])
            if len(exterior) < 3:
                continue
            holes = [h for h in poly_data.get("holes", []) if len(h) >= 3]
            try:
                poly = Polygon(exterior, holes)
                if poly.is_valid:
                    build_polys.append(poly)
            except Exception:
                pass

    all_polys = [p for _, p in island_polys] + build_polys
    if not all_polys:
        logger.warning(
            "build_contour_geometry_graph('%s'): no polygons found; "
            "returning empty graph",
            map_slug,
        )
        return {
            "source": "contour", "map_slug": map_slug, "grid_size": None,
            "cell_count": 0, "match_count": 0, "position_count": 0,
            "player_count": 0, "total_playtime_min": None,
            "nodes": [], "edges": [],
        }

    playable: Any = _unary_union(all_polys)
    if not playable.is_valid:
        playable = playable.buffer(0)

    raw_center = map_context.get("map_center", [0, 0])
    axis_x = float(raw_center[0])
    axis_z = float(raw_center[1])

    # ── 2. Island contour shells ───────────────────────────────────────────
    pts: list[tuple[float, float]] = []
    for _, island_poly in island_polys:
        pts.extend(_contour_shells(island_poly, spacing, shell_gap))

    # ── 3. Build-region hex-grid fill ─────────────────────────────────────
    if build_polys:
        build_union: Any = _unary_union(build_polys)
        if not build_union.is_valid:
            build_union = build_union.buffer(0)
        bminx, bminy, bmaxx, bmaxy = build_union.bounds
        _R_b = 6

        def _brow(z: float, parity: int) -> list[tuple[float, float]]:
            x_off = 0.0 if parity == 0 else spacing / 2.0
            row_pts: list[tuple[float, float]] = []
            x = axis_x + x_off
            while x <= bmaxx + spacing:
                row_pts.append((round(x, _R_b), round(z, _R_b)))
                x += spacing
            x = axis_x - x_off - (0.0 if x_off > 0 else spacing)
            while x >= bminx - spacing:
                row_pts.append((round(x, _R_b), round(z, _R_b)))
                x -= spacing
            return row_pts

        build_cands: list[tuple[float, float]] = []
        r, y = 0, axis_z
        while y <= bmaxy + shell_gap:
            build_cands.extend(_brow(y, r % 2)); r += 1; y += shell_gap
        r, y = 1, axis_z - shell_gap
        while y >= bminy - shell_gap:
            build_cands.extend(_brow(y, r % 2)); r += 1; y -= shell_gap

        if build_cands:
            bc_arr = np.array(build_cands)
            bc_pts = shp_points(bc_arr[:, 0], bc_arr[:, 1])
            build_pieces: list = (
                list(build_union.geoms) if hasattr(build_union, "geoms")
                else [build_union]
            )
            bc_res = STRtree(build_pieces).query(bc_pts, predicate="within")
            if bc_res.shape[1] > 0:
                for idx in set(bc_res[0]):
                    pts.append((float(bc_arr[idx, 0]), float(bc_arr[idx, 1])))

    if not pts:
        logger.warning(
            "build_contour_geometry_graph('%s'): no points generated",
            map_slug,
        )
        return build_geometry_graph(grid_base, wool_pois=wool_pois)

    # ── 4. Add explicit mirrors for each detected symmetry ─────────────────
    # Instead of dropping nodes that lack a close mirror (which silently
    # removes edge nodes when arc-length sampling starts at different ring
    # vertices on two mirror islands), we ADD the mirror of every node.
    # Mirrors that fall in void are removed by the containment check below.
    if symmetry_info is not None:
        detected_sym = {
            entry["type"]
            for entry in symmetry_info.get("global_symmetry", [])
            if entry.get("detected", False)
        }
    else:
        detected_sym = {"mirror_x", "mirror_z", "rot_180"}

    do_mx   = "mirror_x" in detected_sym
    do_mz   = "mirror_z" in detected_sym
    do_r180 = "rot_180"  in detected_sym

    mirror_additions: list[tuple[float, float]] = []
    for px, pz in pts:
        mx = 2.0 * axis_x - px
        mz = 2.0 * axis_z - pz
        if do_mx and abs(mx - px) > 1e-6:
            mirror_additions.append((mx, pz))
        if do_mz and abs(mz - pz) > 1e-6:
            mirror_additions.append((px, mz))
        if do_r180 and (abs(mx - px) > 1e-6 or abs(mz - pz) > 1e-6):
            mirror_additions.append((mx, mz))
    pts.extend(mirror_additions)

    # ── 5. Containment check ──────────────────────────────────────────────
    # Outward buffer ensures boundary-coincident perimeter pts pass `within`.
    # Also removes mirror points that fell outside the playable polygon.
    pts_arr = np.array(pts)
    playable_buf: Any = playable.buffer(0.1)
    play_pieces: list = (
        list(playable_buf.geoms) if hasattr(playable_buf, "geoms")
        else [playable_buf]
    )
    cont_result = STRtree(play_pieces).query(
        shp_points(pts_arr[:, 0], pts_arr[:, 1]), predicate="within"
    )
    in_mask = np.zeros(len(pts_arr), dtype=bool)
    if cont_result.shape[1] > 0:
        in_mask[cont_result[0]] = True
    pts_arr = pts_arr[in_mask]

    if len(pts_arr) == 0:
        logger.warning(
            "build_contour_geometry_graph('%s'): zero points after containment",
            map_slug,
        )
        return build_geometry_graph(grid_base, wool_pois=wool_pois)

    # ── 6. Deduplicate within spacing * 0.4 ───────────────────────────────
    # Mirrors of existing nodes and nodes from mirror islands both contribute;
    # near-duplicate pairs are collapsed here.
    dedup_tree = _cKDTree(pts_arr)
    pairs = dedup_tree.query_pairs(spacing * 0.4)
    keep_mask = np.ones(len(pts_arr), dtype=bool)
    for a, b in sorted(pairs):
        if keep_mask[a] and keep_mask[b]:
            keep_mask[b] = False
    pts_arr = pts_arr[keep_mask]

    # ── 7. Assign island_id ────────────────────────────────────────────────
    island_id_list: list[Optional[int]] = [None] * len(pts_arr)
    if island_polys:
        isl_strtree = STRtree([p for _, p in island_polys])
        isl_ids = [iid for iid, _ in island_polys]
        res_isl = isl_strtree.query(
            shp_points(pts_arr[:, 0], pts_arr[:, 1]), predicate="within"
        )
        if res_isl.shape[1] > 0:
            for pi, gi in zip(res_isl[0], res_isl[1]):
                if island_id_list[int(pi)] is None:
                    island_id_list[int(pi)] = isl_ids[int(gi)]

    # ── 9. Build node list ─────────────────────────────────────────────────
    nodes: list[dict] = []
    for idx in range(len(pts_arr)):
        px, pz = float(pts_arr[idx, 0]), float(pts_arr[idx, 1])
        nodes.append({
            "node_id":    idx,
            "cx":         round(px),
            "cz":         round(pz),
            "coords":     [px, pz],
            "occupation": 0,
            "island_id":  island_id_list[idx],
            "poi_type":   None,
            "poi_color":  None,
            "team":       None,
            "fixed":      False,
        })

    # ── 10. Delaunay triangulation + void-crossing edge pruning ────────────
    edges: list[dict] = []
    if len(pts_arr) >= 3:
        tri = _Delaunay(pts_arr)
        seen_edges: set[tuple[int, int]] = set()
        max_len_sq = (spacing * 2.5) ** 2
        for simplex in tri.simplices:
            for i, j in ((0, 1), (1, 2), (0, 2)):
                a, b = int(simplex[i]), int(simplex[j])
                if a > b:
                    a, b = b, a
                if (a, b) in seen_edges:
                    continue
                seen_edges.add((a, b))
                pa, pb = pts_arr[a], pts_arr[b]
                dx, dz = float(pa[0] - pb[0]), float(pa[1] - pb[1])
                if dx * dx + dz * dz > max_len_sq:
                    continue
                inside_edge = True
                for k in (1, 2, 3, 4):
                    t = k / 5.0
                    if not playable.contains(
                        _Point(pa[0] * (1 - t) + pb[0] * t,
                               pa[1] * (1 - t) + pb[1] * t)
                    ):
                        inside_edge = False
                        break
                if inside_edge:
                    edges.append({"src": a, "dst": b, "transitions": 1})

    # ── 11. POI injection ──────────────────────────────────────────────────
    poi_sources: list[dict] = list(
        wool_pois if wool_pois is not None else grid_base.wool_pois
    ) + list(grid_base.spawn_pois)

    node_by_id: dict[int, dict] = {n["node_id"]: n for n in nodes}
    next_id = len(nodes)
    extra_edges: list[dict] = []
    pts_for_poi = (
        np.array([[n["coords"][0], n["coords"][1]] for n in nodes])
        if nodes else np.empty((0, 2))
    )

    for poi in poi_sources:
        coords = poi.get("coords")
        if not coords or len(pts_for_poi) == 0:
            continue
        fx, fz = float(coords[0]), float(coords[1])
        dists = np.linalg.norm(pts_for_poi - np.array([fx, fz]), axis=1)
        nearest_idx = int(np.argmin(dists))
        if dists[nearest_idx] < spacing * 0.6:
            node = node_by_id[nearest_idx]
            node["poi_type"]  = poi.get("poi_type")
            node["poi_color"] = poi.get("poi_color")
            node["team"]      = poi.get("team")
            node["fixed"]     = True
        else:
            new_node: dict = {
                "node_id":    next_id,
                "cx":         round(fx),
                "cz":         round(fz),
                "coords":     [fx, fz],
                "occupation": 0,
                "island_id":  poi.get("island_id"),
                "poi_type":   poi.get("poi_type"),
                "poi_color":  poi.get("poi_color"),
                "team":       poi.get("team"),
                "fixed":      True,
            }
            nodes.append(new_node)
            node_by_id[next_id] = new_node
            for nbr_idx in np.argsort(dists)[:min(3, len(dists))]:
                src_id = min(next_id, int(nbr_idx))
                dst_id = max(next_id, int(nbr_idx))
                extra_edges.append({"src": src_id, "dst": dst_id, "transitions": 1})
            next_id += 1

    all_edges = edges + extra_edges

    graph = {
        "source":             "contour",
        "map_slug":           map_slug,
        "grid_size":          None,
        "cell_count":         len(pts_arr),
        "match_count":        0,
        "position_count":     0,
        "player_count":       0,
        "total_playtime_min": None,
        "nodes":              nodes,
        "edges":              all_edges,
    }

    logger.info(
        "Contour geometry graph '%s': %d nodes, %d edges  "
        "(spacing=%.1f, shell_gap=%.1f)",
        map_slug, len(nodes), len(all_edges), spacing, shell_gap,
    )
    return graph
