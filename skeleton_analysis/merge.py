"""
Junction blob merging.

After skeletonization, junction pixels (degree >= 3) often form small clusters
of adjacent pixels that logically represent a single junction. This module
merges each cluster into one representative node and remaps edges accordingly.
"""

import numpy as np
from typing import List, Tuple, Dict, Set
from collections import deque

from ctw.core.models import GraphNode, GraphEdge
from ctw.core.geometry import NEIGHBOR_OFFSETS_8, NEIGHBOR_OFFSETS_4


def merge_junction_blobs(
    nodes: List[GraphNode],
    edges: List[GraphEdge],
    connectivity: int = 8
) -> Tuple[List[GraphNode], List[GraphEdge]]:
    """
    Merge clusters of adjacent junction pixels into single nodes.

    Algorithm:
      1. Find connected components of junction nodes using flood fill
      2. For each cluster, pick the pixel closest to the centroid
      3. Remap all edges from old junction IDs to the representative ID
      4. Drop intra-cluster edges (both endpoints in same cluster)
      5. De-duplicate parallel edges (keep shortest per node pair)
      6. Re-number all nodes and edges sequentially

    Endpoints are never merged.

    Args:
        nodes: List of GraphNode from extract_nodes
        edges: List of GraphEdge from extract_edges
        connectivity: 8 or 4 for adjacency when clustering junctions

    Returns:
        (merged_nodes, merged_edges) with sequential IDs starting from 0
    """
    junctions = [n for n in nodes if n.node_type == 'junction']
    endpoints = [n for n in nodes if n.node_type == 'endpoint']

    if len(junctions) <= 1:
        return nodes, edges

    # Step 1: Cluster adjacent junctions
    clusters = _cluster_junctions(junctions, connectivity)

    # Step 2: Build old_id -> representative_id mapping
    id_remap: Dict[int, int] = {}
    merged_junctions: List[GraphNode] = []

    for cluster in clusters:
        rep_rc = _pick_representative(cluster)
        # Find the original node at rep_rc to get its degree
        rep_node = None
        max_degree = 0
        for node in cluster:
            id_remap[node.node_id] = None  # placeholder, set below
            if node.rc == rep_rc:
                rep_node = node
            max_degree = max(max_degree, node.degree)

        if rep_node is None:
            # Fallback: pick first node in cluster sorted by rc
            rep_node = sorted(cluster, key=lambda n: n.rc)[0]
            rep_rc = rep_node.rc

        merged_node = GraphNode(
            node_id=-1,  # will be reassigned
            rc=rep_rc,
            degree=max_degree,
            node_type='junction'
        )
        merged_junctions.append(merged_node)

        # Map all old IDs in this cluster to this merged node
        for node in cluster:
            id_remap[node.node_id] = id(merged_node)  # temp unique key

    # Endpoints keep their identity (no remapping)
    # Build map from temp key -> final merged node
    temp_to_merged = {id(mn): mn for mn in merged_junctions}

    # Step 3: Assign final sequential IDs
    all_nodes: List[GraphNode] = []
    final_id = 0

    # Endpoints first (sorted by rc for determinism)
    for ep in sorted(endpoints, key=lambda n: n.rc):
        old_id = ep.node_id
        ep_new = GraphNode(
            node_id=final_id,
            rc=ep.rc,
            degree=ep.degree,
            node_type='endpoint'
        )
        all_nodes.append(ep_new)
        id_remap[old_id] = final_id
        final_id += 1

    # Merged junctions (sorted by rc for determinism)
    for mn in sorted(merged_junctions, key=lambda n: n.rc):
        temp_key = id(mn)
        mn_new = GraphNode(
            node_id=final_id,
            rc=mn.rc,
            degree=mn.degree,
            node_type='junction'
        )
        all_nodes.append(mn_new)
        # Update all old IDs that pointed to this merged node
        for old_id, mapped in list(id_remap.items()):
            if mapped == temp_key:
                id_remap[old_id] = final_id
        final_id += 1

    # Build node_id -> rc lookup for the final nodes
    node_rc: Dict[int, Tuple[int, int]] = {n.node_id: n.rc for n in all_nodes}

    # Step 4: Remap edges, drop intra-cluster, de-duplicate
    seen_pairs: Dict[frozenset, GraphEdge] = {}

    for edge in edges:
        new_src = id_remap.get(edge.src, edge.src)
        new_dst = id_remap.get(edge.dst, edge.dst)

        # Drop self-loops (intra-cluster edges)
        if new_src == new_dst:
            continue

        pair = frozenset((new_src, new_dst))
        path_len = len(edge.pixel_path)

        if pair not in seen_pairs or path_len < len(seen_pairs[pair].pixel_path):
            # Fix pixel_path endpoints to match the (possibly moved) node positions
            fixed_path = _fix_path_endpoints(
                edge.pixel_path, new_src, new_dst, node_rc
            )
            seen_pairs[pair] = GraphEdge(
                edge_id=-1,  # reassigned below
                src=min(new_src, new_dst),
                dst=max(new_src, new_dst),
                pixel_path=fixed_path
            )

    # Assign final sequential edge IDs
    merged_edges: List[GraphEdge] = []
    edge_id = 0
    for pair in sorted(seen_pairs.keys(), key=lambda s: tuple(sorted(s))):
        e = seen_pairs[pair]
        merged_edges.append(GraphEdge(
            edge_id=edge_id,
            src=e.src,
            dst=e.dst,
            pixel_path=e.pixel_path
        ))
        edge_id += 1

    return all_nodes, merged_edges


def _cluster_junctions(
    junctions: List[GraphNode],
    connectivity: int = 8
) -> List[List[GraphNode]]:
    """
    Find connected components of junction pixels using flood fill.

    Two junctions are in the same cluster if their (r,c) positions
    are adjacent under the given connectivity.

    Args:
        junctions: List of junction GraphNodes
        connectivity: 8 or 4

    Returns:
        List of clusters, each a list of GraphNode
    """
    offsets = NEIGHBOR_OFFSETS_8 if connectivity == 8 else NEIGHBOR_OFFSETS_4

    # Build position -> node lookup
    pos_to_node: Dict[Tuple[int, int], GraphNode] = {n.rc: n for n in junctions}
    visited: Set[Tuple[int, int]] = set()
    clusters: List[List[GraphNode]] = []

    for node in junctions:
        if node.rc in visited:
            continue

        # BFS flood fill
        cluster: List[GraphNode] = []
        queue = deque([node.rc])
        visited.add(node.rc)

        while queue:
            r, c = queue.popleft()
            cluster.append(pos_to_node[(r, c)])

            for dr, dc in offsets:
                nr, nc = r + dr, c + dc
                pos = (nr, nc)
                if pos not in visited and pos in pos_to_node:
                    visited.add(pos)
                    queue.append(pos)

        clusters.append(cluster)

    return clusters


def _fix_path_endpoints(
    pixel_path: np.ndarray,
    src_id: int,
    dst_id: int,
    node_rc: Dict[int, Tuple[int, int]]
) -> np.ndarray:
    """
    Ensure pixel_path starts at the src node's rc and ends at the dst node's rc.

    After junction merging, representative nodes may have moved to a different
    pixel than what was in the original edge path.  This fixes the first and
    last pixels so that drawn edges visually connect to the node markers.

    The path is oriented so that the first pixel is closest to src and the
    last pixel is closest to dst.

    Args:
        pixel_path: Original Px2 (r,c) array
        src_id: Source node id (min of the pair)
        dst_id: Destination node id (max of the pair)
        node_rc: Mapping from node_id to (r,c)

    Returns:
        Fixed copy of the pixel path
    """
    src_rc = node_rc[src_id]
    dst_rc = node_rc[dst_id]

    path = pixel_path.copy()

    # Determine which end of the path is closer to src vs dst
    first = (int(path[0, 0]), int(path[0, 1]))
    last = (int(path[-1, 0]), int(path[-1, 1]))

    dist_first_to_src = abs(first[0] - src_rc[0]) + abs(first[1] - src_rc[1])
    dist_first_to_dst = abs(first[0] - dst_rc[0]) + abs(first[1] - dst_rc[1])

    if dist_first_to_src > dist_first_to_dst:
        # Path is reversed relative to src->dst ordering; flip it
        path = path[::-1].copy()

    # Now path[0] should be near src, path[-1] near dst
    path[0] = [src_rc[0], src_rc[1]]
    path[-1] = [dst_rc[0], dst_rc[1]]

    return path


def _pick_representative(cluster: List[GraphNode]) -> Tuple[int, int]:
    """
    Pick the pixel in the cluster closest to the cluster centroid.

    Ties broken by lexicographic (r, c) order.

    Args:
        cluster: List of GraphNode in the same junction blob

    Returns:
        (r, c) of the representative pixel
    """
    if len(cluster) == 1:
        return cluster[0].rc

    positions = np.array([n.rc for n in cluster], dtype=float)
    centroid = positions.mean(axis=0)

    # Compute distances to centroid
    dists = np.sqrt(((positions - centroid) ** 2).sum(axis=1))
    min_dist = dists.min()

    # Among all pixels at minimum distance, pick lexicographically first
    candidates = []
    for i, node in enumerate(cluster):
        if abs(dists[i] - min_dist) < 1e-9:
            candidates.append(node.rc)

    candidates.sort()
    return candidates[0]
