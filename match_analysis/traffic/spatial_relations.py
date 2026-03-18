"""Compute and persist vector-based spatial relations between teams/wools.

For each team, the attack direction is the vector from spawn centroid to map
center.  Cross/dot products of that vector against a POI-relative-to-spawn
vector give a coordinate-system-agnostic signed classification:

    cross > 0  → POI is to the LEFT  of the attack axis
    cross < 0  → POI is to the RIGHT of the attack axis
    dot   > 0  → POI is FORWARD  (toward the enemy side)
    dot   < 0  → POI is BEHIND   (toward own side)

This works correctly for mirror_x, mirror_z, rot_180, and any team count.

Two tables are populated:
    map_wool_attack_relations  — one row per (map, attacking_team, wool)
    map_team_spatial           — one row per (map, from_team, to_team)
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger("ctw")

# ±5° dead-band around the attack axis before a POI is called on-axis
_ANGLE_THRESHOLD_DEG = 5.0


def _classify(angle_deg: float, dot_val: float) -> tuple[str, str]:
    """Return (relative_side, relative_depth) from angle and dot value."""
    if angle_deg > _ANGLE_THRESHOLD_DEG:
        side = "left"
    elif angle_deg < -_ANGLE_THRESHOLD_DEG:
        side = "right"
    else:
        side = "on_axis"

    if dot_val > 0:
        depth = "forward"
    elif dot_val < 0:
        depth = "behind"
    else:
        depth = "on_axis"

    return side, depth


def _vector_stats(
    ax: float, az: float,           # attack vector components
    sx: float, sz: float,           # spawn centroid
    px: float, pz: float,           # POI position
) -> dict[str, float]:
    """Compute cross, dot, distance, and angle for a POI from an attack vector.

    Minecraft's XZ plane is left-handed (Z increases southward, like screen
    coordinates), which inverts the standard right-handed cross product sign.
    We use ``cross_val = A.z * W.x - A.x * W.z`` so that:
        cross_val > 0  →  POI is to the LEFT  of the attack axis
        cross_val < 0  →  POI is to the RIGHT of the attack axis
    consistent with Minecraft facing conventions:
        facing +Z (South): left = +X (East),  right = -X (West)
        facing -Z (North): left = -X (West),  right = +X (East)
    """
    wrx = px - sx
    wrz = pz - sz
    cross_val = az * wrx - ax * wrz   # Minecraft left-handed XZ convention
    dot_val   = ax * wrx + az * wrz
    distance  = math.sqrt(wrx * wrx + wrz * wrz)
    angle_deg = math.degrees(math.atan2(cross_val, dot_val))
    return {
        "cross_val": cross_val,
        "dot_val":   dot_val,
        "distance":  distance,
        "angle_deg": angle_deg,
    }


def compute_wool_attack_relations(
    conn: Any,
    map_slug: str,
) -> list[dict]:
    """Return rows for map_wool_attack_relations for *map_slug*.

    One row per (attacking_team, wool_id) where attacking_team != defending_team.

    Data sources (all from DB):
        maps         → center_x, center_z, map_id
        map_spawns   → x, z, team  (mean centroid per team)
        map_wool_locations → x, z, wool_id, wool_color, team
    """
    meta = conn.execute(
        "SELECT map_id, center_x, center_z FROM maps WHERE map_slug = ?",
        [map_slug],
    ).fetchone()
    if meta is None:
        logger.warning("compute_wool_attack_relations: map '%s' not in maps table", map_slug)
        return []
    map_id, cx, cz = meta

    # Mean spawn centroid per team
    spawn_rows = conn.execute(
        "SELECT team, AVG(x) AS sx, AVG(z) AS sz "
        "FROM map_spawns WHERE map_id = ? GROUP BY team",
        [map_id],
    ).fetchall()
    if not spawn_rows:
        logger.warning(
            "compute_wool_attack_relations: no spawn data for '%s' (map_id=%d)",
            map_slug, map_id,
        )
        return []
    spawns = {row[0]: (row[1], row[2]) for row in spawn_rows}  # team → (sx, sz)

    # Wool locations — position and color only
    wool_rows = conn.execute(
        "SELECT wool_id, wool_color, x, z "
        "FROM map_wool_locations WHERE map_id = ?",
        [map_id],
    ).fetchall()
    if not wool_rows:
        logger.warning(
            "compute_wool_attack_relations: no wool_locations for '%s' (map_id=%d)",
            map_slug, map_id,
        )
        return []

    # Wool objectives: wool_id → set of capturing teams.
    # Primary source: map_wool_objectives (populated by update-wool-locations).
    # Fallback: nearest-spawn heuristic if objectives table is empty for this map.
    obj_rows = conn.execute(
        "SELECT wool_id, team FROM map_wool_objectives WHERE map_id = ?",
        [map_id],
    ).fetchall()
    wool_objectives: dict[int, set[str]] = {}
    for wid, team in obj_rows:
        wool_objectives.setdefault(int(wid), set()).add(team)

    all_teams = set(spawns.keys())

    def _nearest_spawn(wx: float, wz: float) -> str:
        return min(
            spawns,
            key=lambda t: (spawns[t][0] - wx) ** 2 + (spawns[t][1] - wz) ** 2,
        )

    def _defending_team(wool_id: int, wx: float, wz: float) -> str | None:
        """Return the defending team for a wool, using objectives data when
        available and falling back to nearest spawn otherwise."""
        capturing = wool_objectives.get(wool_id)
        if capturing:
            defenders = all_teams - capturing
            if len(defenders) == 1:
                return defenders.pop()
            # Multiple or zero defenders — fall through to heuristic
        return _nearest_spawn(wx, wz)

    results: list[dict] = []
    for attacking_team, (sx, sz) in spawns.items():
        ax = cx - sx
        az = cz - sz

        for wool_id, wool_color, wx, wz in wool_rows:
            wool_id = int(wool_id)
            capturing = wool_objectives.get(wool_id)
            if capturing:
                # Objectives data available: skip if not this team's objective
                if attacking_team not in capturing:
                    continue
            else:
                # Fallback: skip if this team's own base (nearest spawn)
                if _nearest_spawn(wx, wz) == attacking_team:
                    continue

            defending_team = _defending_team(wool_id, wx, wz)

            stats = _vector_stats(ax, az, sx, sz, wx, wz)
            side, depth = _classify(stats["angle_deg"], stats["dot_val"])

            # Defending team's perspective: how do they see this wool relative
            # to their own spawn and attack axis?
            def_side: str | None = None
            def_angle: float | None = None
            if defending_team in spawns:
                dsx, dsz = spawns[defending_team]
                dax = cx - dsx
                daz = cz - dsz
                def_stats = _vector_stats(dax, daz, dsx, dsz, wx, wz)
                def_side, _ = _classify(def_stats["angle_deg"], def_stats["dot_val"])
                def_angle = def_stats["angle_deg"]

            results.append({
                "map_id":              map_id,
                "attacking_team":      attacking_team,
                "wool_id":             wool_id,
                "defending_team":      defending_team,
                "wool_color":          wool_color,
                "wool_x":              float(wx),
                "wool_z":              float(wz),
                "spawn_x":             float(sx),
                "spawn_z":             float(sz),
                "cross_val":           stats["cross_val"],
                "dot_val":             stats["dot_val"],
                "distance":            stats["distance"],
                "angle_deg":           stats["angle_deg"],
                "relative_side":       side,
                "relative_depth":      depth,
                "defending_side":      def_side,
                "defending_angle_deg": def_angle,
            })

    logger.debug(
        "compute_wool_attack_relations: '%s' → %d row(s) for %d team(s), %d wool(s)",
        map_slug, len(results), len(spawns), len(wool_rows),
    )
    return results


def compute_team_spatial(
    conn: Any,
    map_slug: str,
) -> list[dict]:
    """Return rows for map_team_spatial for *map_slug*.

    One row per (from_team, to_team) pair — both directions included.

    Data sources (all from DB):
        maps       → center_x, center_z, map_id
        map_spawns → x, z, team  (mean centroid per team)
    """
    meta = conn.execute(
        "SELECT map_id, center_x, center_z FROM maps WHERE map_slug = ?",
        [map_slug],
    ).fetchone()
    if meta is None:
        logger.warning("compute_team_spatial: map '%s' not in maps table", map_slug)
        return []
    map_id, cx, cz = meta

    spawn_rows = conn.execute(
        "SELECT team, AVG(x) AS sx, AVG(z) AS sz "
        "FROM map_spawns WHERE map_id = ? GROUP BY team",
        [map_id],
    ).fetchall()
    if not spawn_rows:
        logger.warning(
            "compute_team_spatial: no spawn data for '%s' (map_id=%d)", map_slug, map_id
        )
        return []
    spawns = {row[0]: (row[1], row[2]) for row in spawn_rows}

    results: list[dict] = []
    teams = list(spawns.keys())
    for from_team in teams:
        sx, sz = spawns[from_team]
        ax = cx - sx
        az = cz - sz

        for to_team in teams:
            if to_team == from_team:
                continue
            tx, tz = spawns[to_team]
            stats = _vector_stats(ax, az, sx, sz, tx, tz)
            side, depth = _classify(stats["angle_deg"], stats["dot_val"])

            results.append({
                "map_id":       map_id,
                "from_team":    from_team,
                "to_team":      to_team,
                "from_spawn_x": float(sx),
                "from_spawn_z": float(sz),
                "to_spawn_x":   float(tx),
                "to_spawn_z":   float(tz),
                "cross_val":    stats["cross_val"],
                "dot_val":      stats["dot_val"],
                "distance":     stats["distance"],
                "angle_deg":    stats["angle_deg"],
                "relative_side":  side,
                "relative_depth": depth,
            })

    logger.debug(
        "compute_team_spatial: '%s' → %d pair(s) for %d team(s)",
        map_slug, len(results), len(teams),
    )
    return results


def upsert_spatial_relations(
    conn: Any,
    map_slug: str,
    wool_rows: list[dict],
    team_rows: list[dict],
) -> None:
    """DELETE existing rows for *map_slug* then INSERT new rows.

    Both tables are cleared and repopulated atomically within the same
    connection (caller is responsible for commit if using explicit transactions).
    """
    map_id_row = conn.execute(
        "SELECT map_id FROM maps WHERE map_slug = ?", [map_slug]
    ).fetchone()
    if map_id_row is None:
        logger.warning("upsert_spatial_relations: map_slug '%s' not found", map_slug)
        return
    map_id = int(map_id_row[0])

    # ── map_wool_attack_relations ────────────────────────────────────────────
    conn.execute(
        "DELETE FROM map_wool_attack_relations WHERE map_id = ?", [map_id]
    )
    for row in wool_rows:
        conn.execute("""
            INSERT INTO map_wool_attack_relations (
                map_id, attacking_team, wool_id, defending_team,
                wool_color, wool_x, wool_z,
                spawn_x, spawn_z,
                cross_val, dot_val, distance, angle_deg,
                relative_side, relative_depth,
                defending_side, defending_angle_deg
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            map_id,
            row["attacking_team"],
            row["wool_id"],
            row.get("defending_team"),
            row["wool_color"],
            row["wool_x"],
            row["wool_z"],
            row["spawn_x"],
            row["spawn_z"],
            row["cross_val"],
            row["dot_val"],
            row["distance"],
            row["angle_deg"],
            row["relative_side"],
            row["relative_depth"],
            row.get("defending_side"),
            row.get("defending_angle_deg"),
        ])

    # ── map_team_spatial ─────────────────────────────────────────────────────
    conn.execute(
        "DELETE FROM map_team_spatial WHERE map_id = ?", [map_id]
    )
    for row in team_rows:
        conn.execute("""
            INSERT INTO map_team_spatial (
                map_id, from_team, to_team,
                from_spawn_x, from_spawn_z,
                to_spawn_x, to_spawn_z,
                cross_val, dot_val, distance, angle_deg,
                relative_side, relative_depth
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            map_id,
            row["from_team"],
            row["to_team"],
            row["from_spawn_x"],
            row["from_spawn_z"],
            row["to_spawn_x"],
            row["to_spawn_z"],
            row["cross_val"],
            row["dot_val"],
            row["distance"],
            row["angle_deg"],
            row["relative_side"],
            row["relative_depth"],
        ])

    logger.debug(
        "upsert_spatial_relations: '%s' → %d wool row(s), %d team pair(s)",
        map_slug, len(wool_rows), len(team_rows),
    )


def compute_and_upsert(
    conn_ro: Any,
    conn_rw: Any,
    map_slug: str,
) -> None:
    """Top-level entry point: compute spatial relations and upsert for *map_slug*.

    Parameters
    ----------
    conn_ro:
        Read-only DuckDB connection used for queries.
    conn_rw:
        Read-write DuckDB connection used for the upsert.
    map_slug:
        Map identifier (maps.map_slug).
    """
    wool_rows = compute_wool_attack_relations(conn_ro, map_slug)
    team_rows = compute_team_spatial(conn_ro, map_slug)
    upsert_spatial_relations(conn_rw, map_slug, wool_rows, team_rows)
