"""Geometry-derived navigation graph from GridBase cell adjacency.

Builds a 4-connected adjacency graph from a GridBase — one node per
rasterized grid cell, edges between face-adjacent cells.  No player data
is required.  This graph captures the theoretical maximum connectivity of
the map geometry and can be used as a geometry-only navigation graph or
as a seed for build_traffic_graph().

Node and edge schema is identical to the traffic graph so that all
downstream consumers (build_traffic_topology, plot_traffic_graph, etc.)
work without modification.

Typical usage (CLI):
    python ctw.py maps geometry-graph --map tumbleweed

Output:
    output/<map_slug>/geometry_graph.json
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np

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
