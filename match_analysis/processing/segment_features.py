"""Build life_segment_summary and life_segment_skeleton_features per life segment."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb as _duckdb

from match_analysis.processing._helpers import (
    ATTACK_DEPTH_CLAMP_MAX,
    SKYBRIDGE_Y_THRESHOLD,
    _LOC_ISLAND,
    _LOC_BUILD,
    _LOC_VOID,
    _get_map_slug,
    _get_map_id,
    _load_map_context,
    _normalize_team,
    _assign_wool_ids,
    _resolve_team,
    _euclidean_2d,
)


# ---------------------------------------------------------------------------
# Map graph helpers (used only by build_life_features)
# ---------------------------------------------------------------------------

def _load_map_graph(map_slug: str) -> dict:
    path = Path('output') / map_slug / 'map_graph.json'
    if not path.exists():
        raise FileNotFoundError(
            f"map_graph.json not found at {path}. "
            f"Run 'ctw run --map <folder>' first."
        )
    with open(path) as f:
        return json.load(f)


def _build_node_lookup(map_graph: dict) -> dict[int, dict]:
    """Build global map_node_id -> {'type': str, 'degree': int} from map_graph.json.

    Degree is stored only in the per-island skeleton nodes (keyed by local_node_id).
    The flat map_graph.nodes section carries global map_node_id and local_node_id,
    so we cross-reference to attach the degree to each global ID.
    """
    # Step 1: (island_id, local_node_id) -> degree from per-island skeleton
    local_degree: dict[tuple[int, int], int] = {}
    for isl in map_graph.get('islands', []):
        isl_id = isl['island_id']
        for n in isl['skeleton']['nodes']:
            local_degree[(isl_id, n['node_id'])] = n['degree']

    # Step 2: build global lookup
    lookup: dict[int, dict] = {}
    for n in map_graph.get('map_graph', {}).get('nodes', []):
        gid      = n['map_node_id']
        isl_id   = n['island_id']
        local_id = n['local_node_id']
        degree   = local_degree.get((isl_id, local_id), 1)
        lookup[gid] = {
            'type':   n.get('node_type', 'endpoint'),
            'degree': degree,
        }
    return lookup


def _shannon_entropy(counts: Counter) -> float:
    """Shannon entropy in bits from a Counter of node visit counts."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return -sum(
        (c / total) * math.log2(c / total)
        for c in counts.values()
        if c > 0
    )


# ---------------------------------------------------------------------------
# Feature-specific helpers
# ---------------------------------------------------------------------------

def _get_home_island_id(player_team: str, ctx: dict) -> int | None:
    """Return the island_id of the home spawn island for the given team."""
    for sp in ctx.get('poi_assignments', {}).get('spawns', []):
        if _normalize_team(sp['team']) == player_team:
            return sp.get('island_id')
    return None


def _compute_attack_depth(
    pos_rows: list[tuple],
    player_team: str | None,
    wool_by_team: dict[str, list[dict]],
    baselines: dict[tuple[str, int], float],
) -> tuple[float, int | None]:
    """Compute max attack depth over all non-void ticks and all enemy wools.

    Returns (max_depth, target_wool_id).
    """
    if not player_team or player_team not in wool_by_team:
        return 0.0, None

    enemy_wools = wool_by_team[player_team]
    if not enemy_wools:
        return 0.0, None

    max_depth = 0.0
    target_wool_id: int | None = None

    for pr in pos_rows:
        px = float(pr[3])
        pz = float(pr[4])

        for wool in enemy_wools:
            wool_id  = wool['wool_id']
            baseline = baselines.get((player_team, wool_id))
            if baseline is None or baseline == 0:
                continue
            dist  = _euclidean_2d(px, pz, float(wool['x']), float(wool['z']))
            depth = 1.0 - dist / baseline
            depth = min(depth, ATTACK_DEPTH_CLAMP_MAX)
            depth = max(depth, 0.0)
            if depth > max_depth:
                max_depth      = depth
                target_wool_id = wool_id

    return max_depth, target_wool_id


# ---------------------------------------------------------------------------
# Public pipeline steps
# ---------------------------------------------------------------------------

def build_life_features(
    conn: '_duckdb.DuckDBPyConnection',
    match_id: int,
) -> None:
    """Build life_segment_summary and life_segment_skeleton_features for all
    life segments in a match.

    Idempotent — deletes existing rows for the match before inserting.
    Requires wool_spawn_baselines and life_segment_region_visits to be
    already populated.
    """
    map_slug    = _get_map_slug(conn, match_id)
    map_id      = _get_map_id(conn, match_id)
    ctx         = _load_map_context(map_slug)
    map_graph   = _load_map_graph(map_slug)
    node_lookup = _build_node_lookup(map_graph)
    wools       = _assign_wool_ids(ctx.get('poi_assignments', {}).get('wools', []))

    # Team → list of enemy wools (wool that team must capture)
    wool_by_team: dict[str, list[dict]] = {}
    for w in wools:
        norm_team = _normalize_team(w['team'])
        w2 = dict(w)
        w2['team'] = norm_team
        wool_by_team.setdefault(norm_team, []).append(w2)

    # Baseline distances: (team, wool_id) -> baseline_distance
    baseline_rows = conn.execute(
        "SELECT team, wool_id, baseline_distance "
        "FROM wool_spawn_baselines WHERE map_id = ?",
        [map_id],
    ).fetchall()
    baselines: dict[tuple[str, int], float] = {
        (r[0], r[1]): r[2] for r in baseline_rows
    }

    # Fetch life segments
    seg_rows = conn.execute(
        """
        SELECT segment_id, player_id, segment_idx,
               start_timestamp, end_timestamp,
               kill_count, wool_touches, wool_captures, outcome
        FROM life_segments
        WHERE match_id = ?
        ORDER BY segment_id
        """,
        [match_id],
    ).fetchall()

    # Fetch team segments for team resolution
    team_rows = conn.execute(
        """
        SELECT player_id, team, start_timestamp, end_timestamp, spawn_x, spawn_z
        FROM player_team_segments
        WHERE match_id = ?
        """,
        [match_id],
    ).fetchall()
    team_segments_by_player: dict[int, list[tuple]] = {}
    for tr in team_rows:
        pid = int(tr[0])
        team_segments_by_player.setdefault(pid, []).append(tr)

    # Fetch non-void position events (for attack depth)
    pos_rows = conn.execute(
        """
        SELECT player_id, segment_idx, timestamp, x, z, location_type
        FROM position_events
        WHERE match_id = ? AND location_type != ?
        ORDER BY player_id, segment_idx, timestamp
        """,
        [match_id, _LOC_VOID],
    ).fetchall()
    pos_by_seg: dict[tuple[int, int], list[tuple]] = {}
    for pr in pos_rows:
        pid, sidx = int(pr[0]), pr[1]
        if sidx is None:
            continue
        pos_by_seg.setdefault((pid, int(sidx)), []).append(pr)

    # Delete existing rows for this match
    conn.execute(
        """
        DELETE FROM life_segment_summary
        WHERE segment_id IN (
            SELECT segment_id FROM life_segments WHERE match_id = ?
        )
        """,
        [match_id],
    )
    conn.execute(
        """
        DELETE FROM life_segment_skeleton_features
        WHERE segment_id IN (
            SELECT segment_id FROM life_segments WHERE match_id = ?
        )
        """,
        [match_id],
    )

    total = 0
    for seg_row in seg_rows:
        (segment_id, player_id, segment_idx,
         start_ts, end_ts,
         kills, wool_touches, wool_captures, outcome) = seg_row
        player_id   = int(player_id)
        segment_idx = int(segment_idx)
        start_ts    = int(start_ts)
        end_ts      = int(end_ts)
        kills         = int(kills)         if kills         is not None else 0
        wool_touches  = int(wool_touches)  if wool_touches  is not None else 0
        wool_captures = int(wool_captures) if wool_captures is not None else 0
        deaths = 1 if outcome == 'death' else 0

        seg_pos     = pos_by_seg.get((player_id, segment_idx), [])
        player_team = _resolve_team(player_id, start_ts, team_segments_by_player)

        # Fetch visits for this segment (includes node-path columns)
        visit_rows = conn.execute(
            """
            SELECT visit_idx, location_type, island_id,
                   bridge_island_1, bridge_island_2,
                   entry_timestamp, exit_timestamp, duration_s,
                   is_home_island, is_enemy_island, kill_count, was_death,
                   entry_node, exit_node, bridge_node_1, bridge_node_2, node_path
            FROM life_segment_region_visits
            WHERE segment_id = ?
            ORDER BY visit_idx
            """,
            [segment_id],
        ).fetchall()

        # --- Movement profile ---
        island_ids_visited: set[int] = set()
        build_pairs_visited: set[tuple] = set()
        dur_home = dur_enemy = dur_neutral_island = dur_build = total_dur = 0.0

        kill_in_build = kill_on_enemy_island = 0
        first_departure_ts: int | None = None
        ended_on_enemy = False

        # --- Node-path metrics ---
        island_visits_total = island_visits_with_junction = 0
        max_degree_visited  = traversal_count = total_unique_node_path_len = 0
        all_node_counts: Counter = Counter()
        unique_corridors: set[tuple] = set()
        died_at_endpoint: bool | None = None

        home_island_id = (
            _get_home_island_id(player_team, ctx)
            if player_team else None
        )

        for vr in visit_rows:
            (vidx, loc, v_isl, bi1, bi2, ent_ts, ex_ts, dur,
             is_home, is_enemy, vkills, vdeath,
             entry_node, exit_node, bridge_node_1, bridge_node_2,
             node_path_json) = vr
            total_dur += dur or 0.0

            if loc == _LOC_ISLAND and v_isl is not None:
                island_ids_visited.add(v_isl)
                if is_home:
                    dur_home += dur or 0.0
                elif is_enemy:
                    dur_enemy           += dur or 0.0
                    kill_on_enemy_island += vkills or 0
                else:
                    dur_neutral_island += dur or 0.0
                if not is_home and first_departure_ts is None:
                    first_departure_ts = ent_ts

                island_visits_total += 1
                node_path: list[int] = (
                    json.loads(node_path_json) if node_path_json else []
                )

                seen: set[int] = set()
                unique_nodes: list[int] = []
                for n in node_path:
                    if n not in seen:
                        seen.add(n)
                        unique_nodes.append(n)

                has_junction = any(
                    node_lookup.get(n, {}).get('degree', 1) >= 3
                    for n in unique_nodes
                )
                if has_junction:
                    island_visits_with_junction += 1

                for n in unique_nodes:
                    d = node_lookup.get(n, {}).get('degree', 1)
                    if d > max_degree_visited:
                        max_degree_visited = d

                if (entry_node is not None
                        and exit_node is not None
                        and entry_node != exit_node):
                    traversal_count += 1

                total_unique_node_path_len += len(unique_nodes)

                for n in node_path:
                    all_node_counts[n] += 1

                if vdeath and exit_node is not None:
                    exit_info = node_lookup.get(exit_node, {})
                    died_at_endpoint = (exit_info.get('type', 'endpoint') == 'endpoint')

            elif loc == _LOC_BUILD:
                dur_build    += dur or 0.0
                kill_in_build += vkills or 0
                if bi1 is not None and bi2 is not None:
                    build_pairs_visited.add((min(bi1, bi2), max(bi1, bi2)))
                if first_departure_ts is None:
                    first_departure_ts = ent_ts

                if bridge_node_1 is not None and bridge_node_2 is not None:
                    corridor = (
                        min(bridge_node_1, bridge_node_2),
                        max(bridge_node_1, bridge_node_2),
                    )
                    unique_corridors.add(corridor)

        n_transitions = len(visit_rows)

        # --- Aggregate node-path metrics ---
        visited_junction           = max_degree_visited >= 3
        frac_visits_with_junction  = (
            island_visits_with_junction / island_visits_total
            if island_visits_total > 0 else 0.0
        )
        traversal_rate             = (
            traversal_count / island_visits_total
            if island_visits_total > 0 else 0.0
        )
        avg_nodes_per_island_visit = (
            total_unique_node_path_len / island_visits_total
            if island_visits_total > 0 else 0.0
        )
        position_entropy     = _shannon_entropy(all_node_counts)
        total_node_visits    = sum(all_node_counts.values())
        dominant_node_frac   = (
            max(all_node_counts.values()) / total_node_visits
            if total_node_visits > 0 else 1.0
        )
        n_unique_corridors = len(unique_corridors)

        # --- Progression ---
        last_visit = visit_rows[-1] if visit_rows else None
        ended_on_enemy  = bool(last_visit[9]) if last_visit is not None else False
        ended_in_build  = (last_visit[1] == _LOC_BUILD) if last_visit is not None else False

        # --- Time fractions ---
        life_dur = float(end_ts - start_ts)
        denom    = total_dur if total_dur > 0 else life_dur if life_dur > 0 else 1.0
        frac_home    = dur_home           / denom
        frac_enemy   = dur_enemy          / denom
        frac_neutral = dur_neutral_island / denom
        frac_build   = dur_build          / denom

        # --- Attack depth ---
        max_depth, target_wool_id = _compute_attack_depth(
            seg_pos, player_team, wool_by_team, baselines
        )

        # --- Tempo ---
        time_to_first_dep = (
            float(first_departure_ts - start_ts)
            if first_departure_ts is not None else None
        )

        # Insert core facts into life_segment_summary
        conn.execute(
            """
            INSERT INTO life_segment_summary (
                segment_id,
                n_islands_visited, n_build_regions_visited, n_transitions,
                frac_time_home_island, frac_time_enemy_island,
                frac_time_neutral_island, frac_time_build,
                max_attack_depth, target_wool_id,
                ended_on_enemy_island, ended_in_build,
                duration_s, time_to_first_departure_s,
                kills, deaths, kill_in_build, kill_on_enemy_island,
                wool_touches, wool_captures
            ) VALUES (
                ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?, ?, ?,
                ?, ?
            )
            """,
            [
                segment_id,
                len(island_ids_visited), len(build_pairs_visited), n_transitions,
                frac_home, frac_enemy, frac_neutral, frac_build,
                max_depth, target_wool_id,
                ended_on_enemy, ended_in_build,
                life_dur, time_to_first_dep,
                kills, deaths, kill_in_build, kill_on_enemy_island,
                wool_touches, wool_captures,
            ],
        )

        # Insert skeleton node-path metrics into life_segment_skeleton_features
        conn.execute(
            """
            INSERT INTO life_segment_skeleton_features (
                segment_id,
                visited_junction, frac_island_visits_with_junction,
                max_node_degree_visited, traversal_rate,
                avg_nodes_per_island_visit, died_at_endpoint,
                n_unique_corridors, position_entropy, dominant_node_frac
            ) VALUES (
                ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                segment_id,
                visited_junction, frac_visits_with_junction,
                max_degree_visited, traversal_rate,
                avg_nodes_per_island_visit, died_at_endpoint,
                n_unique_corridors, position_entropy, dominant_node_frac,
            ],
        )
        total += 1

    print(f"  life_segment_summary + life_segment_skeleton_features: inserted {total} rows for match {match_id}")


def build_y_features(
    conn: '_duckdb.DuckDBPyConnection',
    match_id: int,
) -> None:
    """Populate y_avg, y_max, frac_time_elevated in life_segment_summary.

    Reads from position_events for each life segment and updates the row
    that was already inserted by build_life_features.  Idempotent.
    """
    rows = conn.execute("""
        SELECT ls.segment_id, ls.player_id, ls.start_timestamp, ls.end_timestamp
        FROM life_segments ls
        WHERE ls.match_id = ?
        ORDER BY ls.segment_id
    """, [match_id]).fetchall()

    updated = 0
    for seg_id, player_id, start_ts, end_ts in rows:
        result = conn.execute("""
            SELECT
                AVG(y)::FLOAT                                   AS y_avg,
                MAX(y)                                          AS y_max,
                AVG(CASE WHEN y >= ? THEN 1.0 ELSE 0.0 END)::FLOAT AS frac_elev
            FROM position_events
            WHERE match_id = ?
              AND player_id = ?
              AND timestamp BETWEEN ? AND ?
        """, [SKYBRIDGE_Y_THRESHOLD, match_id, player_id, start_ts, end_ts]).fetchone()

        if result is None or result[0] is None:
            continue

        conn.execute("""
            UPDATE life_segment_summary
            SET y_avg = ?, y_max = ?, frac_time_elevated = ?
            WHERE segment_id = ?
        """, [result[0], result[1], result[2], seg_id])
        updated += 1

    print(f"  life_segment_summary (Y): updated {updated} rows for match {match_id}")
