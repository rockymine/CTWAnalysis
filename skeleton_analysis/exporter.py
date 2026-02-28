"""JSON exporter for skeleton / map-graph data.

Public API:
    to_dict(island_graphs, map_name)  — serialize map graph to a plain dict
    save(island_graphs, map_name, output_dir)  — write map_graph.json
"""

import logging
from pathlib import Path

import numpy as np

from .datatypes import IslandGraph, IslandSkeleton
from common.json_export import save_json as _save_json

logger = logging.getLogger('ctw')


def to_dict(island_graphs: list[IslandGraph], map_name: str) -> dict:
    """Build the complete map_graph.json structure from IslandGraph objects.

    Args:
        island_graphs: List of IslandGraph from
            :func:`skeleton_analysis.builder.build_island_graphs`.
        map_name: Name of the map.

    Returns:
        JSON-serializable dictionary.
    """
    map_nodes = []
    map_node_id = 0
    islands_out = []

    for ig in island_graphs:
        skeleton_dict = _skeleton_to_dict(ig.skeleton) if ig.skeleton else None

        node_annotations_dict = {
            str(nid): {'poi_type': ann.poi_type, 'poi_color': ann.poi_color}
            for nid, ann in ig.node_annotations.items()
        }

        islands_out.append({
            'island_id': ig.island_id,
            'team': ig.team,
            'skeleton': skeleton_dict,
            'node_annotations': node_annotations_dict,
            'pathfinding': None,
        })

        # Enrich map_graph.nodes with team/poi context for all endpoints
        if skeleton_dict is not None:
            for node in skeleton_dict.get('nodes', []):
                if node.get('type') == 'endpoint':
                    local_id = node['node_id']
                    ann = ig.node_annotations.get(local_id)
                    map_nodes.append({
                        'map_node_id': map_node_id,
                        'island_id': ig.island_id,
                        'local_node_id': local_id,
                        'coords': [node['x'], node['z']],
                        'team': ig.team,
                        'poi_type': ann.poi_type if ann else None,
                        'poi_color': ann.poi_color if ann else None,
                    })
                    map_node_id += 1

    return {
        'map_name': map_name,
        'islands': islands_out,
        'map_graph': {'nodes': map_nodes, 'edges': []},
    }


def save(island_graphs: list[IslandGraph], map_name: str, output_dir: Path) -> None:
    """Save map_graph.json containing island skeleton data.

    Downstream consumers (match analysis / PositionClassifier) read
    islands[].skeleton.edge_pixels from this file for spatial queries.
    """
    output_path = output_dir / 'map_graph.json'
    _save_json(to_dict(island_graphs, map_name), output_path)
    logger.debug(f"  Saved: {output_path}")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _skeleton_to_dict(skel: IslandSkeleton) -> dict:
    """Convert an IslandSkeleton to a JSON-serializable dict in world coords."""
    transform = skel.canonical.transform
    raster = skel.raster

    nodes = []
    for node in skel.graph.nodes:
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
    for edge in skel.graph.edges:
        edges.append({
            'edge_id': edge.edge_id,
            'src': edge.src,
            'dst': edge.dst,
        })

    edge_pixels = {}
    for edge in skel.graph.edges:
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
