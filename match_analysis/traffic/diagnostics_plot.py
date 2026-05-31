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

from common.visualization import (
    DARK_THEME_BG as _BG_COLOR,
    style_dark_ax as _style_ax,
    draw_dark_island_polygons,
    draw_dark_graph_background as _draw_graph_background,
)

# ---------------------------------------------------------------------------
# Colour / style constants (match existing dark-theme traffic_graph.py style)
# ---------------------------------------------------------------------------

_EDGE_ALPHA    = 0.14       # faint background graph edges
_NODE_ALPHA    = 0.14       # faint background graph nodes
_OBS_CMAP      = cm.get_cmap("plasma")   # temporal colouring for observed data
_INFER_COLOR   = "#44ccff"               # colour for inferred intermediate nodes
_ANCHOR_COLOR  = "#ffdd44"              # colour for snapped anchor nodes (observed)
_START_COLOR   = "#00ff88"
_END_COLOR     = "#ff4444"
_FIGSIZE       = (20, 13)
_MAP_PAD       = 15         # extra padding around map bounds (blocks)

# ---------------------------------------------------------------------------
# Held-item category → colour mapping (for Panel A alternate colouring)
# ---------------------------------------------------------------------------

_ITEM_BOW_IDS:     frozenset[int] = frozenset({203})
_ITEM_MELEE_IDS:   frozenset[int] = frozenset({
    200, 209, 210, 213, 214, 217, 218, 221, 225, 228,
})
_ITEM_BRIDGE_IDS:  frozenset[int] = frozenset({
    1, 4, 5, 12, 20, 24, 35, 85, 95, 101,
    159, 160, 171, 188, 189, 190, 191, 192,
})
_ITEM_TOOL_IDS:    frozenset[int] = frozenset({
    198, 199, 211, 212, 215, 216, 219, 220,
})

_ITEM_CAT_COLORS: dict[str, str] = {
    "bow":   "#ff8c00",   # amber
    "melee": "#ff3333",   # red
    "block": "#44ff88",   # green
    "tool":  "#ffdd44",   # yellow
    "other": "#888888",   # gray
}

_ITEM_CAT_LABELS: dict[str, str] = {
    "bow":   "Bow",
    "melee": "Sword / Axe",
    "block": "Bridge block",
    "tool":  "Tool",
    "other": "Other / empty",
}


def _categorise_item(item_id: int) -> str:
    if item_id < 0:
        return "other"
    if item_id in _ITEM_BOW_IDS:
        return "bow"
    if item_id in _ITEM_MELEE_IDS:
        return "melee"
    if item_id in _ITEM_BRIDGE_IDS:
        return "block"
    if item_id in _ITEM_TOOL_IDS:
        return "tool"
    return "other"


def _item_category_colors(held_item_series: list[int]) -> list[str]:
    """Return a per-position list of hex colour strings by item category."""
    return [_ITEM_CAT_COLORS[_categorise_item(i)] for i in held_item_series]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _map_bounds(node_info: dict[int, dict], pad: int = _MAP_PAD) -> tuple[float, float, float, float]:
    """Return (xmin, xmax, zmin, zmax) with padding from node coordinates."""
    xs = [n["coords"][0] for n in node_info.values()]
    zs = [n["coords"][1] for n in node_info.values()]
    return min(xs) - pad, max(xs) + pad, min(zs) - pad, max(zs) + pad


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
    held_item_series: list[int] | None = None,
    positions_y: list[float] | None = None,
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
    if map_context:
        draw_dark_island_polygons(ax_a, map_context, alpha=0.10)
    if held_item_series is not None and len(held_item_series) == len(xs):
        # Held-item category colouring — Panel A title update
        _style_ax(ax_a, xmin, xmax, zmin, zmax,
                  "A — Raw positions coloured by held item\n(observed, ground truth)")
        item_colors = _item_category_colors(held_item_series)
        ax_a.plot(xs, zs, color="#cccccc", lw=1.4, alpha=0.55, zorder=3)
        ax_a.scatter(xs, zs, c=item_colors, s=55, linewidths=0.6,
                     edgecolors="white", zorder=4)
        ax_a.scatter([xs[0]], [zs[0]], s=180, color=_START_COLOR,
                     marker="*", zorder=6, edgecolors="white", linewidths=1.0)
        ax_a.scatter([xs[-1]], [zs[-1]], s=130, color=_END_COLOR,
                     marker="X", zorder=6, edgecolors="white", linewidths=1.2)
        # Item category legend
        from matplotlib.patches import Patch as _Patch
        seen_cats = {_categorise_item(i) for i in held_item_series}
        legend_handles_a = [
            _Patch(facecolor=_ITEM_CAT_COLORS[c], edgecolor="white",
                   linewidth=0.5, label=_ITEM_CAT_LABELS[c])
            for c in ("bow", "melee", "block", "tool", "other")
            if c in seen_cats
        ]
        if legend_handles_a:
            ax_a.legend(handles=legend_handles_a, loc="lower left", fontsize=5.5,
                        facecolor="#0e0e1a", labelcolor="white", framealpha=0.85)
    elif positions_y is not None and len(positions_y) == len(xs):
        # Elevation colouring — Panel A title update
        _style_ax(ax_a, xmin, xmax, zmin, zmax,
                  "A — Raw positions coloured by elevation (y)\n(observed, ground truth)")
        y_arr = np.array(positions_y, dtype=float)
        y_norm = (y_arr - y_arr.min()) / max(y_arr.max() - y_arr.min(), 1.0)
        elev_cmap = cm.get_cmap("RdYlGn")
        elev_colors = elev_cmap(y_norm)
        ax_a.plot(xs, zs, color="#cccccc", lw=1.4, alpha=0.55, zorder=3)
        sc = ax_a.scatter(xs, zs, c=y_norm, cmap="RdYlGn", s=55,
                          linewidths=0.6, edgecolors="white", zorder=4,
                          vmin=0, vmax=1)
        ax_a.scatter([xs[0]], [zs[0]], s=180, color=_START_COLOR,
                     marker="*", zorder=6, edgecolors="white", linewidths=1.0)
        ax_a.scatter([xs[-1]], [zs[-1]], s=130, color=_END_COLOR,
                     marker="X", zorder=6, edgecolors="white", linewidths=1.2)
        # Mini colourbar: low y → high y
        cb = plt.colorbar(sc, ax=ax_a, orientation="horizontal",
                          fraction=0.04, pad=0.04, aspect=25)
        cb.set_label(f"y level  [{int(y_arr.min())}–{int(y_arr.max())}]",
                     color="#cccccc", fontsize=6)
        cb.ax.tick_params(colors="#cccccc", labelsize=5)
    else:
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

    # Optional: held-item breakdown block
    if held_item_series is not None and len(held_item_series) > 0:
        from collections import Counter as _Counter
        cat_counts = _Counter(_categorise_item(i) for i in held_item_series)
        total_items = len(held_item_series)
        lines.append(("", ""))
        lines.append(("Held item (pos):", ""))
        for cat in ("bow", "melee", "block", "tool", "other"):
            cnt = cat_counts.get(cat, 0)
            if cnt:
                pct = 100.0 * cnt / total_items
                lines.append((f"  {_ITEM_CAT_LABELS[cat]}", f"{pct:.0f}%"))

    # Optional: elevation breakdown block
    if positions_y is not None and len(positions_y) > 0:
        y_np = np.array(positions_y, dtype=float)
        lines.append(("", ""))
        lines.append(("Elevation (y):", ""))
        lines.append(("  avg / max", f"{y_np.mean():.1f} / {int(y_np.max())}"))
        lines.append(("  frac ≥22 (sky)", f"{np.mean(y_np >= 22):.0%}"))

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

    # Colour-ramp legend — temporal for standard plots, note for held-item/elevation
    from matplotlib.colors import Normalize
    from matplotlib.cm import ScalarMappable
    if held_item_series is not None:
        # Show item-category colour swatches instead of temporal bar
        from matplotlib.patches import Patch as _PatchCB
        from collections import Counter as _CounterCB
        cat_counts2 = _CounterCB(_categorise_item(i) for i in held_item_series)
        swatch_handles = [
            _PatchCB(facecolor=_ITEM_CAT_COLORS[c], edgecolor="white",
                     linewidth=0.5, label=_ITEM_CAT_LABELS[c])
            for c in ("bow", "melee", "block", "tool", "other")
            if cat_counts2.get(c, 0) > 0
        ]
        ax_f.legend(handles=swatch_handles, loc="lower center",
                    fontsize=6, facecolor="#0e0e1a", labelcolor="white",
                    framealpha=0.85, ncol=2)
    else:
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
