#!/usr/bin/env python3
"""Generate defense-setup analysis images for one map.

Analyses segment_idx=0 (each player's first life, starting at match second 0)
near the team wool with the richest early-defense signal.

Produces three images in <output_dir>/<map>/defense_analysis/:
  defense_overview.png     — 3-panel aggregate: spatial map + lane section + stats
  defense_digger.png       — 6-panel diagnostic for the deepest pit-digger segment
  defense_builder.png      — 6-panel diagnostic for the highest trap/gate-builder segment

Usage
-----
    python scripts/run_defense_analysis.py --map tumbleweed
    python scripts/run_defense_analysis.py --map tumbleweed --output output/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPT_DIR   = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import duckdb
import numpy as np
import pandas as pd

from match_analysis.traffic_graph        import load_traffic_graph, build_traffic_topology
from match_analysis.traffic_snapping     import snap_positions, reconstruct_full_path, simplify_sequence
from match_analysis.traffic_diagnostics_plot import plot_life_segment_diagnostic
from match_analysis.defense_plot         import (
    classify_defense_activity, plot_defense_overview,
)

DB_PATH = _PROJECT_ROOT / "match_analysis" / "metadata.db"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_map_context(output_dir: Path) -> dict | None:
    p = output_dir / "map_context.json"
    if p.exists():
        import json
        with open(p) as f:
            return json.load(f)
    return None


def _load_early_positions(conn, map_slug: str) -> pd.DataFrame:
    """Load all segment_idx=0 position events for map_slug."""
    return conn.execute("""
        SELECT pe.match_id, pe.player_id, pe.segment_idx,
               pe.timestamp, pe.x, pe.y, pe.z
        FROM position_events pe
        JOIN life_segments ls
          ON ls.match_id = pe.match_id
         AND ls.player_id = pe.player_id
         AND ls.segment_idx = pe.segment_idx
        JOIN matches mat ON mat.match_id = pe.match_id
        JOIN maps    m   ON m.map_id     = mat.map_id
        WHERE m.map_slug = ?
          AND pe.segment_idx = 0
        ORDER BY pe.player_id, pe.timestamp
    """, [map_slug]).df()


def _load_life_segments(conn, map_slug: str) -> pd.DataFrame:
    return conn.execute("""
        SELECT ls.*
        FROM life_segments ls
        JOIN matches mat ON mat.match_id = ls.match_id
        JOIN maps m      ON m.map_id     = mat.map_id
        WHERE m.map_slug = ?
    """, [map_slug]).df()


def _load_held_items(parquet_path: Path) -> pd.DataFrame:
    """Extract per-position held_item from the raw parquet (event_type=5)."""
    raw = pd.read_parquet(parquet_path)
    pos = raw[raw["event_type"] == 5][["player_id", "timestamp", "held_item"]].copy()
    pos["held_item"] = pos["held_item"].astype("Int64")
    return pos.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Team / wool helpers (reuse logic from run_traffic_diagnostics.py)
# ---------------------------------------------------------------------------

def _nearest_spawn_team(spawn_x: float, spawn_z: float,
                        node_info: dict) -> str | None:
    best_team, best_d = None, float("inf")
    for n in node_info.values():
        if n.get("poi_type") != "spawn":
            continue
        cx, cz = n["coords"]
        d = (cx - spawn_x) ** 2 + (cz - spawn_z) ** 2
        if d < best_d:
            best_d, best_team = d, n.get("team")
    return best_team


def _wool_nodes_by_team(node_info: dict) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    for nid, n in node_info.items():
        if n.get("poi_type") == "wool" and n.get("team"):
            result.setdefault(n["team"], []).append(nid)
    return result


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

def _enrich_positions(
    positions: pd.DataFrame,
    held_items: pd.DataFrame,
    node_info: dict,
    dijkstra: dict,
    life_segments: pd.DataFrame,
) -> pd.DataFrame:
    """Join held_item, snap to graph, compute wool_dist, classify activity.

    Returns extended DataFrame with extra columns:
        snapped_node, held_item (nullable Int64), activity,
        team, home_wool_id, wool_dist
    """
    # Join held_item
    df = positions.merge(
        held_items[["player_id", "timestamp", "held_item"]],
        on=["player_id", "timestamp"],
        how="left",
    )

    # Snap all positions to nearest graph node
    snapped = snap_positions(df["x"].to_numpy(), df["z"].to_numpy(), node_info)
    df["snapped_node"] = snapped

    # Determine team per player from their segment_idx=0 spawn location
    spawn_lookup: dict[int, tuple[float, float]] = {
        int(r.player_id): (float(r.spawn_x), float(r.spawn_z))
        for r in life_segments[life_segments["segment_idx"] == 0].itertuples()
    }
    wool_by_team = _wool_nodes_by_team(node_info)

    player_team: dict[int, str | None] = {}
    for pid, (sx, sz) in spawn_lookup.items():
        player_team[pid] = _nearest_spawn_team(sx, sz, node_info)

    # Per-player home wool IDs
    player_home_wools: dict[int, list[int]] = {
        pid: wool_by_team.get(team, [])
        for pid, team in player_team.items()
    }

    # Assign team and home_wool_id to each row
    df["team"] = df["player_id"].map(player_team)

    # Compute wool_dist: min Dijkstra dist from snapped_node to any home wool
    def _min_wool_dist(row) -> float:
        home_wools = player_home_wools.get(int(row["player_id"]), [])
        nid = int(row["snapped_node"])
        best = float("inf")
        for w in home_wools:
            d = dijkstra.get(w, {}).get(nid, float("inf"))
            if d < best:
                best = d
        return best

    # Vectorise per-team for speed
    df["wool_dist"] = float("inf")
    for team_name, wools in wool_by_team.items():
        team_mask = df["team"] == team_name
        if not team_mask.any() or not wools:
            continue
        snapped_team = df.loc[team_mask, "snapped_node"].to_numpy(int)
        # For each node, min dist to any of this team's wools
        dists = np.full(len(snapped_team), float("inf"))
        for w in wools:
            w_dists = dijkstra.get(w, {})
            for i, nid in enumerate(snapped_team):
                d = w_dists.get(int(nid), float("inf"))
                if d < dists[i]:
                    dists[i] = d
        df.loc[team_mask, "wool_dist"] = dists

    # Classify activity from held_item
    def _act(row) -> str:
        hi = row["held_item"]
        if hi is pd.NA or (isinstance(hi, float) and np.isnan(hi)):
            return "other"
        return classify_defense_activity(int(hi))

    df["activity"] = df.apply(_act, axis=1)

    return df


# ---------------------------------------------------------------------------
# Wool selection
# ---------------------------------------------------------------------------

def _select_defense_wool(
    enriched: pd.DataFrame,
    node_info: dict,
) -> tuple[int, str]:
    """Pick the wool node + team with the most pit-digging signal.

    Metric: count of positions with y < 5 AND spatial distance < 40 blocks from
    each specific wool node.  Uses spatial (Euclidean) proximity so that each
    wool is evaluated independently — not the pre-computed multi-wool minimum.
    """
    wool_by_team = _wool_nodes_by_team(node_info)
    best_wool, best_team, best_count = -1, "", 0

    for team_name, wools in wool_by_team.items():
        team_df = enriched[enriched["team"] == team_name]
        if team_df.empty:
            continue
        for w in wools:
            wx, wz = node_info[w]["coords"]
            spatial_dist = np.sqrt(
                (team_df["x"].to_numpy(float) - wx) ** 2
                + (team_df["z"].to_numpy(float) - wz) ** 2
            )
            mask = (spatial_dist < 40) & (team_df["y"].to_numpy(float) < 5)
            cnt  = int(mask.sum())
            if cnt > best_count:
                best_count = cnt
                best_wool  = w
                best_team  = team_name

    if best_wool < 0:
        # Fallback: wool with most spatially nearby positions at any y
        for team_name, wools in wool_by_team.items():
            team_df = enriched[enriched["team"] == team_name]
            if team_df.empty:
                continue
            for w in wools:
                wx, wz = node_info[w]["coords"]
                spatial_dist = np.sqrt(
                    (team_df["x"].to_numpy(float) - wx) ** 2
                    + (team_df["z"].to_numpy(float) - wz) ** 2
                )
                cnt = int((spatial_dist < 40).sum())
                if cnt > best_count:
                    best_count = cnt
                    best_wool  = w
                    best_team  = team_name

    return best_wool, best_team


# ---------------------------------------------------------------------------
# Defense segment metrics
# ---------------------------------------------------------------------------

def _compute_defense_segment_metrics(
    enriched: pd.DataFrame,
    life_segments: pd.DataFrame,
    home_wool_ids: list[int],
    team: str,
) -> pd.DataFrame:
    """Per segment_idx=0 segment near target wool: compute defense metrics."""
    team_df = enriched[(enriched["team"] == team)].copy()

    records = []
    for (player_id, seg_idx), grp in team_df.groupby(["player_id", "segment_idx"]):
        if len(grp) < 4:
            continue
        grp = grp.sort_values("timestamp")

        near_wool = grp[grp["wool_dist"] < 30]
        if near_wool.empty:
            min_y_near = float("inf")
        else:
            min_y_near = float(near_wool["y"].min())

        near_zone = grp[grp["wool_dist"] < 60]
        if near_zone.empty:
            frac_trap  = 0.0
            avg_wool_dist = float(grp["wool_dist"].mean())
        else:
            frac_trap = float(
                near_zone["activity"].isin(["trap", "gate"]).sum()
            ) / len(near_zone)
            avg_wool_dist = float(near_zone["wool_dist"].mean())

        ls_row = life_segments[
            (life_segments["player_id"] == player_id)
            & (life_segments["segment_idx"] == seg_idx)
        ]
        if ls_row.empty:
            continue
        seg_id   = int(ls_row["segment_id"].iloc[0])
        duration = float(ls_row["duration"].iloc[0])
        kill_count = int(ls_row["kill_count"].iloc[0])

        records.append({
            "segment_id":   seg_id,
            "player_id":    int(player_id),
            "segment_idx":  int(seg_idx),
            "n_positions":  len(grp),
            "min_y_near":   min_y_near,
            "frac_trap":    frac_trap,
            "avg_wool_dist": avg_wool_dist,
            "duration":     duration,
            "kill_count":   kill_count,
        })

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Segment selection
# ---------------------------------------------------------------------------

def _select_segments(
    defense_metrics: pd.DataFrame,
) -> dict[str, dict]:
    """Select early_digger and early_builder from defense metrics."""
    if defense_metrics.empty:
        return {}

    selected: dict[str, dict] = {}

    # early_digger: lowest min_y_near_wool, avg_wool_dist < 60, n_positions >= 8
    dig_pool = defense_metrics[
        (defense_metrics["n_positions"] >= 8)
        & (defense_metrics["avg_wool_dist"] < 60)
        & (defense_metrics["min_y_near"] < float("inf"))
    ]
    if not dig_pool.empty:
        row = dig_pool.loc[dig_pool["min_y_near"].idxmin()]
        selected["early_digger"] = row.to_dict()

    selected_ids = {v["segment_id"] for v in selected.values()}

    # early_builder: highest frac_trap, avg_wool_dist < 60, n_positions >= 8
    build_pool = defense_metrics[
        (defense_metrics["n_positions"] >= 8)
        & (defense_metrics["avg_wool_dist"] < 60)
        & (defense_metrics["frac_trap"] > 0.0)
        & ~defense_metrics["segment_id"].isin(selected_ids)
    ]
    if not build_pool.empty:
        row = build_pool.loc[build_pool["frac_trap"].idxmax()]
        selected["early_builder"] = row.to_dict()

    return selected


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run(map_slug: str, output_root: Path) -> None:
    output_dir = output_root / map_slug
    out_dir    = output_dir / "defense_analysis"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== Defense setup analysis for '{map_slug}' ===\n")

    # ── Load topology ─────────────────────────────────────────────────────
    graph_path = output_dir / "traffic_graph.json"
    if not graph_path.exists():
        raise FileNotFoundError(
            f"traffic_graph.json not found at {graph_path}\n"
            "Run: python ctw.py matches traffic-graph --map-name <map>"
        )
    graph    = load_traffic_graph(graph_path)
    topology = build_traffic_topology(graph)
    node_info  = topology["node_info"]
    G_full     = topology["full_graph"]
    dijkstra   = topology["dijkstra_dists"]
    grid_size  = float(graph.get("grid_size", 5.0))

    map_context = _load_map_context(output_dir)

    # ── Load positions and life segments ──────────────────────────────────
    conn = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        print("Loading segment_idx=0 positions …")
        positions     = _load_early_positions(conn, map_slug)
        life_segments = _load_life_segments(conn, map_slug)
        match_row     = conn.execute(
            "SELECT match_file FROM matches LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    print(f"  {len(positions)} first-life position events, "
          f"{positions['player_id'].nunique()} unique players\n")

    # ── Load held_item from parquet ───────────────────────────────────────
    held_items: pd.DataFrame | None = None
    if match_row:
        pq_path = _PROJECT_ROOT / match_row[0]
        if pq_path.exists():
            print(f"Loading held_item data from {pq_path.name} …")
            held_items = _load_held_items(pq_path)
    if held_items is None:
        held_items = pd.DataFrame(columns=["player_id", "timestamp", "held_item"])

    # ── Enrich positions ──────────────────────────────────────────────────
    print("Snapping positions and computing wool distances …")
    enriched = _enrich_positions(
        positions, held_items, node_info, dijkstra, life_segments
    )

    # ── Select target wool ────────────────────────────────────────────────
    wool_id, team = _select_defense_wool(enriched, node_info)
    wool_node  = node_info[wool_id]
    wx, wz     = wool_node["coords"]
    wool_by_team = _wool_nodes_by_team(node_info)
    home_wools = wool_by_team.get(team, [])

    # Compute Dijkstra distances to the SPECIFIC selected wool for the overview.
    # The generic wool_dist column holds min-over-all-home-wools and must not be
    # used for the section-view x-axis or pit-depth stats.
    w_dists_specific = dijkstra.get(wool_id, {})
    snapped_arr = enriched["snapped_node"].to_numpy(int)
    specific_dists = np.array([
        w_dists_specific.get(int(nid), float("inf")) for nid in snapped_arr
    ])
    enriched["wool_dist_specific"] = specific_dists

    # For zone_df: use spatial proximity to the selected wool so positions that
    # cannot be reached via Dijkstra are still included if they are close.
    spatial_all = np.sqrt(
        (enriched["x"].to_numpy(float) - wx) ** 2
        + (enriched["z"].to_numpy(float) - wz) ** 2
    )
    zone_mask = (spatial_all <= 70) | (specific_dists <= 60)
    zone_df = enriched[zone_mask].copy()
    # Overwrite wool_dist with specific-wool distance for section view x-axis and stats.
    # For unreachable positions use spatial distance as a fallback approximation.
    zone_specific = zone_df["wool_dist_specific"].to_numpy(float)
    zone_spatial  = spatial_all[zone_mask]
    zone_df["wool_dist"] = np.where(
        np.isfinite(zone_specific), zone_specific, zone_spatial
    )

    print(f"Target wool: node {wool_id}  team={team}  coords=({wx}, {wz})")
    print(f"  {zone_df['player_id'].nunique()} players active within 60 blocks")
    print(f"  {int((zone_df['y'] < 5).sum())} positions with y<5 (pit digging)")
    print(f"  Activity breakdown: {dict(zone_df['activity'].value_counts())}\n")

    # ── Defense segment metrics ───────────────────────────────────────────
    print("Computing per-segment defense metrics …")
    def_metrics = _compute_defense_segment_metrics(
        enriched, life_segments, home_wools, team
    )
    print(f"  {len(def_metrics)} first-life segments with ≥4 positions near wool\n")

    # ── Segment selection ─────────────────────────────────────────────────
    selections = _select_segments(def_metrics)
    if not selections:
        print("WARNING: No defense segments found — check data.")
        return

    print("Selected segments:")
    for label, meta in selections.items():
        print(
            f"  {label:16s}  seg_id={meta['segment_id']}  "
            f"player={meta['player_id']}  n={meta['n_positions']}  "
            f"min_y_near={meta['min_y_near']:.1f}  frac_trap={meta['frac_trap']:.0%}  "
            f"avg_dist={meta['avg_wool_dist']:.1f}"
        )
    print()

    # ── Generate 6-panel segment diagnostics ─────────────────────────────
    for label, meta in selections.items():
        player_id  = meta["player_id"]
        seg_idx    = meta["segment_idx"]
        segment_id = meta["segment_id"]

        # Get segment positions from enriched (has y + held_item)
        seg_df = enriched[
            (enriched["player_id"] == player_id)
            & (enriched["segment_idx"] == seg_idx)
        ].sort_values("timestamp").reset_index(drop=True)

        # Snapped sequence
        snapped_seq = seg_df["snapped_node"].tolist()
        recon_path  = reconstruct_full_path(
            snapped_seq, G_full, mode="dense", grid_size=grid_size
        )
        simplified  = simplify_sequence(snapped_seq, method="consecutive_dedup")

        # Choose Panel A colouring
        if label == "early_digger":
            seg_positions_y     = seg_df["y"].tolist()
            seg_held_item_series = None
        else:  # early_builder
            seg_positions_y      = None
            hi_raw = seg_df["held_item"].tolist()
            seg_held_item_series = [
                int(v) if v is not pd.NA and not (isinstance(v, float) and np.isnan(v))
                else -1
                for v in hi_raw
            ]

        # Extra Panel F metadata specific to defense
        ls_row = life_segments[
            (life_segments["player_id"] == player_id)
            & (life_segments["segment_idx"] == seg_idx)
        ]
        has_wool = bool(ls_row["wool_touches"].iloc[0] > 0) if len(ls_row) else False

        out_path = out_dir / f"defense_{label.split('_')[1]}.png"
        print(f"Plotting [{label}] → {out_path}")
        plot_life_segment_diagnostic(
            map_slug=map_slug,
            match_id=int(seg_df["match_id"].iloc[0]),
            player_id=player_id,
            segment_idx=seg_idx,
            positions_df=seg_df[["x", "z", "timestamp"]],
            snapped_sequence=snapped_seq,
            node_info=node_info,
            G_full=G_full,
            reconstructed_path=recon_path,
            simplified_sequence=simplified,
            map_context=map_context,
            has_wool_event=has_wool,
            label=label,
            simplification_method="consecutive_dedup",
            reconstruction_mode="dense",
            tortuosity=None,
            held_item_series=seg_held_item_series,
            positions_y=seg_positions_y,
            output_path=out_path,
        )

    # ── Generate defense overview ─────────────────────────────────────────
    overview_path = out_dir / "defense_overview.png"
    print(f"Plotting [defense overview] → {overview_path}")
    plot_defense_overview(
        positions_df=zone_df,
        node_info=node_info,
        G_full=G_full,
        wool_node_id=wool_id,
        team=team,
        map_context=map_context,
        output_path=overview_path,
    )

    print("\nDone. Output directory:")
    for p in sorted(out_dir.iterdir()):
        size_kb = p.stat().st_size // 1024
        print(f"  {p.name}  ({size_kb} KB)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--map", required=True, metavar="MAP_SLUG")
    p.add_argument("--output", default="output/", metavar="OUTPUT_ROOT")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run(args.map, _PROJECT_ROOT / args.output)
