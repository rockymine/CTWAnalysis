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
