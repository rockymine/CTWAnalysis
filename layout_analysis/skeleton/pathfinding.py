"""
Intra-island pathfinding on skeleton graphs.

Computes shortest paths between POIs (spawn/wool) and endpoints,
plus defender paths (spawn->wool) when both are on the same island.

All data is read from map_context.json (embedded skeleton per island).
All coordinates are in world (x, z) space.
"""

import json
import math
import os
from typing import Dict, List, Optional, Tuple

import networkx as nx


def load_skeleton_graph(island_skeleton: dict) -> Optional[nx.Graph]:
    """
    Build a networkx Graph from an island's embedded skeleton dict.

    Args:
        island_skeleton: The 'skeleton' dict from an island in map_context.json,
            containing 'nodes', 'edges', and 'edge_pixels' keys.

    Returns:
        networkx.Graph or None if skeleton data is missing.
    """
    if island_skeleton is None:
        return None

    G = nx.Graph()

    for node in island_skeleton['nodes']:
        G.add_node(node['node_id'],
                   x=float(node['x']),
                   z=float(node['z']),
                   node_type=node['type'],
                   degree=int(node['degree']))

    for edge in island_skeleton['edges']:
        src, dst = edge['src'], edge['dst']
        sx, sz = G.nodes[src]['x'], G.nodes[src]['z']
        dx, dz = G.nodes[dst]['x'], G.nodes[dst]['z']
        weight = math.hypot(dx - sx, dz - sz)
        G.add_edge(src, dst, edge_id=edge['edge_id'], weight=weight)

    return G


def should_analyze_island(island_data: dict, poi_assignments: dict) -> bool:
    """
    Determine if island should have pathfinding analysis.

    Only analyze if island has at least one POI (spawn or wool).

    Args:
        island_data: Island dict from map_context.json.
        poi_assignments: POI assignments dict from map_context.json.

    Returns:
        True if island has spawn or wool POI.
    """
    iid = island_data['id']
    for spawn in poi_assignments.get('spawns', []):
        if spawn['island_id'] == iid:
            return True
    for wool in poi_assignments.get('wools', []):
        if wool['island_id'] == iid:
            return True
    return False


def get_endpoint_nodes(G: nx.Graph) -> List[int]:
    """
    Find all endpoint nodes (degree=1) in the skeleton graph.

    Returns:
        List of node IDs that are endpoints.
    """
    return [n for n, d in G.nodes(data=True) if d.get('node_type') == 'endpoint']


def _get_island_pois(island_id: int, poi_assignments: dict) -> Tuple[List[dict], List[dict]]:
    """
    Get spawn and wool POIs for a specific island.

    Returns:
        (spawns, wools) - lists of POI dicts for this island.
    """
    spawns = [s for s in poi_assignments.get('spawns', []) if s['island_id'] == island_id]
    wools = [w for w in poi_assignments.get('wools', []) if w['island_id'] == island_id]
    return spawns, wools


def _path_distance(G: nx.Graph, path: List[int]) -> float:
    """Compute total euclidean distance along a path of node IDs."""
    total = 0.0
    for i in range(len(path) - 1):
        n1, n2 = path[i], path[i + 1]
        d1, d2 = G.nodes[n1], G.nodes[n2]
        total += math.hypot(d2['x'] - d1['x'], d2['z'] - d1['z'])
    return round(total, 2)


def _path_coords(G: nx.Graph, path: List[int]) -> List[Tuple[float, float]]:
    """Convert a path of node IDs to a list of (x, z) coordinate tuples."""
    return [(G.nodes[n]['x'], G.nodes[n]['z']) for n in path]


def compute_poi_to_endpoint_paths(
    G: nx.Graph,
    poi_node: int,
    poi_type: str,
    poi_id: str,
) -> List[dict]:
    """
    Compute all shortest paths from a POI to every endpoint.

    For wool nodes, these are NOT "wool lanes" yet -- that requires
    more sophisticated analysis. These are just the possible paths.

    Args:
        G: Skeleton graph.
        poi_node: Node ID of the POI.
        poi_type: 'spawn' or 'wool'.
        poi_id: Identifier (team name for spawn, wool color for wool).

    Returns:
        List of path dicts.
    """
    if poi_node not in G:
        print(f"  WARNING: POI node {poi_node} not in graph, skipping")
        return []

    endpoints = get_endpoint_nodes(G)
    results = []

    for ep in endpoints:
        if ep == poi_node:
            continue
        try:
            path = nx.shortest_path(G, poi_node, ep, weight='weight')
        except nx.NetworkXNoPath:
            continue

        poi_data = G.nodes[poi_node]
        ep_data = G.nodes[ep]
        results.append({
            'poi_type': poi_type,
            'poi_id': poi_id,
            'poi_node': poi_node,
            'poi_coords': (poi_data['x'], poi_data['z']),
            'endpoint_node': ep,
            'endpoint_coords': (ep_data['x'], ep_data['z']),
            'path_nodes': path,
            'path_coords': _path_coords(G, path),
            'length': len(path),
            'distance': _path_distance(G, path),
        })

    return results


def compute_defender_paths(
    G: nx.Graph,
    spawn_node: int,
    spawn_team: str,
    wool_nodes: List[dict],
) -> List[dict]:
    """
    Compute paths from spawn to each wool objective on the same island.

    These represent likely defender patrol/defense routes.

    Args:
        G: Skeleton graph.
        spawn_node: Node ID of spawn.
        spawn_team: Team ID of the spawn.
        wool_nodes: List of dicts with 'node_id' and 'wool_color'.

    Returns:
        List of defender path dicts.
    """
    if spawn_node not in G:
        print(f"  WARNING: Spawn node {spawn_node} not in graph, skipping defender paths")
        return []

    results = []
    for wool in wool_nodes:
        wool_node = wool['node_id']
        if wool_node not in G:
            print(f"  WARNING: Wool node {wool_node} not in graph, skipping")
            continue
        try:
            path = nx.shortest_path(G, spawn_node, wool_node, weight='weight')
        except nx.NetworkXNoPath:
            continue

        spawn_data = G.nodes[spawn_node]
        wool_data = G.nodes[wool_node]
        results.append({
            'spawn_team': spawn_team,
            'wool_color': wool.get('wool_color', ''),
            'spawn_node': spawn_node,
            'spawn_coords': (spawn_data['x'], spawn_data['z']),
            'wool_node': wool_node,
            'wool_coords': (wool_data['x'], wool_data['z']),
            'path_nodes': path,
            'path_coords': _path_coords(G, path),
            'length': len(path),
            'distance': _path_distance(G, path),
        })

    return results


def analyze_island_paths(
    island_id: int,
    island_data: dict,
    poi_assignments: dict,
    G: nx.Graph,
) -> Optional[dict]:
    """
    Run complete pathfinding analysis for an island.

    Process:
    1. Check if island has POIs
    2. If no, return None
    3. If yes:
        a. Find all endpoint nodes
        b. For each POI, compute paths to all endpoints
        c. If spawn and wool(s) on same island, compute defender paths

    Args:
        island_id: Island ID.
        island_data: Island dict from map_context.json.
        poi_assignments: Full POI assignments dict.
        G: Skeleton graph for this island.

    Returns:
        Analysis dict or None if island has no POIs.
    """
    if not should_analyze_island(island_data, poi_assignments):
        return None

    spawns, wools = _get_island_pois(island_id, poi_assignments)
    endpoints = get_endpoint_nodes(G)

    poi_to_endpoint = []
    defender_paths = []

    # Spawn -> endpoint paths
    for spawn in spawns:
        paths = compute_poi_to_endpoint_paths(
            G, spawn['node_id'], 'spawn', spawn['team'])
        poi_to_endpoint.extend(paths)

    # Wool -> endpoint paths
    for wool in wools:
        paths = compute_poi_to_endpoint_paths(
            G, wool['node_id'], 'wool', wool.get('wool_color', ''))
        poi_to_endpoint.extend(paths)

    # Defender paths: spawn -> wool on same island
    if spawns and wools:
        for spawn in spawns:
            defender_paths.extend(
                compute_defender_paths(G, spawn['node_id'], spawn['team'], wools))

    team = island_data.get('team')
    if not team and spawns:
        team = spawns[0].get('team')

    return {
        'island_id': island_id,
        'team': team,
        'has_spawn': len(spawns) > 0,
        'has_wool': len(wools) > 0,
        'spawn_count': len(spawns),
        'wool_count': len(wools),
        'endpoint_count': len(endpoints),
        'poi_to_endpoint_paths': poi_to_endpoint,
        'defender_paths': defender_paths if defender_paths else None,
    }


def run_pathfinding_analysis(map_folder: str) -> Optional[dict]:
    """
    Run pathfinding analysis for all islands of a map.

    Loads map_context.json (with embedded skeleton data per island),
    computes paths, and writes results back into map_context.json
    under each island's 'pathfinding' key.

    Args:
        map_folder: Path to the map folder (e.g. map_folders/tumbleweed).

    Returns:
        Full analysis results dict, or None on error.
    """
    island_analysis_dir = os.path.join(map_folder, 'island_analysis')
    context_path = os.path.join(island_analysis_dir, 'map_context.json')

    if not os.path.exists(context_path):
        print(f"  ERROR: map_context.json not found at {context_path}")
        return None

    with open(context_path, 'r') as f:
        context = json.load(f)

    poi_assignments = context.get('poi_assignments', {})
    islands = context.get('islands', [])
    map_name = context.get('map_name', os.path.basename(map_folder))

    results = {
        'map_name': map_name,
        'islands_analyzed': 0,
        'islands_skipped': 0,
        'total_poi_endpoint_paths': 0,
        'total_defender_paths': 0,
        'island_results': [],
    }

    for island_data in islands:
        iid = island_data['id']
        skeleton_data = island_data.get('skeleton')
        G = load_skeleton_graph(skeleton_data)
        if G is None:
            continue

        analysis = analyze_island_paths(iid, island_data, poi_assignments, G)
        if analysis is None:
            results['islands_skipped'] += 1
            island_data['pathfinding'] = None
            continue

        results['islands_analyzed'] += 1
        results['total_poi_endpoint_paths'] += len(analysis['poi_to_endpoint_paths'])
        results['total_defender_paths'] += len(analysis['defender_paths'] or [])
        results['island_results'].append(analysis)
        island_data['pathfinding'] = analysis

    # Save updated map_context.json with embedded pathfinding
    with open(context_path, 'w', encoding='utf-8') as f:
        json.dump(context, f, indent=2)

    return results


# ---------------------------------------------------------------------------
# Edge pixel path loading and chaining
# ---------------------------------------------------------------------------

def load_edge_pixels(island_skeleton: dict) -> Optional[Dict]:
    """
    Extract edge pixel paths from an island's embedded skeleton dict.

    Args:
        island_skeleton: The 'skeleton' dict from an island in map_context.json.

    Returns:
        Dict mapping (src, dst) frozenset -> list of [x, z] pixel coords,
        or None if skeleton data is missing.
    """
    if island_skeleton is None or 'edge_pixels' not in island_skeleton:
        return None

    edge_pixels = {}
    for edge_id_str, data in island_skeleton['edge_pixels'].items():
        key = frozenset((data['src'], data['dst']))
        edge_pixels[key] = data['pixels']

    return edge_pixels


def get_edge_detail(
    edge_pixels: Dict,
    src: int,
    dst: int,
) -> Optional[List[List[float]]]:
    """
    Get the dense pixel-level path between two adjacent nodes.

    The returned path always runs src -> dst (reversed if needed).

    Args:
        edge_pixels: Dict from load_edge_pixels().
        src: Source node ID.
        dst: Destination node ID.

    Returns:
        List of [x, z] coordinates, or None if edge not found.
    """
    key = frozenset((src, dst))
    pixels = edge_pixels.get(key)
    if pixels is None:
        return None

    if len(pixels) < 2:
        return pixels

    # The stored path starts from the node with the lower ID
    # (edges are sorted src < dst). If the caller wants dst -> src, reverse.
    first_key = min(src, dst)
    if src != first_key:
        return list(reversed(pixels))
    return pixels


def get_path_detail(
    edge_pixels: Dict,
    path_nodes: List[int],
) -> Optional[List[List[float]]]:
    """
    Get the dense pixel-level path for a multi-hop node path.

    Chains the pixel paths of consecutive edges, removing duplicate
    junction points at seams.

    Args:
        edge_pixels: Dict from load_edge_pixels().
        path_nodes: Ordered list of node IDs (e.g. from shortest_path).

    Returns:
        List of [x, z] world coordinates forming the dense path,
        or None if any edge is missing.
    """
    if len(path_nodes) < 2:
        return None

    full_path = []
    for i in range(len(path_nodes) - 1):
        segment = get_edge_detail(edge_pixels, path_nodes[i], path_nodes[i + 1])
        if segment is None:
            print(f"  WARNING: No pixel data for edge {path_nodes[i]}->{path_nodes[i+1]}")
            return None
        if i == 0:
            full_path.extend(segment)
        else:
            # Skip first point (duplicate of previous segment's last point)
            full_path.extend(segment[1:])

    return full_path
