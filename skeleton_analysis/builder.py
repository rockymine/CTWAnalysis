"""Builder for per-island skeleton dicts used by map_graph.json.

Converts IslandResult objects (canonical-space skeletons) into
world-coordinate JSON-serializable dictionaries.
"""

from typing import List

import numpy as np

from island_analysis.datatypes import Island
from .datatypes import IslandResult


def build_skeleton_dicts(
    islands: List[Island],
    skeleton_results: List[IslandResult],
) -> List[dict]:
    """Build per-island skeleton dicts for map_graph.json.

    Returns:
        List of dicts: [{"island_id": int, "team": str, "skeleton": {...}, "pathfinding": None}]
    """
    result_by_id = {r.island_id: r for r in skeleton_results}
    island_skeletons = []
    for island in islands:
        skel_result = result_by_id.get(island.id)
        island_skeletons.append({
            'island_id': island.id,
            'team': island.team,
            'skeleton': _build_skeleton_dict(skel_result) if skel_result else None,
            'pathfinding': None,
        })
    return island_skeletons


def _build_skeleton_dict(result: IslandResult) -> dict:
    """Convert IslandResult skeleton data to a JSON-serializable dict in world coords."""
    transform = result.canonical.transform
    raster = result.raster

    nodes = []
    for node in result.graph.nodes:
        cx, cz = raster.rc_to_canonical(node.rc[0], node.rc[1])
        canonical_pt = np.array([[cx, cz]], dtype=float)
        world_pt = transform.to_original(canonical_pt)[0]
        nodes.append({
            'node_id': node.node_id,
            'x': round(float(world_pt[0]), 1),
            'z': round(float(world_pt[1]), 1),
            'type': node.node_type,
            'degree': node.degree,
        })

    edges = []
    for edge in result.graph.edges:
        edges.append({
            'edge_id': edge.edge_id,
            'src': edge.src,
            'dst': edge.dst,
        })

    edge_pixels = {}
    for edge in result.graph.edges:
        path_canonical = np.array([
            raster.rc_to_canonical(r, c) for r, c in edge.pixel_path
        ], dtype=float)
        path_world = transform.to_original(path_canonical)
        edge_pixels[str(edge.edge_id)] = {
            'src': edge.src,
            'dst': edge.dst,
            'pixels': [[round(float(pt[0]), 1), round(float(pt[1]), 1)]
                        for pt in path_world],
        }

    return {
        'nodes': nodes,
        'edges': edges,
        'edge_pixels': edge_pixels,
    }
