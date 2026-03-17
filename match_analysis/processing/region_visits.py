"""Build life_segment_region_visits: RLE position sequences into region visits."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb as _duckdb

from match_analysis.processing._helpers import (
    MIN_VISIT_TICKS,
    _LOC_ISLAND,
    _LOC_BUILD,
    _LOC_VOID,
    _get_map_slug,
    _load_map_context,
    _normalize_team,
    _resolve_team,
)


# ---------------------------------------------------------------------------
# Run-length encoding
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


def _make_visit(
    key: tuple, entry_ts: int, exit_ts: int, ticks: int, node_seq: list[int]
) -> dict:
    loc, island_id, bi1, bi2 = key
    entry_node = node_seq[0] if node_seq else None
    exit_node  = node_seq[-1] if node_seq else None
    return {
        'location_type':   loc,
        'island_id':       island_id,
        'bridge_island_1': bi1,
        'bridge_island_2': bi2,
        'entry_timestamp': entry_ts,
        'exit_timestamp':  exit_ts,
        'duration_s':      float(exit_ts - entry_ts),
        'ticks':           ticks,
        'entry_node':      entry_node,
        'exit_node':       exit_node,
        'node_path':       node_seq,
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

    current_key  = _region_key(rows[0])
    visit_start_ts = rows[0][0]
    visit_end_ts   = rows[0][0]
    tick_count   = 1
    node_seq: list[int] = []
    first_ngn = rows[0][5] if len(rows[0]) > 5 else None
    if first_ngn is not None:
        node_seq.append(first_ngn)

    for row in rows[1:]:
        key = _region_key(row)
        ts  = row[0]
        ngn = row[5] if len(row) > 5 else None
        if key == current_key:
            visit_end_ts = ts
            tick_count  += 1
            if ngn is not None and (not node_seq or node_seq[-1] != ngn):
                node_seq.append(ngn)
        else:
            if tick_count >= MIN_VISIT_TICKS:
                visits.append(_make_visit(
                    current_key, visit_start_ts, visit_end_ts,
                    tick_count, list(node_seq),
                ))
            current_key    = key
            visit_start_ts = ts
            visit_end_ts   = ts
            tick_count     = 1
            node_seq       = [ngn] if ngn is not None else []

    # flush last run
    if tick_count >= MIN_VISIT_TICKS:
        visits.append(_make_visit(
            current_key, visit_start_ts, visit_end_ts,
            tick_count, list(node_seq),
        ))

    _annotate_bridge_nodes(visits)
    return visits


# ---------------------------------------------------------------------------
# Public pipeline step
# ---------------------------------------------------------------------------

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

    # Fetch all non-void position events for the match in one query,
    # grouped by (player_id, segment_idx) in Python to avoid N per-segment queries.
    all_pos_rows = conn.execute(
        """
        SELECT player_id, segment_idx, timestamp, location_type, island_id,
               nearest_island_1, nearest_island_2, nearest_graph_node
        FROM position_events
        WHERE match_id = ?
          AND location_type != ?
        ORDER BY player_id, segment_idx, timestamp
        """,
        [match_id, _LOC_VOID],
    ).fetchall()

    pos_by_seg: dict[tuple[int, int], list[tuple]] = {}
    for row in all_pos_rows:
        key = (int(row[0]), int(row[1]))
        # Store only the columns expected by _run_length_encode:
        # (timestamp, location_type, island_id, nearest_island_1, nearest_island_2, nearest_graph_node)
        pos_by_seg.setdefault(key, []).append(row[2:])

    # Delete existing rows for this match
    conn.execute(
        "DELETE FROM life_segment_region_visits WHERE match_id = ?",
        [match_id],
    )

    all_records: list[list] = []
    for seg_row in segments:
        segment_id  = int(seg_row[0])
        player_id   = int(seg_row[1])
        segment_idx = int(seg_row[2])
        outcome     = seg_row[5]

        pos_rows = pos_by_seg.get((player_id, segment_idx), [])
        if not pos_rows:
            continue

        visits = _run_length_encode(pos_rows)
        if not visits:
            continue

        last_visit_idx = len(visits) - 1
        kills_for_seg  = kills_by_seg.get((player_id, segment_idx), [])

        for visit_idx, visit in enumerate(visits):
            entry_ts    = visit['entry_timestamp']
            exit_ts     = visit['exit_timestamp']
            loc         = visit['location_type']
            v_island_id = visit['island_id']

            player_team = _resolve_team(
                player_id, entry_ts, team_segments_by_player
            )

            is_home: bool | None = None
            is_enemy: bool | None = None
            if loc == _LOC_ISLAND and v_island_id is not None:
                home_island_id = (
                    spawn_island_by_team.get(player_team)
                    if player_team else None
                )
                is_home  = v_island_id == home_island_id
                isl_team = island_team.get(v_island_id)
                is_enemy = (
                    isl_team is not None
                    and player_team is not None
                    and isl_team != player_team
                )

            visit_kills = sum(
                1 for ts in kills_for_seg
                if entry_ts <= ts <= exit_ts
            )

            was_death = (visit_idx == last_visit_idx and outcome == 'death')

            node_path_json = json.dumps(visit['node_path']) if visit.get('node_path') else None
            all_records.append([
                segment_id, match_id, player_id, visit_idx,
                loc, v_island_id,
                visit['bridge_island_1'], visit['bridge_island_2'],
                entry_ts, exit_ts, visit['duration_s'],
                is_home, is_enemy, visit_kills, was_death,
                visit.get('entry_node'), visit.get('exit_node'),
                visit.get('bridge_node_1'), visit.get('bridge_node_2'),
                node_path_json,
            ])

    if all_records:
        conn.executemany(
            """
            INSERT INTO life_segment_region_visits (
                segment_id, match_id, player_id, visit_idx,
                location_type, island_id, bridge_island_1, bridge_island_2,
                entry_timestamp, exit_timestamp, duration_s,
                is_home_island, is_enemy_island, kill_count, was_death,
                entry_node, exit_node, bridge_node_1, bridge_node_2, node_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            all_records,
        )

    print(f"  life_segment_region_visits: inserted {len(all_records)} rows for match {match_id}")
