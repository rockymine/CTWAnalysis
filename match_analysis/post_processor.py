"""Post-processing layer for match analysis.

Runs after match processing is complete and reads from the already-populated
database to produce life_segment_features for clustering.

Tables produced:
  - wool_spawn_baselines        (once per map)
  - life_segment_region_visits  (once per match)
  - life_segment_features       (once per match)
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb as _duckdb

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------
MIN_VISIT_TICKS = 1           # minimum consecutive ticks to count as a visit
ATTACK_DEPTH_CLAMP_MAX = 1.0  # clamp ceiling for normalised attack depth

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
                     nearest_island_1, nearest_island_2)
    Returns list of dicts with keys:
        location_type, island_id, bridge_island_1, bridge_island_2,
        entry_timestamp, exit_timestamp, ticks
    """
    visits: list[dict] = []
    if not rows:
        return visits

    current_key = _region_key(rows[0])
    visit_start_ts = rows[0][0]
    visit_end_ts = rows[0][0]
    tick_count = 1

    for row in rows[1:]:
        key = _region_key(row)
        ts = row[0]
        if key == current_key:
            visit_end_ts = ts
            tick_count += 1
        else:
            if tick_count >= MIN_VISIT_TICKS:
                visits.append(_make_visit(current_key, visit_start_ts, visit_end_ts, tick_count))
            current_key = key
            visit_start_ts = ts
            visit_end_ts = ts
            tick_count = 1

    # flush last run
    if tick_count >= MIN_VISIT_TICKS:
        visits.append(_make_visit(current_key, visit_start_ts, visit_end_ts, tick_count))

    return visits


def _make_visit(key: tuple, entry_ts: int, exit_ts: int, ticks: int) -> dict:
    loc, island_id, bi1, bi2 = key
    return {
        'location_type': loc,
        'island_id': island_id,
        'bridge_island_1': bi1,
        'bridge_island_2': bi2,
        'entry_timestamp': entry_ts,
        'exit_timestamp': exit_ts,
        'duration_ms': float(exit_ts - entry_ts),
        'ticks': ticks,
    }


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
                   nearest_island_1, nearest_island_2
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

            conn.execute(
                """
                INSERT INTO life_segment_region_visits (
                    segment_id, match_id, player_id, visit_idx,
                    location_type, island_id, bridge_island_1, bridge_island_2,
                    entry_timestamp, exit_timestamp, duration_ms,
                    is_home_island, is_enemy_island, kill_count, was_death
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    segment_id, match_id, player_id, visit_idx,
                    loc, v_island_id,
                    visit['bridge_island_1'], visit['bridge_island_2'],
                    entry_ts, exit_ts, visit['duration_ms'],
                    is_home, is_enemy, visit_kills, was_death,
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

        # Fetch visits for this segment
        visit_rows = conn.execute(
            """
            SELECT visit_idx, location_type, island_id,
                   bridge_island_1, bridge_island_2,
                   entry_timestamp, exit_timestamp, duration_ms,
                   is_home_island, is_enemy_island, kill_count, was_death
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

        home_island_id = (
            _get_home_island_id(player_team, ctx)
            if player_team else None
        )

        for vr in visit_rows:
            (vidx, loc, v_isl, bi1, bi2, ent_ts, ex_ts, dur,
             is_home, is_enemy, vkills, vdeath) = vr
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
            elif loc == _LOC_BUILD:
                dur_build += dur or 0.0
                kill_in_build += vkills or 0
                if bi1 is not None and bi2 is not None:
                    build_pairs_visited.add((min(bi1, bi2), max(bi1, bi2)))
                # First departure if we leave the build region into something non-home
                if first_departure_ts is None:
                    first_departure_ts = ent_ts

        n_transitions = len(visit_rows)

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
                duration_ms, time_to_first_departure_ms,
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
# Orchestrator
# ---------------------------------------------------------------------------

def run_post_processing(
    conn: '_duckdb.DuckDBPyConnection',
    match_id: int,
) -> None:
    """Run all post-processing steps for a match in order.

    Steps:
      1. populate_wool_spawn_baselines  (idempotent, per-map)
      2. build_region_visits            (per-match)
      3. build_life_features            (per-match)
    """
    map_slug = _get_map_slug(conn, match_id)
    print(f"Post-processing match {match_id} (map: {map_slug})")

    print("Step 1/3: wool spawn baselines")
    populate_wool_spawn_baselines(conn, map_slug)

    print("Step 2/3: region visits")
    build_region_visits(conn, match_id)

    print("Step 3/3: life segment features")
    build_life_features(conn, match_id)

    print(f"Post-processing complete for match {match_id}")
