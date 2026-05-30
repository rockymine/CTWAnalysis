#!/usr/bin/env python3
"""Generate demo images for a CTW map.

Creates a set of clean, legend-free images showcasing the analysis pipeline
output. Images are saved with stable numbered filenames so the Markdown
showcase page never breaks when internal naming changes.

Usage:
    python docs/demo/generate_demo.py --map Ingwaz
    python docs/demo/generate_demo.py --map tumbleweed --match 3 --player 21
    python docs/demo/generate_demo.py --map tumbleweed --output docs/demo/assets/tumbleweed
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path so imports work when running directly
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

from ctw.common import resolve_map_folder, resolve_output_dir, ensure_match_db
from common.visualization.map_primitives import (
    draw_block_base,
    draw_build_region,
    draw_island_outlines,
    draw_pois,
    BlockBaseStyle,
    IslandOutlineStyle,
)


# ── Shared figure helpers ───────────────────────────────────────────────

def _new_figure(figsize=(16, 10)):
    """Create a clean figure with no decorations."""
    fig, ax = plt.subplots(figsize=figsize)
    ax.set_aspect('equal')
    ax.axis('off')
    return fig, ax


def _save(fig, path, dpi=200):
    """Save figure and close."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    fig.savefig(str(path), dpi=dpi, bbox_inches='tight', pad_inches=0.05)
    plt.close(fig)
    print(f"  Saved {path}")


def _set_bounds_from_context(ax, map_context, padding=2):
    """Set axis limits from map bounding box with some padding."""
    bbox = map_context.get('bounding_box')
    if bbox:
        min_x, max_x, min_z, max_z = bbox
        ax.set_xlim(min_x - padding, max_x + padding)
        ax.set_ylim(min_z - padding, max_z + padding)


# ── Skeleton / connectivity layer helpers ───────────────────────────────

def _draw_skeleton_edges(ax, map_context, map_graph):
    """Draw skeleton edge pixel paths from map_graph JSON data."""
    graph_islands_by_id = {
        ie['island_id']: ie for ie in map_graph.get('islands', [])
    }
    for island in map_context.get('islands', []):
        iid = island['id']
        graph_island = graph_islands_by_id.get(iid, {})
        skeleton = graph_island.get('skeleton')
        if skeleton is None:
            continue

        edge_pixels = skeleton.get('edge_pixels', {})
        for edge_key, ep_data in edge_pixels.items():
            pixels = ep_data.get('pixels', [])
            if len(pixels) < 2:
                continue
            px = np.array(pixels)
            ax.plot(
                px[:, 0], px[:, 1],
                color='lightblue',
                linewidth=1,
                alpha=0.8,
                zorder=2,
            )


def _draw_skeleton_nodes(ax, map_context, map_graph):
    """Draw skeleton nodes (endpoints + junctions) from map_graph JSON data."""
    graph_islands_by_id = {
        ie['island_id']: ie for ie in map_graph.get('islands', [])
    }
    for island in map_context.get('islands', []):
        iid = island['id']
        graph_island = graph_islands_by_id.get(iid, {})
        skeleton = graph_island.get('skeleton')
        if skeleton is None:
            continue

        for node in skeleton['nodes']:
            if node['type'] == 'endpoint':
                ax.scatter(
                    node['x'], node['z'],
                    s=30, c='#1d3557',
                    edgecolors='white', linewidths=0.6,
                    zorder=7,
                )
            else:
                ax.scatter(
                    node['x'], node['z'],
                    s=12, c='#555555',
                    alpha=0.5, zorder=3,
                )


# ── Image generators ───────────────────────────────────────────────────

def gen_blocks(map_folder, map_context, output_path):
    """01 — Block layout colored by island with POI markers."""
    fig, ax = _new_figure()
    draw_block_base(ax, map_folder, map_context,
                    style=BlockBaseStyle(fill_alpha=0.25, edge_alpha=0.4))
    draw_pois(ax, map_context)
    _set_bounds_from_context(ax, map_context)
    ax.invert_yaxis()
    _save(fig, output_path)


def gen_regions(map_context, output_path):
    """02 — XML regions: build region + island outlines + POIs."""
    fig, ax = _new_figure()
    draw_build_region(ax, map_context)
    draw_island_outlines(ax, map_context)
    draw_pois(ax, map_context)
    _set_bounds_from_context(ax, map_context)
    ax.invert_yaxis()
    _save(fig, output_path)


def gen_skeleton(map_context, map_graph, output_path):
    """03 — Skeleton overlay: island outlines + skeleton edges/nodes + POIs."""
    fig, ax = _new_figure()
    draw_island_outlines(ax, map_context)
    _draw_skeleton_edges(ax, map_context, map_graph)
    _draw_skeleton_nodes(ax, map_context, map_graph)
    draw_pois(ax, map_context)
    _set_bounds_from_context(ax, map_context)
    ax.invert_yaxis()
    _save(fig, output_path)


def gen_outline(map_context, output_path):
    """04 — Polygon outlines only (thicker lines)."""
    fig, ax = _new_figure()
    draw_island_outlines(
        ax, map_context,
        style=IslandOutlineStyle(
            exterior_linewidth=1.5, exterior_alpha=1.0,
            hole_linewidth=1.0, hole_alpha=0.8,
        ),
    )
    draw_pois(ax, map_context)
    _set_bounds_from_context(ax, map_context)
    ax.invert_yaxis()
    _save(fig, output_path)


def gen_trace_single(map_context, match_id, player_id, map_graph, map_folder,
                     output_path):
    """05 — Single player trace (no legend/stats/title)."""
    from match_analysis.visualization import plot_player_traces

    plot_player_traces(
        map_context, match_id, [player_id], output_path,
        map_graph=map_graph,
        show_legend=False,
        show_stats=False,
        show_title=False,
        map_base='outline',
        map_folder=map_folder,
    )
    print(f"  Saved {output_path}")


def gen_trace_team(map_context, match_id, player_ids, map_graph, map_folder,
                   output_path):
    """06 — All players with team coloring (no legend/stats/title)."""
    from match_analysis.visualization import plot_player_traces

    plot_player_traces(
        map_context, match_id, player_ids, output_path,
        map_graph=map_graph,
        show_legend=False,
        show_stats=False,
        show_title=False,
        color_mode='team',
        map_base='outline',
        map_folder=map_folder,
    )
    print(f"  Saved {output_path}")


# ── Match processing helpers ────────────────────────────────────────────

_MINECRAFT_COLORS = {
    "dark_red": "#AA0000", "dark red": "#AA0000",
    "red": "#FF5555",
    "gold": "#FFAA00",
    "yellow": "#DDDD00",
    "dark_green": "#00AA00", "dark green": "#00AA00",
    "green": "#55FF55",
    "aqua": "#55FFFF",
    "dark_aqua": "#00AAAA", "dark aqua": "#00AAAA",
    "dark_blue": "#0000AA", "dark blue": "#0000AA",
    "blue": "#5555FF",
    "light_purple": "#FF55FF", "light purple": "#FF55FF",
    "dark_purple": "#AA00AA", "dark purple": "#AA00AA",
    "white": "#FFFFFF",
    "gray": "#AAAAAA",
    "dark_gray": "#555555", "dark gray": "#555555",
    "black": "#000000",
}


def _get_team_colors(conn, map_id):
    """Return {team: hex_color} for a map's teams."""
    rows = conn.execute(
        "SELECT team, team_color FROM map_spawns WHERE map_id = ?", [map_id]
    ).fetchall()
    tab10 = [matplotlib.colors.to_hex(c) for c in plt.get_cmap("tab10").colors]
    colors = {}
    tab10_idx = 0
    for team_raw, color_raw in rows:
        team = team_raw.removesuffix("-team")
        hex_color = _MINECRAFT_COLORS.get(color_raw)
        if hex_color is None:
            try:
                hex_color = matplotlib.colors.to_hex(color_raw)
            except (ValueError, TypeError):
                hex_color = tab10[tab10_idx % len(tab10)]
                tab10_idx += 1
        colors[team] = hex_color
    return colors


def _add_attack_depth(pos_df, baselines):
    """Compute per-tick attack depth for every row in pos_df."""
    import pandas as pd
    depths = pd.Series(0.0, index=pos_df.index)
    for team, grp in pos_df.groupby("team"):
        if pd.isna(team):
            continue
        team_baselines = baselines[baselines["team"] == team]
        if team_baselines.empty:
            continue
        px = grp["x"].values.astype(float)
        pz = grp["z"].values.astype(float)
        for _, wb in team_baselines.iterrows():
            dist = np.sqrt((px - wb.wool_x) ** 2 + (pz - wb.wool_z) ** 2)
            depth = np.clip(1.0 - dist / wb.baseline_distance, 0.0, 1.0)
            depths.loc[grp.index] = np.maximum(depths.loc[grp.index].values, depth)
    return depths


def gen_timeseries(match_id, output_path, bucket_size_s=60):
    """07 — Single-match time series: per-team attack depth and death rate."""
    import duckdb
    import pandas as pd
    import math

    db_path = str(_PROJECT_ROOT / 'match_analysis' / 'metadata.db')
    conn = duckdb.connect(db_path, read_only=True)

    meta = conn.execute(
        "SELECT mat.match_id, mat.map_id, mat.match_duration, m.map_slug "
        "FROM matches mat JOIN maps m ON mat.map_id = m.map_id "
        "WHERE match_id = ?", [match_id]
    ).fetchone()
    _, map_id, match_duration_s, map_slug = meta

    team_colors = _get_team_colors(conn, map_id)

    pos_df = conn.execute("""
        SELECT pe.player_id, pe.timestamp AS tick_t_s, pe.x, pe.z,
               pe.location_type, pts.team
        FROM position_events pe
        LEFT JOIN player_team_segments pts
            ON pts.player_id = pe.player_id
            AND pts.match_id = pe.match_id
            AND pts.start_timestamp <= pe.timestamp
            AND (pts.end_timestamp IS NULL OR pts.end_timestamp >= pe.timestamp)
        WHERE pe.match_id = ? AND pe.location_type != 'void'
        ORDER BY pe.player_id, pe.timestamp
    """, [match_id]).df()

    death_df = conn.execute("""
        SELECT ce.timestamp AS tick_t_s, pts.team
        FROM combat_events ce
        LEFT JOIN player_team_segments pts
            ON pts.player_id = ce.player_id
            AND pts.match_id = ce.match_id
            AND pts.start_timestamp <= ce.timestamp
            AND (pts.end_timestamp IS NULL OR pts.end_timestamp >= ce.timestamp)
        WHERE ce.match_id = ? AND ce.event_type = 4
    """, [match_id]).df()

    wool_df = conn.execute("""
        SELECT we.timestamp AS tick_t_s, we.event_type, pts.team
        FROM wool_events we
        LEFT JOIN player_team_segments pts
            ON pts.player_id = we.player_id
            AND pts.match_id = we.match_id
            AND pts.start_timestamp <= we.timestamp
            AND (pts.end_timestamp IS NULL OR pts.end_timestamp >= we.timestamp)
        WHERE we.match_id = ?
    """, [match_id]).df()

    baselines = conn.execute("""
        SELECT team, wool_id, wool_x, wool_z, baseline_distance
        FROM wool_spawn_baselines WHERE map_id = ?
    """, [map_id]).df()

    conn.close()

    pos_df["attack_depth"] = _add_attack_depth(pos_df, baselines)
    pos_df["bucket"] = (pos_df["tick_t_s"] // bucket_size_s).astype(int)
    death_df["bucket"] = (death_df["tick_t_s"] // bucket_size_s).astype(int)

    depth_stats = (
        pos_df.groupby(["team", "bucket"])["attack_depth"]
        .agg(["mean", "std"])
        .rename(columns={"mean": "mean_attack_depth", "std": "depth_std"})
        .reset_index()
    )
    death_counts = (
        death_df.groupby(["team", "bucket"]).size()
        .rename("death_count").reset_index()
    )
    metrics = depth_stats.merge(death_counts, on=["team", "bucket"], how="left")
    metrics["death_count"] = metrics["death_count"].fillna(0)
    metrics["depth_std"] = metrics["depth_std"].fillna(0)
    metrics["death_rate"] = metrics["death_count"] / bucket_size_s
    metrics["bucket_mid_s"] = (metrics["bucket"] + 0.5) * bucket_size_s

    teams = sorted(metrics["team"].dropna().unique())
    n_teams = len(teams)
    ncols = min(n_teams, 2)
    nrows = math.ceil(n_teams / ncols)
    fig, axes = plt.subplots(nrows, ncols,
                             figsize=(8 * ncols, 4 * nrows),
                             constrained_layout=True, squeeze=False)

    for ax_idx, team in enumerate(teams):
        row, col = divmod(ax_idx, ncols)
        ax = axes[row][col]
        ax2 = ax.twinx()
        color = team_colors.get(team, "#888888")
        tm = metrics[metrics["team"] == team].sort_values("bucket_mid_s")

        if not tm.empty:
            xs = tm["bucket_mid_s"].values
            ys = tm["mean_attack_depth"].values
            sd = tm["depth_std"].values
            dr = tm["death_rate"].values
            ax.plot(xs, ys, color=color, lw=2, label="attack depth")
            ax.fill_between(xs, ys - sd, ys + sd, color=color, alpha=0.18)
            ax2.plot(xs, dr, color=color, lw=1.2, ls="--", alpha=0.55,
                     label="death rate")

        wool_team = wool_df[wool_df["team"] == team]
        touches = wool_team[wool_team["event_type"] == 6]["tick_t_s"].values
        captures = wool_team[wool_team["event_type"] == 7]["tick_t_s"].values
        if len(touches):
            ax.scatter(touches, [0.02] * len(touches), marker="^",
                       color=color, s=60, alpha=0.5, zorder=5, clip_on=True)
        if len(captures):
            ax.scatter(captures, [0.02] * len(captures), marker="*",
                       color=color, s=140, zorder=6, clip_on=True)

        ax.axvline(match_duration_s, color="grey", ls="--", lw=0.8)
        ax.set_xlim(0, match_duration_s + 5)
        ax.set_ylim(0, 1.05)
        ax.set_xlabel("Elapsed seconds", fontsize=9)
        ax.set_ylabel("Mean attack depth", fontsize=9)
        ax2.set_ylabel("Deaths / second", color=color, fontsize=8)
        ax2.tick_params(axis="y", labelcolor=color, labelsize=8)
        ax.set_title(f"{map_slug} — {team} team", fontsize=10)

        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines1 + lines2, labels1 + labels2, loc="upper left",
                  fontsize=8)

    for ax_idx in range(n_teams, nrows * ncols):
        row, col = divmod(ax_idx, ncols)
        axes[row][col].set_visible(False)

    os.makedirs(os.path.dirname(str(output_path)) or '.', exist_ok=True)
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {output_path}")


def gen_archetype_distribution(map_slug, output_path):
    """08 — Archetype distribution bar chart for this map's matches."""
    import duckdb

    db_path = str(_PROJECT_ROOT / 'match_analysis' / 'metadata.db')
    conn = duckdb.connect(db_path, read_only=True)

    df = conn.execute("""
        SELECT f.cluster_label, pts.team, COUNT(*) AS n_lives
        FROM life_segment_features f
        JOIN life_segments ls ON f.segment_id = ls.segment_id
        JOIN matches mat ON mat.match_id = ls.match_id
        JOIN maps m ON m.map_id = mat.map_id
        LEFT JOIN player_team_segments pts
            ON pts.player_id = ls.player_id
            AND pts.match_id = ls.match_id
            AND pts.start_timestamp <= ls.start_timestamp
            AND (pts.end_timestamp IS NULL
                 OR pts.end_timestamp >= ls.end_timestamp)
        WHERE m.map_slug = ?
          AND f.cluster_label IS NOT NULL
        GROUP BY f.cluster_label, pts.team
        ORDER BY f.cluster_label, pts.team
    """, [map_slug]).df()
    conn.close()

    if df.empty:
        print(f"  Warning: no archetype labels found for {map_slug}, skipping")
        return

    # Pivot so each team is a stacked bar segment
    pivot = df.pivot_table(
        index='cluster_label', columns='team', values='n_lives', fill_value=0
    )

    archetype_order = [
        'deep-attacker', 'attacker', 'bridge-fighter', 'defender', 'outlier',
        'unclassified',
    ]
    pivot = pivot.reindex(
        [a for a in archetype_order if a in pivot.index]
    )

    team_colors_map = {
        'red': '#FF5555', 'blue': '#5555FF', 'green': '#55FF55',
        'yellow': '#DDDD00', 'purple': '#AA00AA', 'aqua': '#55FFFF',
    }
    bar_colors = [
        team_colors_map.get(t, '#AAAAAA') for t in pivot.columns
    ]

    fig, ax = plt.subplots(figsize=(10, 5))
    pivot.plot(kind='bar', ax=ax, color=bar_colors, edgecolor='white',
               linewidth=0.5, rot=25)

    ax.set_xlabel('')
    ax.set_ylabel('Number of life segments', fontsize=10)
    ax.set_title(f'Player role archetypes — {map_slug}', fontsize=12)
    ax.legend(title='Team', fontsize=9, title_fontsize=9)
    ax.tick_params(axis='x', labelsize=9)
    ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    os.makedirs(os.path.dirname(str(output_path)) or '.', exist_ok=True)
    fig.savefig(str(output_path), dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved {output_path}")


# ── Main ────────────────────────────────────────────────────────────────

MAP_STABLE_NAMES = [
    '01_blocks.png',
    '02_regions.png',
    '03_skeleton.png',
    '04_outline.png',
]

MATCH_STABLE_NAMES = [
    '05_trace_single.png',
    '06_trace_team.png',
    '07_timeseries.png',
    '08_archetypes.png',
]

STABLE_NAMES = MAP_STABLE_NAMES + MATCH_STABLE_NAMES


def main():
    parser = argparse.ArgumentParser(
        description='Generate demo images for a CTW map.',
    )
    parser.add_argument('--map', required=True,
                        help='Map name or path (e.g. tumbleweed)')
    parser.add_argument('--output',
                        help='Output directory (default: docs/demo/assets/<map>)')
    parser.add_argument('--match', type=int, default=None,
                        help='Match ID for match images (default: first match for this map)')
    parser.add_argument('--player', type=int, default=None,
                        help='Player ID for single-player trace (default: player with most kills)')
    args = parser.parse_args()

    # Resolve paths
    map_folder = resolve_map_folder(args.map)
    map_name = map_folder.name
    map_output_dir = resolve_output_dir(map_folder, create=False)
    output_dir = Path(args.output) if args.output else (
        _SCRIPT_DIR / 'assets' / map_name
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    def _find(rel_path):
        """Check map_output_dir first, fall back to map_folder."""
        p = map_output_dir / rel_path
        if p.exists():
            return p
        p = map_folder / rel_path
        if p.exists():
            return p
        return None

    print(f"Generating demo images for {map_name}")
    print(f"Output: {output_dir}")

    # Load shared data
    context_path = _find('map_context.json')
    if context_path is None:
        print(f"Error: map_context.json not found. Run 'ctw islands --map {map_name}' first.")
        sys.exit(1)
    with open(context_path) as f:
        map_context = json.load(f)

    graph_path = _find('map_graph.json')
    if graph_path is None:
        print(f"Error: map_graph.json not found. Run 'ctw islands --map {map_name}' first.")
        sys.exit(1)
    with open(graph_path) as f:
        map_graph = json.load(f)

    # Resolve layout dir (where layout_bedrock.parquet lives)
    layout_dir = map_output_dir if (map_output_dir / 'layout_bedrock.parquet').exists() else map_folder

    # Resolve match data
    ensure_match_db()
    from match_analysis.database.queries import get_match_player_ids
    import duckdb

    db_path = str(_PROJECT_ROOT / 'match_analysis' / 'metadata.db')
    match_id = args.match
    map_slug = map_name
    all_player_ids = []
    player_id = args.player

    try:
        conn = duckdb.connect(db_path, read_only=True)

        # Auto-select map slug from DB (handles case mismatches)
        slug_row = conn.execute(
            "SELECT map_slug FROM maps WHERE map_slug ILIKE ?", [map_slug]
        ).fetchone()
        if slug_row:
            map_slug = slug_row[0]

        if match_id is None:
            row = conn.execute(
                "SELECT mat.match_id FROM matches mat "
                "JOIN maps m ON mat.map_id = m.map_id "
                "WHERE m.map_slug = ? AND mat.processed = TRUE "
                "ORDER BY mat.match_id LIMIT 1",
                [map_slug],
            ).fetchone()
            if row:
                match_id = row[0]

        if match_id is not None:
            all_player_ids = get_match_player_ids(match_id)

            if player_id is None:
                row = conn.execute("""
                    SELECT ls.player_id
                    FROM life_segments ls
                    JOIN life_segment_features f ON f.segment_id = ls.segment_id
                    WHERE ls.match_id = ?
                    GROUP BY ls.player_id
                    ORDER BY SUM(f.kills) DESC
                    LIMIT 1
                """, [match_id]).fetchone()
                if row:
                    player_id = row[0]
                else:
                    player_id = all_player_ids[0] if all_player_ids else 0

        conn.close()
    except Exception as e:
        print(f"Warning: could not resolve match data ({e}), skipping match images")
        match_id = None

    has_match = match_id is not None and len(all_player_ids) > 0

    # ── Generate map images ─────────────────────────────────────────────
    outputs = []
    n_total = len(MAP_STABLE_NAMES) + (len(MATCH_STABLE_NAMES) if has_match else 0)
    step = 0

    step += 1
    print(f"\n[{step}/{n_total}] Block layout...")
    path = output_dir / MAP_STABLE_NAMES[0]
    gen_blocks(layout_dir, map_context, path)
    outputs.append(path)

    step += 1
    print(f"[{step}/{n_total}] XML regions...")
    path = output_dir / MAP_STABLE_NAMES[1]
    gen_regions(map_context, path)
    outputs.append(path)

    step += 1
    print(f"[{step}/{n_total}] Skeleton overlay...")
    path = output_dir / MAP_STABLE_NAMES[2]
    gen_skeleton(map_context, map_graph, path)
    outputs.append(path)

    step += 1
    print(f"[{step}/{n_total}] Polygon outlines...")
    path = output_dir / MAP_STABLE_NAMES[3]
    gen_outline(map_context, path)
    outputs.append(path)

    # ── Generate match images ───────────────────────────────────────────
    if has_match:
        step += 1
        print(f"[{step}/{n_total}] Single player trace (player {player_id}, match {match_id})...")
        path = output_dir / MATCH_STABLE_NAMES[0]
        gen_trace_single(map_context, match_id, player_id, map_graph, layout_dir, path)
        outputs.append(path)

        step += 1
        print(f"[{step}/{n_total}] Team trace ({len(all_player_ids)} players, match {match_id})...")
        path = output_dir / MATCH_STABLE_NAMES[1]
        gen_trace_team(map_context, match_id, all_player_ids, map_graph, layout_dir, path)
        outputs.append(path)

        step += 1
        print(f"[{step}/{n_total}] Match time series (match {match_id})...")
        path = output_dir / MATCH_STABLE_NAMES[2]
        gen_timeseries(match_id, path)
        outputs.append(path)

        step += 1
        print(f"[{step}/{n_total}] Archetype distribution ({map_slug})...")
        path = output_dir / MATCH_STABLE_NAMES[3]
        gen_archetype_distribution(map_slug, path)
        outputs.append(path)
    else:
        for name in MATCH_STABLE_NAMES:
            print(f"[skip] {name} (no match data)")

    print(f"\nDone. Generated {len(outputs)} images in {output_dir}")


if __name__ == '__main__':
    main()
