"""Data-driven traffic graph built from player position traces.

Replaces the geometric island skeleton as a navigation graph by treating
player positions as ant-colony traces.  Grid cells with sufficient occupancy
become nodes; consecutive player movements between cells become edges.
Spawn and wool nodes from map_graph.json are injected as fixed anchors.

Typical usage (CLI):
    python ctw.py matches traffic-graph --map tumbleweed

Output:
    output/<map_slug>/traffic_graph.json
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from match_analysis.traffic.snapping import bresenham_cells

logger = logging.getLogger("ctw")

# ---------------------------------------------------------------------------
# Tuning defaults (all overridable from CLI)
# ---------------------------------------------------------------------------
DEFAULT_GRID_SIZE       = 5    # block-side of each grid cell
DEFAULT_MIN_OCCUPATION  = 5    # minimum position ticks to keep a node
DEFAULT_MIN_TRANSITIONS = 2    # minimum crossings to keep an edge
DEFAULT_MAX_GAP_S       = 30.0 # max seconds between consecutive samples before ignoring transition


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build_traffic_graph(
    map_slug: str,
    conn,
    output_dir: Path,
    grid_size: int        = DEFAULT_GRID_SIZE,
    min_occupation: int   = DEFAULT_MIN_OCCUPATION,
    min_transitions: int  = DEFAULT_MIN_TRANSITIONS,
    max_gap_s: float      = DEFAULT_MAX_GAP_S,
    log_interval: int     = 2,
) -> dict:
    """Build a traffic graph from all processed position data for *map_slug*.

    Parameters
    ----------
    map_slug:
        Identifies which map's position data to load from the DB.
    log_interval:
        Only include matches whose ``log_interval`` equals this value (or is
        NULL for un-migrated rows).  Default ``2`` restricts to 2-second
        logged matches, filtering out 5-second logged matches that would
        produce sparser traces.

    Returns the graph as a plain dict (same structure written to JSON).
    The dict includes a ``log_interval`` key recording the filter applied.
    """
    logger.info(
        "Building traffic graph for '%s'  grid=%d  min_occ=%d  min_trans=%d",
        map_slug, grid_size, min_occupation, min_transitions,
    )

    # ── 1. Load positions ──────────────────────────────────────────────────
    pos_df: pd.DataFrame = conn.execute("""
        SELECT pe.player_id, pe.match_id, pe.segment_idx, pe.timestamp,
               pe.x, pe.z, pe.location_type, pe.island_id
        FROM position_events pe
        JOIN matches mat ON mat.match_id = pe.match_id
        JOIN maps m      ON m.map_id     = mat.map_id
        WHERE m.map_slug = ? AND mat.processed = TRUE
          AND pe.y > 0
          AND (mat.log_interval = ? OR mat.log_interval IS NULL)
        ORDER BY pe.player_id, pe.match_id, pe.segment_idx, pe.timestamp
    """, [map_slug, log_interval]).df()

    if pos_df.empty:
        raise ValueError(
            f"No position data found for map '{map_slug}'. "
            "Run 'ctw matches process-all --map-name <slug>' first. "
            f"Also check that log_interval={log_interval} matches your data "
            "(use log_interval=5 for 5-second logged matches)."
        )

    match_count    = int(pos_df["match_id"].nunique())
    position_count = len(pos_df)
    logger.debug("Loaded %d positions from %d match(es)", position_count, match_count)

    # ── 1a. Aggregate match-level stats (player participations, aggregate playtime) ─
    # Note: player_id is re-assigned 0…n per match (anonymisation), so
    # COUNT(DISTINCT player_id) across matches is meaningless.  Use SUM of the
    # per-match player_count instead.
    stats_df: pd.DataFrame = conn.execute("""
        SELECT
            (SELECT SUM(mat.player_count)
             FROM matches mat JOIN maps m ON m.map_id = mat.map_id
             WHERE m.map_slug = ? AND mat.processed = TRUE)           AS player_count,
            (SELECT SUM(ls.end_timestamp - ls.start_timestamp) / 60.0
             FROM life_segments ls
             JOIN matches mat ON mat.match_id = ls.match_id
             JOIN maps m      ON m.map_id     = mat.map_id
             WHERE m.map_slug = ? AND mat.processed = TRUE)           AS total_playtime_min
    """, [map_slug, map_slug]).df()
    player_count       = int(stats_df["player_count"].iloc[0])
    total_playtime_min = round(float(stats_df["total_playtime_min"].iloc[0]), 1)

    # ── 1b. Drop void positions ────────────────────────────────────────────
    # 'void' = outside all island and build-region polygons in 2D.
    # These positions are off the map footprint and must not become graph nodes
    # or contribute to edge transitions.
    # Note: y>0 is enforced at query time, filtering players who have fallen out
    # of the world (y<=0).  This belt-and-suspenders check drops any remaining
    # void-classified positions — e.g. players standing in void at ground level
    # (y=1) whose y>0 filter did not catch them.
    n_void = int((pos_df["location_type"] == "void").sum())
    if n_void:
        pos_df = pos_df[pos_df["location_type"] != "void"].copy()
        logger.debug(
            "Dropped %d void positions (%.1f%% of total)",
            n_void, 100.0 * n_void / position_count,
        )

    # ── 2. Discretise to grid cells ────────────────────────────────────────
    pos_df["cx"] = (pos_df["x"] // grid_size * grid_size).astype(int)
    pos_df["cz"] = (pos_df["z"] // grid_size * grid_size).astype(int)

    # ── 2a. Valid cell set (non-void cells that have y>0 positions) ───────────
    # Used later to reject interpolated edge steps through void territory.
    valid_cells_df = pos_df[pos_df["location_type"] != "void"]
    valid_cell_set: set[tuple[int, int]] = set(
        zip(
            (valid_cells_df["x"] // grid_size * grid_size).astype(int),
            (valid_cells_df["z"] // grid_size * grid_size).astype(int),
        )
    )

    # ── 3. Node occupation & dominant island_id ────────────────────────────
    def _mode_or_none(s: pd.Series) -> Optional[int]:
        valid = s.dropna()
        return int(valid.mode().iloc[0]) if not valid.empty else None

    node_stats = (
        pos_df.groupby(["cx", "cz"])
        .agg(
            occupation=("player_id", "count"),
            island_id=("island_id", _mode_or_none),
        )
        .reset_index()
    )

    # ── 4. Consecutive transitions — Bresenham interpolation ──────────────
    # Group by life segment so no transition crosses a death/respawn boundary.
    # For each consecutive position pair, walk the Bresenham line through
    # all intermediate grid cells and record each adjacent-cell step as a
    # transition.  Steps through void cells are rejected via valid_cell_set.
    pos_s = pos_df.sort_values(
        ["player_id", "match_id", "segment_idx", "timestamp"]
    ).copy()
    grp = pos_s.groupby(["player_id", "match_id", "segment_idx"])

    pos_s["prev_cx"] = grp["cx"].shift(1)
    pos_s["prev_cz"] = grp["cz"].shift(1)
    pos_s["dt"]      = pos_s["timestamp"] - grp["timestamp"].shift(1)

    hops = pos_s[
        pos_s["prev_cx"].notna()
        & ((pos_s["cx"] != pos_s["prev_cx"]) | (pos_s["cz"] != pos_s["prev_cz"]))
        & (pos_s["dt"] <= max_gap_s)
    ].copy()

    # Bresenham line: decompose each hop into adjacent-cell steps
    transition_list: list[tuple[int, int, int, int]] = []  # (cx1, cz1, cx2, cz2)

    if not hops.empty:
        cx_arr  = hops["cx"].astype(int).values
        cz_arr  = hops["cz"].astype(int).values
        pcx_arr = hops["prev_cx"].astype(int).values
        pcz_arr = hops["prev_cz"].astype(int).values

        for cx1, cz1, cx2, cz2 in zip(pcx_arr, pcz_arr, cx_arr, cz_arr):
            # Walk Bresenham line from (cx1,cz1) → (cx2,cz2) in grid-cell steps
            cells = bresenham_cells(cx1, cz1, cx2, cz2, grid_size)
            for a, b in zip(cells, cells[1:]):
                if a in valid_cell_set and b in valid_cell_set:
                    transition_list.append((*a, *b))

    if transition_list:
        trans_df = pd.DataFrame(
            transition_list, columns=["cx1", "cz1", "cx2", "cz2"]
        )
        # Canonical undirected key: smaller cell first
        forward   = (trans_df["cx1"] < trans_df["cx2"]) | (
            (trans_df["cx1"] == trans_df["cx2"]) & (trans_df["cz1"] <= trans_df["cz2"])
        )
        key_cx1 = np.where(forward, trans_df["cx1"], trans_df["cx2"])
        key_cz1 = np.where(forward, trans_df["cz1"], trans_df["cz2"])
        key_cx2 = np.where(forward, trans_df["cx2"], trans_df["cx1"])
        key_cz2 = np.where(forward, trans_df["cz2"], trans_df["cz1"])

        trans_df["key_cx1"] = key_cx1
        trans_df["key_cz1"] = key_cz1
        trans_df["key_cx2"] = key_cx2
        trans_df["key_cz2"] = key_cz2

        edge_counts = (
            trans_df.groupby(["key_cx1", "key_cz1", "key_cx2", "key_cz2"])
            .size()
            .reset_index(name="transitions")
        )
    else:
        edge_counts = pd.DataFrame(
            columns=["key_cx1", "key_cz1", "key_cx2", "key_cz2", "transitions"]
        )

    # ── 5. Prune nodes ─────────────────────────────────────────────────────
    node_stats = node_stats[node_stats["occupation"] >= min_occupation].copy()
    node_stats = node_stats.reset_index(drop=True)
    node_stats["node_id"] = node_stats.index
    cell_to_node: dict[tuple[int, int], int] = {
        (int(r.cx), int(r.cz)): int(r.node_id)
        for r in node_stats.itertuples()
    }

    # ── 6. Prune edges ─────────────────────────────────────────────────────
    valid_cells = set(cell_to_node.keys())
    edge_counts = edge_counts[
        (edge_counts["transitions"] >= min_transitions)
        & edge_counts.apply(
            lambda r: (int(r.key_cx1), int(r.key_cz1)) in valid_cells, axis=1
        )
        & edge_counts.apply(
            lambda r: (int(r.key_cx2), int(r.key_cz2)) in valid_cells, axis=1
        )
    ].copy()

    logger.debug(
        "After pruning: %d nodes, %d edges", len(node_stats), len(edge_counts)
    )

    # ── 7. Inject fixed nodes from map_graph.json ──────────────────────────
    map_graph_path = output_dir / "map_graph.json"
    fixed_nodes_added: list[dict] = []

    if map_graph_path.exists():
        with open(map_graph_path) as f:
            mg = json.load(f)

        fixed_sources = [
            n for n in mg["map_graph"]["nodes"]
            if n.get("poi_type") in ("spawn", "wool")
        ]

        next_id = int(node_stats["node_id"].max()) + 1 if not node_stats.empty else 0

        for fn in fixed_sources:
            coords = fn.get("coords")
            if not coords:
                continue
            fx, fz = float(coords[0]), float(coords[1])
            fcx = int(fx // grid_size * grid_size)
            fcz = int(fz // grid_size * grid_size)

            if (fcx, fcz) in cell_to_node:
                # Annotate the existing node
                nid = cell_to_node[(fcx, fcz)]
                mask = (node_stats["node_id"] == nid)
                node_stats.loc[mask, "poi_type"]  = fn.get("poi_type")
                node_stats.loc[mask, "poi_color"] = fn.get("poi_color")
                node_stats.loc[mask, "team"]      = fn.get("team")
                node_stats.loc[mask, "fixed"]     = True
            else:
                # Add a new node for this fixed position
                new_node = {
                    "node_id":   next_id,
                    "cx":        fcx,
                    "cz":        fcz,
                    "occupation": 0,
                    "island_id": fn.get("island_id"),
                    "poi_type":  fn.get("poi_type"),
                    "poi_color": fn.get("poi_color"),
                    "team":      fn.get("team"),
                    "fixed":     True,
                }
                fixed_nodes_added.append(new_node)
                cell_to_node[(fcx, fcz)] = next_id
                next_id += 1

                # Connect to nearest K existing nodes by Euclidean distance
                if cell_to_node:
                    existing_cells = np.array([
                        [cx + grid_size / 2, cz + grid_size / 2]
                        for (cx, cz) in cell_to_node
                        if (cx, cz) != (fcx, fcz)
                    ])
                    center = np.array([fcx + grid_size / 2, fcz + grid_size / 2])
                    dists  = np.linalg.norm(existing_cells - center, axis=1)
                    k      = min(3, len(dists))
                    for nbr_idx in np.argsort(dists)[:k]:
                        nbr_cx = int(existing_cells[nbr_idx, 0] - grid_size / 2)
                        nbr_cz = int(existing_cells[nbr_idx, 1] - grid_size / 2)
                        nbr_id = cell_to_node.get((nbr_cx, nbr_cz))
                        if nbr_id is not None:
                            ca = (min(next_id - 1, nbr_id), max(next_id - 1, nbr_id))
                            synthetic = pd.DataFrame([{
                                "key_cx1": fcx if (next_id - 1) < nbr_id else nbr_cx,
                                "key_cz1": fcz if (next_id - 1) < nbr_id else nbr_cz,
                                "key_cx2": nbr_cx if (next_id - 1) < nbr_id else fcx,
                                "key_cz2": nbr_cz if (next_id - 1) < nbr_id else fcz,
                                "transitions": 1,
                            }])
                            edge_counts = pd.concat([edge_counts, synthetic], ignore_index=True)

        if fixed_nodes_added:
            extra_df = pd.DataFrame(fixed_nodes_added)
            # Ensure same columns as node_stats
            for col in node_stats.columns:
                if col not in extra_df.columns:
                    extra_df[col] = None
            node_stats = pd.concat([node_stats, extra_df[node_stats.columns]], ignore_index=True)
            logger.debug("Injected %d new fixed nodes", len(fixed_nodes_added))
    else:
        logger.warning("map_graph.json not found at %s — no fixed nodes injected", map_graph_path)

    # Ensure annotation columns exist
    for col in ("poi_type", "poi_color", "team", "fixed"):
        if col not in node_stats.columns:
            node_stats[col] = None

    # ── 8. Serialise ───────────────────────────────────────────────────────
    nodes: list[dict] = []
    for r in node_stats.itertuples(index=False):
        nodes.append({
            "node_id":   int(r.node_id),
            "cx":        int(r.cx),
            "cz":        int(r.cz),
            "coords":    [r.cx + grid_size / 2, r.cz + grid_size / 2],
            "occupation": int(r.occupation) if pd.notna(r.occupation) else 0,
            "island_id": int(r.island_id) if pd.notna(r.island_id) else None,
            "poi_type":  r.poi_type if pd.notna(r.poi_type) else None,
            "poi_color": r.poi_color if pd.notna(r.poi_color) else None,
            "team":      r.team if pd.notna(r.team) else None,
            "fixed":     bool(r.fixed) if pd.notna(r.fixed) else False,
        })

    edges: list[dict] = []
    seen_pairs: set[tuple[int, int]] = set()
    for r in edge_counts.itertuples(index=False):
        src = cell_to_node.get((int(r.key_cx1), int(r.key_cz1)))
        dst = cell_to_node.get((int(r.key_cx2), int(r.key_cz2)))
        if src is None or dst is None or src == dst:
            continue
        key = (min(src, dst), max(src, dst))
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        edges.append({"src": int(src), "dst": int(dst), "transitions": int(r.transitions)})

    graph = {
        "map_slug":           map_slug,
        "grid_size":          grid_size,
        "log_interval":       log_interval,
        "match_count":        match_count,
        "position_count":     position_count,
        "player_count":       player_count,
        "total_playtime_min": total_playtime_min,
        "nodes":          nodes,
        "edges":          edges,
    }

    logger.info(
        "Traffic graph: %d nodes, %d edges  (from %d positions, %d match(es))",
        len(nodes), len(edges), position_count, match_count,
    )
    return graph


def save_traffic_graph(graph: dict, path: Path) -> None:
    """Write *graph* to *path* as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(graph, f, indent=2)
    logger.info("Saved traffic graph → %s", path)


# ---------------------------------------------------------------------------
# Load & topology
# ---------------------------------------------------------------------------

def load_traffic_graph(path: Path) -> dict:
    """Read traffic_graph.json and return the raw dict."""
    with open(path) as f:
        return json.load(f)


def build_traffic_topology(graph: dict) -> dict:
    """Convert a raw traffic graph dict into the same topology interface as
    ``build_graph_topology()`` in the notebook helpers.

    Returns:
        node_info      : {node_id: full node dict}   (coords = [x, z])
        full_graph     : nx.Graph of the entire map (all nodes + edges)
        island_graphs  : {island_id: nx.Graph}  (per-island subgraphs)
        wool_nodes     : list of nodes where poi_type == 'wool'
        spawn_nodes    : list of nodes where poi_type == 'spawn'
        dijkstra_dists : {wool_node_id: {node_id: graph_dist}}
        wool_baselines : {wool_node_id: max_dist_on_island}
        grid_size      : int
    """
    import networkx as nx

    # Copy nodes so we don't mutate the original graph dict
    node_info: dict[int, dict] = {n["node_id"]: dict(n) for n in graph["nodes"]}
    # map_node_id alias for compatibility with add_graph_depth() and Section 4 code
    for n in node_info.values():
        n["map_node_id"] = n["node_id"]

    # Full graph (all nodes, all edges, weight = Euclidean distance between cell centres)
    G_full = nx.Graph()
    for n in graph["nodes"]:
        G_full.add_node(n["node_id"], **n)

    for e in graph["edges"]:
        src_coords = node_info.get(e["src"], {}).get("coords")
        dst_coords = node_info.get(e["dst"], {}).get("coords")
        if src_coords and dst_coords:
            w = math.sqrt(
                (src_coords[0] - dst_coords[0]) ** 2
                + (src_coords[1] - dst_coords[1]) ** 2
            )
            G_full.add_edge(e["src"], e["dst"], weight=w, transitions=e["transitions"])

    # Per-island subgraphs (nodes that share an island_id)
    island_graphs: dict[int, nx.Graph] = {}
    for n in graph["nodes"]:
        iid = n.get("island_id")
        if iid is None:
            continue
        if iid not in island_graphs:
            island_graphs[iid] = nx.Graph()
        island_graphs[iid].add_node(n["node_id"], **n)
    for e in graph["edges"]:
        sn = node_info.get(e["src"])
        dn = node_info.get(e["dst"])
        if sn is None or dn is None:
            continue
        if sn.get("island_id") == dn.get("island_id") and sn.get("island_id") is not None:
            sc = sn.get("coords"); dc = dn.get("coords")
            if sc and dc:
                w = math.sqrt((sc[0]-dc[0])**2 + (sc[1]-dc[1])**2)
                island_graphs[sn["island_id"]].add_edge(
                    e["src"], e["dst"], weight=w, transitions=e["transitions"]
                )

    wool_nodes  = [n for n in node_info.values() if n.get("poi_type") == "wool"]
    spawn_nodes = [n for n in node_info.values() if n.get("poi_type") == "spawn"]

    # Dijkstra from each wool node within the FULL graph (traversal can cross build regions)
    dijkstra_dists: dict[int, dict[int, float]] = {}
    for wn in wool_nodes:
        wid = wn["node_id"]
        if wid not in G_full:
            continue
        dijkstra_dists[wid] = dict(
            nx.single_source_dijkstra_path_length(G_full, wid, weight="weight")
        )

    # Baseline = max distance on the wool's island (for normalisation)
    wool_baselines: dict[int, float] = {}
    for wn in wool_nodes:
        wid   = wn["node_id"]
        iid   = wn.get("island_id")
        dists = dijkstra_dists.get(wid, {})
        if not dists:
            wool_baselines[wid] = 1.0
            continue
        # Only consider nodes on the same island for the baseline
        island_node_ids = set(island_graphs.get(iid, {}).nodes()) if iid else set()
        island_dists    = [d for nid, d in dists.items() if nid in island_node_ids]
        wool_baselines[wid] = max(island_dists) if island_dists else max(dists.values(), default=1.0)

    return {
        "node_info":       node_info,
        "full_graph":      G_full,
        "island_graphs":   island_graphs,
        "wool_nodes":      wool_nodes,
        "spawn_nodes":     spawn_nodes,
        "dijkstra_dists":  dijkstra_dists,
        "wool_baselines":  wool_baselines,
        "grid_size":       graph.get("grid_size", DEFAULT_GRID_SIZE),
    }


# ---------------------------------------------------------------------------
# Visualisation
# ---------------------------------------------------------------------------

def plot_traffic_graph(
    graph: dict,
    map_context: Optional[dict],
    output_path: Path,
) -> None:
    """Render the traffic graph as a map overlay and save to *output_path*."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.patches import Polygon as MplPolygon
    from matplotlib.lines import Line2D
    from matplotlib.colors import Normalize
    from matplotlib.cm import ScalarMappable
    import matplotlib.cm as cm

    nodes = graph["nodes"]
    edges = graph["edges"]
    node_by_id = {n["node_id"]: n for n in nodes}

    grid_size         = graph.get("grid_size", DEFAULT_GRID_SIZE)
    n_matches         = graph.get("match_count", "?")
    n_pos             = graph.get("position_count", "?")
    n_players         = graph.get("player_count", "?")
    playtime_min      = graph.get("total_playtime_min")

    occupations = [n["occupation"] for n in nodes]
    max_occ     = max(occupations) if occupations else 1
    transitions = [e["transitions"] for e in edges]
    max_trans   = max(transitions) if transitions else 1

    # Coordinate bounds
    xs = [n["coords"][0] for n in nodes]
    zs = [n["coords"][1] for n in nodes]
    if not xs:
        logger.warning("No nodes to plot.")
        return
    pad  = 20
    xmin, xmax = min(xs) - pad, max(xs) + pad
    zmin, zmax = min(zs) - pad, max(zs) + pad

    fig, ax = plt.subplots(figsize=(10, 12), facecolor="#0d0d18")
    ax.set_facecolor("#0d0d18")
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(zmax, zmin)  # invert z (north-up)
    ax.set_aspect("equal")
    ax.set_xlabel("World X", color="#aaaaaa")
    ax.set_ylabel("World Z", color="#aaaaaa")
    ax.tick_params(colors="#555555")
    for spine in ax.spines.values():
        spine.set_edgecolor("#333333")

    # Island polygons (faint background)
    if map_context:
        # Build team id → hex colour from map_context teams list
        team_hex: dict[str, str] = {}
        for team in map_context.get("teams", []):
            tid = team.get("id", "")
            raw = team.get("color", "")
            team_hex[tid] = _MINECRAFT_COLORS.get(raw, "#3a3a5a")

        for isl in map_context.get("islands", []):
            pts = (isl.get("simplified_polygon") or {}).get("exterior", [])
            if not pts:
                continue
            isl_t = isl.get("team")
            fc    = team_hex.get(isl_t, "#3a3a5a")
            alpha = 0.20 if isl_t else 0.10
            patch = MplPolygon(np.array(pts), closed=True,
                               facecolor=fc, edgecolor=fc,
                               linewidth=0.3, alpha=alpha, zorder=0)
            ax.add_patch(patch)

    # Edges — colour by transition count
    cmap_e = cm.get_cmap("YlOrRd")
    norm_e = Normalize(vmin=0, vmax=max_trans)
    for e in edges:
        sn = node_by_id.get(e["src"])
        dn = node_by_id.get(e["dst"])
        if sn is None or dn is None:
            continue
        sc = sn["coords"]; dc = dn["coords"]
        t  = e["transitions"]
        lw = 0.4 + 2.5 * t / max_trans
        ax.plot([sc[0], dc[0]], [sc[1], dc[1]],
                color=cmap_e(norm_e(t)), lw=lw, alpha=0.55, zorder=1)

    # Nodes — size by occupation, colour by location (island vs build vs fixed)
    _LOC_COLORS = {"island": "#5599ff", "build_region": "#ffbb44", "void": "#888888"}

    for n in nodes:
        coords = n["coords"]
        occ    = n["occupation"]
        s      = 8 + 100 * occ / max_occ
        if n.get("poi_type") == "wool":
            wc = _WOOL_COLORS.get(n.get("poi_color", ""), "#ffffff")
            ax.scatter(coords[0], coords[1], s=s * 1.5, color=wc,
                       marker="D", edgecolors="white", linewidths=1.2, zorder=5)
            ax.annotate(n.get("poi_color", "?"), (coords[0], coords[1]),
                        xytext=(5, 3), textcoords="offset points",
                        color="white", fontsize=7, fontweight="bold", zorder=6)
        elif n.get("poi_type") == "spawn":
            ax.scatter(coords[0], coords[1], s=s * 1.2, color="#aaaaaa",
                       marker="s", edgecolors="white", linewidths=1.0, zorder=5)
        else:
            iid = n.get("island_id")
            fc  = "#5599ff" if iid is not None else "#ffbb44"
            ax.scatter(coords[0], coords[1], s=s, color=fc, alpha=0.70,
                       linewidths=0, zorder=3)

    # Colorbar for edge transition count
    sm = ScalarMappable(cmap=cmap_e, norm=norm_e)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, fraction=0.03, pad=0.02)
    cbar.set_label("Edge transitions", color="#aaaaaa")
    cbar.ax.yaxis.set_tick_params(color="#aaaaaa")
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color="#aaaaaa")

    # Legend
    legend_els = [
        Line2D([0], [0], color="#5599ff", lw=0, marker="o", ms=7,
               markerfacecolor="#5599ff", label="island node"),
        Line2D([0], [0], color="#ffbb44", lw=0, marker="o", ms=7,
               markerfacecolor="#ffbb44", label="build region node"),
        Line2D([0], [0], color="white", lw=0, marker="D", ms=7,
               label="wool node"),
        Line2D([0], [0], color="#aaaaaa", lw=0, marker="s", ms=6,
               label="spawn node"),
    ]
    ax.legend(handles=legend_els, loc="lower left", fontsize=7,
              facecolor="#0e0e1a", labelcolor="white", framealpha=0.8)

    n_nodes = len(nodes); n_edges = len(edges)
    playtime_str = (
        f"{playtime_min:,.0f} min aggregate playtime"
        if playtime_min is not None else ""
    )
    subtitle_parts = [f"{n_players} participations", f"{n_pos:,} positions"]
    if playtime_str:
        subtitle_parts.append(playtime_str)
    ax.set_title(
        f"Traffic graph — {graph['map_slug']}  "
        f"({n_matches} match{'es' if n_matches != 1 else ''}  |  "
        + "  ·  ".join(subtitle_parts) + ")\n"
        f"{n_nodes} nodes · {n_edges} edges  |  grid={grid_size}×{grid_size} blocks",
        color="white", fontsize=10,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=130, bbox_inches="tight", facecolor="#0d0d1a")
    plt.close(fig)
    logger.info("Saved traffic graph plot → %s", output_path)


# ---------------------------------------------------------------------------
# Colour palettes
# ---------------------------------------------------------------------------

_WOOL_COLORS: dict[str, str] = {
    "cyan": "#00BBCC", "lime": "#44CC44", "orange": "#FFA500",
    "yellow": "#DDDD00", "red": "#FF5555", "blue": "#5555FF",
    "white": "#CCCCCC", "purple": "#AA00AA", "green": "#55FF55",
    "magenta": "#FF55FF", "pink": "#FF99CC", "gray": "#888888",
    "light_gray": "#BBBBBB", "brown": "#AA7733", "black": "#333333",
}

_MINECRAFT_COLORS: dict[str, str] = {
    "dark_red":    "#AA0000", "dark red":    "#AA0000",
    "red":         "#FF5555",
    "gold":        "#FFAA00",
    "yellow":      "#DDDD00",
    "dark_green":  "#00AA00", "dark green":  "#00AA00",
    "green":       "#55FF55",
    "aqua":        "#55FFFF",
    "dark_aqua":   "#00AAAA", "dark aqua":   "#00AAAA",
    "dark_blue":   "#0000AA", "dark blue":   "#0000AA",
    "blue":        "#5555FF",
    "light_purple":"#FF55FF", "light purple":"#FF55FF",
    "dark_purple": "#AA00AA", "dark purple": "#AA00AA",
    "white":       "#FFFFFF",
    "gray":        "#AAAAAA",
    "dark_gray":   "#555555", "dark gray":   "#555555",
    "black":       "#000000",
}
