"""
Inter-island connectivity module.

Builds a map-level graph connecting island endpoints via void links,
enabling cross-island pathfinding for match trajectory analysis.
"""

from .map_graph import build_map_graph, find_void_links, compute_intra_island_distances
from .serialize import save_map_graph, load_map_graph
from .visualize import plot_map_connectivity

__all__ = [
    "build_map_graph",
    "find_void_links",
    "compute_intra_island_distances",
    "save_map_graph",
    "load_map_graph",
    "plot_map_connectivity",
]
