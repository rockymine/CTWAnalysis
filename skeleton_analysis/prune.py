"""
Short endpoint branch pruning.

After skeletonization and junction merging, some junctions have very short
branches ending in endpoints only a few pixels away. These are artifacts
from small features (tiny T-shapes, bumps) and add noise to the graph.
This module removes such branches.
"""

from collections import defaultdict

from .datatypes import GraphNode, GraphEdge


def prune_short_branches(
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    max_length: int = 5,
    min_graph_nodes: int = 5,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """
    Remove endpoint branches shorter than max_length pixels from a junction.

    An endpoint is pruned if:
      - It connects to a junction via an edge with <= max_length pixels
      - The junction keeps at least 1 connection after removal

    After pruning, nodes and edges are re-numbered sequentially.

    Args:
        nodes: List of GraphNode
        edges: List of GraphEdge
        max_length: Maximum pixel path length to prune (0 = disabled)
        min_graph_nodes: Only prune if graph has more than this many nodes

    Returns:
        (pruned_nodes, pruned_edges) with sequential IDs starting from 0
    """
    if max_length <= 0 or len(nodes) <= min_graph_nodes:
        return nodes, edges

    # Build adjacency: node_id -> list of (edge, neighbor_id)
    adjacency: dict[int, list[tuple[GraphEdge, int]]] = defaultdict(list)
    for edge in edges:
        adjacency[edge.src].append((edge, edge.dst))
        adjacency[edge.dst].append((edge, edge.src))

    node_by_id = {n.node_id: n for n in nodes}

    # Find endpoints to prune
    endpoints_to_remove: set[int] = set()
    edges_to_remove: set[int] = set()

    for node in nodes:
        if node.node_type != 'endpoint':
            continue

        neighbors = adjacency.get(node.node_id, [])
        if len(neighbors) != 1:
            continue

        edge, neighbor_id = neighbors[0]
        neighbor = node_by_id.get(neighbor_id)
        if neighbor is None or neighbor.node_type != 'junction':
            continue

        # Check edge length
        if len(edge.pixel_path) > max_length:
            continue

        # Check that the junction keeps at least 1 connection after removal
        junction_neighbors = adjacency.get(neighbor_id, [])
        remaining = sum(
            1 for _, nid in junction_neighbors
            if nid not in endpoints_to_remove and nid != node.node_id
        )
        if remaining < 1:
            continue

        endpoints_to_remove.add(node.node_id)
        edges_to_remove.add(edge.edge_id)

    if not endpoints_to_remove:
        return nodes, edges

    # Filter and re-number
    kept_nodes = [n for n in nodes if n.node_id not in endpoints_to_remove]
    kept_edges = [e for e in edges if e.edge_id not in edges_to_remove]

    # Re-number nodes sequentially (endpoints first, then junctions, sorted by rc)
    old_to_new: dict[int, int] = {}
    final_nodes: list[GraphNode] = []
    new_id = 0

    for ntype in ('endpoint', 'junction'):
        for node in sorted(
            [n for n in kept_nodes if n.node_type == ntype],
            key=lambda n: n.rc
        ):
            old_to_new[node.node_id] = new_id
            final_nodes.append(GraphNode(
                node_id=new_id,
                rc=node.rc,
                degree=node.degree,
                node_type=node.node_type,
            ))
            new_id += 1

    # Re-number edges
    final_edges: list[GraphEdge] = []
    for eid, edge in enumerate(sorted(kept_edges, key=lambda e: (e.src, e.dst))):
        new_src = old_to_new[edge.src]
        new_dst = old_to_new[edge.dst]
        final_edges.append(GraphEdge(
            edge_id=eid,
            src=min(new_src, new_dst),
            dst=max(new_src, new_dst),
            pixel_path=edge.pixel_path,
        ))

    return final_nodes, final_edges
