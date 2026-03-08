#!/usr/bin/env python3
"""Generate traffic-graph diagnostic images for one map.

Produces:
  1. A full-map traffic graph overview (reuses existing plot_traffic_graph).
  2. A 6-panel diagnostic figure for each of four representative life segments:
       - deep_attacker   (snapped closest to a wool node)
       - defender        (long segment, low unique-node count, near spawn)
       - jitter          (highest consecutive-repeat ratio)
       - traversal       (maximum first→last Euclidean span)

Outputs are written to:
  <output_dir>/<map>/traffic_graph_diagnostics/

Usage
-----
    python scripts/run_traffic_diagnostics.py --map tumbleweed
    python scripts/run_traffic_diagnostics.py --map tumbleweed --output output/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running from project root directly
_SCRIPT_DIR  = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import duckdb
import numpy as np
import pandas as pd

from match_analysis.traffic_graph   import load_traffic_graph, build_traffic_topology, plot_traffic_graph
from match_analysis.traffic_snapping import (
    snap_positions,
    reconstruct_full_path,
    simplify_sequence,
)
from match_analysis.traffic_diagnostics_plot import plot_life_segment_diagnostic

DB_PATH = _PROJECT_ROOT / "match_analysis" / "metadata.db"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_map_context(output_dir: Path) -> dict | None:
    path = output_dir / "map_context.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def _load_traffic_graph_data(output_dir: Path) -> dict:
    path = output_dir / "traffic_graph.json"
    if not path.exists():
        raise FileNotFoundError(
            f"traffic_graph.json not found at {path}\n"
            "Run: python ctw.py matches traffic-graph --map-name <map>"
        )
    return load_traffic_graph(path)


def _load_all_positions(conn, map_slug: str) -> pd.DataFrame:
    """Load all position events for *map_slug* in one shot."""
    return conn.execute("""
        SELECT pe.match_id, pe.player_id, pe.segment_idx,
               pe.timestamp, pe.x, pe.z, pe.island_id
        FROM position_events pe
        JOIN life_segments ls
          ON ls.match_id = pe.match_id
          AND ls.player_id = pe.player_id
          AND ls.segment_idx = pe.segment_idx
        JOIN matches mat ON mat.match_id = pe.match_id
        JOIN maps m      ON m.map_id     = mat.map_id
        WHERE m.map_slug = ?
        ORDER BY pe.match_id, pe.player_id, pe.segment_idx, pe.timestamp
    """, [map_slug]).df()


def _load_life_segments(conn, map_slug: str) -> pd.DataFrame:
    return conn.execute("""
        SELECT ls.*
        FROM life_segments ls
        JOIN matches mat ON mat.match_id = ls.match_id
        JOIN maps m      ON m.map_id     = mat.map_id
        WHERE m.map_slug = ?
    """, [map_slug]).df()


def _load_wool_events(conn, map_slug: str) -> pd.DataFrame:
    return conn.execute("""
        SELECT we.match_id, we.player_id, we.segment_idx, COUNT(*) AS wool_event_count
        FROM wool_events we
        JOIN matches mat ON mat.match_id = we.match_id
        JOIN maps m      ON m.map_id     = mat.map_id
        WHERE m.map_slug = ?
        GROUP BY we.match_id, we.player_id, we.segment_idx
    """, [map_slug]).df()


# ---------------------------------------------------------------------------
# Per-segment metric computation
# ---------------------------------------------------------------------------

def _compute_segment_metrics(
    positions_all: pd.DataFrame,
    life_segments: pd.DataFrame,
    node_info: dict[int, dict],
    dijkstra_dists: dict[int, dict[int, float]],
    wool_events: pd.DataFrame,
    min_positions: int = 4,
) -> pd.DataFrame:
    """Snap all positions and compute heuristic metrics for each segment.

    Returns a DataFrame with one row per life_segment and columns:
        segment_id, match_id, player_id, segment_idx, duration,
        position_count, snapped (list), unique_nodes, jitter_ratio,
        min_wool_dist, span_m (Euclidean first→last), has_wool_event
    """
    # Filter to segments with enough positions
    seg_keys = positions_all.groupby(["match_id", "player_id", "segment_idx"]).size()
    valid_keys = seg_keys[seg_keys >= min_positions].reset_index()
    valid_keys.columns = ["match_id", "player_id", "segment_idx", "_cnt"]

    pos_filtered = positions_all.merge(
        valid_keys[["match_id", "player_id", "segment_idx"]],
        on=["match_id", "player_id", "segment_idx"],
    )

    # Vectorised snap of all positions at once
    all_snapped = snap_positions(
        pos_filtered["x"].to_numpy(),
        pos_filtered["z"].to_numpy(),
        node_info,
    )
    pos_filtered = pos_filtered.copy()
    pos_filtered["snapped_node"] = all_snapped

    wool_events_set = set(
        zip(wool_events["match_id"], wool_events["player_id"], wool_events["segment_idx"])
    )

    records = []
    for (match_id, player_id, seg_idx), grp in pos_filtered.groupby(
        ["match_id", "player_id", "segment_idx"]
    ):
        grp = grp.sort_values("timestamp")
        xs  = grp["x"].to_numpy(float)
        zs  = grp["z"].to_numpy(float)
        snapped_seq = grp["snapped_node"].tolist()

        unique_nodes = len(set(snapped_seq))
        n = len(snapped_seq)

        # Jitter ratio: how many consecutive nodes are the same
        consec_same = sum(1 for a, b in zip(snapped_seq, snapped_seq[1:]) if a == b)
        jitter_ratio = consec_same / (n - 1) if n > 1 else 0.0

        # Minimum Dijkstra distance to any wool node (using snapped anchors)
        if dijkstra_dists:
            min_wool_dist = min(
                (
                    min(
                        (dd.get(nid, float("inf")) for dd in dijkstra_dists.values()),
                        default=float("inf"),
                    )
                    for nid in snapped_seq
                ),
                default=float("inf"),
            )
        else:
            min_wool_dist = float("inf")

        # Euclidean span: distance between first and last sample
        span_m = float(np.sqrt((xs[-1] - xs[0]) ** 2 + (zs[-1] - zs[0]) ** 2))

        has_wool = (int(match_id), int(player_id), int(seg_idx)) in wool_events_set

        # Look up duration from life_segments
        ls_row = life_segments[
            (life_segments["match_id"] == match_id)
            & (life_segments["player_id"] == player_id)
            & (life_segments["segment_idx"] == seg_idx)
        ]
        duration = float(ls_row["duration"].iloc[0]) if len(ls_row) else 0.0
        segment_id = int(ls_row["segment_id"].iloc[0]) if len(ls_row) else -1

        records.append({
            "segment_id":   segment_id,
            "match_id":     int(match_id),
            "player_id":    int(player_id),
            "segment_idx":  int(seg_idx),
            "duration":     duration,
            "position_count": n,
            "snapped_seq":  snapped_seq,
            "unique_nodes": unique_nodes,
            "jitter_ratio": jitter_ratio,
            "min_wool_dist": min_wool_dist,
            "span_m":       span_m,
            "has_wool_event": has_wool,
        })

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Heuristic selection
# ---------------------------------------------------------------------------

def _select_representative_segments(metrics: pd.DataFrame) -> dict[str, dict]:
    """Pick one candidate per category using heuristic scoring.

    Categories
    ----------
    deep_attacker
        Minimum Dijkstra distance to any wool node across snapped sequence.
    defender
        Longest duration segment with low unique-node count (≤ Q25 of unique_nodes)
        and not a wool toucher (likely staying near home).
    jitter
        Highest ratio of consecutive repeated snapped nodes.
    traversal
        Maximum first→last Euclidean span.

    Returns
    -------
    dict mapping category label → row dict from metrics DataFrame.
    """
    if metrics.empty:
        return {}

    selected: dict[str, dict] = {}

    # 1. Deep attacker — closest snapped approach to a wool node
    finite_wool = metrics[metrics["min_wool_dist"] < float("inf")]
    if not finite_wool.empty:
        row = finite_wool.loc[finite_wool["min_wool_dist"].idxmin()]
        selected["deep_attacker"] = row.to_dict()

    # 2. Defender — long segment, low unique-node count, no wool touch
    uniq_q25 = metrics["unique_nodes"].quantile(0.25)
    defender_pool = metrics[
        (metrics["unique_nodes"] <= max(uniq_q25, 3))
        & (~metrics["has_wool_event"])
        & (metrics["duration"] > 0)
    ]
    if not defender_pool.empty:
        row = defender_pool.loc[defender_pool["duration"].idxmax()]
        selected["defender"] = row.to_dict()
    else:
        # Fallback: just longest low-unique segment
        low_unique = metrics[metrics["unique_nodes"] <= max(uniq_q25, 3)]
        if not low_unique.empty:
            row = low_unique.loc[low_unique["duration"].idxmax()]
            selected["defender"] = row.to_dict()

    # 3. Jitter — highest consecutive-repeat ratio (min 8 positions so it's meaningful)
    jitter_pool = metrics[metrics["position_count"] >= 8]
    if not jitter_pool.empty:
        row = jitter_pool.loc[jitter_pool["jitter_ratio"].idxmax()]
        selected["jitter"] = row.to_dict()

    # 4. Long traversal — maximum first→last Euclidean span
    row = metrics.loc[metrics["span_m"].idxmax()]
    selected["traversal"] = row.to_dict()

    return selected


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run(map_slug: str, output_root: Path) -> None:
    output_dir  = output_root / map_slug
    diag_dir    = output_dir / "traffic_graph_diagnostics"
    diag_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== Traffic graph diagnostics for '{map_slug}' ===\n")

    # ── Load data ─────────────────────────────────────────────────────────
    print("Loading traffic graph …")
    graph       = _load_traffic_graph_data(output_dir)
    topology    = build_traffic_topology(graph)
    node_info   = topology["node_info"]
    G_full      = topology["full_graph"]
    dijkstra    = topology["dijkstra_dists"]

    map_context = _load_map_context(output_dir)

    conn = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        print("Loading positions and life segment metadata …")
        positions_all  = _load_all_positions(conn, map_slug)
        life_segments  = _load_life_segments(conn, map_slug)
        wool_events    = _load_wool_events(conn, map_slug)
    finally:
        conn.close()

    print(f"  {len(life_segments)} life segments, {len(positions_all)} position events\n")

    # ── Full-map traffic graph overview ───────────────────────────────────
    overview_path = diag_dir / "traffic_graph_overview.png"
    print(f"Plotting traffic graph overview → {overview_path}")
    plot_traffic_graph(graph, map_context, overview_path)

    # ── Compute per-segment metrics ───────────────────────────────────────
    print("Computing snapping metrics for all segments …")
    metrics = _compute_segment_metrics(
        positions_all, life_segments, node_info, dijkstra, wool_events
    )
    print(f"  {len(metrics)} segments with ≥ 4 positions\n")

    # ── Select representative segments ────────────────────────────────────
    selections = _select_representative_segments(metrics)
    if not selections:
        print("ERROR: No representative segments found.")
        return

    print("Selected segments:")
    for label, meta in selections.items():
        print(
            f"  {label:20s}  segment_id={meta['segment_id']}  "
            f"player={meta['player_id']}  seg={meta['segment_idx']}  "
            f"duration={meta['duration']:.0f}s  "
            f"positions={meta['position_count']}  "
            f"unique_nodes={meta['unique_nodes']}  "
            f"jitter={meta['jitter_ratio']:.2f}"
        )
    print()

    # ── Generate diagnostic figures ───────────────────────────────────────
    for label, meta in selections.items():
        match_id    = meta["match_id"]
        player_id   = meta["player_id"]
        seg_idx     = meta["segment_idx"]
        segment_id  = meta["segment_id"]
        snapped_seq = meta["snapped_seq"]

        # Fetch positions for this segment
        seg_pos = positions_all[
            (positions_all["match_id"]     == match_id)
            & (positions_all["player_id"]  == player_id)
            & (positions_all["segment_idx"] == seg_idx)
        ].sort_values("timestamp").reset_index(drop=True)

        # Reconstruct path (shortest)
        recon_path = reconstruct_full_path(snapped_seq, G_full, mode="shortest")

        # Simplified sequence
        simplified = simplify_sequence(snapped_seq, method="consecutive_dedup")

        out_path = diag_dir / f"life_{segment_id}_{label}.png"
        print(f"Plotting [{label}] → {out_path}")

        plot_life_segment_diagnostic(
            map_slug=map_slug,
            match_id=match_id,
            player_id=player_id,
            segment_idx=seg_idx,
            positions_df=seg_pos[["x", "z", "timestamp"]],
            snapped_sequence=snapped_seq,
            node_info=node_info,
            G_full=G_full,
            reconstructed_path=recon_path,
            simplified_sequence=simplified,
            map_context=map_context,
            has_wool_event=meta["has_wool_event"],
            label=label,
            simplification_method="consecutive_dedup",
            output_path=out_path,
        )

    print("\nDone. Output directory:")
    for p in sorted(diag_dir.iterdir()):
        size_kb = p.stat().st_size // 1024
        print(f"  {p.name}  ({size_kb} KB)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--map", required=True, metavar="MAP_SLUG",
                   help="Map slug (e.g. tumbleweed)")
    p.add_argument("--output", default="output/", metavar="OUTPUT_ROOT",
                   help="Root output directory (default: output/)")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run(args.map, Path(args.output))
