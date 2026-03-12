"""Build wool_carry_chains: coordinated carry-attempt waves per wool."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb as _duckdb

from match_analysis.processing._helpers import (
    CARRY_WAVE_GAP_S,
    SKYBRIDGE_Y_THRESHOLD,
)


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
    from match_analysis.database.schema import _ensure_wool_carry_chains_table
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
    match_duration_s = float(match_dur[0]) if match_dur else None  # noqa: F841

    # --- group events by wool_id -------------------------------------------
    by_wool: dict[int, list[tuple]] = defaultdict(list)
    for row in we_rows:
        wool_id = row[3]
        by_wool[wool_id].append(row)

    inserted = 0
    for wool_id, events in by_wool.items():
        touches  = [e for e in events if e[1] == 6]   # event_type 6
        captures = {e[0] for e in events if e[1] == 7}  # timestamps of captures

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

            # Was there a capture event at or after the first touch?
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
                # Check if last carrier died after the wave started
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
