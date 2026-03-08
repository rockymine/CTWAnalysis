"""Six-panel diagnostic figure for traffic-graph-based movement classification.

Each figure shows a single life segment at six levels of abstraction so that
observed data, snapped anchors, and inferred graph traversal can be compared
side-by-side before committing to a final classification scheme.

Panel layout (2 × 3)
---------------------
  A  |  B  |  C
  D  |  E  |  F

A — Raw sampled positions (observed, ground truth)
B — Raw positions over the full traffic graph (graph coverage check)
C — Snapped node sequence (nearest-node anchors, raw — includes repeats)
D — Reconstructed graph path between consecutive snapped anchors (inferred)
E — Simplified version of the reconstructed path
F — Metadata / summary text

Terminology reminder
--------------------
* Observed  = raw x/z position samples recorded every ~2 s.
* Snapped anchor = nearest graph node to each observed sample (approx).
* Inferred  = intermediate graph nodes along the reconstructed path between
              two consecutive snapped anchors; these are *not* directly observed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.cm as cm
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd

try:
    import networkx as nx
except ImportError as exc:
    raise ImportError("networkx is required for traffic_diagnostics_plot") from exc

# ---------------------------------------------------------------------------
# Colour / style constants (match existing dark-theme traffic_graph.py style)
# ---------------------------------------------------------------------------

_BG_COLOR      = "#0d0d18"
_EDGE_ALPHA    = 0.14       # faint background graph edges
_NODE_ALPHA    = 0.14       # faint background graph nodes
_OBS_CMAP      = cm.get_cmap("plasma")   # temporal colouring for observed data
_INFER_COLOR   = "#44ccff"               # colour for inferred intermediate nodes
_ANCHOR_COLOR  = "#ffdd44"              # colour for snapped anchor nodes (observed)
_START_COLOR   = "#00ff88"
_END_COLOR     = "#ff4444"
_FIGSIZE       = (20, 13)
_MAP_PAD       = 15         # extra padding around map bounds (blocks)

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
# Private helpers
# ---------------------------------------------------------------------------

def _map_bounds(node_info: dict[int, dict], pad: int = _MAP_PAD) -> tuple[float, float, float, float]:
    """Return (xmin, xmax, zmin, zmax) with padding from node coordinates."""
    xs = [n["coords"][0] for n in node_info.values()]
    zs = [n["coords"][1] for n in node_info.values()]
    return min(xs) - pad, max(xs) + pad, min(zs) - pad, max(zs) + pad


def _style_ax(ax, xmin: float, xmax: float, zmin: float, zmax: float, title: str = "") -> None:
    """Apply shared dark-theme axis styling and set map bounds."""
    ax.set_facecolor(_BG_COLOR)
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(zmax, zmin)   # Z inverted: north-up
    ax.set_aspect("equal")
    ax.tick_params(colors="#444444", labelsize=6)
    for spine in ax.spines.values():
        spine.set_edgecolor("#333333")
    if title:
        ax.set_title(title, color="#cccccc", fontsize=8, pad=4)


def _draw_graph_background(
    ax,
    node_info: dict[int, dict],
    G_full: nx.Graph,
    map_context: Optional[dict] = None,
    node_alpha: float = _NODE_ALPHA,
    edge_alpha: float = _EDGE_ALPHA,
) -> None:
    """Draw the full traffic graph as a faint background context layer.

    Edges are drawn first (thinner lines), then nodes on top.
    Island polygons are drawn if map_context is provided.
    """
    # Island polygon backgrounds
    if map_context:
        team_hex: dict[str, str] = {}
        for team in map_context.get("teams", []):
            tid = team.get("id", "")
            raw = team.get("color", "")
            team_hex[tid] = _MINECRAFT_COLORS.get(raw, "#3a3a5a")
        for isl in map_context.get("islands", []):
            pts = isl.get("simplified_polygon", {}).get("exterior", [])
            if not pts:
                continue
            isl_t = isl.get("team")
            fc = team_hex.get(isl_t, "#2a2a4a")
            alpha = 0.12 if isl_t else 0.06
            from matplotlib.patches import Polygon as MplPolygon
            patch = MplPolygon(np.array(pts), closed=True,
                               facecolor=fc, edgecolor=fc,
                               linewidth=0.2, alpha=alpha, zorder=0)
            ax.add_patch(patch)

    # Edges
    for u, v, data in G_full.edges(data=True):
        sn = node_info.get(u)
        dn = node_info.get(v)
        if sn is None or dn is None:
            continue
        sc, dc = sn["coords"], dn["coords"]
        ax.plot([sc[0], dc[0]], [sc[1], dc[1]],
                color="#445566", lw=0.5, alpha=edge_alpha, zorder=1)

    # Nodes (tiny dots)
    coords = np.array([n["coords"] for n in node_info.values()])
    ax.scatter(coords[:, 0], coords[:, 1],
               s=4, color="#5577aa", alpha=node_alpha,
               linewidths=0, zorder=2)


def _temporal_colors(n: int) -> np.ndarray:
    """Return (n, 4) RGBA array ramping through the plasma colourmap.

    Start at 0.15 (avoids near-black) and end at 0.98 (bright yellow).
    """
    if n <= 1:
        return _OBS_CMAP(np.array([0.15]))
    return _OBS_CMAP(np.linspace(0.15, 0.98, n))


def _draw_position_trace(ax, xs, zs, size: float = 55) -> None:
    """Draw raw positions with temporal colour gradient and start/end markers."""
    n = len(xs)
    if n == 0:
        return
    colors = _temporal_colors(n)
    # Connecting line — brighter and thicker for visibility
    ax.plot(xs, zs, color="#cccccc", lw=1.4, alpha=0.55, zorder=3)
    # Scatter with temporal colours and white stroke for contrast
    ax.scatter(xs, zs, c=colors, s=size, linewidths=0.6,
               edgecolors="white", zorder=4)
    # Start / end markers — larger
    ax.scatter([xs[0]], [zs[0]], s=180, color=_START_COLOR,
               marker="*", zorder=6, edgecolors="white", linewidths=1.0)
    ax.scatter([xs[-1]], [zs[-1]], s=130, color=_END_COLOR,
               marker="X", zorder=6, edgecolors="white", linewidths=1.2)


def _draw_node_sequence(
    ax,
    node_ids: list[int],
    node_info: dict[int, dict],
    is_anchor: Optional[list[bool]] = None,
    draw_line: bool = True,
    show_repeats: bool = True,
) -> None:
    """Draw a sequence of node ids with temporal colouring.

    Parameters
    ----------
    is_anchor:
        If provided, anchor nodes (True) are drawn as squares and inferred
        intermediates (False) as small diamonds.  If None, all nodes are
        drawn as squares.
    show_repeats:
        If False, jitter repeated consecutive positions slightly so they are
        still individually visible.
    """
    if not node_ids:
        return

    coords = []
    for nid in node_ids:
        n = node_info.get(nid)
        if n:
            coords.append(n["coords"])
    if not coords:
        return

    coords_arr = np.array(coords, dtype=float)
    n = len(coords_arr)
    colors = _temporal_colors(n)

    if draw_line:
        ax.plot(coords_arr[:, 0], coords_arr[:, 1],
                color="#cccccc", lw=1.4, alpha=0.55, zorder=3)

    if is_anchor is None:
        ax.scatter(coords_arr[:, 0], coords_arr[:, 1],
                   c=colors, s=50, marker="s",
                   linewidths=0.6, edgecolors="white", zorder=4)
    else:
        # Draw anchors (squares) and intermediates (diamonds) separately
        anchor_mask = np.array(is_anchor[:len(coords_arr)], dtype=bool)
        if anchor_mask.any():
            ax.scatter(coords_arr[anchor_mask, 0], coords_arr[anchor_mask, 1],
                       c=colors[anchor_mask], s=55, marker="s",
                       linewidths=0.6, edgecolors="white", zorder=5,
                       label="snapped anchor (observed)")
        infer_mask = ~anchor_mask
        if infer_mask.any():
            ax.scatter(coords_arr[infer_mask, 0], coords_arr[infer_mask, 1],
                       s=22, marker="D", color=_INFER_COLOR,
                       alpha=0.75, linewidths=0.4, edgecolors="white",
                       zorder=4, label="inferred intermediate")

    # Start / end markers (use first and last valid node in sequence)
    ax.scatter([coords_arr[0, 0]], [coords_arr[0, 1]], s=180, color=_START_COLOR,
               marker="*", zorder=6, edgecolors="white", linewidths=1.0)
    ax.scatter([coords_arr[-1, 0]], [coords_arr[-1, 1]], s=130, color=_END_COLOR,
               marker="X", zorder=6, edgecolors="white", linewidths=1.2)


def _legend_handles() -> list[Line2D]:
    """Return shared legend handles for the diagnostic figure."""
    return [
        Line2D([0], [0], color=_START_COLOR, lw=0, marker="*", ms=9,
               markerfacecolor=_START_COLOR, label="start"),
        Line2D([0], [0], color=_END_COLOR, lw=0, marker="X", ms=7,
               markerfacecolor=_END_COLOR, label="end"),
        Line2D([0], [0], lw=0, marker="s", ms=7,
               markerfacecolor="#ffdd44", label="snapped anchor (observed)"),
        Line2D([0], [0], lw=0, marker="D", ms=6,
               markerfacecolor=_INFER_COLOR, alpha=0.7, label="inferred intermediate"),
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def plot_life_segment_diagnostic(
    *,
    map_slug: str,
    match_id: int,
    player_id: int,
    segment_idx: int,
    positions_df: pd.DataFrame,
    snapped_sequence: list[int],
    node_info: dict[int, dict],
    G_full: nx.Graph,
    reconstructed_path: tuple[list[int], list[bool]],
    simplified_sequence: list[int],
    map_context: Optional[dict] = None,
    has_wool_event: bool = False,
    label: str = "",
    simplification_method: str = "consecutive_dedup",
    reconstruction_mode: str = "dense",
    tortuosity: float | None = None,
    output_path: Optional[Path] = None,
) -> plt.Figure:
    """Generate a 6-panel diagnostic figure for one life segment.

    Parameters
    ----------
    map_slug, match_id, player_id, segment_idx:
        Identifiers for the metadata panel and file naming.
    positions_df:
        DataFrame with columns ``x``, ``z``, ``timestamp`` for the segment.
    snapped_sequence:
        Raw list of node_ids (one per position sample, *not* deduplicated).
        This is the observed-anchor representation.
    node_info:
        ``{node_id: node_dict}`` from ``build_traffic_topology()``.
    G_full:
        Full traffic graph (networkx) from ``build_traffic_topology()``.
    reconstructed_path:
        ``(path_nodes, is_anchor)`` tuple from ``reconstruct_full_path()``.
        ``is_anchor[i]`` is True when ``path_nodes[i]`` is a snapped anchor
        (observed) and False when it is an inferred intermediate.
    simplified_sequence:
        Simplified snapped sequence (e.g. after consecutive dedup).
        Used for Panel E.
    map_context:
        Parsed ``map_context.json`` dict; used for island polygon backgrounds.
    has_wool_event:
        True if the player touched or captured a wool during this segment.
    label:
        Short label for the segment category (e.g. ``"deep_attacker"``).
    simplification_method:
        Name of the simplification applied to *simplified_sequence*, shown in
        the metadata panel.
    output_path:
        If provided, save the figure as a PNG to this path.

    Returns
    -------
    matplotlib.figure.Figure
    """
    pos = positions_df.copy()
    xs  = pos["x"].to_numpy(dtype=float)
    zs  = pos["z"].to_numpy(dtype=float)
    ts  = pos["timestamp"].to_numpy(dtype=float)

    xmin, xmax, zmin, zmax = _map_bounds(node_info)
    duration_s = float(ts[-1] - ts[0]) if len(ts) > 1 else 0.0

    path_nodes, is_anchor = reconstructed_path

    # ── Figure ──────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=_FIGSIZE, facecolor=_BG_COLOR)
    gs  = fig.add_gridspec(2, 3, hspace=0.15, wspace=0.06)

    ax_a = fig.add_subplot(gs[0, 0])
    ax_b = fig.add_subplot(gs[0, 1])
    ax_c = fig.add_subplot(gs[0, 2])
    ax_d = fig.add_subplot(gs[1, 0])
    ax_e = fig.add_subplot(gs[1, 1])
    ax_f = fig.add_subplot(gs[1, 2])

    # Shared bounds for all plotting panels
    for ax in (ax_a, ax_b, ax_c, ax_d, ax_e):
        _style_ax(ax, xmin, xmax, zmin, zmax)

    # ── Panel A — raw positions only (observed, ground truth) ────────────
    _style_ax(ax_a, xmin, xmax, zmin, zmax,
              "A — Raw positions\n(observed, ground truth)")
    ax_a.set_facecolor(_BG_COLOR)
    if map_context:
        team_hex: dict[str, str] = {}
        for team in map_context.get("teams", []):
            tid = team.get("id", "")
            raw = team.get("color", "")
            team_hex[tid] = _MINECRAFT_COLORS.get(raw, "#3a3a5a")
        for isl in map_context.get("islands", []):
            pts = isl.get("simplified_polygon", {}).get("exterior", [])
            if not pts:
                continue
            isl_t = isl.get("team")
            fc    = team_hex.get(isl_t, "#2a2a4a")
            alpha = 0.10 if isl_t else 0.05
            from matplotlib.patches import Polygon as MplPolygon
            patch = MplPolygon(np.array(pts), closed=True,
                               facecolor=fc, edgecolor="#555555",
                               linewidth=0.3, alpha=alpha, zorder=0)
            ax_a.add_patch(patch)
    _draw_position_trace(ax_a, xs, zs)

    # ── Panel B — raw positions over traffic graph ────────────────────────
    _style_ax(ax_b, xmin, xmax, zmin, zmax,
              "B — Raw positions over traffic graph\n(graph coverage check)")
    _draw_graph_background(ax_b, node_info, G_full, map_context)
    _draw_position_trace(ax_b, xs, zs)

    # ── Panel C — snapped node sequence (raw, includes repeats) ──────────
    _style_ax(ax_c, xmin, xmax, zmin, zmax,
              "C — Snapped node sequence\n(observed anchors, raw — shows ABAB oscillation)")
    _draw_graph_background(ax_c, node_info, G_full, map_context,
                           node_alpha=0.15, edge_alpha=0.12)
    _draw_node_sequence(ax_c, snapped_sequence, node_info)

    # ── Panel D — reconstructed path (unpruned, inferred) ─────────────────
    _style_ax(ax_d, xmin, xmax, zmin, zmax,
              f"D — Reconstructed path ({reconstruction_mode} mode)\n"
              "⚠ inferred layer — not directly observed")
    _draw_graph_background(ax_d, node_info, G_full, map_context,
                           node_alpha=0.12, edge_alpha=0.10)
    _draw_node_sequence(ax_d, path_nodes, node_info, is_anchor=is_anchor)
    legend_d = ax_d.legend(
        handles=_legend_handles(), loc="lower left", fontsize=6,
        facecolor="#0e0e1a", labelcolor="white", framealpha=0.85,
    )
    ax_d.add_artist(legend_d)

    # ── Panel E — simplified reconstructed path ────────────────────────────
    _style_ax(ax_e, xmin, xmax, zmin, zmax,
              f"E — Simplified path ({simplification_method})\n"
              "⚠ inferred layer — not directly observed")
    _draw_graph_background(ax_e, node_info, G_full, map_context,
                           node_alpha=0.12, edge_alpha=0.10)
    # Simplified sequence contains only snapped anchors (all observed)
    all_anchor = [True] * len(simplified_sequence)
    _draw_node_sequence(ax_e, simplified_sequence, node_info, is_anchor=all_anchor)

    # ── Panel F — metadata / summary text ────────────────────────────────
    ax_f.set_facecolor(_BG_COLOR)
    ax_f.axis("off")

    n_unique_snapped = len(set(snapped_sequence))
    consec_dedup_removed = len(snapped_sequence) - len(simplified_sequence)
    dedup_pct = (
        100.0 * consec_dedup_removed / len(snapped_sequence)
        if snapped_sequence else 0.0
    )
    span_m = float(np.sqrt((xs[-1] - xs[0]) ** 2 + (zs[-1] - zs[0]) ** 2)) if len(xs) > 1 else 0.0

    lines = [
        ("Map",               map_slug),
        ("Match ID",          str(match_id)),
        ("Player ID",         str(player_id)),
        ("Segment",           str(segment_idx)),
        ("Category",          label or "—"),
        ("",                  ""),
        ("Duration",          f"{duration_s:.1f} s"),
        ("Position samples",  str(len(xs))),
        ("Snapped nodes",     str(len(snapped_sequence))),
        ("Unique snapped",    str(n_unique_snapped)),
        ("Dedup removed",     f"{consec_dedup_removed} ({dedup_pct:.0f}%)"),
        ("Span (start→end)",  f"{span_m:.0f} blocks"),
        ("Tortuosity",        f"{tortuosity:.2f}" if tortuosity is not None else "—"),
        ("Reconstructed",     str(len(path_nodes))),
        ("Recon mode",        reconstruction_mode),
        ("Simplified",        str(len(simplified_sequence))),
        ("Wool touched",      "YES" if has_wool_event else "no"),
        ("",                  ""),
        ("Layers note:",      ""),
        (" observed",         "raw positions, snapped anchors"),
        (" inferred",         "reconstructed intermediates"),
    ]

    y = 0.97
    ax_f.set_title("F — Metadata", color="#cccccc", fontsize=8, pad=4)
    for key, val in lines:
        if not key and not val:
            y -= 0.022
            continue
        bold = key in ("Layers note:", " observed", " inferred")
        col  = "#ffffff" if bold else "#cccccc"
        kw = dict(transform=ax_f.transAxes, va="top", fontsize=7.5, color=col)
        if key:
            ax_f.text(0.05, y, f"{key}:", fontweight="bold" if bold else "normal", **kw)
            ax_f.text(0.52, y, val, **kw)
        else:
            ax_f.text(0.05, y, val, **kw)
        y -= 0.048

    # Colour-ramp legend for temporal colouring
    from matplotlib.colors import Normalize
    from matplotlib.cm import ScalarMappable
    sm = ScalarMappable(cmap=_OBS_CMAP, norm=Normalize(vmin=0, vmax=1))
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax_f, fraction=0.06, pad=0.04, orientation="horizontal")
    cbar.set_label("time (start → end)", color="#aaaaaa", fontsize=7)
    cbar.ax.xaxis.set_tick_params(color="#aaaaaa", labelsize=6)
    plt.setp(cbar.ax.xaxis.get_ticklabels(), color="#aaaaaa")
    cbar.set_ticks([0, 1])
    cbar.set_ticklabels(["start", "end"])

    # ── Overall title ────────────────────────────────────────────────────
    title_str = (
        f"Traffic-graph diagnostics — {map_slug}  "
        f"match {match_id}  player {player_id}  segment {segment_idx}"
    )
    if label:
        title_str += f"  [{label}]"
    fig.suptitle(title_str, color="white", fontsize=10, y=1.005)

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=130, bbox_inches="tight", facecolor=_BG_COLOR)
        plt.close(fig)

    return fig
