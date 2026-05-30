"""Defense setup overview plot for CTW early-game analysis.

Produces a 3-panel figure for a single wool node showing ALL segment_idx=0
player positions in the defense zone:

  ┌──────────────────┬──────────────────────────────┐
  │  Spatial map     │  Lane section (wool dist × y) │
  ├──────────────────┴──────────────────────────────┤
  │           Summary statistics                    │
  └─────────────────────────────────────────────────┘

Positions are coloured by defense activity category derived from the
held_item field in position events.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Circle
import numpy as np
import pandas as pd

try:
    import networkx as nx
except ImportError as exc:
    raise ImportError("networkx required for defense_plot") from exc

# ---------------------------------------------------------------------------
# Activity category IDs (0-indexed, from materials.txt)
# ---------------------------------------------------------------------------

_DIG_IDS: frozenset[int] = frozenset({
    198, 199, 211, 212, 215, 216, 219, 220,   # shovels + pickaxes (all tiers)
})
_WALL_IDS: frozenset[int] = frozenset({
    1, 4, 5, 12, 20, 24, 44, 95, 98, 155, 159, 160, 172,
    # STONE, COBBLESTONE, WOOD, SAND, GLASS, SANDSTONE, STEP, STAINED_GLASS,
    # SMOOTH_BRICK, QUARTZ_BLOCK, STAINED_CLAY, STAINED_GLASS_PANE, HARD_CLAY
})
_TRAP_IDS: frozenset[int] = frozenset({
    58, 70, 72, 77, 85, 101, 131, 139, 143, 188, 189, 190, 191, 192,
    # WORKBENCH, STONE_PLATE, WOOD_PLATE, STONE_BUTTON, FENCE, IRON_FENCE,
    # TRIPWIRE_HOOK, COBBLE_WALL, WOOD_BUTTON, wood-type fences
})
_GATE_IDS: frozenset[int] = frozenset({
    107, 183, 184, 185, 186, 187,
    # FENCE_GATE + spruce/birch/jungle/dark_oak/acacia fence gates
})
_GUARD_IDS: frozenset[int] = frozenset({
    200, 203, 209, 210, 213, 214, 217, 218, 221, 225, 228,
    # BOW, IRON/WOOD/STONE/DIAMOND_SWORD, IRON/WOOD/STONE/DIAMOND_AXE, GOLD variants
})

_ACT_PALETTE: dict[str, str] = {
    "dig":   "#ff6600",   # orange  — pickaxe / shovel
    "wall":  "#44ff88",   # green   — solid building block
    "trap":  "#44ccff",   # cyan    — fence / plate / button / cobble wall
    "gate":  "#ff44ff",   # magenta — fence gate
    "guard": "#ffdd44",   # amber   — bow / sword / axe
    "other": "#666666",   # gray    — air / food / armor / misc
}

_ACT_LABELS: dict[str, str] = {
    "dig":   "Dig (pick / shovel)",
    "wall":  "Wall block",
    "trap":  "Trap / obstacle",
    "gate":  "Fence gate",
    "guard": "Guard (bow / sword)",
    "other": "Other / empty",
}

_BG_COLOR = "#0d0d18"
_FIGSIZE  = (18, 11)


def classify_defense_activity(item_id: int) -> str:
    """Map a held-item ID to a defense activity category string."""
    if item_id < 0:
        return "other"
    if item_id in _DIG_IDS:
        return "dig"
    if item_id in _WALL_IDS:
        return "wall"
    if item_id in _TRAP_IDS:
        return "trap"
    if item_id in _GATE_IDS:
        return "gate"
    if item_id in _GUARD_IDS:
        return "guard"
    return "other"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _style_ax(ax, title: str = "", xlabel: str = "", ylabel: str = "") -> None:
    ax.set_facecolor(_BG_COLOR)
    ax.tick_params(colors="#888888", labelsize=7)
    for spine in ax.spines.values():
        spine.set_edgecolor("#333344")
    if title:
        ax.set_title(title, color="#cccccc", fontsize=8, pad=5)
    if xlabel:
        ax.set_xlabel(xlabel, color="#aaaaaa", fontsize=7)
    if ylabel:
        ax.set_ylabel(ylabel, color="#aaaaaa", fontsize=7)


def _draw_graph_background(
    ax,
    node_info: dict,
    G_full: "nx.Graph",
    xlim: tuple[float, float],
    zlim: tuple[float, float],
    node_alpha: float = 0.12,
    edge_alpha: float = 0.08,
) -> None:
    """Draw faint traffic graph within the given bounds."""
    xlo, xhi = xlim
    zlo, zhi = zlim
    for u, v in G_full.edges():
        sn = node_info.get(u)
        dn = node_info.get(v)
        if sn is None or dn is None:
            continue
        sc, dc = sn["coords"], dn["coords"]
        if not (xlo <= sc[0] <= xhi and zlo <= sc[1] <= zhi):
            continue
        ax.plot([sc[0], dc[0]], [sc[1], dc[1]],
                color="#445566", lw=0.5, alpha=edge_alpha, zorder=1)
    # Nodes
    vis_coords = [
        n["coords"] for n in node_info.values()
        if xlo <= n["coords"][0] <= xhi and zlo <= n["coords"][1] <= zhi
    ]
    if vis_coords:
        arr = np.array(vis_coords)
        ax.scatter(arr[:, 0], arr[:, 1], s=3, color="#5577aa",
                   alpha=node_alpha, linewidths=0, zorder=2)


def _legend_swatches(categories: list[str]) -> list[Patch]:
    return [
        Patch(facecolor=_ACT_PALETTE[c], edgecolor="none", label=_ACT_LABELS[c])
        for c in categories
        if c in _ACT_PALETTE
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def plot_defense_overview(
    *,
    positions_df: pd.DataFrame,
    node_info: dict,
    G_full: "nx.Graph",
    wool_node_id: int,
    team: str,
    map_context: Optional[dict] = None,
    output_path: Optional[Path] = None,
) -> plt.Figure:
    """Generate the 3-panel defense setup overview figure.

    Parameters
    ----------
    positions_df:
        DataFrame with columns: x, y, z, timestamp, wool_dist, activity, player_id.
        Should contain only segment_idx=0 positions within the target defense zone
        (typically wool_dist ≤ 60).
    node_info:
        {node_id: node_dict} from build_traffic_topology().
    G_full:
        Full traffic graph (networkx) from build_traffic_topology().
    wool_node_id:
        Node ID of the wool being analysed.
    team:
        Team name string ("blue" / "red").
    map_context:
        Parsed map_context.json for island background polygons.
    output_path:
        If provided, save the figure as a PNG.
    """
    df = positions_df.copy()
    if df.empty:
        raise ValueError("positions_df is empty — no defense positions to plot")

    wool_node = node_info.get(wool_node_id)
    if wool_node is None:
        raise ValueError(f"Wool node {wool_node_id} not found in node_info")
    wx, wz = wool_node["coords"]

    # ── Figure setup ─────────────────────────────────────────────────────
    fig = plt.figure(figsize=_FIGSIZE, facecolor=_BG_COLOR)
    gs  = gridspec.GridSpec(
        2, 2,
        figure=fig,
        height_ratios=[3.2, 1.0],
        width_ratios=[1.0, 1.5],
        hspace=0.28,
        wspace=0.22,
    )
    ax_map     = fig.add_subplot(gs[0, 0])
    ax_section = fig.add_subplot(gs[0, 1])
    ax_stats   = fig.add_subplot(gs[1, :])

    # ── Precompute activity colours ───────────────────────────────────────
    act_colors = [_ACT_PALETTE.get(a, _ACT_PALETTE["other"]) for a in df["activity"]]
    seen_acts  = [a for a in ("dig", "wall", "trap", "gate", "guard", "other")
                  if a in df["activity"].values]

    # ── Panel ax_map — x-z spatial map ───────────────────────────────────
    pad = 70.0
    xmin, xmax = wx - pad, wx + pad
    zmin, zmax = wz - pad, wz + pad
    ax_map.set_xlim(xmin, xmax)
    ax_map.set_ylim(zmin, zmax)
    ax_map.invert_yaxis()
    _style_ax(ax_map,
              title=f"Spatial map — segment 0 near wool {wool_node_id} ({team} team)",
              xlabel="x", ylabel="z")

    # Island backgrounds
    if map_context:
        _MC_COLORS = {
            "dark_red": "#AA0000", "red": "#FF5555", "gold": "#FFAA00",
            "yellow": "#DDDD00", "dark_green": "#00AA00", "green": "#55FF55",
            "aqua": "#55FFFF", "dark_aqua": "#00AAAA", "blue": "#5555FF",
            "light_purple": "#FF55FF", "white": "#FFFFFF", "gray": "#AAAAAA",
        }
        team_hex: dict[str, str] = {}
        for t in map_context.get("teams", []):
            team_hex[t.get("id", "")] = _MC_COLORS.get(t.get("color", ""), "#3a3a5a")
        from matplotlib.patches import Polygon as MplPolygon
        for isl in map_context.get("islands", []):
            pts = isl.get("simplified_polygon", {}).get("exterior", [])
            if not pts:
                continue
            isl_t = isl.get("team")
            fc    = team_hex.get(isl_t, "#2a2a4a")
            alpha = 0.10 if isl_t else 0.05
            patch = MplPolygon(np.array(pts), closed=True,
                               facecolor=fc, edgecolor="#555555",
                               linewidth=0.3, alpha=alpha, zorder=0)
            ax_map.add_patch(patch)

    _draw_graph_background(ax_map, node_info, G_full,
                           (xmin, xmax), (zmin, zmax))

    # Dijkstra distance rings (approximate as circles; valid at short range)
    for ring_d, ring_lw in [(10, 0.7), (20, 0.7), (30, 1.0), (50, 0.5)]:
        circle = Circle((wx, wz), radius=ring_d, fill=False,
                        edgecolor="#334455", linewidth=ring_lw,
                        linestyle="--", alpha=0.45, zorder=3)
        ax_map.add_patch(circle)
        ax_map.text(wx + ring_d * 0.72, wz - ring_d * 0.72,
                    f"{ring_d}b", color="#445566", fontsize=5,
                    ha="center", va="center", zorder=4)

    # Positions
    n_pts = len(df)
    s_val     = 12 if n_pts > 300 else 20
    alpha_val = 0.30 if n_pts > 300 else 0.65
    ax_map.scatter(df["x"], df["z"], c=act_colors,
                   s=s_val, alpha=alpha_val, linewidths=0, zorder=5)

    # Wool node highlight
    ax_map.scatter([wx], [wz], s=260, color="#ffffff",
                   marker="*", zorder=8, edgecolors="#ffdd44", linewidths=1.2)
    ax_map.text(wx, wz - 5, f"wool {wool_node_id}", color="#ffffff",
                fontsize=6, ha="center", va="top", zorder=9)

    # Legend
    leg = ax_map.legend(
        handles=_legend_swatches(seen_acts),
        loc="lower right", fontsize=5.5,
        facecolor="#0e0e1a", labelcolor="white", framealpha=0.85,
    )
    ax_map.add_artist(leg)

    # ── Panel ax_section — Lane section view ─────────────────────────────
    y_arr   = df["y"].to_numpy(float)
    dist_arr = df["wool_dist"].to_numpy(float)

    y_min_plot = max(-2.0, float(y_arr.min()) - 2)
    y_max_plot = float(y_arr.max()) + 2

    ax_section.set_xlim(-1, 52)
    ax_section.set_ylim(y_min_plot, y_max_plot)
    _style_ax(ax_section,
              title="Lane section view  (distance from wool × elevation)",
              xlabel="Dijkstra distance from wool node (blocks)",
              ylabel="Elevation (y)")

    # Reference lines
    for ref_y, ref_label, ref_col in [
        (0,  "y = 0", "#553333"),
        (5,  "pit zone ≤ y5", "#664422"),
        (9,  "ground ≈ y9", "#335533"),
        (22, "skybridge y≥22", "#334455"),
    ]:
        if y_min_plot <= ref_y <= y_max_plot:
            ax_section.axhline(ref_y, color=ref_col, lw=0.8,
                               linestyle="--", alpha=0.6, zorder=2)
            ax_section.text(51, ref_y, ref_label, color=ref_col,
                            fontsize=5.5, va="bottom", ha="right", zorder=3)

    # Positions
    s_sec     = 12 if n_pts > 300 else 20
    alpha_sec = 0.35 if n_pts > 300 else 0.70
    ax_section.scatter(dist_arr, y_arr, c=act_colors,
                       s=s_sec, alpha=alpha_sec, linewidths=0, zorder=4)

    # Annotate pit cluster if any
    pit_mask = (y_arr < 5) & (dist_arr < 35)
    if pit_mask.sum() > 5:
        pit_x = float(dist_arr[pit_mask].mean())
        pit_y = float(y_arr[pit_mask].min())
        ax_section.annotate(
            f"pit depth y={int(pit_y)}",
            xy=(pit_x, pit_y), xytext=(pit_x + 8, pit_y - 1),
            color="#ff6600", fontsize=6,
            arrowprops=dict(arrowstyle="->", color="#ff6600", lw=0.8),
            zorder=6,
        )

    # ── Panel ax_stats — Summary text ────────────────────────────────────
    ax_stats.set_facecolor(_BG_COLOR)
    ax_stats.axis("off")

    n_players  = df["player_id"].nunique()
    pit_mask30 = (df["wool_dist"] < 30) & (df["y"] < 5)
    min_y_near = int(df.loc[pit_mask30, "y"].min()) if pit_mask30.sum() > 0 else "—"
    wall_mask  = (df["activity"].isin(["wall", "trap", "gate"])) & (df["wool_dist"] < 15)
    max_h      = int(df.loc[wall_mask, "y"].max()) if wall_mask.sum() > 0 else "—"
    def_acts   = df["activity"].isin(["dig", "wall", "trap", "gate"])
    max_perim  = int(df.loc[def_acts, "wool_dist"].max()) if def_acts.sum() > 0 else "—"
    n_dig      = int((df["activity"] == "dig").sum())
    n_trap_gate = int(df["activity"].isin(["trap", "gate"]).sum())
    n_guard    = int((df["activity"] == "guard").sum())
    n_wall     = int((df["activity"] == "wall").sum())
    n_other    = int((df["activity"] == "other").sum())
    total_pos  = len(df)

    stats = [
        ("Active players", str(n_players)),
        ("Total positions", str(total_pos)),
        ("Pit depth (min y, dist<30)", str(min_y_near)),
        ("Max wall/gate height (dist<15)", str(max_h)),
        ("Defense perimeter (max dist)", str(max_perim)),
        ("Dig events (y<5)", str(n_dig)),
        ("Trap + gate events", str(n_trap_gate)),
        ("Wall block events", str(n_wall)),
        ("Guard events", str(n_guard)),
        ("Other events", str(n_other)),
    ]

    # Lay out in two rows of 5 columns
    cols = 5
    rows = 2
    for i, (key, val) in enumerate(stats):
        col = i % cols
        row = i // cols
        xi  = 0.02 + col * 0.20
        yi  = 0.75 - row * 0.40
        ax_stats.text(xi, yi, key + ":", transform=ax_stats.transAxes,
                      color="#888888", fontsize=7, va="top")
        ax_stats.text(xi, yi - 0.28, val, transform=ax_stats.transAxes,
                      color="#ffffff", fontsize=8.5, fontweight="bold", va="top")

    # ── Overall title ─────────────────────────────────────────────────────
    fig.suptitle(
        f"Defense setup overview — tumbleweed  |  wool {wool_node_id}  |  team {team}  "
        f"|  all segment_idx=0 positions within 60 blocks",
        color="white", fontsize=9, y=1.002,
    )

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=130, bbox_inches="tight", facecolor=_BG_COLOR)
        plt.close(fig)

    return fig
