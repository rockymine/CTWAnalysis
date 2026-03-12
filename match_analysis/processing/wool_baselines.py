"""Compute and store wool spawn baseline distances (once per map)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb as _duckdb

from match_analysis.processing._helpers import (
    _load_map_context,
    _normalize_team,
    _assign_wool_ids,
    _euclidean_2d,
)


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
