"""
Serialization for map connectivity graphs.

Saves/loads map_graph.json and updates map_context.json metadata.
"""

import json
import os
from pathlib import Path
from typing import List

import numpy as np

from .map_graph import DEFAULT_CONNECTIVITY_PARAMS


def _json_default(obj):
    """JSON serializer for numpy types."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def save_initial_map_graph(
    island_skeletons: List[dict],
    map_name: str,
    map_folder: Path,
    params: dict = None,
) -> None:
    """
    Create the initial map_graph.json with skeleton data only.

    Called after skeleton extraction but before pathfinding and connectivity.
    Pathfinding and connectivity steps will update this file in place.

    Args:
        island_skeletons: Per-island dicts from build_skeleton_dicts().
        map_name: Name of the map.
        map_folder: Path to the map folder.
        params: Optional connectivity parameter overrides.
    """
    map_folder = Path(map_folder)
    p = dict(DEFAULT_CONNECTIVITY_PARAMS)
    if params:
        p.update(params)

    data = {
        'map_name': map_name,
        'params': p,
        'islands': island_skeletons,
        'map_graph': {'nodes': [], 'edges': []},
        'connectivity_summary': {},
    }

    output_path = map_folder / 'map_graph.json'
    os.makedirs(map_folder, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, default=_json_default)
    print(f"  Initial map graph saved to: {output_path}")


def save_map_graph(map_graph_result: dict, map_folder: Path) -> None:
    """
    Merge connectivity graph results into existing map_graph.json.

    Preserves the islands array (with skeleton + pathfinding) and adds
    the map-level graph nodes, edges, and connectivity summary.

    Also updates map_context.json to record that the graph was generated.

    Args:
        map_graph_result: Dict from build_map_graph() with params, nodes,
            edges, connectivity_summary.
        map_folder: Path to the map folder.
    """
    map_folder = Path(map_folder)
    output_path = map_folder / 'map_graph.json'

    # Load existing (has islands with skeleton + pathfinding)
    existing = {}
    if output_path.exists():
        with open(output_path, 'r', encoding='utf-8') as f:
            existing = json.load(f)

    existing['params'] = map_graph_result['params']
    existing['map_graph'] = {
        'nodes': map_graph_result['nodes'],
        'edges': map_graph_result['edges'],
    }
    existing['connectivity_summary'] = map_graph_result['connectivity_summary']

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(existing, f, indent=2, default=_json_default)
    print(f"  Map graph saved to: {output_path}")

    # Update map_context.json metadata
    context_path = map_folder / 'island_analysis' / 'map_context.json'
    if context_path.exists():
        with open(context_path, 'r', encoding='utf-8') as f:
            context = json.load(f)
        context['map_graph_generated'] = True
        context['map_graph_params'] = map_graph_result.get('params', {})
        with open(context_path, 'w', encoding='utf-8') as f:
            json.dump(context, f, indent=2)


def load_map_graph(map_folder: Path) -> dict:
    """
    Load map graph from map_graph.json.

    Args:
        map_folder: Path to the map folder.

    Returns:
        Map graph dict.

    Raises:
        FileNotFoundError: If map_graph.json does not exist.
    """
    path = Path(map_folder) / 'map_graph.json'
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)
