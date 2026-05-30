"""Compute and store traffic-graph-based features for life segments.

For each life segment of a map, snaps the raw position sequence to the
traffic graph and computes scalar metrics that characterise the player's
movement relative to map objectives.

Table written: life_segment_traffic_features
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import duckdb as _duckdb

from match_analysis.traffic.graph import load_traffic_graph, build_traffic_topology
from match_analysis.traffic.snapping import snap_positions


def compute_match_set_hash(
    conn: '_duckdb.DuckDBPyConnection',
    map_id: int,
    log_interval: int = 2,
) -> str:
    """Return a stable hash of the processed 2s-interval match IDs for a map.

    Used to detect whether the traffic graph needs to be rebuilt after new
    matches have been processed.
    """
    rows = conn.execute(
        """
        SELECT match_id FROM matches
        WHERE map_id = ?
          AND processed = TRUE
          AND (log_interval = ? OR log_interval IS NULL)
        ORDER BY match_id
        """,
        [map_id, log_interval],
    ).fetchall()
    ids_str = ",".join(str(r[0]) for r in rows)
    return hashlib.md5(ids_str.encode()).hexdigest()


def _build_team_wool_lookup(node_info: dict) -> dict[str, list[int]]:
    """Map team name -> list of wool node_ids on that team's island."""
    result: dict[str, list[int]] = {}
    for nid, n in node_info.items():
        if n.get("poi_type") == "wool" and n.get("team"):
            result.setdefault(n["team"], []).append(nid)
    return result


def _nearest_spawn_team(
    spawn_x: float,
    spawn_z: float,
    node_info: dict,
) -> str | None:
    """Return the team of the spawn node closest to (spawn_x, spawn_z)."""
    best_team = None
    best_d = float("inf")
    for n in node_info.values():
        if n.get("poi_type") != "spawn":
            continue
        cx, cz = n["coords"]
        d = (cx - spawn_x) ** 2 + (cz - spawn_z) ** 2
        if d < best_d:
            best_d = d
            best_team = n.get("team")
    return best_team


def build_traffic_segment_features(
    map_slug: str,
    conn: '_duckdb.DuckDBPyConnection',
    graph_data: dict,
) -> int:
    """Snap all life segments for a map to the traffic graph and store features.

    Idempotent — deletes existing rows for the map before inserting.

    Parameters
    ----------
    map_slug:
        Map identifier used to look up position events and life segments.
    conn:
        Read-write DuckDB connection.
    graph_data:
        Parsed traffic_graph.json dict (from load_traffic_graph / save_traffic_graph).

    Returns
    -------
    Number of rows inserted into life_segment_traffic_features.
    """
    topology = build_traffic_topology(graph_data)
    node_info = topology["node_info"]
    dijkstra = topology["dijkstra_dists"]

    team_wool = _build_team_wool_lookup(node_info)
    all_wool_ids = [nid for nid, n in node_info.items() if n.get("poi_type") == "wool"]

    # Node coords for tortuosity computation
    node_coords: dict[int, tuple[float, float]] = {
        nid: (n["coords"][0], n["coords"][1]) for nid, n in node_info.items()
    }

    # Load all position events for the map (2s matches only, y>0)
    pos_df = conn.execute(
        """
        SELECT pe.match_id, pe.player_id, pe.segment_idx,
               pe.timestamp, pe.x, pe.z
        FROM position_events pe
        JOIN matches mat ON mat.match_id = pe.match_id
        JOIN maps m ON m.map_id = mat.map_id
        WHERE m.map_slug = ?
          AND pe.y > 0
          AND (mat.log_interval = 2 OR mat.log_interval IS NULL)
        ORDER BY pe.match_id, pe.player_id, pe.segment_idx, pe.timestamp
        """,
        [map_slug],
    ).df()

    if pos_df.empty:
        print(f"  No position data for '{map_slug}' — skipping traffic features.")
        return 0

    # Load life segment spawn positions for team resolution
    seg_df = conn.execute(
        """
        SELECT ls.segment_id, ls.match_id, ls.player_id, ls.segment_idx,
               ls.spawn_x, ls.spawn_z
        FROM life_segments ls
        JOIN matches mat ON mat.match_id = ls.match_id
        JOIN maps m ON m.map_id = mat.map_id
        WHERE m.map_slug = ?
        """,
        [map_slug],
    ).df()

    if seg_df.empty:
        print(f"  No life segments for '{map_slug}' — skipping traffic features.")
        return 0

    # Snap all positions at once (vectorised)
    all_snapped = snap_positions(
        pos_df["x"].to_numpy(),
        pos_df["z"].to_numpy(),
        node_info,
    )
    pos_df = pos_df.copy()
    pos_df["snapped_node"] = all_snapped

    # Build spawn lookup: (match_id, player_id, segment_idx) -> (spawn_x, spawn_z)
    spawn_lookup = {
        (int(r.match_id), int(r.player_id), int(r.segment_idx)): (
            float(r.spawn_x), float(r.spawn_z)
        )
        for r in seg_df.itertuples()
    }

    # Build segment_id lookup: (match_id, player_id, segment_idx) -> segment_id
    seg_id_lookup = {
        (int(r.match_id), int(r.player_id), int(r.segment_idx)): int(r.segment_id)
        for r in seg_df.itertuples()
    }

    # Delete existing rows for this map
    conn.execute(
        """
        DELETE FROM life_segment_traffic_features
        WHERE segment_id IN (
            SELECT ls.segment_id
            FROM life_segments ls
            JOIN matches mat ON mat.match_id = ls.match_id
            JOIN maps m ON m.map_id = mat.map_id
            WHERE m.map_slug = ?
        )
        """,
        [map_slug],
    )

    records = []
    min_positions = 4

    for (match_id, player_id, seg_idx), grp in pos_df.groupby(
        ["match_id", "player_id", "segment_idx"]
    ):
        if len(grp) < min_positions:
            continue

        grp = grp.sort_values("timestamp")
        xs = grp["x"].to_numpy(float)
        zs = grp["z"].to_numpy(float)
        snapped_seq: list[int] = grp["snapped_node"].tolist()

        key = (int(match_id), int(player_id), int(seg_idx))
        segment_id = seg_id_lookup.get(key)
        if segment_id is None:
            continue

        unique_nodes = len(set(snapped_seq))

        # Determine player team
        spawn_x, spawn_z = spawn_lookup.get(key, (xs[0], zs[0]))
        player_team = _nearest_spawn_team(spawn_x, spawn_z, node_info)

        home_wool_ids = team_wool.get(player_team, []) if player_team else []
        enemy_wool_ids = [w for w in all_wool_ids if w not in home_wool_ids]

        # Min Dijkstra distance to any enemy wool node
        if enemy_wool_ids and dijkstra:
            min_enemy_wool_dist = min(
                min(
                    dijkstra.get(w, {}).get(nid, float("inf"))
                    for w in enemy_wool_ids
                    if w in dijkstra
                )
                for nid in snapped_seq
            )
        else:
            min_enemy_wool_dist = float("inf")

        # Avg Dijkstra distance to home wool nodes
        if home_wool_ids and dijkstra:
            per_node = [
                min(
                    dijkstra.get(w, {}).get(nid, float("inf"))
                    for w in home_wool_ids
                    if w in dijkstra
                )
                for nid in snapped_seq
            ]
            finite = [d for d in per_node if d < float("inf")]
            avg_home_wool_dist = float(np.mean(finite)) if finite else float("inf")
        else:
            avg_home_wool_dist = float("inf")

        # Euclidean span (start → end)
        span_m = float(np.sqrt((xs[-1] - xs[0]) ** 2 + (zs[-1] - zs[0]) ** 2))

        # Tortuosity: total snapped-path length / span
        traj_len = sum(
            np.sqrt(
                (node_coords[a][0] - node_coords[b][0]) ** 2
                + (node_coords[a][1] - node_coords[b][1]) ** 2
            )
            for a, b in zip(snapped_seq, snapped_seq[1:])
            if a in node_coords and b in node_coords and a != b
        )
        tortuosity = traj_len / max(span_m, 1.0)

        # Clamp infinities to NULL-friendly sentinel for storage
        if min_enemy_wool_dist == float("inf"):
            min_enemy_wool_dist = None
        if avg_home_wool_dist == float("inf"):
            avg_home_wool_dist = None

        records.append((
            segment_id,
            json.dumps(snapped_seq),
            unique_nodes,
            min_enemy_wool_dist,
            avg_home_wool_dist,
            span_m,
            tortuosity,
        ))

    if not records:
        return 0

    conn.executemany(
        """
        INSERT INTO life_segment_traffic_features (
            segment_id, snapped_sequence, unique_nodes,
            min_enemy_wool_dist, avg_home_wool_dist, span_m, tortuosity
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        records,
    )

    return len(records)


# ---------------------------------------------------------------------------
# Per-match traffic features (new minimal schema: snapped_sequence,
# max_attack_depth, death_region)
# ---------------------------------------------------------------------------

def _normalize_team_local(team: str | None) -> str:
    """Normalize 'red-team' -> 'red'."""
    if not team:
        return ''
    return team.removesuffix('-team')


def _home_island_by_team(map_context: dict) -> dict[str, int | None]:
    """Return mapping of team -> home island_id from map_context.json."""
    result: dict[str, int | None] = {}
    for sp in map_context.get('poi_assignments', {}).get('spawns', []):
        team = _normalize_team_local(sp.get('team', ''))
        if team:
            result[team] = sp.get('island_id')
    return result


def _death_region(
    last_loc_type: str | None,
    last_island_id: int | None,
    player_team: str | None,
    home_by_team: dict[str, int | None],
) -> str:
    """Map last-position info to a death_region label."""
    if last_loc_type is None or last_loc_type == 'void':
        return 'void'
    if last_loc_type == 'build_region':
        return 'bridge'
    if last_loc_type == 'island' and last_island_id is not None:
        home_iid = home_by_team.get(player_team or '')
        if home_iid is not None and last_island_id == home_iid:
            return 'home_island'
        return 'enemy_island'
    return 'void'


def build_traffic_features_for_match(
    conn: '_duckdb.DuckDBPyConnection',
    match_id: int,
    graph_data: dict,
    map_context: dict,
) -> int:
    import pandas as _pd  # noqa: PLC0415
    """Snap all life segments for one match to the traffic graph and store features.

    Writes to life_segment_traffic_features with the minimal schema:
    (segment_id, snapped_sequence, max_attack_depth, death_region).

    Requires position_events to already have location_type / island_id populated
    (i.e. classify step must have run first).

    Idempotent — deletes existing rows for this match before inserting.

    Returns number of rows inserted.
    """
    topology  = build_traffic_topology(graph_data)
    node_info = topology["node_info"]
    dijkstra  = topology["dijkstra_dists"]

    team_wool    = _build_team_wool_lookup(node_info)
    all_wool_ids = [nid for nid, n in node_info.items() if n.get("poi_type") == "wool"]
    home_by_team = _home_island_by_team(map_context)

    # Load position events for this match (y > 0 only, spatial cols required)
    pos_df = conn.execute(
        """
        SELECT pe.player_id, pe.segment_idx,
               pe.timestamp, pe.x, pe.z,
               pe.location_type, pe.island_id
        FROM position_events pe
        WHERE pe.match_id = ?
          AND pe.y > 0
        ORDER BY pe.player_id, pe.segment_idx, pe.timestamp
        """,
        [match_id],
    ).df()

    if pos_df.empty:
        return 0

    # Snap all positions to the traffic graph
    all_snapped = snap_positions(
        pos_df["x"].to_numpy(),
        pos_df["z"].to_numpy(),
        node_info,
    )
    pos_df = pos_df.copy()
    pos_df["snapped_node"] = all_snapped

    # Load life segments with team info
    seg_df = conn.execute(
        """
        SELECT ls.segment_id, ls.player_id, ls.segment_idx,
               ls.start_timestamp, ls.end_timestamp,
               pts.team
        FROM life_segments ls
        LEFT JOIN player_team_segments pts
          ON pts.match_id = ls.match_id
          AND pts.player_id = ls.player_id
          AND ls.start_timestamp >= pts.start_timestamp
          AND (pts.end_timestamp IS NULL OR ls.start_timestamp <= pts.end_timestamp)
        WHERE ls.match_id = ?
        """,
        [match_id],
    ).df()

    if seg_df.empty:
        return 0

    seg_id_lookup: dict[tuple, int] = {
        (int(r.player_id), int(r.segment_idx)): int(r.segment_id)
        for r in seg_df.itertuples()
    }
    team_lookup: dict[tuple, str | None] = {
        (int(r.player_id), int(r.segment_idx)): _normalize_team_local(r.team)
        for r in seg_df.itertuples()
    }

    # Get last position per (player_id, segment_idx) for death_region
    last_pos_df = conn.execute(
        """
        SELECT player_id, segment_idx, location_type, island_id
        FROM position_events
        WHERE match_id = ?
          AND segment_idx IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY player_id, segment_idx ORDER BY timestamp DESC
        ) = 1
        """,
        [match_id],
    ).df()
    last_pos_lookup: dict[tuple, tuple] = {
        (int(r.player_id), int(r.segment_idx)): (r.location_type, r.island_id)
        for r in last_pos_df.itertuples()
    }

    # Delete existing rows for this match
    conn.execute(
        """
        DELETE FROM life_segment_traffic_features
        WHERE segment_id IN (
            SELECT segment_id FROM life_segments WHERE match_id = ?
        )
        """,
        [match_id],
    )

    records = []
    min_positions = 4

    for (player_id, seg_idx), grp in pos_df.groupby(["player_id", "segment_idx"]):
        if len(grp) < min_positions or seg_idx is None:
            continue

        grp = grp.sort_values("timestamp")
        snapped_seq: list[int] = grp["snapped_node"].tolist()

        key = (int(player_id), int(seg_idx))
        segment_id = seg_id_lookup.get(key)
        if segment_id is None:
            continue

        player_team = team_lookup.get(key)

        home_wool_ids  = team_wool.get(player_team, []) if player_team else []
        enemy_wool_ids = [w for w in all_wool_ids if w not in home_wool_ids]

        # max_attack_depth: min Dijkstra distance to any enemy wool
        max_attack_depth: float | None = None
        if enemy_wool_ids and dijkstra:
            min_dist = float("inf")
            for nid in snapped_seq:
                for w in enemy_wool_ids:
                    d = dijkstra.get(w, {}).get(nid, float("inf"))
                    if d < min_dist:
                        min_dist = d
            if min_dist < float("inf"):
                max_attack_depth = float(min_dist)

        # death_region: derived from last classified position event
        last_loc, last_iid = last_pos_lookup.get(key, (None, None))
        last_iid_int: int | None = None
        if last_iid is not None and not _pd.isna(last_iid):
            last_iid_int = int(last_iid)
        region = _death_region(last_loc, last_iid_int, player_team, home_by_team)

        records.append((
            segment_id,
            json.dumps(snapped_seq),
            max_attack_depth,
            region,
        ))

    if not records:
        return 0

    conn.executemany(
        """
        INSERT INTO life_segment_traffic_features (
            segment_id, snapped_sequence, max_attack_depth, death_region
        ) VALUES (?, ?, ?, ?)
        """,
        records,
    )

    return len(records)
