"""
Deterministic edge walking along skeleton pixels.

Edges are extracted by walking from node pixels through degree-2 pixels
until reaching another node pixel. No pathfinding, no shortest-path search.
"""

import numpy as np
from typing import Optional

from .datatypes import SkeletonPixels, GraphNode, GraphEdge
from .nodes import NEIGHBOR_OFFSETS_8, NEIGHBOR_OFFSETS_4


def extract_edges(
    skeleton: SkeletonPixels,
    degree_map: np.ndarray,
    nodes: list[GraphNode],
    connectivity: int = 8,
) -> list[GraphEdge]:
    """
    Extract edges by deterministic walking along skeleton pixels.

    Algorithm:
      1. Build lookup structures for skeleton pixels and nodes
      2. For each node N, enumerate skeleton-pixel neighbors
      3. For each neighbor: walk through deg-2 pixels until reaching
         another node or a dead-end
      4. Record edges with full pixel paths
      5. De-duplicate parallel edges (keep shortest)

    Args:
        skeleton: SkeletonPixels with skeleton mask
        degree_map: Pixel degree map
        nodes: List of GraphNode
        connectivity: 4 or 8

    Returns:
        List of GraphEdge with de-duplicated edges
    """
    offsets = NEIGHBOR_OFFSETS_8 if connectivity == 8 else NEIGHBOR_OFFSETS_4

    # Build lookup structures
    skeleton_set = set(map(tuple, skeleton.pixel_coords))
    node_positions: set[tuple[int, int]] = {n.rc for n in nodes}
    node_at: dict[tuple[int, int], int] = {n.rc: n.node_id for n in nodes}

    mask = skeleton.mask
    h, w = mask.shape

    # Track discovered edges: frozenset(src_id, dst_id) -> (path, edge_id)
    discovered: dict[frozenset[int], tuple[np.ndarray, int]] = {}
    edge_id = 0

    # Walk from each node
    for node in nodes:
        nr, nc = node.rc

        # Find all skeleton neighbors of this node
        neighbors = []
        for dr, dc in offsets:
            cr, cc = nr + dr, nc + dc
            if 0 <= cr < h and 0 <= cc < w and mask[cr, cc]:
                neighbors.append((cr, cc))

        for first_step in neighbors:
            if first_step in node_positions:
                # Direct node-to-node adjacency
                other_id = node_at[first_step]
                if other_id == node.node_id:
                    continue  # Self-loop
                key = frozenset((node.node_id, other_id))
                path = np.array([node.rc, first_step], dtype=np.int32)
                if key not in discovered or len(path) < len(discovered[key][0]):
                    discovered[key] = (path, edge_id)
                    edge_id += 1
            else:
                # Walk along skeleton until reaching another node
                end_rc, path = _walk_edge(
                    start_rc=node.rc,
                    first_step_rc=first_step,
                    skeleton_set=skeleton_set,
                    node_positions=node_positions,
                    offsets=offsets,
                    mask_shape=(h, w)
                )
                if end_rc is not None:
                    other_id = node_at[end_rc]
                    if other_id == node.node_id:
                        continue  # Self-loop
                    key = frozenset((node.node_id, other_id))
                    path_arr = np.array(path, dtype=np.int32)
                    if key not in discovered or len(path_arr) < len(discovered[key][0]):
                        discovered[key] = (path_arr, edge_id)
                        edge_id += 1

    # Build final edge list
    edges = []
    final_id = 0
    for key, (path, _) in sorted(discovered.items(), key=lambda x: sorted(x[0])):
        src, dst = sorted(key)
        edges.append(GraphEdge(
            edge_id=final_id,
            src=src,
            dst=dst,
            pixel_path=path
        ))
        final_id += 1

    return edges


def _walk_edge(
    start_rc: tuple[int, int],
    first_step_rc: tuple[int, int],
    skeleton_set: set[tuple[int, int]],
    node_positions: set[tuple[int, int]],
    offsets: list[tuple[int, int]],
    mask_shape: tuple[int, int],
) -> tuple[Optional[tuple[int, int]], list[tuple[int, int]]]:
    """
    Walk along skeleton from a node through a first step pixel,
    following degree-2 continuation until reaching another node or dead-end.

    Args:
        start_rc: (r, c) of the starting node
        first_step_rc: (r, c) of the first pixel to step into
        skeleton_set: Set of all skeleton pixel positions
        node_positions: Set of all node pixel positions
        offsets: Neighbor offsets to use (4 or 8 connectivity)
        mask_shape: (height, width) for bounds checking

    Returns:
        (end_node_rc or None, pixel_path including start and end)
    """
    h, w = mask_shape
    path = [start_rc, first_step_rc]
    visited = {start_rc, first_step_rc}
    current = first_step_rc

    while True:
        # Find unvisited skeleton neighbors
        candidates = []
        for dr, dc in offsets:
            nr, nc = current[0] + dr, current[1] + dc
            pos = (nr, nc)
            if (0 <= nr < h and 0 <= nc < w
                    and pos not in visited
                    and pos in skeleton_set):
                candidates.append(pos)

        if len(candidates) == 0:
            # Dead end (no unvisited neighbors)
            return None, path

        if len(candidates) == 1:
            nxt = candidates[0]
            path.append(nxt)
            visited.add(nxt)
            if nxt in node_positions:
                return nxt, path
            current = nxt
        else:
            # Multiple candidates: check if any is a node (prefer it)
            node_candidates = [c for c in candidates if c in node_positions]
            if node_candidates:
                # Pick the lexicographically first node
                nxt = sorted(node_candidates)[0]
                path.append(nxt)
                return nxt, path
            # No node among candidates: pick lexicographically first
            nxt = sorted(candidates)[0]
            path.append(nxt)
            visited.add(nxt)
            current = nxt
