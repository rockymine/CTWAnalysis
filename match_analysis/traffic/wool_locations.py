"""Compute and persist verified wool chest locations and monument positions.

Wool chest locations are derived from first-touch events in the DB (event_type=6).
The first touch of a wool in a match always happens at the chest (wool room),
not en-route. Subsequent touches may happen anywhere on the map.

Monument positions are derived from capture events (event_type=7). Each capture
always fires at the exact monument block — stddev=0.0 per monument per team.

wool_id is the Minecraft wool damage value (0–15), which maps directly to color.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ctw")

WOOL_ID_TO_COLOR: dict[int, str] = {
    0: "white",      1: "orange",    2: "magenta",   3: "light_blue",
    4: "yellow",     5: "lime",      6: "pink",      7: "gray",
    8: "light_gray", 9: "cyan",     10: "purple",   11: "blue",
   12: "brown",     13: "green",    14: "red",       15: "black",
}

# Maximum Manhattan distance (blocks) between a first-touch and the cluster
# median for that first-touch to count as a confirmation of the wool location.
FIRST_TOUCH_CLUSTER_RADIUS = 2


_WOOL_COLOR_ALIASES: dict[str, str] = {
    # Old Minecraft names → current canonical names (as in WOOL_ID_TO_COLOR)
    "light blue":  "light_blue",
    "light gray":  "light_gray",
    "silver":      "light_gray",
}


def _normalize_wool_color(color: str) -> str:
    """Normalize a wool color string to the canonical underscore form."""
    normalized = color.strip().lower().replace(" ", "_")
    return _WOOL_COLOR_ALIASES.get(color.strip().lower(), normalized)


def _team_for_color(wool_color: str, map_context: dict) -> Optional[str]:
    """Return the owning team for *wool_color* from *map_context*, or None."""
    canonical = _normalize_wool_color(wool_color)
    for w in map_context.get("poi_assignments", {}).get("wools", []):
        stored = w.get("wool_color", "")
        if _normalize_wool_color(stored) == canonical:
            team = w.get("team")
            return team if team else None
    return None


def compute_wool_locations(
    conn,
    map_slug: str,
    output_dir: Path,
) -> list[dict]:
    """Compute verified wool chest locations for *map_slug*.

    Algorithm
    ---------
    1. For each (match, wool_id) take the single earliest touch event.
    2. Across all matches, compute the median (x, z) of those first touches.
    3. Retain only first-touches within FIRST_TOUCH_CLUSTER_RADIUS Manhattan
       blocks of the median — these are the confirmed wool-room touches.
    4. Final position = median of the confirmed subset.
    5. Annotate wool_color from wool_id (direct mapping).
    6. Annotate team from map_context.json (by wool_color).

    Falls back to map_context.json positions if no touch events exist.

    Returns a list of dicts ready for upsert into map_wool_locations.
    """
    import pandas as pd

    # ── Load map_context for team annotation ──────────────────────────────
    map_context: dict = {}
    mc_path = output_dir / "map_context.json"
    if mc_path.exists():
        with open(mc_path) as f:
            map_context = json.load(f)

    # ── First touch per (match, wool_id) ──────────────────────────────────
    rows = conn.execute("""
        WITH first_touch AS (
            SELECT
                we.wool_id,
                we.x,
                we.z,
                ROW_NUMBER() OVER (
                    PARTITION BY we.match_id, we.wool_id
                    ORDER BY we.timestamp
                ) AS rn
            FROM wool_events we
            JOIN matches mat ON mat.match_id = we.match_id
            JOIN maps m      ON m.map_id     = mat.map_id
            WHERE m.map_slug = ?
              AND we.event_type = 6
        )
        SELECT wool_id, x, z
        FROM first_touch
        WHERE rn = 1
    """, [map_slug]).fetchdf()

    results: list[dict] = []

    if not rows.empty:
        for wool_id, grp in rows.groupby("wool_id"):
            wool_id = int(wool_id)
            wool_color = WOOL_ID_TO_COLOR.get(wool_id)
            if wool_color is None:
                logger.warning("Unknown wool_id %d for map '%s' — skipping", wool_id, map_slug)
                continue

            # Cluster: keep first touches within radius of median
            x_med = grp["x"].median()
            z_med = grp["z"].median()
            manhattan = (grp["x"] - x_med).abs() + (grp["z"] - z_med).abs()
            cluster = grp[manhattan <= FIRST_TOUCH_CLUSTER_RADIUS]

            if cluster.empty:
                cluster = grp  # shouldn't happen; fall back to all

            x_final = float(cluster["x"].median())
            z_final = float(cluster["z"].median())
            n = len(cluster)
            x_std = float(cluster["x"].std()) if n > 1 else None
            z_std = float(cluster["z"].std()) if n > 1 else None

            results.append({
                "wool_id":           wool_id,
                "wool_color":        wool_color,
                "team":              _team_for_color(wool_color, map_context),
                "x":                 x_final,
                "z":                 z_final,
                "source":            "first_touch_db",
                "first_touch_count": n,
                "x_std":             x_std,
                "z_std":             z_std,
            })

        if results:
            logger.debug(
                "Computed first-touch wool locations for '%s': %d wool(s)",
                map_slug, len(results),
            )
    else:
        logger.debug("No touch events for '%s'; falling back to map_context", map_slug)

    # ── Fallback: map_context for any wool_ids not yet covered ────────────
    covered_colors = {r["wool_color"] for r in results}
    for w in map_context.get("poi_assignments", {}).get("wools", []):
        color = w.get("wool_color")
        if not color or color in covered_colors:
            continue
        # Find wool_id by reverse-looking up WOOL_ID_TO_COLOR
        wool_id = next(
            (k for k, v in WOOL_ID_TO_COLOR.items() if v == color), None
        )
        if wool_id is None:
            continue
        covered_colors.add(color)
        results.append({
            "wool_id":           wool_id,
            "wool_color":        color,
            "team":              w.get("team"),
            "x":                 float(w["x"]),
            "z":                 float(w["z"]),
            "source":            "map_context",
            "first_touch_count": None,
            "x_std":             None,
            "z_std":             None,
        })

    return results


def compute_wool_monuments(
    conn,
    map_slug: str,
    output_dir: Path,
) -> list[dict]:
    """Compute monument positions for *map_slug*.

    Capture events (event_type=7) always fire at the exact monument block.
    Grouping by exact (wool_id, x, z) naturally separates per-team monuments
    on multi-team maps (stddev=0.0 per monument — verified empirically).

    Falls back to map_context.json monument entries if no capture events exist.

    Returns a list of dicts ready for upsert into map_wool_monuments.
    """
    rows = conn.execute("""
        SELECT
            we.wool_id,
            we.x        AS monument_x,
            we.z        AS monument_z,
            COUNT(*)    AS capture_count
        FROM wool_events we
        JOIN matches mat ON mat.match_id = we.match_id
        JOIN maps m      ON m.map_id     = mat.map_id
        WHERE m.map_slug = ?
          AND we.event_type = 7
        GROUP BY we.wool_id, we.x, we.z
    """, [map_slug]).fetchall()

    results: list[dict] = []
    seen: set[tuple[int, float, float]] = set()

    for wool_id, monument_x, monument_z, capture_count in rows:
        wool_id = int(wool_id)
        wool_color = WOOL_ID_TO_COLOR.get(wool_id)
        if wool_color is None:
            continue
        key = (wool_id, float(monument_x), float(monument_z))
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "wool_id":       wool_id,
            "wool_color":    wool_color,
            "monument_x":    float(monument_x),
            "monument_z":    float(monument_z),
            "capture_count": int(capture_count),
            "source":        "capture_events_db",
        })

    if results:
        logger.debug(
            "Computed monument positions for '%s': %d monument(s) across %d wool(s)",
            map_slug,
            len(results),
            len({r["wool_id"] for r in results}),
        )
    else:
        logger.debug(
            "No capture events for '%s'; falling back to map_context monuments", map_slug
        )
        # Fallback: use map_context monument data if available
        mc_path = output_dir / "map_context.json"
        if mc_path.exists():
            with open(mc_path) as f:
                mc = json.load(f)
            seen_mc: set[tuple[int, float, float]] = set()
            for w in mc.get("poi_assignments", {}).get("wools", []):
                color = w.get("wool_color")
                wool_id = next(
                    (k for k, v in WOOL_ID_TO_COLOR.items() if v == color), None
                )
                if wool_id is None:
                    continue
                mx = float(w.get("monument_x", w["x"]))
                mz = float(w.get("monument_z", w["z"]))
                key = (wool_id, mx, mz)
                if key in seen_mc:
                    continue
                seen_mc.add(key)
                results.append({
                    "wool_id":       wool_id,
                    "wool_color":    color,
                    "monument_x":    mx,
                    "monument_z":    mz,
                    "capture_count": 0,
                    "source":        "map_context",
                })

    return results


def compute_wool_objectives(
    conn,
    map_slug: str,
    output_dir: Path,
) -> list[dict]:
    """Compute wool-team objective assignments for *map_slug*.

    Returns a list of {wool_id, wool_color, team, source} dicts representing
    the many-to-many relationship: which teams must capture each wool.

    Primary source: capture events (event_type=7) from the DB.  Any team
    that captured a wool in at least one recorded match is a capturing team
    for that wool.

    Fallback: map_context.json poi_assignments.wools.  The wool positions in
    map_context can be off on some maps (lazy authors), but the team field is
    reliable and safe to use here.  Used for any (wool, team) pairs not
    already covered by the DB data.
    """
    # ── Primary: capture events ───────────────────────────────────────────
    # EXISTS filter on map_spawns normalises team names: only teams whose
    # name in player_team_segments matches map_spawns exactly are kept.
    # Where names differ (e.g. "blue" vs "blue-team") the row is dropped
    # and map_context provides the canonical assignment as fallback.
    rows = conn.execute("""
        SELECT DISTINCT we.wool_id, pts.team
        FROM wool_events we
        JOIN matches mat ON mat.match_id = we.match_id
        JOIN maps m      ON m.map_id     = mat.map_id
        JOIN (
            SELECT DISTINCT ON (match_id, player_id)
                match_id, player_id, team
            FROM player_team_segments
            ORDER BY match_id, player_id, start_timestamp
        ) pts ON pts.match_id = we.match_id AND pts.player_id = we.player_id
        WHERE m.map_slug = ?
          AND we.event_type = 7
          AND EXISTS (
              SELECT 1 FROM map_spawns ms
              WHERE ms.map_id = mat.map_id AND ms.team = pts.team
          )
    """, [map_slug]).fetchall()

    results: list[dict] = []
    covered: set[tuple[int, str]] = set()  # (wool_id, team)

    for wool_id, team in rows:
        wool_id = int(wool_id)
        wool_color = WOOL_ID_TO_COLOR.get(wool_id)
        if wool_color is None:
            continue
        key = (wool_id, team)
        if key in covered:
            continue
        covered.add(key)
        results.append({
            "wool_id":    wool_id,
            "wool_color": wool_color,
            "team":       team,
            "source":     "capture_events_db",
        })

    if results:
        logger.debug(
            "Computed wool objectives for '%s' from DB: %d (wool, team) pair(s)",
            map_slug, len(results),
        )
    else:
        logger.debug(
            "No capture events for '%s'; falling back to map_context for objectives",
            map_slug,
        )

    # ── Fallback: map_context.json for any pairs not covered by DB ────────
    mc_path = output_dir / "map_context.json"
    if mc_path.exists():
        with open(mc_path) as f:
            mc = json.load(f)
        for w in mc.get("poi_assignments", {}).get("wools", []):
            color = w.get("wool_color")
            team = w.get("team", "").removesuffix('-team') or None
            if not color or not team:
                continue
            wool_id = next(
                (k for k, v in WOOL_ID_TO_COLOR.items() if v == color), None
            )
            if wool_id is None:
                continue
            key = (wool_id, team)
            if key in covered:
                continue
            covered.add(key)
            results.append({
                "wool_id":    wool_id,
                "wool_color": color,
                "team":       team,
                "source":     "map_context",
            })

    return results


def upsert_wool_objectives(
    conn,
    map_slug: str,
    objectives: list[dict],
) -> None:
    """Insert or replace wool objective rows for *map_slug*."""
    map_id_row = conn.execute(
        "SELECT map_id FROM maps WHERE map_slug = ?", [map_slug]
    ).fetchone()
    if map_id_row is None:
        logger.warning("upsert_wool_objectives: map_slug '%s' not found", map_slug)
        return
    map_id = int(map_id_row[0])

    conn.execute("DELETE FROM map_wool_objectives WHERE map_id = ?", [map_id])
    for obj in objectives:
        conn.execute("""
            INSERT INTO map_wool_objectives (map_id, wool_id, wool_color, team, source)
            VALUES (?, ?, ?, ?, ?)
        """, [map_id, obj["wool_id"], obj["wool_color"], obj["team"], obj["source"]])

    logger.debug(
        "Upserted %d wool objective(s) for '%s'",
        len(objectives), map_slug,
    )


def upsert_wool_locations(
    conn,
    map_slug: str,
    locations: list[dict],
    monuments: list[dict],
) -> None:
    """Insert or replace wool location and monument rows for *map_slug*.

    Uses DELETE + INSERT within the same connection (no transaction wrapping
    needed here — caller is responsible for commit if using explicit transactions).
    """
    map_id_row = conn.execute(
        "SELECT map_id FROM maps WHERE map_slug = ?", [map_slug]
    ).fetchone()
    if map_id_row is None:
        logger.warning("upsert_wool_locations: map_slug '%s' not found", map_slug)
        return
    map_id = int(map_id_row[0])

    # ── Wool locations ─────────────────────────────────────────────────────
    conn.execute(
        "DELETE FROM map_wool_locations WHERE map_id = ?", [map_id]
    )
    for loc in locations:
        conn.execute("""
            INSERT INTO map_wool_locations
                (map_id, wool_id, wool_color, team, x, z,
                 source, first_touch_count, x_std, z_std)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            map_id,
            loc["wool_id"],
            loc["wool_color"],
            loc.get("team"),
            loc["x"],
            loc["z"],
            loc["source"],
            loc.get("first_touch_count"),
            loc.get("x_std"),
            loc.get("z_std"),
        ])

    # ── Monuments ──────────────────────────────────────────────────────────
    conn.execute(
        "DELETE FROM map_wool_monuments WHERE map_id = ?", [map_id]
    )
    for mon in monuments:
        conn.execute("""
            INSERT INTO map_wool_monuments
                (map_id, wool_id, wool_color, monument_x, monument_z,
                 capture_count, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [
            map_id,
            mon["wool_id"],
            mon["wool_color"],
            mon["monument_x"],
            mon["monument_z"],
            mon["capture_count"],
            mon["source"],
        ])

    logger.debug(
        "Upserted %d wool location(s) and %d monument(s) for '%s'",
        len(locations), len(monuments), map_slug,
    )


def compute_and_upsert(conn_ro, conn_rw, map_slug: str, output_dir: Path) -> list[dict]:
    """Convenience: compute locations + monuments + objectives and upsert in one call.

    Parameters
    ----------
    conn_ro : read-only DuckDB connection (used for queries)
    conn_rw : read-write DuckDB connection (used for upsert)
    map_slug : map identifier
    output_dir : Path to output/<map_slug>/ (for map_context.json)

    Returns the locations list (so callers can use it directly for graph building).
    """
    locations = compute_wool_locations(conn_ro, map_slug, output_dir)
    monuments = compute_wool_monuments(conn_ro, map_slug, output_dir)
    objectives = compute_wool_objectives(conn_ro, map_slug, output_dir)
    upsert_wool_locations(conn_rw, map_slug, locations, monuments)
    upsert_wool_objectives(conn_rw, map_slug, objectives)
    return locations
