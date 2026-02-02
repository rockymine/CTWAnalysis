"""
Serialization for map connectivity graphs.

Saves/loads map_graph.json and updates map_context.json metadata.
"""

import json
import os
from pathlib import Path


def save_map_graph(map_graph: dict, map_folder: Path) -> None:
    """
    Save map graph to map_folder/map_graph.json.

    Also updates map_context.json to record that the graph was generated.

    Args:
        map_graph: Map graph dict from build_map_graph().
        map_folder: Path to the map folder (e.g. map_folders/segment).
    """
    map_folder = Path(map_folder)
    output_path = map_folder / 'map_graph.json'

    os.makedirs(map_folder, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(map_graph, f, indent=2)
    print(f"  Map graph saved to: {output_path}")

    # Update map_context.json
    context_path = map_folder / 'island_analysis' / 'map_context.json'
    if context_path.exists():
        with open(context_path, 'r', encoding='utf-8') as f:
            context = json.load(f)
        context['map_graph_generated'] = True
        context['map_graph_params'] = map_graph.get('params', {})
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
