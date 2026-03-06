"""Post-processing layer for match analysis.

Runs after match processing is complete and reads from the already-populated
database to produce life_segment_features for clustering.

Tables produced:
  - wool_spawn_baselines        (once per map)
  - life_segment_region_visits  (once per match)
  - life_segment_features       (once per match)
  - wool_carry_chains           (once per match)
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb as _duckdb

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------
MIN_VISIT_TICKS = 1           # minimum consecutive ticks to count as a visit
ATTACK_DEPTH_CLAMP_MAX = 1.0  # clamp ceiling for normalised attack depth

# Y-level thresholds for skybridge detection.
# A player at Y >= SKYBRIDGE_Y_THRESHOLD is considered to be on or near the
# skybridge (built at max_build_height).  Values from ~22 upward are elevated.
SKYBRIDGE_Y_THRESHOLD = 22

# Maximum gap in seconds between consecutive wool touches of the same wool
# before we treat them as separate carry attempts ("waves").
CARRY_WAVE_GAP_S = 120

# location_type values written by the position classifier
_LOC_ISLAND = 'island'
_LOC_BUILD = 'build_region'
_LOC_VOID = 'void'

_MAP_CONTEXT_CANDIDATES = [
    Path('output'),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _map_context_path(map_slug: str) -> Path:
    """Return path to map_context.json for the given map_slug."""
    return Path('output') / map_slug / 'map_context.json'


def _load_map_context(map_slug: str) -> dict:
    path = _map_context_path(map_slug)
    if not path.exists():
        raise FileNotFoundError(
            f"map_context.json not found at {path}. "
            f"Run 'ctw run --map <folder>' first."
        )
    with open(path) as f:
        return json.load(f)


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
        gid = n['map_node_id']
        isl_id = n['island_id']
        local_id = n['local_node_id']
        degree = local_degree.get((isl_id, local_id), 1)
        lookup[gid] = {
            'type': n.get('node_type', 'endpoint'),
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


def _euclidean_2d(x1: float, z1: float, x2: float, z2: float) -> float:
    return math.sqrt((x2 - x1) ** 2 + (z2 - z1) ** 2)


def _normalize_team(team: str) -> str:
    """Normalize team name to short form: 'red-team' -> 'red'."""
    return team.removesuffix('-team')


def _get_map_slug(conn: '_duckdb.DuckDBPyConnection', match_id: int) -> str:
    row = conn.execute(
        "SELECT m.map_slug FROM matches mat "
        "JOIN maps m ON mat.map_id = m.map_id "
        "WHERE mat.match_id = ?",
        [match_id],
    ).fetchone()
    if row is None:
        raise ValueError(f"Match {match_id} not found in database")
    return row[0]


def _get_map_id(conn: '_duckdb.DuckDBPyConnection', match_id: int) -> int:
    row = conn.execute(
        "SELECT map_id FROM matches WHERE match_id = ?", [match_id]
    ).fetchone()
    if row is None:
        raise ValueError(f"Match {match_id} not found in database")
    return row[0]


def _assign_wool_ids(wools: list[dict]) -> list[dict]:
    """Return wools with a synthetic 1-based integer wool_id assigned by list position."""
    result = []
    for idx, w in enumerate(wools):
        w2 = dict(w)
        w2['wool_id'] = idx + 1
        result.append(w2)
    return result


# ---------------------------------------------------------------------------
# 1. wool_spawn_baselines
# ---------------------------------------------------------------------------

def populate_wool_spawn_baselines(
    conn: '_duckdb.DuckDBPyConnection',
    map_slug: str,
) -> None:
    """Read map_context.json for map_slug and insert into wool_spawn_baselines.

    Idempotent — deletes existing rows for the map before inserting.
    Baselines are computed from each team's spawn centre to each wool that
    team must capture (wool.team == player_team → those are the enemy wools
    the player needs to go get).
    """
    map_row = conn.execute(
        "SELECT map_id FROM maps WHERE map_slug = ?", [map_slug]
    ).fetchone()
    if map_row is None:
        raise ValueError(f"Map '{map_slug}' not found in maps table")
    map_id = map_row[0]

    ctx = _load_map_context(map_slug)
    wools = _assign_wool_ids(ctx.get('poi_assignments', {}).get('wools', []))
    spawns = ctx.get('poi_assignments', {}).get('spawns', [])

    # Build spawn lookup: normalized_team -> (spawn_x, spawn_z)
    spawn_by_team: dict[str, tuple[float, float]] = {
        _normalize_team(sp['team']): (float(sp['x']), float(sp['z']))
        for sp in spawns
    }

    # Delete existing rows for this map (idempotent)
    conn.execute(
        "DELETE FROM wool_spawn_baselines WHERE map_id = ?", [map_id]
    )

    rows_inserted = 0
    for wool in wools:
        wool_team = _normalize_team(wool['team'])  # normalized team name
        wool_x = float(wool['x'])
        wool_z = float(wool['z'])
        wool_id = wool['wool_id']

        if wool_team not in spawn_by_team:
            continue

        spawn_x, spawn_z = spawn_by_team[wool_team]
        dist = _euclidean_2d(spawn_x, spawn_z, wool_x, wool_z)

        conn.execute(
            """
            INSERT INTO wool_spawn_baselines
                (map_id, team, wool_id, spawn_x, spawn_z, wool_x, wool_z,
                 baseline_distance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [map_id, wool_team, wool_id, spawn_x, spawn_z,
             wool_x, wool_z, dist],
        )
        rows_inserted += 1

    print(f"  wool_spawn_baselines: inserted {rows_inserted} rows for {map_slug}")


# ---------------------------------------------------------------------------
# 2. life_segment_region_visits
# ---------------------------------------------------------------------------

def _region_key(row: tuple) -> tuple:
    """Return the region-identity key for a position row.

    row = (timestamp, location_type, island_id, nearest_island_1, nearest_island_2)
    """
    loc = row[1]
    if loc == _LOC_ISLAND:
        return (_LOC_ISLAND, row[2], None, None)
    elif loc == _LOC_BUILD:
        i1 = row[3]
        i2 = row[4]
        # Canonical order so (A,B) == (B,A)
        if i1 is not None and i2 is not None and i1 > i2:
            i1, i2 = i2, i1
        return (_LOC_BUILD, None, i1, i2)
    else:
        return (_LOC_VOID, None, None, None)


def _run_length_encode(rows: list[tuple]) -> list[dict]:
    """RLE non-void position rows into visits.

    Each input row: (timestamp, location_type, island_id,
                     nearest_island_1, nearest_island_2, nearest_graph_node)
    Returns list of dicts with keys:
        location_type, island_id, bridge_island_1, bridge_island_2,
        entry_timestamp, exit_timestamp, ticks,
        entry_node, exit_node, node_path
    """
    visits: list[dict] = []
    if not rows:
        return visits

    current_key = _region_key(rows[0])
    visit_start_ts = rows[0][0]
    visit_end_ts = rows[0][0]
    tick_count = 1
    # Accumulate deduplicated nearest_graph_node sequence for this run
    node_seq: list[int] = []
    first_ngn = rows[0][5] if len(rows[0]) > 5 else None
    if first_ngn is not None:
        node_seq.append(first_ngn)

    for row in rows[1:]:
        key = _region_key(row)
        ts = row[0]
        ngn = row[5] if len(row) > 5 else None
        if key == current_key:
            visit_end_ts = ts
            tick_count += 1
            # Append to node_seq only when node changes
            if ngn is not None and (not node_seq or node_seq[-1] != ngn):
                node_seq.append(ngn)
        else:
            if tick_count >= MIN_VISIT_TICKS:
                visits.append(_make_visit(current_key, visit_start_ts, visit_end_ts, tick_count, list(node_seq)))
            current_key = key
            visit_start_ts = ts
            visit_end_ts = ts
            tick_count = 1
            node_seq = [ngn] if ngn is not None else []

    # flush last run
    if tick_count >= MIN_VISIT_TICKS:
        visits.append(_make_visit(current_key, visit_start_ts, visit_end_ts, tick_count, list(node_seq)))

    # Second pass: annotate build_region visits with bridge_node_1/2 from adjacent island visits
    _annotate_bridge_nodes(visits)

    return visits


def _make_visit(key: tuple, entry_ts: int, exit_ts: int, ticks: int, node_seq: list[int]) -> dict:
    loc, island_id, bi1, bi2 = key
    entry_node = node_seq[0] if node_seq else None
    exit_node = node_seq[-1] if node_seq else None
    return {
        'location_type': loc,
        'island_id': island_id,
        'bridge_island_1': bi1,
        'bridge_island_2': bi2,
        'entry_timestamp': entry_ts,
        'exit_timestamp': exit_ts,
        'duration_s': float(exit_ts - entry_ts),
        'ticks': ticks,
        'entry_node': entry_node,
        'exit_node': exit_node,
        'node_path': node_seq,
    }


def _annotate_bridge_nodes(visits: list[dict]) -> None:
    """In-place: set bridge_node_1/2 for build_region visits from adjacent island visits."""
    for i, visit in enumerate(visits):
        if visit['location_type'] != _LOC_BUILD:
            continue
        bridge_node_1 = None
        bridge_node_2 = None
        # bridge_node_1: exit_node of the nearest preceding island visit
        for j in range(i - 1, -1, -1):
            if visits[j]['location_type'] == _LOC_ISLAND and visits[j]['exit_node'] is not None:
                bridge_node_1 = visits[j]['exit_node']
                break
        # bridge_node_2: entry_node of the nearest succeeding island visit
        for j in range(i + 1, len(visits)):
            if visits[j]['location_type'] == _LOC_ISLAND and visits[j]['entry_node'] is not None:
                bridge_node_2 = visits[j]['entry_node']
                break
        visit['bridge_node_1'] = bridge_node_1
        visit['bridge_node_2'] = bridge_node_2


def build_region_visits(
    conn: '_duckdb.DuckDBPyConnection',
    match_id: int,
) -> None:
    """Build life_segment_region_visits for all life segments in a match.

    Idempotent — deletes existing rows for the match before inserting.
    """
    map_slug = _get_map_slug(conn, match_id)
    ctx = _load_map_context(map_slug)

    # Build island → normalized-team lookup from map context
    island_team: dict[int, str] = {
        isl['id']: _normalize_team(isl.get('team', ''))
        for isl in ctx.get('islands', [])
    }

    # Fetch all life segments for this match
    segments = conn.execute(
        """
        SELECT segment_id, player_id, segment_idx, spawn_x, spawn_z, outcome
        FROM life_segments
        WHERE match_id = ?
        ORDER BY segment_id
        """,
        [match_id],
    ).fetchall()

    # Fetch all team membership for this match keyed by player_id
    team_rows = conn.execute(
        """
        SELECT player_id, team, start_timestamp, end_timestamp, spawn_x, spawn_z
        FROM player_team_segments
        WHERE match_id = ?
        """,
        [match_id],
    ).fetchall()
    # List of (player_id, team, start_ts, end_ts, sx, sz)
    team_segments_by_player: dict[int, list[tuple]] = {}
    for tr in team_rows:
        pid = int(tr[0])
        team_segments_by_player.setdefault(pid, []).append(tr)

    # Fetch all combat kills for this match (for kill_count per visit)
    kill_rows = conn.execute(
        """
        SELECT player_id, timestamp, segment_idx
        FROM combat_events
        WHERE match_id = ? AND event_type = 3
        ORDER BY player_id, timestamp
        """,
        [match_id],
    ).fetchall()
    # Group by (player_id, segment_idx) -> sorted list of timestamps
    kills_by_seg: dict[tuple[int, int], list[int]] = {}
    for kr in kill_rows:
        pid, ts, sidx = int(kr[0]), int(kr[1]), kr[2]
        if sidx is None:
            continue
        key = (pid, int(sidx))
        kills_by_seg.setdefault(key, []).append(ts)

    # Spawns: normalized team -> home island_id (from map_context)
    spawn_island_by_team: dict[str, int] = {
        _normalize_team(sp['team']): sp['island_id']
        for sp in ctx.get('poi_assignments', {}).get('spawns', [])
    }

    # Delete existing rows for this match
    conn.execute(
        "DELETE FROM life_segment_region_visits WHERE match_id = ?",
        [match_id],
    )

    total_visits = 0
    for seg_row in segments:
        segment_id = int(seg_row[0])
        player_id = int(seg_row[1])
        segment_idx = int(seg_row[2])
        # spawn_x, spawn_z = seg_row[3], seg_row[4]
        outcome = seg_row[5]

        # Fetch non-void position ticks for this segment
        pos_rows = conn.execute(
            """
            SELECT timestamp, location_type, island_id,
                   nearest_island_1, nearest_island_2, nearest_graph_node
            FROM position_events
            WHERE match_id = ? AND player_id = ? AND segment_idx = ?
              AND location_type != ?
            ORDER BY timestamp
            """,
            [match_id, player_id, segment_idx, _LOC_VOID],
        ).fetchall()

        if not pos_rows:
            continue

        visits = _run_length_encode(pos_rows)
        if not visits:
            continue

        # Determine player team at entry of each visit, and classify islands
        last_visit_idx = len(visits) - 1
        kills_for_seg = kills_by_seg.get((player_id, segment_idx), [])

        for visit_idx, visit in enumerate(visits):
            entry_ts = visit['entry_timestamp']
            exit_ts = visit['exit_timestamp']
            loc = visit['location_type']
            v_island_id = visit['island_id']

            # Resolve player team at entry_timestamp
            player_team = _resolve_team(
                player_id, entry_ts, team_segments_by_player
            )

            # Classify home / enemy island
            is_home: bool | None = None
            is_enemy: bool | None = None
            if loc == _LOC_ISLAND and v_island_id is not None:
                home_island_id = (
                    spawn_island_by_team.get(player_team)
                    if player_team else None
                )
                is_home = v_island_id == home_island_id
                # Enemy island = island belongs to a different team than player
                isl_team = island_team.get(v_island_id)
                is_enemy = (
                    isl_team is not None
                    and player_team is not None
                    and isl_team != player_team
                )

            # Count kills within this visit's time window
            visit_kills = sum(
                1 for ts in kills_for_seg
                if entry_ts <= ts <= exit_ts
            )

            # was_death: last visit of a life that ended in death
            was_death = (visit_idx == last_visit_idx and outcome == 'death')

            node_path_json = json.dumps(visit['node_path']) if visit.get('node_path') else None
            conn.execute(
                """
                INSERT INTO life_segment_region_visits (
                    segment_id, match_id, player_id, visit_idx,
                    location_type, island_id, bridge_island_1, bridge_island_2,
                    entry_timestamp, exit_timestamp, duration_s,
                    is_home_island, is_enemy_island, kill_count, was_death,
                    entry_node, exit_node, bridge_node_1, bridge_node_2, node_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    segment_id, match_id, player_id, visit_idx,
                    loc, v_island_id,
                    visit['bridge_island_1'], visit['bridge_island_2'],
                    entry_ts, exit_ts, visit['duration_s'],
                    is_home, is_enemy, visit_kills, was_death,
                    visit.get('entry_node'), visit.get('exit_node'),
                    visit.get('bridge_node_1'), visit.get('bridge_node_2'),
                    node_path_json,
                ],
            )
            total_visits += 1

    print(f"  life_segment_region_visits: inserted {total_visits} rows for match {match_id}")


def _resolve_team(
    player_id: int,
    timestamp: int,
    team_segments: dict[int, list[tuple]],
) -> str | None:
    """Return the team for player_id at the given timestamp."""
    segs = team_segments.get(player_id, [])
    best_team = None
    for seg in segs:
        _, team, start_ts, end_ts, _sx, _sz = seg
        start_ts = int(start_ts)
        end_ts_val = int(end_ts) if end_ts is not None else None
        if start_ts <= timestamp:
            if end_ts_val is None or timestamp <= end_ts_val:
                return team
            # Keep track of last known team in case we fall off the end
            best_team = team
    return best_team


# ---------------------------------------------------------------------------
# 3. life_segment_features
# ---------------------------------------------------------------------------

def build_life_features(
    conn: '_duckdb.DuckDBPyConnection',
    match_id: int,
) -> None:
    """Build life_segment_features for all life segments in a match.

    Idempotent — deletes existing rows for the match before inserting.
    Requires wool_spawn_baselines and life_segment_region_visits to be
    already populated.
    """
    map_slug = _get_map_slug(conn, match_id)
    map_id = _get_map_id(conn, match_id)
    ctx = _load_map_context(map_slug)
    map_graph = _load_map_graph(map_slug)
    node_lookup = _build_node_lookup(map_graph)
    wools = _assign_wool_ids(ctx.get('poi_assignments', {}).get('wools', []))

    # Team → list of enemy wools (wool that team must capture)
    # wool.team == the team that needs to capture it; normalize to short form
    # So enemy wools for a player on team T = wools where wool['team'] == T
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
    # Load all at once, grouped by (player_id, segment_idx)
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
        DELETE FROM life_segment_features
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
        player_id = int(player_id)
        segment_idx = int(segment_idx)
        start_ts = int(start_ts)
        end_ts = int(end_ts)
        kills = int(kills) if kills is not None else 0
        wool_touches = int(wool_touches) if wool_touches is not None else 0
        wool_captures = int(wool_captures) if wool_captures is not None else 0
        deaths = 1 if outcome == 'death' else 0

        seg_pos = pos_by_seg.get((player_id, segment_idx), [])

        # Resolve player team at segment start
        player_team = _resolve_team(
            player_id, start_ts, team_segments_by_player
        )

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
        dur_home = 0.0
        dur_enemy = 0.0
        dur_neutral_island = 0.0
        dur_build = 0.0
        total_dur = 0.0

        kill_in_build = 0
        kill_on_enemy_island = 0
        first_departure_ts: int | None = None
        ended_on_enemy = False
        ended_in_build = False

        # --- Node-path metrics ---
        island_visits_total = 0
        island_visits_with_junction = 0
        max_degree_visited = 0
        traversal_count = 0
        total_unique_node_path_len = 0
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
                    dur_enemy += dur or 0.0
                    kill_on_enemy_island += vkills or 0
                else:
                    dur_neutral_island += dur or 0.0
                # First departure = first visit that is NOT home island
                if not is_home and first_departure_ts is None:
                    first_departure_ts = ent_ts

                # --- Node-path analysis for island visits ---
                island_visits_total += 1

                node_path: list[int] = (
                    json.loads(node_path_json) if node_path_json else []
                )
                # Unique ordered nodes (preserves traversal order, collapses repeats)
                seen: set[int] = set()
                unique_nodes: list[int] = []
                for n in node_path:
                    if n not in seen:
                        seen.add(n)
                        unique_nodes.append(n)

                # Junction presence
                has_junction = any(
                    node_lookup.get(n, {}).get('degree', 1) >= 3
                    for n in unique_nodes
                )
                if has_junction:
                    island_visits_with_junction += 1

                # Max degree across all nodes touched in this life
                for n in unique_nodes:
                    d = node_lookup.get(n, {}).get('degree', 1)
                    if d > max_degree_visited:
                        max_degree_visited = d

                # Traversal: player moved across enough ground to shift closest node
                if (entry_node is not None
                        and exit_node is not None
                        and entry_node != exit_node):
                    traversal_count += 1

                # Path length (unique nodes touched in this visit)
                total_unique_node_path_len += len(unique_nodes)

                # Position entropy: count every node appearance (not just unique)
                for n in node_path:
                    all_node_counts[n] += 1

                # Death position: was the final node an endpoint or junction?
                if vdeath and exit_node is not None:
                    exit_info = node_lookup.get(exit_node, {})
                    died_at_endpoint = (exit_info.get('type', 'endpoint') == 'endpoint')

            elif loc == _LOC_BUILD:
                dur_build += dur or 0.0
                kill_in_build += vkills or 0
                if bi1 is not None and bi2 is not None:
                    build_pairs_visited.add((min(bi1, bi2), max(bi1, bi2)))
                # First departure if we leave the build region into something non-home
                if first_departure_ts is None:
                    first_departure_ts = ent_ts

                # Node-level corridor tracking (8x more granular than island pairs)
                if bridge_node_1 is not None and bridge_node_2 is not None:
                    corridor = (
                        min(bridge_node_1, bridge_node_2),
                        max(bridge_node_1, bridge_node_2),
                    )
                    unique_corridors.add(corridor)

        n_transitions = len(visit_rows)

        # --- Aggregate node-path metrics ---
        visited_junction = max_degree_visited >= 3
        frac_visits_with_junction = (
            island_visits_with_junction / island_visits_total
            if island_visits_total > 0 else 0.0
        )
        traversal_rate = (
            traversal_count / island_visits_total
            if island_visits_total > 0 else 0.0
        )
        avg_nodes_per_island_visit = (
            total_unique_node_path_len / island_visits_total
            if island_visits_total > 0 else 0.0
        )
        position_entropy = _shannon_entropy(all_node_counts)
        total_node_visits = sum(all_node_counts.values())
        dominant_node_frac = (
            max(all_node_counts.values()) / total_node_visits
            if total_node_visits > 0 else 1.0
        )
        n_unique_corridors = len(unique_corridors)

        # --- Progression ---
        last_visit = visit_rows[-1] if visit_rows else None
        if last_visit is not None:
            last_loc = last_visit[1]
            last_is_enemy = last_visit[9]
            ended_on_enemy = bool(last_is_enemy)
            ended_in_build = last_loc == _LOC_BUILD

        # --- Time fractions ---
        life_dur = float(end_ts - start_ts)
        # Use total_dur (non-void active time) for fractions if positive
        denom = total_dur if total_dur > 0 else life_dur if life_dur > 0 else 1.0
        frac_home = dur_home / denom
        frac_enemy = dur_enemy / denom
        frac_neutral = dur_neutral_island / denom
        frac_build = dur_build / denom

        # --- Attack depth ---
        max_depth, target_wool_id = _compute_attack_depth(
            seg_pos, player_team, wool_by_team, baselines
        )

        # --- Tempo ---
        time_to_first_dep = (
            float(first_departure_ts - start_ts)
            if first_departure_ts is not None else None
        )

        conn.execute(
            """
            INSERT INTO life_segment_features (
                segment_id,
                n_islands_visited, n_build_regions_visited, n_transitions,
                frac_time_home_island, frac_time_enemy_island,
                frac_time_neutral_island, frac_time_build,
                max_attack_depth, target_wool_id,
                ended_on_enemy_island, ended_in_build,
                duration_s, time_to_first_departure_s,
                kills, deaths, kill_in_build, kill_on_enemy_island,
                wool_touches, wool_captures,
                visited_junction, frac_island_visits_with_junction,
                max_node_degree_visited, traversal_rate,
                avg_nodes_per_island_visit, died_at_endpoint,
                n_unique_corridors, position_entropy, dominant_node_frac
            ) VALUES (
                ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?
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
                visited_junction, frac_visits_with_junction,
                max_degree_visited, traversal_rate,
                avg_nodes_per_island_visit, died_at_endpoint,
                n_unique_corridors, position_entropy, dominant_node_frac,
            ],
        )
        total += 1

    print(f"  life_segment_features: inserted {total} rows for match {match_id}")


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
            wool_id = wool['wool_id']
            baseline = baselines.get((player_team, wool_id))
            if baseline is None or baseline == 0:
                continue
            dist = _euclidean_2d(px, pz, float(wool['x']), float(wool['z']))
            depth = 1.0 - dist / baseline
            depth = min(depth, ATTACK_DEPTH_CLAMP_MAX)
            depth = max(depth, 0.0)
            if depth > max_depth:
                max_depth = depth
                target_wool_id = wool_id

    return max_depth, target_wool_id


# ---------------------------------------------------------------------------
# Step 4 — Y-level features per life segment
# ---------------------------------------------------------------------------

def build_y_features(
    conn: '_duckdb.DuckDBPyConnection',
    match_id: int,
) -> None:
    """Populate y_avg, y_max, frac_time_elevated in life_segment_features.

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
            UPDATE life_segment_features
            SET y_avg = ?, y_max = ?, frac_time_elevated = ?
            WHERE segment_id = ?
        """, [result[0], result[1], result[2], seg_id])
        updated += 1

    print(f"  life_segment_features (Y): updated {updated} rows for match {match_id}")


# ---------------------------------------------------------------------------
# Step 5 — Wool carry chain reconstruction
# ---------------------------------------------------------------------------

def build_wool_carry_chains(
    conn: '_duckdb.DuckDBPyConnection',
    match_id: int,
) -> None:
    """Reconstruct wool carry chains from wool_events and combat_events.

    Each "chain" (wave) covers one coordinated carry attempt per wool:
    from the first touch in a burst through either capture, void-death loss,
    or the end of the match.  A new wave starts when more than
    CARRY_WAVE_GAP_S seconds pass without any touch of that wool_id.

    Idempotent — deletes existing rows for the match before inserting.
    """
    from match_analysis.initialize_analysis_db import _ensure_wool_carry_chains_table
    _ensure_wool_carry_chains_table(conn)

    conn.execute("DELETE FROM wool_carry_chains WHERE match_id = ?", [match_id])

    # --- load wool events ---------------------------------------------------
    we_rows = conn.execute("""
        SELECT we.timestamp, we.event_type, we.player_id,
               we.wool_id, we.x, we.y, we.z, pts.team
        FROM wool_events we
        LEFT JOIN player_team_segments pts
            ON  pts.player_id  = we.player_id
            AND pts.match_id   = we.match_id
            AND pts.start_timestamp <= we.timestamp
            AND (pts.end_timestamp IS NULL OR pts.end_timestamp >= we.timestamp)
        WHERE we.match_id = ?
        ORDER BY we.wool_id, we.timestamp
    """, [match_id]).fetchall()

    # --- load deaths for void-loss detection --------------------------------
    death_rows = conn.execute("""
        SELECT timestamp, player_id, y
        FROM combat_events
        WHERE match_id = ? AND event_type = 4
        ORDER BY timestamp
    """, [match_id]).fetchall()
    # {player_id: sorted list of (timestamp, y)}
    deaths_by_player: dict[int, list[tuple]] = {}
    for ts, pid, y in death_rows:
        deaths_by_player.setdefault(pid, []).append((ts, y))

    # --- load match duration for 'incomplete' detection ---------------------
    match_dur = conn.execute(
        "SELECT match_duration FROM matches WHERE match_id = ?", [match_id]
    ).fetchone()
    match_duration_s = float(match_dur[0]) if match_dur else None

    # --- group events by wool_id -------------------------------------------
    from collections import defaultdict
    by_wool: dict[int, list[tuple]] = defaultdict(list)
    for row in we_rows:
        wool_id = row[3]
        by_wool[wool_id].append(row)

    inserted = 0
    for wool_id, events in by_wool.items():
        touches   = [e for e in events if e[1] == 6]  # event_type 6
        captures  = {e[0] for e in events if e[1] == 7}  # timestamps of captures

        if not touches:
            continue

        # --- split touches into waves (gap > CARRY_WAVE_GAP_S) ------------
        waves: list[list[tuple]] = []
        current_wave: list[tuple] = []
        for touch in touches:
            if not current_wave:
                current_wave.append(touch)
            elif touch[0] - current_wave[-1][0] <= CARRY_WAVE_GAP_S:
                current_wave.append(touch)
            else:
                waves.append(current_wave)
                current_wave = [touch]
        if current_wave:
            waves.append(current_wave)

        for wave_idx, wave in enumerate(waves):
            first = wave[0]
            last  = wave[-1]

            # carriers in order (deduplicated run-length to count handoffs)
            carriers: list[int] = []
            for t in wave:
                if not carriers or t[2] != carriers[-1]:
                    carriers.append(t[2])
            n_handoffs = len(carriers) - 1
            n_carriers = len(set(carriers))
            attacking_team = first[7]  # team of first carrier

            start_ts = first[0]
            first_x, first_y, first_z = first[4], first[5], first[6]
            final_x, final_y, final_z = last[4], last[5], last[6]

            # max Y of the first carrier in the 60s window before first touch
            carrier_deaths = deaths_by_player.get(first[2], [])
            pre_touch_y = conn.execute("""
                SELECT MAX(y)
                FROM position_events
                WHERE match_id = ? AND player_id = ?
                  AND timestamp BETWEEN ? AND ?
            """, [match_id, first[2], max(0, start_ts - 60), start_ts]).fetchone()
            max_y_before = int(pre_touch_y[0]) if pre_touch_y and pre_touch_y[0] is not None else None
            approach_type = None
            if max_y_before is not None:
                approach_type = 'skybridge' if max_y_before >= SKYBRIDGE_Y_THRESHOLD else 'ground'

            # Determine outcome
            outcome = 'incomplete'
            end_ts = last[0]

            # Was there a capture event shortly after the last touch?
            wave_end_cap = min(
                (c for c in captures if c >= start_ts),
                default=None,
            )
            if wave_end_cap is not None:
                outcome = 'captured'
                end_ts = wave_end_cap
                final_x_cap = conn.execute(
                    "SELECT x, y, z FROM wool_events "
                    "WHERE match_id = ? AND event_type = 7 AND timestamp = ? AND wool_id = ?",
                    [match_id, wave_end_cap, wool_id]
                ).fetchone()
                if final_x_cap:
                    final_x, final_y, final_z = final_x_cap
            else:
                # Check if last carrier died in void
                last_carrier = carriers[-1]
                for d_ts, d_y in deaths_by_player.get(last_carrier, []):
                    if d_ts >= start_ts:
                        end_ts = d_ts
                        outcome = 'dropped_void' if d_y < 0 else 'dropped_land'
                        break

            duration_s = float(end_ts - start_ts) if end_ts else None

            conn.execute("""
                INSERT INTO wool_carry_chains (
                    match_id, wool_id, wave_idx,
                    attacking_team, n_carriers, n_handoffs,
                    start_timestamp, end_timestamp, duration_s, outcome,
                    first_x, first_y, first_z,
                    final_x, final_y, final_z,
                    max_y_before_touch, approach_type
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, [
                match_id, wool_id, wave_idx,
                attacking_team, n_carriers, n_handoffs,
                start_ts, end_ts, duration_s, outcome,
                first_x, first_y, first_z,
                final_x, final_y, final_z,
                max_y_before, approach_type,
            ])
            inserted += 1

    print(f"  wool_carry_chains: inserted {inserted} rows for match {match_id}")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_post_processing(
    conn: '_duckdb.DuckDBPyConnection',
    match_id: int,
) -> None:
    """Run all post-processing steps for a match in order.

    Steps:
      0. Schema migrations (node-path columns, Y columns, carry-chains table)
      1. populate_wool_spawn_baselines  (idempotent, per-map)
      2. build_region_visits            (per-match)
      3. build_life_features            (per-match)
      4. build_y_features               (per-match)
      5. build_wool_carry_chains        (per-match)
    """
    from match_analysis.initialize_analysis_db import (
        migrate_node_path_columns,
        migrate_y_columns,
    )

    map_slug = _get_map_slug(conn, match_id)
    print(f"Post-processing match {match_id} (map: {map_slug})")

    print("Step 0/5: migrate schema columns if needed")
    migrate_node_path_columns()
    migrate_y_columns()

    print("Step 1/5: wool spawn baselines")
    populate_wool_spawn_baselines(conn, map_slug)

    print("Step 2/5: region visits")
    build_region_visits(conn, match_id)

    print("Step 3/5: life segment features")
    build_life_features(conn, match_id)

    print("Step 4/5: Y-level features")
    build_y_features(conn, match_id)

    print("Step 5/5: wool carry chains")
    build_wool_carry_chains(conn, match_id)

    print(f"Post-processing complete for match {match_id}")
