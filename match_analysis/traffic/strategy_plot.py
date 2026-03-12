"""Six-panel strategy comparison figure for traffic graph construction methods.

Compares five graph construction strategies side-by-side for a given map,
plus a stats panel.  Used to evaluate graph quality before choosing
production parameters.

Panel layout (2 × 3)
---------------------
  A  |  B  |  C
  D  |  E  |  F

A — Raw position scatter (all 2s-logged matches, no grid)
B — Grid 5×5 (current default)
C — Grid 3×3 (fine fixed)
D — Adaptive grid (size = max(2, sqrt(total_blocks / 300)) rounded)
E — Voronoi / k-means cluster nodes
F — Strategy stats table
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib.patches
import matplotlib.colors
from matplotlib.lines import Line2D

try:
    from sklearn.cluster import MiniBatchKMeans
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False

from match_analysis.traffic.snapping import bresenham_cells

# ---------------------------------------------------------------------------
# Colour palettes (copied from traffic_graph.py — module-private there)
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BG_COLOR   = "#0d0d18"
_GRID_COLOR = "#222233"

logger = logging.getLogger("ctw")

# ---------------------------------------------------------------------------
# Strategy build functions
# ---------------------------------------------------------------------------


def _build_grid_graph(
    pos_df: pd.DataFrame,
    grid_size: int,
    min_occupation: int,
    min_transitions: int,
    valid_cell_set: set[tuple[int, int]],
) -> tuple[list[dict], list[dict]]:
    """Build a grid-based traffic graph from position data.

    Parameters
    ----------
    pos_df:
        DataFrame with columns ``x``, ``z``, ``location_type``,
        ``player_id``, ``match_id``, ``segment_idx``, ``timestamp``.
    grid_size:
        Side length (in blocks) for each grid cell.
    min_occupation:
        Minimum position ticks for a cell to become a node.
    min_transitions:
        Minimum edge crossings for an edge to be kept.
    valid_cell_set:
        Set of (cx, cz) grid-5 cells that contain non-void positions.
        Used to reject Bresenham steps through void territory.

    Returns
    -------
    nodes_list:
        Each dict has ``cx``, ``cz``, ``coords``, ``occupation``.
    edges_list:
        Each dict has ``src_cx``, ``src_cz``, ``dst_cx``, ``dst_cz``,
        ``transitions``.
    """
    if pos_df.empty:
        return [], []

    df = pos_df.copy()
    df["cx"] = (df["x"] // grid_size * grid_size).astype(int)
    df["cz"] = (df["z"] // grid_size * grid_size).astype(int)

    # Build this strategy's own valid_cell_set at the requested grid_size
    strategy_valid: set[tuple[int, int]] = set(
        zip(
            (df["x"] // grid_size * grid_size).astype(int),
            (df["z"] // grid_size * grid_size).astype(int),
        )
    )

    # Node occupation
    node_stats = (
        df.groupby(["cx", "cz"])
        .agg(occupation=("player_id", "count"))
        .reset_index()
    )

    # Consecutive transitions with Bresenham interpolation
    max_gap_s = 30.0
    pos_s = df.sort_values(
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

    transition_list: list[tuple[int, int, int, int]] = []
    if not hops.empty:
        cx_arr  = hops["cx"].astype(int).values
        cz_arr  = hops["cz"].astype(int).values
        pcx_arr = hops["prev_cx"].astype(int).values
        pcz_arr = hops["prev_cz"].astype(int).values

        for cx1, cz1, cx2, cz2 in zip(pcx_arr, pcz_arr, cx_arr, cz_arr):
            cells = bresenham_cells(cx1, cz1, cx2, cz2, grid_size)
            for a, b in zip(cells, cells[1:]):
                if a in strategy_valid and b in strategy_valid:
                    transition_list.append((*a, *b))

    if transition_list:
        trans_df = pd.DataFrame(
            transition_list, columns=["cx1", "cz1", "cx2", "cz2"]
        )
        forward = (trans_df["cx1"] < trans_df["cx2"]) | (
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

    # Prune nodes
    node_stats = node_stats[node_stats["occupation"] >= min_occupation].copy()
    node_stats = node_stats.reset_index(drop=True)
    valid_cells: set[tuple[int, int]] = {
        (int(r.cx), int(r.cz)) for r in node_stats.itertuples()
    }

    # Prune edges
    if not edge_counts.empty:
        edge_counts = edge_counts[
            (edge_counts["transitions"] >= min_transitions)
            & edge_counts.apply(
                lambda r: (int(r.key_cx1), int(r.key_cz1)) in valid_cells, axis=1
            )
            & edge_counts.apply(
                lambda r: (int(r.key_cx2), int(r.key_cz2)) in valid_cells, axis=1
            )
        ].copy()

    nodes_list: list[dict] = []
    for r in node_stats.itertuples(index=False):
        nodes_list.append({
            "cx":         int(r.cx),
            "cz":         int(r.cz),
            "coords":     [r.cx + grid_size / 2, r.cz + grid_size / 2],
            "occupation": int(r.occupation),
        })

    edges_list: list[dict] = []
    node_lookup: dict[tuple[int, int], dict] = {
        (n["cx"], n["cz"]): n for n in nodes_list
    }
    for r in edge_counts.itertuples(index=False):
        src_key = (int(r.key_cx1), int(r.key_cz1))
        dst_key = (int(r.key_cx2), int(r.key_cz2))
        if src_key not in node_lookup or dst_key not in node_lookup:
            continue
        edges_list.append({
            "src_cx":     src_key[0],
            "src_cz":     src_key[1],
            "dst_cx":     dst_key[0],
            "dst_cz":     dst_key[1],
            "transitions": int(r.transitions),
        })

    return nodes_list, edges_list


def _build_voronoi_graph(
    pos_df: pd.DataFrame,
    min_occupation: int,
    min_transitions: int,
    valid_cell_set: set[tuple[int, int]],
    n_clusters: Optional[int] = None,
) -> tuple[list[dict], list[dict]]:
    """Build a Voronoi (k-means cluster) traffic graph from position data.

    Parameters
    ----------
    pos_df:
        DataFrame with columns ``x``, ``z``, ``player_id``, ``match_id``,
        ``segment_idx``, ``timestamp``.
    min_occupation:
        Minimum position ticks for a cluster node to be retained.
    min_transitions:
        Minimum transitions between adjacent clusters for an edge to be kept.
    valid_cell_set:
        Set of (cx, cz) grid-5 cells for void-rejection of cluster centres.
    n_clusters:
        Number of k-means clusters.  Auto-computed if None.

    Returns
    -------
    nodes_list, edges_list — same format as ``_build_grid_graph``.
    """
    if not _SKLEARN_AVAILABLE:
        logger.warning(
            "scikit-learn is not available; skipping Voronoi/k-means strategy."
        )
        return [], []

    if pos_df.empty:
        return [], []

    if n_clusters is None:
        n_clusters = min(400, max(20, int(math.sqrt(len(pos_df) / 4))))

    xy = pos_df[["x", "z"]].values.astype(float)
    kmeans = MiniBatchKMeans(n_clusters=n_clusters, random_state=42)
    labels = kmeans.fit_predict(xy)
    centers = kmeans.cluster_centers_  # shape (n_clusters, 2)

    # Occupation per cluster
    occ_counts: dict[int, int] = {}
    for lbl in labels:
        occ_counts[int(lbl)] = occ_counts.get(int(lbl), 0) + 1

    # Consecutive cluster-to-cluster transitions (direct, no Bresenham)
    df = pos_df.copy()
    df["cluster"] = labels.astype(int)

    max_gap_s = 30.0
    pos_s = df.sort_values(
        ["player_id", "match_id", "segment_idx", "timestamp"]
    ).copy()
    grp = pos_s.groupby(["player_id", "match_id", "segment_idx"])
    pos_s["prev_cluster"] = grp["cluster"].shift(1)
    pos_s["dt"]           = pos_s["timestamp"] - grp["timestamp"].shift(1)

    hops = pos_s[
        pos_s["prev_cluster"].notna()
        & (pos_s["cluster"] != pos_s["prev_cluster"])
        & (pos_s["dt"] <= max_gap_s)
    ].copy()

    transition_list: list[tuple[int, int]] = []
    if not hops.empty:
        src_arr = hops["prev_cluster"].astype(int).values
        dst_arr = hops["cluster"].astype(int).values
        for src, dst in zip(src_arr, dst_arr):
            # Void-rejection: floor cluster centre to grid-5 and check valid_cell_set
            src_cx5 = int(centers[src, 0] // 5 * 5)
            src_cz5 = int(centers[src, 1] // 5 * 5)
            dst_cx5 = int(centers[dst, 0] // 5 * 5)
            dst_cz5 = int(centers[dst, 1] // 5 * 5)
            if (src_cx5, src_cz5) in valid_cell_set and (dst_cx5, dst_cz5) in valid_cell_set:
                transition_list.append((src, dst))

    if transition_list:
        trans_df = pd.DataFrame(transition_list, columns=["src", "dst"])
        # Canonical undirected key
        forward = trans_df["src"] <= trans_df["dst"]
        trans_df["key_src"] = np.where(forward, trans_df["src"], trans_df["dst"])
        trans_df["key_dst"] = np.where(forward, trans_df["dst"], trans_df["src"])
        edge_counts = (
            trans_df.groupby(["key_src", "key_dst"])
            .size()
            .reset_index(name="transitions")
        )
    else:
        edge_counts = pd.DataFrame(columns=["key_src", "key_dst", "transitions"])

    # Prune nodes by occupation and void rejection
    valid_cluster_ids: set[int] = set()
    for cid, occ in occ_counts.items():
        if occ < min_occupation:
            continue
        cx5 = int(centers[cid, 0] // 5 * 5)
        cz5 = int(centers[cid, 1] // 5 * 5)
        if (cx5, cz5) in valid_cell_set:
            valid_cluster_ids.add(cid)

    nodes_list: list[dict] = []
    node_by_id: dict[int, dict] = {}
    for cid in sorted(valid_cluster_ids):
        n = {
            "node_id":    cid,
            "cx":         float(centers[cid, 0]),
            "cz":         float(centers[cid, 1]),
            "coords":     [float(centers[cid, 0]), float(centers[cid, 1])],
            "occupation": occ_counts.get(cid, 0),
        }
        nodes_list.append(n)
        node_by_id[cid] = n

    # Prune edges
    edges_list: list[dict] = []
    for r in edge_counts.itertuples(index=False):
        src = int(r.key_src)
        dst = int(r.key_dst)
        if src not in node_by_id or dst not in node_by_id:
            continue
        if int(r.transitions) < min_transitions:
            continue
        edges_list.append({
            "src_cx":      float(centers[src, 0]),
            "src_cz":      float(centers[src, 1]),
            "dst_cx":      float(centers[dst, 0]),
            "dst_cz":      float(centers[dst, 1]),
            "transitions": int(r.transitions),
        })

    return nodes_list, edges_list


def _adaptive_grid_size(total_blocks: int) -> int:
    """Compute map-adaptive grid size from total playable blocks."""
    return max(2, round(math.sqrt(max(total_blocks, 1) / 300)))


# ---------------------------------------------------------------------------
# Panel drawing helpers
# ---------------------------------------------------------------------------


def _style_ax(
    ax: plt.Axes,
    xmin: float,
    xmax: float,
    zmin: float,
    zmax: float,
    title: str = "",
) -> None:
    """Apply shared dark-theme axis styling."""
    ax.set_facecolor(_BG_COLOR)
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(zmax, zmin)  # Z inverted: north-up
    ax.set_aspect("equal")
    ax.set_xlabel("World X", color="#aaaaaa", fontsize=7)
    ax.set_ylabel("World Z", color="#aaaaaa", fontsize=7)
    ax.tick_params(colors="#555555", labelsize=6)
    for spine in ax.spines.values():
        spine.set_edgecolor("#333333")
    if title:
        ax.set_title(title, color="#cccccc", fontsize=8, pad=4)


def _draw_island_polygons(ax: plt.Axes, map_context: dict, alpha: float = 0.15) -> None:
    """Draw island polygon fills using team colours."""
    from matplotlib.patches import Polygon as MplPolygon

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
        a     = alpha if isl_t else alpha * 0.5
        patch = MplPolygon(
            np.array(pts), closed=True,
            facecolor=fc, edgecolor=fc,
            linewidth=0.3, alpha=a, zorder=0,
        )
        ax.add_patch(patch)


def _draw_graph_panel(
    ax: plt.Axes,
    nodes: list[dict],
    edges: list[dict],
    xmin: float,
    xmax: float,
    zmin: float,
    zmax: float,
    title: str,
    map_context: Optional[dict] = None,
) -> None:
    """Draw a single graph panel (nodes + edges) with dark-theme styling."""
    _style_ax(ax, xmin, xmax, zmin, zmax, title)

    if map_context:
        _draw_island_polygons(ax, map_context)

    if not nodes:
        ax.text(
            0.5, 0.5, "No nodes",
            transform=ax.transAxes, ha="center", va="center",
            color="#888888", fontsize=10,
        )
        return

    occupations = [n["occupation"] for n in nodes]
    max_occ = max(occupations) if occupations else 1

    transitions_vals = [e["transitions"] for e in edges]
    max_trans = max(transitions_vals) if transitions_vals else 1

    cmap_e = cm.get_cmap("YlOrRd")
    norm_e = matplotlib.colors.Normalize(vmin=0, vmax=max_trans)

    # Edges
    for e in edges:
        t  = e["transitions"]
        lw = 0.3 + 2.0 * t / max_trans
        ax.plot(
            [e["src_cx"], e["dst_cx"]],
            [e["src_cz"], e["dst_cz"]],
            color=cmap_e(norm_e(t)), lw=lw, alpha=0.4, zorder=1,
        )

    # Nodes
    xs_n = [n["coords"][0] for n in nodes]
    zs_n = [n["coords"][1] for n in nodes]
    sizes = [8 + 80 * n["occupation"] / max_occ for n in nodes]
    ax.scatter(xs_n, zs_n, s=sizes, color="#5599ff", alpha=0.75,
               linewidths=0, zorder=3)


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------


def plot_traffic_strategy_comparison(
    *,
    map_slug: str,
    pos_df: pd.DataFrame,
    total_blocks: int,
    n_matches: int = 0,
    map_context: Optional[dict] = None,
    min_occupation: int = 5,
    min_transitions: int = 2,
    output_path: Optional[Path] = None,
) -> plt.Figure:
    """Generate a 2×3 strategy comparison figure for a map's traffic graph.

    Parameters
    ----------
    map_slug:
        Map identifier used in the figure title.
    pos_df:
        Position DataFrame with columns ``x``, ``z``, ``location_type``,
        ``y``, ``player_id``, ``match_id``, ``segment_idx``, ``timestamp``.
        Should already be filtered to ``y > 0`` and the relevant log_interval.
    total_blocks:
        Total playable block count; used to compute the adaptive grid size.
    map_context:
        Parsed ``map_context.json`` dict for island polygon backgrounds.
    min_occupation:
        Minimum position ticks to retain a node (all strategies).
    min_transitions:
        Minimum crossings to retain an edge (all strategies).
    output_path:
        If provided, save the figure as PNG here and close it.

    Returns
    -------
    matplotlib.figure.Figure
    """
    n_pos     = len(pos_df)
    n_matches = int(pos_df["match_id"].nunique()) if "match_id" in pos_df.columns else 0

    logger.info(
        "Building strategy comparison for '%s'  (%d positions, %d matches)",
        map_slug, n_pos, n_matches,
    )

    # ── 1. Valid cell set (grid-5 reference, non-void) ─────────────────────
    valid_cells_df = pos_df[pos_df["location_type"] != "void"]
    valid_cell_set: set[tuple[int, int]] = set(
        zip(
            (valid_cells_df["x"] // 5 * 5).astype(int),
            (valid_cells_df["z"] // 5 * 5).astype(int),
        )
    )

    # ── 2. Build all strategy graphs ──────────────────────────────────────
    logger.debug("Building grid-5 graph …")
    nodes_g5, edges_g5 = _build_grid_graph(
        pos_df, 5, min_occupation, min_transitions, valid_cell_set
    )

    logger.debug("Building grid-3 graph …")
    nodes_g3, edges_g3 = _build_grid_graph(
        pos_df, 3, min_occupation, min_transitions, valid_cell_set
    )

    adaptive_gs = _adaptive_grid_size(total_blocks)
    logger.debug("Building adaptive grid-%d graph …", adaptive_gs)
    nodes_ga, edges_ga = _build_grid_graph(
        pos_df, adaptive_gs, min_occupation, min_transitions, valid_cell_set
    )

    logger.debug("Building Voronoi/k-means graph …")
    nodes_vor, edges_vor = _build_voronoi_graph(
        pos_df, min_occupation, min_transitions, valid_cell_set
    )

    n_clusters_vor = (
        min(400, max(20, int(math.sqrt(n_pos / 4)))) if n_pos > 0 else 0
    )

    logger.debug(
        "Strategy results — g5:%d/%d  g3:%d/%d  ga(gs=%d):%d/%d  vor:%d/%d",
        len(nodes_g5), len(edges_g5),
        len(nodes_g3), len(edges_g3),
        adaptive_gs, len(nodes_ga), len(edges_ga),
        len(nodes_vor), len(edges_vor),
    )

    # ── 3. Coordinate bounds from all positions ───────────────────────────
    if n_pos > 0:
        pad  = 20
        xmin = float(pos_df["x"].min()) - pad
        xmax = float(pos_df["x"].max()) + pad
        zmin = float(pos_df["z"].min()) - pad
        zmax = float(pos_df["z"].max()) + pad
    else:
        xmin, xmax, zmin, zmax = -100.0, 100.0, -100.0, 100.0

    # ── 4. Figure ─────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(22, 14), facecolor=_BG_COLOR)
    gs  = fig.add_gridspec(2, 3, hspace=0.18, wspace=0.08)

    ax_a = fig.add_subplot(gs[0, 0])
    ax_b = fig.add_subplot(gs[0, 1])
    ax_c = fig.add_subplot(gs[0, 2])
    ax_d = fig.add_subplot(gs[1, 0])
    ax_e = fig.add_subplot(gs[1, 1])
    ax_f = fig.add_subplot(gs[1, 2])

    # ── Panel A — raw scatter ─────────────────────────────────────────────
    _style_ax(
        ax_a, xmin, xmax, zmin, zmax,
        f"A — Raw positions\n(all 2s-logged matches, n={n_pos:,})",
    )
    if map_context:
        _draw_island_polygons(ax_a, map_context)

    if n_pos > 0:
        xs_all = pos_df["x"].values.astype(float)
        zs_all = pos_df["z"].values.astype(float)

        # 2D histogram for density colouring
        hist, xedges, zedges = np.histogram2d(
            xs_all, zs_all,
            bins=[
                max(1, int((xmax - xmin) / 5)),
                max(1, int((zmax - zmin) / 5)),
            ],
            range=[[xmin, xmax], [zmin, zmax]],
        )
        # Map each point to its bin density
        xi = np.clip(
            np.searchsorted(xedges[1:], xs_all),
            0, hist.shape[0] - 1,
        )
        zi = np.clip(
            np.searchsorted(zedges[1:], zs_all),
            0, hist.shape[1] - 1,
        )
        density = hist[xi, zi].astype(float)
        max_d   = density.max() if density.max() > 0 else 1.0
        density_norm = density / max_d

        ax_a.scatter(
            xs_all, zs_all,
            c=density_norm, cmap="plasma",
            s=2, alpha=0.25, linewidths=0, zorder=2,
        )

    # ── Panel B — Grid 5×5 ────────────────────────────────────────────────
    _draw_graph_panel(
        ax_b, nodes_g5, edges_g5,
        xmin, xmax, zmin, zmax,
        title=(
            f"B — Grid 5×5 (default)\n"
            f"{len(nodes_g5):,} nodes · {len(edges_g5):,} edges"
        ),
        map_context=map_context,
    )

    # ── Panel C — Grid 3×3 ────────────────────────────────────────────────
    _draw_graph_panel(
        ax_c, nodes_g3, edges_g3,
        xmin, xmax, zmin, zmax,
        title=(
            f"C — Grid 3×3 (fine fixed)\n"
            f"{len(nodes_g3):,} nodes · {len(edges_g3):,} edges"
        ),
        map_context=map_context,
    )

    # ── Panel D — Adaptive grid ───────────────────────────────────────────
    _draw_graph_panel(
        ax_d, nodes_ga, edges_ga,
        xmin, xmax, zmin, zmax,
        title=(
            f"D — Adaptive grid {adaptive_gs}×{adaptive_gs}\n"
            f"{len(nodes_ga):,} nodes · {len(edges_ga):,} edges"
        ),
        map_context=map_context,
    )

    # ── Panel E — Voronoi / k-means ───────────────────────────────────────
    if not _SKLEARN_AVAILABLE:
        _style_ax(ax_e, xmin, xmax, zmin, zmax,
                  "E — Voronoi (k-means)\nscikit-learn not available")
        if map_context:
            _draw_island_polygons(ax_e, map_context)
        ax_e.text(
            0.5, 0.5,
            "scikit-learn not available\n(pip install scikit-learn)",
            transform=ax_e.transAxes, ha="center", va="center",
            color="#ff8844", fontsize=9,
        )
    else:
        _draw_graph_panel(
            ax_e, nodes_vor, edges_vor,
            xmin, xmax, zmin, zmax,
            title=(
                f"E — Voronoi (k-means)\n"
                f"{len(nodes_vor):,} nodes · {len(edges_vor):,} edges"
                f" · k={n_clusters_vor}"
            ),
            map_context=map_context,
        )

    # ── Panel F — Stats table ─────────────────────────────────────────────
    ax_f.set_facecolor(_BG_COLOR)
    ax_f.axis("off")
    ax_f.set_title("F — Strategy stats", color="#cccccc", fontsize=8, pad=4)

    n_valid_cells = len(valid_cell_set)

    def _avg_degree(nodes: list[dict], edges: list[dict]) -> float:
        if not nodes:
            return 0.0
        degree: dict[tuple[float, float], int] = {}
        for e in edges:
            sk = (e["src_cx"], e["src_cz"])
            dk = (e["dst_cx"], e["dst_cz"])
            degree[sk] = degree.get(sk, 0) + 1
            degree[dk] = degree.get(dk, 0) + 1
        total = sum(degree.values())
        return total / len(nodes) if nodes else 0.0

    def _coverage_grid(nodes: list[dict], n_valid: int) -> float:
        if n_valid == 0:
            return 0.0
        occ = sum(1 for n in nodes if n["occupation"] > 0)
        return 100.0 * occ / n_valid

    def _coverage_vor(n_node: int, n_total: int) -> float:
        if n_total == 0:
            return 0.0
        return 100.0 * n_node / n_total

    strategies = [
        (
            "Grid 5×5",
            "5",
            nodes_g5, edges_g5,
            _coverage_grid(nodes_g5, n_valid_cells),
        ),
        (
            "Grid 3×3",
            "3",
            nodes_g3, edges_g3,
            _coverage_grid(nodes_g3, n_valid_cells),
        ),
        (
            f"Adaptive {adaptive_gs}×{adaptive_gs}",
            str(adaptive_gs),
            nodes_ga, edges_ga,
            _coverage_grid(nodes_ga, n_valid_cells),
        ),
        (
            "Voronoi",
            str(n_clusters_vor),
            nodes_vor, edges_vor,
            _coverage_vor(len(nodes_vor), n_pos),
        ),
    ]

    # Table header
    col_x = [0.02, 0.30, 0.46, 0.58, 0.72, 0.86]
    headers = ["Strategy", "Grid/k", "Nodes", "Edges", "Avg deg", "Cov %"]
    y = 0.90
    kw_hdr = dict(transform=ax_f.transAxes, va="top", fontsize=7,
                  color="#ffffff", fontweight="bold")
    for cx, hdr in zip(col_x, headers):
        ax_f.text(cx, y, hdr, **kw_hdr)

    y -= 0.04
    # Thin separator line
    ax_f.plot(
        [0.02, 0.98], [y + 0.005, y + 0.005],
        color="#444466", linewidth=0.8, transform=ax_f.transAxes,
    )
    y -= 0.02

    kw_cell = dict(transform=ax_f.transAxes, va="top", fontsize=7, color="#cccccc")
    for strat_name, grid_k, nodes, edges, cov in strategies:
        avg_deg = _avg_degree(nodes, edges)
        row_vals = [
            strat_name,
            grid_k,
            f"{len(nodes):,}",
            f"{len(edges):,}",
            f"{avg_deg:.1f}",
            f"{cov:.1f}%",
        ]
        for cx, val in zip(col_x, row_vals):
            ax_f.text(cx, y, val, **kw_cell)
        y -= 0.075

    y -= 0.04
    # Additional info block
    info_lines = [
        ("Map",             map_slug),
        ("Positions",       f"{n_pos:,}"),
        ("Matches",         str(n_matches)),
        ("Total blocks",    f"{total_blocks:,}"),
        ("Adaptive gs",     str(adaptive_gs)),
        ("min_occupation",  str(min_occupation)),
        ("min_transitions", str(min_transitions)),
        ("Valid cells(5×5)", f"{n_valid_cells:,}"),
    ]
    kw_info_k = dict(transform=ax_f.transAxes, va="top", fontsize=7,
                     color="#aaaaaa", fontweight="bold")
    kw_info_v = dict(transform=ax_f.transAxes, va="top", fontsize=7, color="#cccccc")
    for key, val in info_lines:
        ax_f.text(0.02, y, f"{key}:", **kw_info_k)
        ax_f.text(0.50, y, val, **kw_info_v)
        y -= 0.055

    # ── Overall title ─────────────────────────────────────────────────────
    fig.suptitle(
        f"Traffic graph strategy comparison — {map_slug}"
        f"  ({n_pos:,} positions, {n_matches} matches)",
        color="white", fontsize=11, y=1.002,
    )

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=130, bbox_inches="tight", facecolor=_BG_COLOR)
        plt.close(fig)
        logger.info("Saved strategy comparison plot → %s", output_path)

    return fig
