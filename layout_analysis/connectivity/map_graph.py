"""
Map-level connectivity graph construction.

Builds a small graph (~10-50 nodes) of island endpoints connected by:
- Intra-island edges: shortest paths through skeleton graphs
- Void links: direct jumps between endpoints on different islands

Void crossings have NO cost penalty (weight=1.0 per block of distance).
"""

import math
from itertools import combinations
from typing import Dict, List, Optional, Tuple

import networkx as nx

from ..skeleton.pathfinding import load_skeleton_graph, get_endpoint_nodes


DEFAULT_CONNECTIVITY_PARAMS = {
    'D_MAX': 40.0,
    'K_NEAREST': 3,
    'MIN_SEPARATION': 3.0,
    'VOID_WEIGHT': 1.0,
}


def build_map_graph(map_context: dict, params: dict = None) -> dict:
    """
    Build complete map-level connectivity graph.

    Args:
        map_context: Full map_context dict (from map_context.json).
        params: Override default connectivity parameters.

    Returns:
        Map graph dict with 'params', 'nodes', 'edges', 'connectivity_summary'.
    """
    p = dict(DEFAULT_CONNECTIVITY_PARAMS)
    if params:
        p.update(params)

    islands = map_context.get('islands', [])

    # Step 1: Extract all endpoint nodes per island
    endpoints_by_island: Dict[int, List[dict]] = {}
    global_nodes: List[dict] = []
    map_node_id = 0

    # Track mapping: (island_id, local_node_id) -> map_node_id
    local_to_global: Dict[Tuple[int, int], int] = {}

    for island in islands:
        iid = island['id']
        skeleton = island.get('skeleton')
        if skeleton is None:
            continue

        island_endpoints = []
        for node in skeleton['nodes']:
            if node['type'] != 'endpoint':
                continue

            global_node = {
                'map_node_id': map_node_id,
                'island_id': iid,
                'local_node_id': node['node_id'],
                'coords': [node['x'], node['z']],
                'node_type': 'endpoint',
            }
            global_nodes.append(global_node)
            island_endpoints.append(global_node)
            local_to_global[(iid, node['node_id'])] = map_node_id
            map_node_id += 1

        if island_endpoints:
            endpoints_by_island[iid] = island_endpoints

    # Step 2: Compute intra-island edges
    edges: List[dict] = []
    edge_id = 0

    for island in islands:
        iid = island['id']
        skeleton = island.get('skeleton')
        if skeleton is None or iid not in endpoints_by_island:
            continue

        intra_distances = compute_intra_island_distances(skeleton)
        island_eps = endpoints_by_island[iid]

        for i, ep_a in enumerate(island_eps):
            for ep_b in island_eps[i + 1:]:
                local_a = ep_a['local_node_id']
                local_b = ep_b['local_node_id']
                key = (min(local_a, local_b), max(local_a, local_b))

                if key not in intra_distances:
                    continue

                info = intra_distances[key]
                edges.append({
                    'edge_id': edge_id,
                    'src': ep_a['map_node_id'],
                    'dst': ep_b['map_node_id'],
                    'edge_type': 'intra',
                    'distance': info['distance'],
                    'path_nodes': info['path_nodes'],
                    'island_id': iid,
                })
                edge_id += 1

    # Step 3: Find void links
    void_links = find_void_links(endpoints_by_island, p)
    for vl in void_links:
        vl['edge_id'] = edge_id
        edge_id += 1
        edges.append(vl)

    # Step 4: Build connectivity summary
    connectivity_summary = _build_connectivity_summary(void_links, endpoints_by_island)

    return {
        'params': p,
        'nodes': global_nodes,
        'edges': edges,
        'connectivity_summary': connectivity_summary,
    }


def find_void_links(endpoints_by_island: Dict[int, List[dict]], params: dict) -> list:
    """
    Find plausible void crossings between island endpoints.

    For each endpoint on island A, finds the K nearest endpoints on
    other islands within D_MAX distance, skipping pairs closer than
    MIN_SEPARATION.

    Args:
        endpoints_by_island: {island_id: [endpoint node dicts with map_node_id, coords]}
        params: D_MAX, K_NEAREST, MIN_SEPARATION, VOID_WEIGHT

    Returns:
        List of void link edge dicts (undirected, stored once per pair).
    """
    d_max = params['D_MAX']
    k_nearest = params['K_NEAREST']
    min_sep = params['MIN_SEPARATION']

    island_ids = sorted(endpoints_by_island.keys())
    seen_pairs = set()
    void_links = []

    for src_iid in island_ids:
        for src_ep in endpoints_by_island[src_iid]:
            sx, sz = src_ep['coords']
            candidates = []

            for dst_iid in island_ids:
                if dst_iid == src_iid:
                    continue
                for dst_ep in endpoints_by_island[dst_iid]:
                    dx, dz = dst_ep['coords']
                    dist = math.hypot(dx - sx, dz - sz)

                    if dist < min_sep or dist > d_max:
                        continue

                    candidates.append((dist, dst_ep, dst_iid))

            # Keep K nearest
            candidates.sort(key=lambda c: c[0])
            for dist, dst_ep, dst_iid in candidates[:k_nearest]:
                pair = (min(src_ep['map_node_id'], dst_ep['map_node_id']),
                        max(src_ep['map_node_id'], dst_ep['map_node_id']))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                void_links.append({
                    'edge_id': -1,  # assigned by caller
                    'src': src_ep['map_node_id'],
                    'dst': dst_ep['map_node_id'],
                    'edge_type': 'void_link',
                    'distance': round(dist, 2),
                    'src_island': src_iid,
                    'dst_island': dst_iid,
                    'src_coords': src_ep['coords'],
                    'dst_coords': dst_ep['coords'],
                })

    return void_links


def compute_intra_island_distances(island_skeleton: dict) -> dict:
    """
    Precompute shortest path distances between all endpoint pairs within an island.

    Uses NetworkX shortest_path on the skeleton graph.

    Args:
        island_skeleton: The 'skeleton' dict from an island in map_context.json.

    Returns:
        Dict mapping (endpoint_a, endpoint_b) sorted tuple -> {distance, path_nodes}
    """
    G = load_skeleton_graph(island_skeleton)
    if G is None:
        return {}

    endpoints = get_endpoint_nodes(G)
    results = {}

    for i, ep_a in enumerate(endpoints):
        for ep_b in endpoints[i + 1:]:
            try:
                path = nx.shortest_path(G, ep_a, ep_b, weight='weight')
            except nx.NetworkXNoPath:
                continue

            dist = 0.0
            for k in range(len(path) - 1):
                n1, n2 = path[k], path[k + 1]
                d1, d2 = G.nodes[n1], G.nodes[n2]
                dist += math.hypot(d2['x'] - d1['x'], d2['z'] - d1['z'])

            key = (min(ep_a, ep_b), max(ep_a, ep_b))
            results[key] = {
                'distance': round(dist, 2),
                'path_nodes': path,
            }

    return results


def _build_connectivity_summary(
    void_links: list,
    endpoints_by_island: Dict[int, List[dict]],
) -> dict:
    """Build a summary of inter-island connectivity from void links."""
    summary = {}

    for vl in void_links:
        src_iid = vl['src_island']
        dst_iid = vl['dst_island']
        pair_key = f"{min(src_iid, dst_iid)}_to_{max(src_iid, dst_iid)}"

        if pair_key not in summary:
            summary[pair_key] = {
                'min_gap': vl['distance'],
                'link_count': 0,
                'closest_endpoints': [],
            }

        entry = summary[pair_key]
        entry['link_count'] += 1
        entry['closest_endpoints'].append([vl['src'], vl['dst']])
        if vl['distance'] < entry['min_gap']:
            entry['min_gap'] = vl['distance']

    return summary
