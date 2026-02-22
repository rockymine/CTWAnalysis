"""JSON exporter for skeleton / map-graph data.

Public API:
    to_dict(island_skeletons, map_name)  — serialize map graph to a plain dict
    save(island_skeletons, map_name, output_dir)  — write map_graph.json
"""

from pathlib import Path

from common.json_export import save_json as _save_json


def to_dict(island_skeletons: list, map_name: str) -> dict:
    """Build the complete map_graph.json structure.

    Args:
        island_skeletons: Per-island skeleton dicts from
            :func:`skeleton_analysis.builder.build_skeleton_dicts`.
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
