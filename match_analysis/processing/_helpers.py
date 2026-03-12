"""Shared private helpers and constants for the post-processing pipeline."""

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

# Y-level thresholds for skybridge detection.
# A player at Y >= SKYBRIDGE_Y_THRESHOLD is considered to be on or near the
# skybridge (built at max_build_height).  Values from ~22 upward are elevated.
SKYBRIDGE_Y_THRESHOLD = 22

# Maximum gap in seconds between consecutive wool touches of the same wool
# before we treat them as separate carry attempts ("waves").
CARRY_WAVE_GAP_S = 120

# location_type values written by the position classifier
_LOC_ISLAND = 'island'
_LOC_BUILD  = 'build_region'
_LOC_VOID   = 'void'


# ---------------------------------------------------------------------------
# Map context / graph loading
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


# ---------------------------------------------------------------------------
# Pure math helpers
# ---------------------------------------------------------------------------

def _euclidean_2d(x1: float, z1: float, x2: float, z2: float) -> float:
    return math.sqrt((x2 - x1) ** 2 + (z2 - z1) ** 2)


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------

def _normalize_team(team: str) -> str:
    """Normalize team name to short form: 'red-team' -> 'red'."""
    return team.removesuffix('-team')


def _assign_wool_ids(wools: list[dict]) -> list[dict]:
    """Return wools with a synthetic 1-based integer wool_id assigned by list position."""
    result = []
    for idx, w in enumerate(wools):
        w2 = dict(w)
        w2['wool_id'] = idx + 1
        result.append(w2)
    return result


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

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
