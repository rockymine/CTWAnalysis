"""Builder for per-island IslandGraph objects used by map_graph.json.

Converts IslandSkeleton objects (canonical-space skeletons) together with
team assignments and POI NodeAnnotations into world-coordinate IslandGraph
objects ready for JSON serialization.
"""


import numpy as np

from .datatypes import IslandSkeleton, IslandGraph, NodeAnnotation


def build_island_graphs(
    islands: list,
    skeleton_results: list[IslandSkeleton],
    node_annotations: dict,
) -> list[IslandGraph]:
    """Build per-island IslandGraph objects for map_graph.json.

    Args:
        islands: Fully contextualized Island objects (with .id and .team set).
        skeleton_results: List of IslandSkeleton from the skeleton pipeline.
        node_annotations: Mapping of island_id -> {node_id -> NodeAnnotation}.
            Pass an empty dict when POI annotation was skipped.

    Returns:
        List of IslandGraph — one per island, skeleton may be None for small islands.
    """
    skel_by_id = {r.island_id: r for r in skeleton_results}
    island_graphs = []
    for island in islands:
        skel = skel_by_id.get(island.id)
        island_graphs.append(IslandGraph(
            island_id=island.id,
            team=island.team,
            skeleton=skel,
            node_annotations=node_annotations.get(island.id, {}),
        ))
    return island_graphs


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

def build_skeleton_dicts(islands: list, skeleton_results: list) -> list[IslandGraph]:
    """Deprecated alias for build_island_graphs (no POI annotations).

    Kept for backward compatibility. Use build_island_graphs() instead.
    """
    return build_island_graphs(islands, skeleton_results, node_annotations={})
