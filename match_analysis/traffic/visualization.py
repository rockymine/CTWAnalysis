"""Traffic graph visualizations for CTW match analysis."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

import numpy as np

from common.visualization import mc_color, NEUTRAL_COLOR, draw_island_fills
from common.visualization.map_primitives import island_path

logger = logging.getLogger("ctw")



def plot_traffic_graph(
    graph: dict,
    map_context: Optional[dict],
    output_path: Path,
) -> None:
    """Render the traffic graph as a map overlay and save to output_path."""
    from matplotlib.patches import PathPatch

    nodes = graph["nodes"]
    edges = graph["edges"]
    node_by_id = {n["node_id"]: n for n in nodes}

    grid_size    = graph.get("grid_size")
    n_matches    = graph.get("match_count", "?")
    n_pos        = graph.get("position_count", "?")
    n_players    = graph.get("player_count", "?")
    playtime_min = graph.get("total_playtime_min")

    occupations = [n["occupation"] for n in nodes]
    max_occ  = max(max(occupations), 1) if occupations else 1
    transitions = [e["transitions"] for e in edges]
    max_trans = max(transitions) if transitions else 1

    xs = [n["coords"][0] for n in nodes]
    zs = [n["coords"][1] for n in nodes]
    if not xs:
        logger.warning("No nodes to plot.")
        return
    pad = 20
    xmin, xmax = min(xs) - pad, max(xs) + pad
    zmin, zmax = min(zs) - pad, max(zs) + pad

    fig, ax = plt.subplots(figsize=(10, 12))
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(zmax, zmin)  # invert z (north-up)
    ax.set_aspect("equal")
    ax.set_xlabel("X", color="#444444")
    ax.set_ylabel("Z", color="#444444")
    ax.tick_params(colors="#666666")
    for spine in ax.spines.values():
        spine.set_edgecolor("#cccccc")

    if map_context:
        draw_island_fills(ax, map_context, alpha=0.20)

        # Build-region polygons (faint gold overlay)
        build_region = map_context.get("build_region")
        if build_region:
            for poly_data in build_region.get("buildable_void", []):
                path = island_path(poly_data.get("exterior", []), poly_data.get("holes", []))
                if path is not None:
                    ax.add_patch(PathPatch(path, facecolor="#ddaa33", edgecolor="#ddaa33",
                                           linewidth=0.5, alpha=0.18, zorder=0))

    # Edges — width encodes transition count
    for e in edges:
        sn = node_by_id.get(e["src"])
        dn = node_by_id.get(e["dst"])
        if sn is None or dn is None:
            continue
        sc = sn["coords"]; dc = dn["coords"]
        lw = 0.3 + 1.2 * e["transitions"] / max_trans
        ax.plot([sc[0], dc[0]], [sc[1], dc[1]],
                color="#aaaaaa", lw=lw, alpha=0.6, zorder=1)

    # Nodes — size by occupation, color by location type
    for n in nodes:
        coords = n["coords"]
        s = 8 + 100 * n["occupation"] / max_occ
        if n.get("poi_type") == "wool":
            wc = mc_color(n.get("poi_color", ""), "#555555")
            ax.scatter(coords[0], coords[1], s=s * 1.5, color=wc,
                       marker="D", edgecolors="#333333", linewidths=0.8, zorder=5)
            ax.annotate(n.get("poi_color", "?"), (coords[0], coords[1]),
                        xytext=(5, 3), textcoords="offset points",
                        color="#222222", fontsize=7, fontweight="bold", zorder=6)
        elif n.get("poi_type") == "spawn":
            ax.scatter(coords[0], coords[1], s=s * 1.2, color=NEUTRAL_COLOR,
                       marker="s", edgecolors="#333333", linewidths=0.8, zorder=5)
        else:
            iid = n.get("island_id")
            fc = "#3a6fd8" if iid is not None else "#cc8800"
            ax.scatter(coords[0], coords[1], s=s, color=fc, alpha=0.80,
                       linewidths=0, zorder=3)

    legend_els = [
        Line2D([0], [0], color="#3a6fd8", lw=0, marker="o", ms=7,
               markerfacecolor="#3a6fd8", label="island node"),
        Line2D([0], [0], color="#cc8800", lw=0, marker="o", ms=7,
               markerfacecolor="#cc8800", label="build region node"),
        Line2D([0], [0], color="#555555", lw=0, marker="D", ms=7, label="wool node"),
        Line2D([0], [0], color=NEUTRAL_COLOR, lw=0, marker="s", ms=6, label="spawn node"),
        Line2D([0], [0], color="#aaaaaa", lw=1.5, label="edge (width = transitions)"),
    ]
    ax.legend(handles=legend_els, loc="lower left", fontsize=7,
              facecolor="#ffffff", labelcolor="#222222", framealpha=0.85, edgecolor="#cccccc")

    n_nodes = len(nodes); n_edges = len(edges)
    playtime_str = f"{playtime_min:,.0f} min aggregate playtime" if playtime_min is not None else ""
    subtitle_parts = [f"{n_players} participations", f"{n_pos:,} positions"]
    if playtime_str:
        subtitle_parts.append(playtime_str)

    source = graph.get("source", "")
    grid_label = (f"grid={grid_size}×{grid_size} blocks" if grid_size
                  else {"contour": "contour sampling", "adaptive": "adaptive sampling"}.get(source, "adaptive sampling"))
    ax.set_title(
        f"Traffic graph — {graph['map_slug']}  "
        f"({n_matches} match{'es' if n_matches != 1 else ''}  |  "
        + "  ·  ".join(subtitle_parts) + ")\n"
        f"{n_nodes} nodes · {n_edges} edges  |  {grid_label}",
        color="#222222", fontsize=10,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved traffic graph plot → %s", output_path)
