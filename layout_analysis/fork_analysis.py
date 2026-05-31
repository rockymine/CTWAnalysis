"""Fork layout analysis for 2-team, 2-wool CTW maps.

Tests the hypothesis that the defending (home) half of every 2-team, 2-wool
CTW map follows a "fork" topology: a horizontal connector lane with three
prongs pointing outward — spawn in the centre, one wool room on each flank.

The skeleton graph stored in map_graph.json (per-island) is used so that
topological distances reflect actual traversal geometry rather than
straight-line distances.
"""

from __future__ import annotations

import heapq
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import duckdb


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TeamIsland:
    """Skeleton graph for one team's home island."""
    team: str
    island_id: int
    nodes: dict[int, dict]       # node_id -> merged node+annotation dict
    adj: dict[int, list[int]]    # undirected adjacency list
    spawn_id: int
    wool_ids: list[int]          # [id_left, id_right] — ordered by x-coordinate


@dataclass
class ForkMetrics:
    """Fork analysis result for one (map, team) pair."""
    map_slug: str
    team: str
    size_tier: str | None

    # Graph path distances (sum of Euclidean edge lengths) from spawn to each wool
    d_graph: list[float]         # [d_wool_0, d_wool_1]

    # Straight-line distances from spawn to each wool
    d_euclidean: list[float]     # [d_wool_0, d_wool_1]

    # Number of junction nodes encountered on each graph path
    junction_counts: list[int]   # [n_junctions_to_wool_0, n_junctions_to_wool_1]

    # Angle at spawn between vectors to the two wools (degrees)
    fork_angle_deg: float

    # Perpendicular distance of spawn from the line connecting the two wools
    lateral_offset: float

    # Graph distance from spawn to the first point where the two wool paths diverge
    d_to_fork_junction: float

    # Fraction of the longer arm that is shared with the shorter arm
    shared_path_fraction: float

    # |d_graph[0] - d_graph[1]| / max(d_graph)  — 0 = perfectly symmetric
    arm_asymmetry: float


# ---------------------------------------------------------------------------
# Graph loading
# ---------------------------------------------------------------------------

def _load_team_island(
    map_slug: str,
    spawn_x: float,
    spawn_z: float,
    wool_coords: list[tuple[float, float]],
    output_dir: Path,
    max_spawn_dist: float = 50.0,
    max_wool_dist: float = 20.0,
    min_transitions: int = 2,
) -> Optional[TeamIsland]:
    """Load a team's home island from traffic_graph.json.

    The traffic graph gives better path resolution than the skeleton graph
    (5-block grid, transitions from real match data, accurate POI positions).

    Strategy:
    - Find the fixed spawn node closest to (spawn_x, spawn_z).
    - For each expected wool position in *wool_coords*, find the closest fixed
      wool node on the same island (avoiding reliance on the traffic graph's
      `team` field, which is inconsistently defined across maps).
    - Extract the island subgraph and prune low-traffic edges.

    Returns None if the traffic graph is absent, no spawn can be matched,
    either wool cannot be matched to a node on the spawn island within
    *max_wool_dist*, or fewer than 2 distinct wool nodes are found.
    """
    tg_path = output_dir / map_slug / "traffic_graph.json"
    if not tg_path.exists():
        return None

    tg = json.loads(tg_path.read_text(encoding="utf-8"))
    all_nodes: dict[int, dict] = {n["node_id"]: n for n in tg["nodes"]}
    all_edges: list[dict] = tg["edges"]

    # Find the spawn fixed node closest to the DB spawn position
    spawn_node: dict | None = None
    best_dist = max_spawn_dist
    for node in all_nodes.values():
        if node.get("poi_type") == "spawn":
            nx, nz = node["coords"]
            d = math.sqrt((nx - spawn_x) ** 2 + (nz - spawn_z) ** 2)
            if d < best_dist:
                best_dist = d
                spawn_node = node

    if spawn_node is None:
        return None

    spawn_island_id: int = spawn_node["island_id"]
    spawn_team: str = spawn_node.get("team") or ""
    spawn_id: int = spawn_node["node_id"]

    # Collect all nodes belonging to this island; normalise coords to x/z fields
    island_node_ids: set[int] = {
        nid for nid, n in all_nodes.items()
        if n["island_id"] == spawn_island_id
    }
    nodes: dict[int, dict] = {}
    for nid in island_node_ids:
        node = dict(all_nodes[nid])
        node["x"], node["z"] = node["coords"]
        nodes[nid] = node

    # Match each expected wool position to the closest fixed wool node on this
    # island.  Using DB coordinates avoids the inconsistent `team` field.
    wool_fixed: list[dict] = [n for n in nodes.values() if n.get("poi_type") == "wool"]
    wool_ids: list[int] = []
    for wx, wz in wool_coords:
        best_wdist = max_wool_dist
        best_wid: int | None = None
        for wnode in wool_fixed:
            d = math.sqrt((wnode["x"] - wx) ** 2 + (wnode["z"] - wz) ** 2)
            if d < best_wdist:
                best_wdist = d
                best_wid = wnode["node_id"]
        if best_wid is not None:
            wool_ids.append(best_wid)

    wool_ids = list(dict.fromkeys(wool_ids))  # deduplicate while preserving order
    if len(wool_ids) != 2:
        return None  # wools on different islands or not found in traffic graph

    wool_ids.sort(key=lambda wid: nodes[wid]["x"])

    # Build adjacency from edges within the island, pruning noise
    adj: dict[int, list[int]] = defaultdict(list)
    for edge in all_edges:
        s, d = edge["src"], edge["dst"]
        if s in island_node_ids and d in island_node_ids:
            if edge.get("transitions", 0) >= min_transitions:
                adj[s].append(d)
                adj[d].append(s)

    return TeamIsland(
        team=spawn_team,
        island_id=spawn_island_id,
        nodes=nodes,
        adj=dict(adj),
        spawn_id=spawn_id,
        wool_ids=wool_ids,
    )


# ---------------------------------------------------------------------------
# Graph algorithms
# ---------------------------------------------------------------------------

def _euclid(n1: dict, n2: dict) -> float:
    return math.sqrt((n1["x"] - n2["x"]) ** 2 + (n1["z"] - n2["z"]) ** 2)


def _dijkstra(
    nodes: dict[int, dict],
    adj: dict[int, list[int]],
    start: int,
) -> tuple[dict[int, float], dict[int, int | None]]:
    """Dijkstra from *start* with Euclidean edge weights.

    Returns (dist, prev) — dist[n] is the shortest path cost, prev[n] is
    the preceding node on that path (None for the start node).
    """
    inf = math.inf
    dist: dict[int, float] = {n: inf for n in nodes}
    prev: dict[int, int | None] = {n: None for n in nodes}
    dist[start] = 0.0
    heap: list[tuple[float, int]] = [(0.0, start)]

    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue
        for v in adj.get(u, []):
            nd = d + _euclid(nodes[u], nodes[v])
            if nd < dist[v]:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(heap, (nd, v))

    return dist, prev


def _path(prev: dict[int, int | None], start: int, end: int) -> list[int]:
    """Reconstruct path start → ... → end from Dijkstra prev pointers."""
    nodes: list[int] = []
    cur: int | None = end
    while cur is not None:
        nodes.append(cur)
        cur = prev[cur]
    nodes.reverse()
    return nodes if nodes and nodes[0] == start else []


def _fork_junction_and_shared(
    path1: list[int], path2: list[int]
) -> tuple[int | None, int]:
    """Return (fork_junction_node_id, shared_prefix_length).

    Walk both paths from the start (spawn) and find where they first diverge.
    The last shared node before divergence is the fork junction.
    """
    shared = 0
    for a, b in zip(path1, path2):
        if a == b:
            shared += 1
        else:
            break
    if shared == 0:
        return None, 0
    return path1[shared - 1], shared


# ---------------------------------------------------------------------------
# Geometric helpers
# ---------------------------------------------------------------------------

def _fork_angle_deg(spawn: dict, w1: dict, w2: dict) -> float:
    """Angle at spawn between spawn→w1 and spawn→w2 vectors (degrees)."""
    dx1, dz1 = w1["x"] - spawn["x"], w1["z"] - spawn["z"]
    dx2, dz2 = w2["x"] - spawn["x"], w2["z"] - spawn["z"]
    dot = dx1 * dx2 + dz1 * dz2
    mag1 = math.sqrt(dx1 ** 2 + dz1 ** 2) or 1e-9
    mag2 = math.sqrt(dx2 ** 2 + dz2 ** 2) or 1e-9
    return math.degrees(math.acos(max(-1.0, min(1.0, dot / (mag1 * mag2)))))


def _lateral_offset(spawn: dict, w1: dict, w2: dict) -> float:
    """Perpendicular distance from spawn to the line segment connecting w1 and w2."""
    wx1, wz1 = w1["x"], w1["z"]
    wx2, wz2 = w2["x"], w2["z"]
    sx, sz = spawn["x"], spawn["z"]
    # |cross product of (w2-w1) and (w1-spawn)| / |w2-w1|
    area2 = abs((wx2 - wx1) * (wz1 - sz) - (wx1 - sx) * (wz2 - wz1))
    base = math.sqrt((wx2 - wx1) ** 2 + (wz2 - wz1) ** 2) or 1e-9
    return area2 / base


# ---------------------------------------------------------------------------
# Per-map analysis
# ---------------------------------------------------------------------------

def analyze_fork(
    map_slug: str,
    team: str,
    size_tier: str | None,
    spawn_x: float,
    spawn_z: float,
    wool_coords: list[tuple[float, float]],
    output_dir: Path,
    min_transitions: int = 2,
) -> Optional[ForkMetrics]:
    """Compute fork metrics for one (map, team) pair.

    Returns None if the traffic graph is unavailable, no spawn can be matched,
    the island lacks exactly two defending wools, or the graph is disconnected.
    """
    island = _load_team_island(map_slug, spawn_x, spawn_z, wool_coords,
                               output_dir, min_transitions=min_transitions)
    if island is None:
        return None

    nodes = island.nodes
    adj = island.adj
    spawn_id = island.spawn_id
    wool_ids = island.wool_ids
    spawn_node = nodes[spawn_id]
    wool_nodes = [nodes[wid] for wid in wool_ids]

    # Shortest paths from spawn
    dist, prev = _dijkstra(nodes, adj, spawn_id)

    d_graph = [dist[wid] for wid in wool_ids]
    if any(math.isinf(d) for d in d_graph):
        return None  # disconnected

    d_euclidean = [_euclid(spawn_node, wn) for wn in wool_nodes]

    paths = [_path(prev, spawn_id, wid) for wid in wool_ids]

    # Junction counts along each path (excluding the endpoints)
    junction_counts = [
        sum(1 for nid in path[1:-1] if nodes[nid].get("type") == "junction")
        for path in paths
    ]

    # Fork junction: last common node before paths diverge
    fork_id, shared_len = _fork_junction_and_shared(paths[0], paths[1])
    d_to_fork = dist[fork_id] if fork_id is not None else 0.0

    # Shared path fraction: shared_len / length of the longer path
    longer_path_len = max(len(p) for p in paths)
    shared_path_fraction = (shared_len / longer_path_len) if longer_path_len > 0 else 0.0

    # Geometric metrics
    fork_angle_deg = _fork_angle_deg(spawn_node, wool_nodes[0], wool_nodes[1])
    lateral_offset = _lateral_offset(spawn_node, wool_nodes[0], wool_nodes[1])

    d_max = max(d_graph) or 1e-9
    arm_asymmetry = abs(d_graph[0] - d_graph[1]) / d_max

    return ForkMetrics(
        map_slug=map_slug,
        team=team,
        size_tier=size_tier,
        d_graph=d_graph,
        d_euclidean=d_euclidean,
        junction_counts=junction_counts,
        fork_angle_deg=fork_angle_deg,
        lateral_offset=lateral_offset,
        d_to_fork_junction=d_to_fork,
        shared_path_fraction=shared_path_fraction,
        arm_asymmetry=arm_asymmetry,
    )


# ---------------------------------------------------------------------------
# Batch runner + visualisation
# ---------------------------------------------------------------------------

_ELIGIBLE_QUERY = """
-- 2-team, 2-wool-per-team processed maps.
-- Returns one row per (map, defending_team, wool) so Python can group them.
-- spawn_x/z is the DEFENDING team's spawn (from map_spawns), not the attacker's.
WITH team_counts AS (
    SELECT map_id, COUNT(DISTINCT team) AS n_teams
    FROM map_spawns GROUP BY map_id
),
wool_per_team AS (
    SELECT map_id, defending_team AS team, COUNT(DISTINCT wool_id) AS n_wools
    FROM map_wool_attack_relations GROUP BY map_id, defending_team
),
wool_check AS (
    SELECT map_id,
           COUNT(DISTINCT team)  AS n_wool_teams,
           MAX(n_wools)          AS max_wools,
           MIN(n_wools)          AS min_wools
    FROM wool_per_team GROUP BY map_id
)
SELECT m.map_slug, war.defending_team, m.size_tier,
       ms.x  AS spawn_x, ms.z  AS spawn_z,
       war.wool_x,        war.wool_z
FROM maps m
JOIN team_counts           tc  ON m.map_id = tc.map_id
JOIN wool_check            wc  ON m.map_id = wc.map_id
JOIN map_wool_attack_relations war ON m.map_id = war.map_id
JOIN (
    SELECT map_id, team, AVG(x) AS x, AVG(z) AS z
    FROM map_spawns GROUP BY map_id, team
)                          ms  ON m.map_id = ms.map_id
                               AND ms.team = war.defending_team
WHERE m.stub IS NOT TRUE
  AND tc.n_teams       = 2
  AND wc.n_wool_teams  = 2
  AND wc.max_wools     = 2
  AND wc.min_wools     = 2
ORDER BY m.map_slug, war.defending_team, war.wool_id
"""

_TIER_ORDER = ["pico", "nano", "micro", "centi", "milli"]
_TIER_COLORS = {
    "pico":  "#9e0142",
    "nano":  "#f46d43",
    "micro": "#fee090",
    "centi": "#abdda4",
    "milli": "#3288bd",
}


def run(args: object) -> None:
    """Collect fork metrics for all eligible maps and render a summary figure."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np

    db_path    = getattr(args, "fork_db",     "match_analysis/metadata.db")
    output_dir = Path(getattr(args, "output", "output"))
    save_path  = Path(getattr(args, "save_path", None) or
                      "output/_debug/fork_analysis.png")

    # ---- load eligible maps -------------------------------------------------
    conn = duckdb.connect(db_path, read_only=True)
    eligible = conn.execute(_ELIGIBLE_QUERY).fetchall()
    conn.close()

    # Group flat wool rows into (map, team) pairs
    grouped: dict[tuple[str, str, str | None, float, float], list[tuple[float, float]]] = {}
    for map_slug, defending_team, size_tier, spawn_x, spawn_z, wool_x, wool_z in eligible:
        key = (map_slug, defending_team, size_tier, spawn_x, spawn_z)
        grouped.setdefault(key, []).append((wool_x, wool_z))

    results: list[ForkMetrics] = []
    skipped_no_graph: list[str] = []
    skipped_wrong_wool_count: list[str] = []
    skipped_other: list[str] = []

    for (map_slug, team, size_tier, spawn_x, spawn_z), wool_coords in grouped.items():
        if len(wool_coords) != 2:
            skipped_wrong_wool_count.append(
                f"{map_slug}/{team} (wool count={len(wool_coords)})")
            continue
        fm = analyze_fork(map_slug, team, size_tier, spawn_x, spawn_z,
                          wool_coords, output_dir, min_transitions=1)
        if fm is None:
            tg_path = output_dir / map_slug / "traffic_graph.json"
            if not tg_path.exists():
                skipped_no_graph.append(map_slug)
            else:
                skipped_other.append(f"{map_slug}/{team}")
        else:
            results.append(fm)

    n_maps    = len({r.map_slug for r in results})
    n_halves  = len(results)
    no_graph  = len(set(skipped_no_graph))
    print(f"Analyzed {n_halves} team-halves across {n_maps} maps.")
    print(f"Skipped: {no_graph} maps without traffic graph, "
          f"{len(skipped_wrong_wool_count)} wrong wool count, "
          f"{len(skipped_other)} other (disconnected/no spawn).")
    if skipped_other:
        print("  Other failures:", ", ".join(skipped_other[:20]),
              ("..." if len(skipped_other) > 20 else ""))

    if not results:
        print("No results — nothing to plot.")
        return

    from layout_analysis.visualization import plot_fork_analysis
    plot_fork_analysis(results, save_path)
    print(f"Saved: {save_path}")
