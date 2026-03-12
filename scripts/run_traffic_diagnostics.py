#!/usr/bin/env python3
"""Generate traffic-graph diagnostic images for one map.

Produces:
  1. A full-map traffic graph overview (reuses existing plot_traffic_graph).
  2. A 6-panel diagnostic figure for each of four representative life segments:
       - deep_attacker   (snapped closest to an ENEMY wool node)
       - defender        (player whose snapped nodes hug their HOME wool room)
       - roamer          (high unique-node count with high path tortuosity)
       - traversal       (maximum first->last Euclidean span)

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

from match_analysis.traffic.graph    import load_traffic_graph, build_traffic_topology, plot_traffic_graph
from match_analysis.traffic.snapping import (
    snap_positions,
    reconstruct_full_path,
    simplify_sequence,
)
from match_analysis.traffic.diagnostics_plot import plot_life_segment_diagnostic

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
               pe.timestamp, pe.x, pe.y, pe.z, pe.island_id
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


def _load_held_items_from_parquet(match_file: Path) -> pd.DataFrame:
    """Extract per-position held_item from raw parquet (event_type=5).

    Returns DataFrame with columns: player_id, timestamp, held_item (nullable Int64).
    """
    raw = pd.read_parquet(match_file)
    pos = raw[raw["event_type"] == 5][["player_id", "timestamp", "held_item"]].copy()
    pos["held_item"] = pos["held_item"].astype("Int64")
    return pos.reset_index(drop=True)


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

def _build_team_wool_lookup(node_info: dict[int, dict]) -> dict[str, list[int]]:
    """Map team name -> list of wool node_ids on that team's island.

    These are the wools that team *defends* (located on their own island).
    """
    result: dict[str, list[int]] = {}
    for nid, n in node_info.items():
        if n.get("poi_type") == "wool" and n.get("team"):
            team = n["team"]
            result.setdefault(team, []).append(nid)
    return result


def _nearest_spawn_team(
    spawn_x: float,
    spawn_z: float,
    node_info: dict[int, dict],
) -> str | None:
    """Return the team of the spawn node closest to (spawn_x, spawn_z)."""
    best_team = None
    best_d    = float("inf")
    for n in node_info.values():
        if n.get("poi_type") != "spawn":
            continue
        cx, cz = n["coords"]
        d = (cx - spawn_x) ** 2 + (cz - spawn_z) ** 2
        if d < best_d:
            best_d    = d
            best_team = n.get("team")
    return best_team


_BOW_IDS: frozenset[int] = frozenset({203})
_BRIDGE_IDS: frozenset[int] = frozenset({
    1, 4, 5, 12, 20, 24, 35, 85, 95, 101,
    159, 160, 171, 188, 189, 190, 191, 192,
})
_MELEE_IDS: frozenset[int] = frozenset({
    200, 209, 210, 213, 214, 217, 218, 221, 225, 228,
})
_TOOL_IDS: frozenset[int] = frozenset({
    198, 199, 211, 212, 215, 216, 219, 220,
})


def _compute_segment_metrics(
    positions_all: pd.DataFrame,
    life_segments: pd.DataFrame,
    node_info: dict[int, dict],
    dijkstra_dists: dict[int, dict[int, float]],
    wool_events: pd.DataFrame,
    held_items: pd.DataFrame | None = None,
    min_positions: int = 4,
) -> pd.DataFrame:
    """Snap all positions and compute heuristic metrics for each segment.

    Returns a DataFrame with one row per life_segment and columns:
        segment_id, match_id, player_id, segment_idx, duration,
        position_count, snapped_seq, unique_nodes,
        min_enemy_wool_dist, avg_home_wool_dist, span_m,
        tortuosity, has_wool_event, kill_count,
        avg_y, frac_elevated,
        frac_bow, frac_builder,
        held_item_series, positions_y
    """
    # Pre-build team -> home wool ids lookup
    team_wool = _build_team_wool_lookup(node_info)

    # Pre-build spawn lookup from life_segments
    spawn_lookup: dict[tuple, tuple[float, float]] = {
        (int(r.match_id), int(r.player_id), int(r.segment_idx)): (
            float(r.spawn_x), float(r.spawn_z)
        )
        for r in life_segments.itertuples()
    }

    # Attach held_item column from parquet (join on player_id + timestamp)
    if held_items is not None and not held_items.empty:
        positions_all = positions_all.merge(
            held_items[["player_id", "timestamp", "held_item"]],
            on=["player_id", "timestamp"],
            how="left",
        )
    else:
        positions_all = positions_all.copy()
        positions_all["held_item"] = pd.NA

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

    # Pre-extract node coords for trajectory-length computation
    node_coords: dict[int, tuple[float, float]] = {
        nid: (n["coords"][0], n["coords"][1]) for nid, n in node_info.items()
    }

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

        # Determine player team from closest spawn node to their recorded spawn position
        spawn_x, spawn_z = spawn_lookup.get(
            (int(match_id), int(player_id), int(seg_idx)), (xs[0], zs[0])
        )
        player_team = _nearest_spawn_team(spawn_x, spawn_z, node_info)

        # Home wools = wools on the player's OWN island (which they defend)
        home_wool_ids = team_wool.get(player_team, []) if player_team else []
        # Enemy wools = all other wool nodes
        all_wool_ids  = [
            nid for nid, nd in node_info.items() if nd.get("poi_type") == "wool"
        ]
        enemy_wool_ids = [w for w in all_wool_ids if w not in home_wool_ids]

        # Minimum Dijkstra distance to an ENEMY wool (deep attacker metric)
        if enemy_wool_ids and dijkstra_dists:
            min_enemy_wool_dist = min(
                min(
                    dijkstra_dists.get(w, {}).get(nid, float("inf"))
                    for w in enemy_wool_ids
                    if w in dijkstra_dists
                )
                for nid in snapped_seq
            )
        else:
            min_enemy_wool_dist = float("inf")

        # Average Dijkstra distance to HOME wools (defender metric)
        if home_wool_ids and dijkstra_dists:
            per_node_home_dists = [
                min(
                    dijkstra_dists.get(w, {}).get(nid, float("inf"))
                    for w in home_wool_ids
                    if w in dijkstra_dists
                )
                for nid in snapped_seq
            ]
            finite_home = [d for d in per_node_home_dists if d < float("inf")]
            avg_home_wool_dist = float(np.mean(finite_home)) if finite_home else float("inf")
        else:
            avg_home_wool_dist = float("inf")

        # Euclidean span: distance between first and last sample
        span_m = float(np.sqrt((xs[-1] - xs[0]) ** 2 + (zs[-1] - zs[0]) ** 2))

        # Tortuosity: total trajectory length (through snapped nodes) / span
        # High tortuosity means the player looped around rather than going straight.
        traj_len = sum(
            np.sqrt(
                (node_coords[a][0] - node_coords[b][0]) ** 2
                + (node_coords[a][1] - node_coords[b][1]) ** 2
            )
            for a, b in zip(snapped_seq, snapped_seq[1:])
            if a in node_coords and b in node_coords and a != b
        )
        tortuosity = traj_len / max(span_m, 1.0)

        has_wool = (int(match_id), int(player_id), int(seg_idx)) in wool_events_set

        # --- Elevation (y) metrics ---
        ys = grp["y"].to_numpy(float)
        avg_y        = float(np.mean(ys))
        frac_elevated = float(np.mean(ys >= 22))
        positions_y  = ys.tolist()

        # --- Held-item metrics (from parquet join) ---
        hi_raw = grp["held_item"].dropna()
        held_arr = hi_raw.to_numpy(dtype=int) if len(hi_raw) else np.array([], dtype=int)
        frac_bow     = float(np.isin(held_arr, list(_BOW_IDS)).mean())    if len(held_arr) else 0.0
        frac_builder = float(np.isin(held_arr, list(_BRIDGE_IDS)).mean()) if len(held_arr) else 0.0
        # Build held_item_series aligned to all positions (NA -> -1 sentinel)
        hi_full = grp["held_item"].to_numpy()
        held_item_series = [int(v) if v is not pd.NA and not (isinstance(v, float) and np.isnan(v)) else -1
                            for v in hi_full]

        # Look up duration from life_segments
        ls_row = life_segments[
            (life_segments["match_id"] == match_id)
            & (life_segments["player_id"] == player_id)
            & (life_segments["segment_idx"] == seg_idx)
        ]
        duration = float(ls_row["duration"].iloc[0]) if len(ls_row) else 0.0
        segment_id = int(ls_row["segment_id"].iloc[0]) if len(ls_row) else -1

        records.append({
            "segment_id":          segment_id,
            "match_id":            int(match_id),
            "player_id":           int(player_id),
            "segment_idx":         int(seg_idx),
            "duration":            duration,
            "position_count":      n,
            "kill_count":          int(ls_row["kill_count"].iloc[0]) if len(ls_row) else 0,
            "snapped_seq":         snapped_seq,
            "unique_nodes":        unique_nodes,
            "min_enemy_wool_dist": min_enemy_wool_dist,
            "avg_home_wool_dist":  avg_home_wool_dist,
            "span_m":              span_m,
            "tortuosity":          tortuosity,
            "has_wool_event":      has_wool,
            "avg_y":               avg_y,
            "frac_elevated":       frac_elevated,
            "frac_bow":            frac_bow,
            "frac_builder":        frac_builder,
            "held_item_series":    held_item_series,
            "positions_y":         positions_y,
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
        Closest snapped approach to an ENEMY wool node across the whole segment.

    defender
        Player whose snapped positions average the lowest Dijkstra distance to
        their HOME wool nodes (on their own island).  Must have >= 8 positions,
        no wool touch (not carrying), and not selected as deep_attacker.

    roamer
        High path tortuosity (total trajectory length / Euclidean span) combined
        with high unique-node count.  Captures players who cover lots of ground
        without moving in a straight line — pushing, retreating, looping.
        Requires span_m >= 40 blocks and unique_nodes >= 12.

    traversal
        Maximum first->last Euclidean span — the most sustained directional
        movement in a single life.

    Returns
    -------
    dict mapping category label -> row dict from metrics DataFrame.
    """
    if metrics.empty:
        return {}

    selected: dict[str, dict] = {}

    # 1. Deep attacker — closest approach to an enemy wool node
    finite_enemy = metrics[metrics["min_enemy_wool_dist"] < float("inf")]
    if not finite_enemy.empty:
        row = finite_enemy.loc[finite_enemy["min_enemy_wool_dist"].idxmin()]
        selected["deep_attacker"] = row.to_dict()
        attacker_id = (row["match_id"], row["player_id"], row["segment_idx"])
    else:
        attacker_id = None

    # 2. Defender — lowest average home-wool distance, no wool touch, >= 8 positions
    finite_home = metrics[
        (metrics["avg_home_wool_dist"] < float("inf"))
        & (~metrics["has_wool_event"])
        & (metrics["position_count"] >= 8)
    ]
    if not finite_home.empty:
        # Exclude the segment already chosen as deep_attacker
        if attacker_id:
            finite_home = finite_home[
                ~(
                    (finite_home["match_id"]    == attacker_id[0])
                    & (finite_home["player_id"] == attacker_id[1])
                    & (finite_home["segment_idx"] == attacker_id[2])
                )
            ]
        if not finite_home.empty:
            row = finite_home.loc[finite_home["avg_home_wool_dist"].idxmin()]
            selected["defender"] = row.to_dict()

    # 3. Roamer — high unique-node count AND high tortuosity, meaningful span
    roamer_pool = metrics[
        (metrics["span_m"] >= 40)
        & (metrics["unique_nodes"] >= 12)
    ]
    if not roamer_pool.empty:
        # Score = tortuosity × log(unique_nodes): rewards both qualities together
        roamer_pool = roamer_pool.copy()
        roamer_pool["roamer_score"] = (
            roamer_pool["tortuosity"] * np.log1p(roamer_pool["unique_nodes"])
        )
        row = roamer_pool.loc[roamer_pool["roamer_score"].idxmax()]
        selected["roamer"] = row.to_dict()

    # 4. Long traversal — maximum first->last Euclidean span
    row = metrics.loc[metrics["span_m"].idxmax()]
    selected["traversal"] = row.to_dict()

    # Helper: set of segment_ids already selected (to avoid duplicates)
    def _selected_ids() -> set[int]:
        return {v["segment_id"] for v in selected.values()}

    # 5. High killer — max kill_count in one life (>=4 positions)
    hk_pool = metrics[
        (metrics["position_count"] >= 4)
        & ~metrics["segment_id"].isin(_selected_ids())
    ]
    if not hk_pool.empty:
        row = hk_pool.loc[hk_pool["kill_count"].idxmax()]
        selected["high_killer"] = row.to_dict()

    # 6. Skybridge — most time at y>=22 (>=8 positions, span>=20 blocks)
    sky_pool = metrics[
        (metrics["position_count"] >= 8)
        & (metrics["span_m"] >= 20)
        & ~metrics["segment_id"].isin(_selected_ids())
    ]
    if not sky_pool.empty:
        row = sky_pool.loc[sky_pool["frac_elevated"].idxmax()]
        selected["skybridge"] = row.to_dict()

    # 7. Bow archer — highest bow-holding fraction (>=8 positions, frac_bow>0.1)
    bow_pool = metrics[
        (metrics["position_count"] >= 8)
        & (metrics["frac_bow"] > 0.1)
        & ~metrics["segment_id"].isin(_selected_ids())
    ]
    if not bow_pool.empty:
        row = bow_pool.loc[bow_pool["frac_bow"].idxmax()]
        selected["bow_archer"] = row.to_dict()

    # 8. Builder — highest bridge-block holding fraction (>=8 positions, frac_builder>0.1)
    builder_pool = metrics[
        (metrics["position_count"] >= 8)
        & (metrics["frac_builder"] > 0.1)
        & ~metrics["segment_id"].isin(_selected_ids())
    ]
    if not builder_pool.empty:
        row = builder_pool.loc[builder_pool["frac_builder"].idxmax()]
        selected["builder"] = row.to_dict()

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
    print("Loading traffic graph ...")
    graph       = _load_traffic_graph_data(output_dir)
    topology    = build_traffic_topology(graph)
    node_info   = topology["node_info"]
    G_full      = topology["full_graph"]
    dijkstra    = topology["dijkstra_dists"]
    grid_size   = float(graph.get("grid_size", 5.0))

    map_context = _load_map_context(output_dir)

    conn = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        print("Loading positions and life segment metadata ...")
        positions_all  = _load_all_positions(conn, map_slug)
        life_segments  = _load_life_segments(conn, map_slug)
        wool_events    = _load_wool_events(conn, map_slug)
        # Find match parquet file for held_item data
        match_file_rel = conn.execute(
            "SELECT match_file FROM matches LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    # Load held_item from raw parquet
    held_items: pd.DataFrame | None = None
    if match_file_rel:
        match_file_path = _PROJECT_ROOT / match_file_rel[0]
        if match_file_path.exists():
            print(f"Loading held_item data from parquet ...")
            held_items = _load_held_items_from_parquet(match_file_path)

    print(f"  {len(life_segments)} life segments, {len(positions_all)} position events\n")

    # ── Full-map traffic graph overview ───────────────────────────────────
    overview_path = diag_dir / "traffic_graph_overview.png"
    print(f"Plotting traffic graph overview -> {overview_path}")
    plot_traffic_graph(graph, map_context, overview_path)

    # ── Compute per-segment metrics ───────────────────────────────────────
    print("Computing snapping metrics for all segments ...")
    metrics = _compute_segment_metrics(
        positions_all, life_segments, node_info, dijkstra, wool_events,
        held_items=held_items,
    )
    print(f"  {len(metrics)} segments with >= 4 positions\n")

    # ── Select representative segments ────────────────────────────────────
    selections = _select_representative_segments(metrics)
    if not selections:
        print("ERROR: No representative segments found.")
        return

    print("Selected segments:")
    for label, meta in selections.items():
        extra = ""
        if label == "high_killer":
            extra = f"  kills={meta['kill_count']}"
        elif label == "skybridge":
            extra = f"  avg_y={meta['avg_y']:.1f}  frac_elevated={meta['frac_elevated']:.0%}"
        elif label == "bow_archer":
            extra = f"  frac_bow={meta['frac_bow']:.0%}"
        elif label == "builder":
            extra = f"  frac_builder={meta['frac_builder']:.0%}"
        print(
            f"  {label:20s}  segment_id={meta['segment_id']}  "
            f"player={meta['player_id']}  seg={meta['segment_idx']}  "
            f"duration={meta['duration']:.0f}s  "
            f"positions={meta['position_count']}  "
            f"unique_nodes={meta['unique_nodes']}  "
            f"span={meta['span_m']:.0f}m  "
            f"tortuosity={meta['tortuosity']:.2f}"
            + extra
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

        # Reconstruct path (dense-hop: penalises long edges with dist²/grid_size)
        recon_path = reconstruct_full_path(snapped_seq, G_full, mode="dense", grid_size=grid_size)

        # Simplified sequence
        simplified = simplify_sequence(snapped_seq, method="consecutive_dedup")

        out_path = diag_dir / f"life_{segment_id}_{label}.png"
        print(f"Plotting [{label}] -> {out_path}")

        # Determine which optional visual overlays to pass
        seg_held_items = meta.get("held_item_series") if label in ("bow_archer", "builder") else None
        seg_positions_y = meta.get("positions_y") if label == "skybridge" else None

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
            reconstruction_mode="dense",
            tortuosity=meta.get("tortuosity"),
            held_item_series=seg_held_items,
            positions_y=seg_positions_y,
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
