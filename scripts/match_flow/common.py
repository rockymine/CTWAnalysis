#!/usr/bin/env python3
"""Shared loaders for the match-flow scripts.

Everything in this package reads the processed DuckDB database plus the raw
pgmlogger parquet files. The database drops two columns the parquet keeps —
`held_item` and `inventory_count` — so any analysis of what a player was
holding has to go back to the parquet.

Two coordinate conventions are used throughout:

  rel   height above the map's ORIGINAL terrain surface, from map_terrain_height.
        Only defined over land, so it silently excludes play over the void —
        on some maps a third of all ceiling-height activity.
  y     absolute height. Use this whenever the whole sky network matters.
"""

from __future__ import annotations

import math
import os
from collections import defaultdict
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "match_analysis" / "metadata.db"
OUTPUT_DIR = PROJECT_ROOT / "output"

# pgmlogger parquet corpus; override with CTW_MATCH_LOGS
MATCH_LOGS = Path(os.environ.get("CTW_MATCH_LOGS", "/media/sf_repos/PGMLoggerResults/logs"))

# Minecraft 1.8 DyeColor ordinals, which is what wool_id holds
DYE = ['white', 'orange', 'magenta', 'light_blue', 'yellow', 'lime', 'pink', 'gray',
       'silver', 'cyan', 'purple', 'blue', 'brown', 'green', 'red', 'black']
DYE_ORDINAL = {c: i for i, c in enumerate(DYE)}


def connect(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB_PATH), read_only=read_only)


# ---------------------------------------------------------------- materials

def load_materials() -> tuple[dict[str, int], dict[int, str]]:
    """materials.txt is indexed by Bukkit Material.ordinal(), NOT by block id.

    They coincide for blocks (0..197) and diverge for items, which is why
    held_item 209 is IRON_SWORD and not BUCKET.
    """
    by_name: dict[str, int] = {}
    by_ordinal: dict[int, str] = {}
    with open(PROJECT_ROOT / "materials.txt") as handle:
        for line in handle:
            if ':' not in line:
                continue
            ordinal, name = line.strip().split(':', 1)
            try:
                by_name[name.strip().upper()] = int(ordinal)
                by_ordinal[int(ordinal)] = name.strip()
            except ValueError:
                continue
    return by_name, by_ordinal


MATERIAL_ORDINAL, MATERIAL_NAME = load_materials()

# stairs, fences, iron bars, signs and ladders — the detail work that goes into
# a structure people walk on, as opposed to the bulk block a wall is made of
DETAIL_MATERIALS = (
    {o for n, o in MATERIAL_ORDINAL.items() if n.endswith('STAIRS')}
    | {o for n, o in MATERIAL_ORDINAL.items() if 'FENCE' in n and 'GATE' not in n}
    | {MATERIAL_ORDINAL[n] for n in ('SIGN', 'IRON_FENCE', 'LADDER') if n in MATERIAL_ORDINAL}
)
BOW = MATERIAL_ORDINAL['BOW']


def kit_build_materials(con, map_slug: str, min_stack: int = 16) -> set[int]:
    """The placeable blocks a map's kit hands out in bulk — its building material."""
    rows = con.execute(
        """select distinct k.material, k.amount
             from maps m join map_kit_items k on k.map_id = m.map_id
            where m.map_slug = ?""", [map_slug]).fetchall()
    out = set()
    for material, amount in rows:
        ordinal = MATERIAL_ORDINAL.get(material.strip().upper().replace(' ', '_'))
        if ordinal is not None and ordinal <= 197 and amount >= min_stack:
            out.add(ordinal)
    return out


# ---------------------------------------------------------------- wool rooms

def load_wool_rooms() -> dict[tuple[str, int], tuple[float, float, float, float]]:
    """(map_slug, wool_id) -> (min_x, min_z, max_x, max_z) of the wool-room region.

    Read from the parsed XML in output/<map>/map_data.json, which carries a
    `wool_room_region` id per wool. The wool block itself sits a median nine
    blocks behind its own room face, so measuring anything defensive from the
    wool point rather than the room rectangle biases it by that much.
    """
    import json
    rooms: dict[tuple[str, int], tuple[float, float, float, float]] = {}
    for path in OUTPUT_DIR.glob('*/map_data.json'):
        slug = path.parent.name
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        regions = data.get('regions') or {}
        for wool in data.get('wools') or []:
            region_id = wool.get('wool_room_region')
            colour = (wool.get('color') or '').lower().replace(' ', '_')
            if not region_id or region_id not in regions or colour not in DYE_ORDINAL:
                continue
            region = regions[region_id]
            try:
                xs = sorted([float(region['min_x']), float(region['max_x'])])
                zs = sorted([float(region['min_z']), float(region['max_z'])])
            except (KeyError, TypeError):
                continue
            rooms[(slug, DYE_ORDINAL[colour])] = (xs[0], zs[0], xs[1], zs[1])
    return rooms


def distance_to_rect(x: float, z: float, rect) -> float:
    """0 inside the rectangle, else the shortest distance to its boundary."""
    x0, z0, x1, z1 = rect
    dx = max(x0 - x, 0.0, x - x1)
    dz = max(z0 - z, 0.0, z - z1)
    return math.hypot(dx, dz)


# ---------------------------------------------------------------- match load

def team_by_player(con, match_id: int) -> dict[int, str]:
    """Player -> team, taking each player's FIRST segment.

    Keying on `start_timestamp = 0` loses everyone who joined mid-match, which
    on a long match includes the player who eventually captures the last wool.
    """
    teams: dict[int, str] = {}
    for player_id, team in con.execute(
        """select player_id, team from player_team_segments
            where match_id = ? order by start_timestamp""", [match_id]).fetchall():
        teams.setdefault(player_id, team)
    return teams


def attacking_team(con, match_id: int, map_id: int) -> dict[int, str]:
    """wool_id -> the team that must capture it.

    Capture events are the reliable source; map_wool_objectives has rows that
    list a single wool as an objective for both teams on a few maps, so it is
    only used as a fallback.
    """
    attacker: dict[int, str] = {}
    teams = team_by_player(con, match_id)
    for wool_id, player_id in con.execute(
        """select wool_id, player_id from wool_events
            where match_id = ? and event_type = 7 order by timestamp""", [match_id]).fetchall():
        attacker.setdefault(wool_id, teams.get(player_id))
    for wool_id, team in con.execute(
        "select wool_id, team from map_wool_objectives where map_id = ?", [map_id]).fetchall():
        attacker.setdefault(wool_id, team)
    return {k: v for k, v in attacker.items() if v}


def load_match(con, map_slug: str, match_id: int, cell: int = 2) -> dict | None:
    """Positions joined to team and terrain, plus the map's static geometry.

    Returns None when the map has no terrain rows at all. Rows without a terrain
    reference are KEPT (rel is NaN for them) so that callers can choose between
    `rel` and absolute `y`.
    """
    row = con.execute(
        """select m.map_id, m.max_build_height, mt.match_file, mt.match_duration
             from matches mt join maps m using(map_id) where mt.match_id = ?""",
        [match_id]).fetchone()
    if row is None:
        return None
    map_id, build_cap, match_file, duration = row

    parquet = MATCH_LOGS / map_slug / os.path.basename(match_file)
    if not parquet.exists():
        return None
    raw = pd.read_parquet(parquet)

    surface = pd.DataFrame(
        con.execute("""select world_x as x, world_z as z, surface_y
                         from map_terrain_height where map_id = ?""", [map_id]).fetchall(),
        columns=['x', 'z', 'surface_y'])
    if surface.empty:
        return None

    teams = team_by_player(con, match_id)
    pos = raw[raw.event_type == 5].merge(surface, on=['x', 'z'], how='left')
    pos['team'] = pos.player_id.map(teams)
    pos = pos[pos.team.notna()].copy()
    pos['rel'] = pos.y - pos.surface_y
    pos['cx'] = (pos.x // cell * cell).astype(int)
    pos['cz'] = (pos.z // cell * cell).astype(int)

    deaths: dict[int, list[int]] = defaultdict(list)
    for player_id, timestamp in raw[raw.event_type == 4][['player_id', 'timestamp']].itertuples(index=False):
        deaths[player_id].append(timestamp)

    spawns = {team: (min_x, min_z, max_x, max_z) for team, min_x, min_z, max_x, max_z in con.execute(
        "select team, min_x, min_z, max_x, max_z from map_spawns where map_id = ?", [map_id]).fetchall()}
    all_rooms = load_wool_rooms()
    rooms = {wool_id: rect for (slug, wool_id), rect in all_rooms.items() if slug == map_slug}
    wool_colour = dict(con.execute(
        "select wool_id, wool_color from map_wool_locations where map_id = ?", [map_id]).fetchall())
    captures = dict(con.execute(
        """select wool_id, min(timestamp) from wool_events
            where match_id = ? and event_type = 7 group by 1""", [match_id]).fetchall())

    return dict(map_slug=map_slug, match_id=match_id, map_id=map_id, cell=cell,
                build_cap=build_cap, duration=float(duration), raw=raw, pos=pos,
                deaths=deaths, spawns=spawns, rooms=rooms, wool_colour=wool_colour,
                captures=captures, attacker=attacking_team(con, match_id, map_id),
                kit=kit_build_materials(con, map_slug))


def ceiling(ctx: dict, margin: int = 4) -> int:
    """Absolute y at or above which a player counts as being on the sky layer.

    max_build_height is a hard ceiling where it is recorded — the 95th percentile
    of player y lands exactly on it — but 14 maps in the corpus have it NULL, so
    fall back to a high percentile of observed y.
    """
    if ctx.get('build_cap'):
        return int(ctx['build_cap']) - margin
    return int(np.percentile(ctx['pos'].y, 99)) - margin
