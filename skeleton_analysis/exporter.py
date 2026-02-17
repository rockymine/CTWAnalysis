"""JSON exporter for skeleton / map-graph data.

Public API:
    to_dict(island_skeletons, map_name)  — serialize map graph to a plain dict
    save(island_skeletons, map_name, output_dir)  — write map_graph.json

Helper:
    build_skeleton_dicts(islands, skeleton_results)  — build per-island dicts
"""

from pathlib import Path
from typing import Dict, List

import numpy as np

from json_export import save_json as _save_json

from island_analysis.datatypes import Island
from .datatypes import IslandResult


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def to_dict(island_skeletons: list, map_name: str) -> dict:
    """Build the complete map_graph.json structure.

    Args:
        island_skeletons: Per-island skeleton dicts from :func:`build_skeleton_dicts`.
        map_name: Name of the map.

    Returns:
        JSON-serializable dictionary.
    """
    map_nodes = []
    node_id = 0
    for isle in island_skeletons:
        skeleton = isle.get('skeleton')
        if skeleton is None:
            continue
        iid = isle['island_id']
        for node in skeleton.get('nodes', []):
            if node.get('type') == 'endpoint':
                map_nodes.append({
                    'map_node_id': node_id,
                    'island_id': iid,
                    'local_node_id': node['node_id'],
                    'coords': [node['x'], node['z']],
                })
                node_id += 1

    return {
        'map_name': map_name,
        'islands': island_skeletons,
        'map_graph': {'nodes': map_nodes, 'edges': []},
    }


def save(island_skeletons: list, map_name: str, output_dir: Path) -> None:
    """Save map_graph.json containing island skeleton data.

    Downstream consumers (match analysis / PositionClassifier) read
    islands[].skeleton.edge_pixels from this file for spatial queries.
    """
    output_path = output_dir / 'map_graph.json'
    _save_json(to_dict(island_skeletons, map_name), output_path)
    print(f"  Saved JSON: {output_path}")


# ---------------------------------------------------------------------------
# Skeleton dict builders
# ---------------------------------------------------------------------------

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
