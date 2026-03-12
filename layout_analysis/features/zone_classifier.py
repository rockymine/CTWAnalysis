"""
Zone classifier for CTW map positions.

Classifies a (world_x, world_z) position into one of four zones:

    spawn       — inside a team's spawn region
    wool_room   — inside a team's wool room (vorum)
    defense     — outside a wool room but within ``defense_buffer`` blocks of it
    field       — everywhere else

Also assigns the owning team where possible, using ``apply_rules`` deny entries
and keyword matching on region IDs as a fallback.

Reads from the ``regions`` and ``apply_rules`` keys in ``map_data.json``.
"""

import logging
import re
from typing import Any, Optional

from shapely.geometry import Point, box
from shapely.ops import unary_union

logger = logging.getLogger('ctw')

# Zone labels (ordered by classification priority)
ZONE_SPAWN = 'spawn'
ZONE_NEAR_SPAWN = 'near_spawn'
ZONE_WOOL_ROOM = 'wool_room'
ZONE_DEFENSE = 'defense'
ZONE_FIELD = 'field'

# Candidate keys to look up in regions dict (ordered by preference)
_WOOL_ROOM_COMBINED_KEYS = ('wool-rooms', 'woolrooms', 'wool_rooms')
_SPAWN_COMBINED_KEYS = ('spawns',)

# Patterns that identify individual team wool-room regions
_WOOL_ROOM_PATTERN = re.compile(r'wool.?room|wr$', re.IGNORECASE)
# Patterns that identify individual team spawn regions (exclude sub-region noise)
_SPAWN_PATTERN = re.compile(r'spawn$|-spawn$', re.IGNORECASE)
_SPAWN_EXCLUDE = re.compile(r'wool.spawn|spawn.point|spawn.kit', re.IGNORECASE)


def _nbt_or_val(v: Any) -> Any:
    return v.value if hasattr(v, 'value') else v


def _region_to_geometry(region: dict) -> Any:
    """Recursively convert a region dict to a 2D Shapely geometry (x, z plane)."""
    rtype = region.get('type', '')

    if rtype == 'rectangle':
        return box(region['min_x'], region['min_z'],
                   region['max_x'], region['max_z'])

    elif rtype == 'union':
        children = region.get('children', [])
        geoms = [_region_to_geometry(c) for c in children]
        geoms = [g for g in geoms if g is not None and not g.is_empty]
        return unary_union(geoms) if geoms else None

    elif rtype == 'cylinder':
        base = region.get('base', {})
        radius = float(region.get('radius', 0))
        return Point(float(base.get('x', 0)), float(base.get('z', 0))).buffer(radius)

    elif rtype == 'complement':
        # First child is the base; remaining children are subtracted from it.
        children = region.get('children', [])
        if not children:
            return None
        geom = _region_to_geometry(children[0])
        if geom is None or geom.is_empty:
            return None
        for child in children[1:]:
            sub = _region_to_geometry(child)
            if sub is not None and not sub.is_empty:
                geom = geom.difference(sub)
        return geom if not geom.is_empty else None

    elif rtype == 'intersect':
        children = region.get('children', [])
        geoms = [_region_to_geometry(c) for c in children]
        geoms = [g for g in geoms if g is not None and not g.is_empty]
        if not geoms:
            return None
        result = geoms[0]
        for g in geoms[1:]:
            result = result.intersection(g)
        return result if not result.is_empty else None

    else:
        # Fallback: use bounding box
        bounds = region.get('bounds_2d', {})
        if bounds:
            mn = bounds['min']
            mx = bounds['max']
            return box(float(mn['x']), float(mn['z']),
                       float(mx['x']), float(mx['z']))
        return None


def _first_matching_geometry(regions: dict, candidate_keys: tuple[str, ...]) -> Optional[Any]:
    """Return the Shapely geometry for the first matching key, or None."""
    for key in candidate_keys:
        if key in regions:
            geom = _region_to_geometry(regions[key])
            if geom is not None and not geom.is_empty:
                return geom
    return None


def _extract_deny_team(use_str: str) -> Optional[str]:
    """Parse 'deny(team-id)' → 'team-id', or None if not that pattern."""
    m = re.match(r'^deny\((.+)\)$', use_str or '')
    return m.group(1) if m else None


class ZoneClassifier:
    """
    Classifies (world_x, world_z) positions into spawn / wool_room / defense / field
    and assigns the owning team where determinable.

    Args:
        map_data:        Parsed ``map_data.json`` dict.
        defense_buffer:  Blocks outside the wool-room boundary that count as
                         "defense" (default: 10).
    """

    def __init__(
        self,
        map_data: dict,
        defense_buffer: float = 10.0,
        near_spawn_buffer: float = 15.0,
    ):
        regions: dict = map_data.get('regions', {})
        apply_rules: list = map_data.get('apply_rules', [])

        self._defense_buffer = defense_buffer
        self._near_spawn_buffer = near_spawn_buffer
        self._wool_room_geom = _first_matching_geometry(regions, _WOOL_ROOM_COMBINED_KEYS)
        self._spawn_geom = _first_matching_geometry(regions, _SPAWN_COMBINED_KEYS)

        # Defense zone: buffer outside wool rooms, minus spawn areas
        if self._wool_room_geom is not None:
            defense = self._wool_room_geom.buffer(defense_buffer).difference(
                self._wool_room_geom
            )
            if self._spawn_geom is not None:
                defense = defense.difference(self._spawn_geom)
            self._defense_geom = defense if not defense.is_empty else None
        else:
            self._defense_geom = None

        # Near-spawn zone: buffer outside spawn regions, minus wool rooms and defense
        if self._spawn_geom is not None:
            near_spawn = self._spawn_geom.buffer(near_spawn_buffer).difference(
                self._spawn_geom
            )
            if self._wool_room_geom is not None:
                near_spawn = near_spawn.difference(self._wool_room_geom)
            if self._defense_geom is not None:
                near_spawn = near_spawn.difference(self._defense_geom)
            self._near_spawn_geom = near_spawn if not near_spawn.is_empty else None
        else:
            self._near_spawn_geom = None

        # Build team-specific region geometries for team assignment
        self._team_spawn_geoms: list[tuple[str, Any]] = []     # [(team_id, geom)]
        self._team_wool_geoms: list[tuple[str, Any]] = []       # [(team_id, geom)]

        self._build_team_regions(regions, apply_rules, map_data)

        logger.debug(
            f"ZoneClassifier: wool_room={'yes' if self._wool_room_geom else 'no'}, "
            f"spawn={'yes' if self._spawn_geom else 'no'}, "
            f"near_spawn={'yes' if self._near_spawn_geom else 'no'}, "
            f"defense={'yes' if self._defense_geom else 'no'}, "
            f"team_spawns={len(self._team_spawn_geoms)}, "
            f"team_wool_rooms={len(self._team_wool_geoms)}"
        )

    def _build_team_regions(
        self,
        regions: dict,
        apply_rules: list,
        map_data: dict,
    ) -> None:
        """Populate team-specific spawn and wool-room geometry lists."""
        # Step 1: extract region→team from deny rules
        deny_map: dict[str, str] = {}  # region_id → team_id
        for rule in apply_rules:
            use = rule.get('use', '')
            team_id = _extract_deny_team(use)
            region_id = rule.get('region')
            if team_id and region_id:
                deny_map[region_id] = team_id

        # Get team IDs from the teams list for fallback matching
        team_ids: list[str] = [t['id'] for t in map_data.get('teams', []) if t.get('id')]
        # Build color keywords: 'blue-team' → 'blue', 'team-1' → 'team-1'
        team_colors: dict[str, str] = {}  # color_keyword → team_id
        for tid in team_ids:
            # Remove common suffixes to get the color/key
            color = re.sub(r'-team$|_team$', '', tid)
            team_colors[color] = tid
            team_colors[color + 's'] = tid  # plurals: blue→blues

        def _team_for_region(region_id: str) -> Optional[str]:
            # 1. deny rule mapping
            if region_id in deny_map:
                return deny_map[region_id]
            # 2. keyword search
            rid_lower = region_id.lower()
            for kw, tid in team_colors.items():
                if rid_lower.startswith(kw) or f'-{kw}-' in rid_lower or f'-{kw}' in rid_lower:
                    return tid
            return None

        # Step 2: assign geometries to teams for wool rooms and spawns
        for region_id, region in regions.items():
            geom = _region_to_geometry(region)
            if geom is None or geom.is_empty:
                continue
            team = _team_for_region(region_id)
            if team is None:
                continue

            if _WOOL_ROOM_PATTERN.search(region_id) and not _SPAWN_EXCLUDE.search(region_id):
                # Avoid duplicating what the combined region already covers — only keep
                # regions that are clearly per-team (contain the team keyword)
                self._team_wool_geoms.append((team, geom))

            if _SPAWN_PATTERN.search(region_id) and not _SPAWN_EXCLUDE.search(region_id):
                self._team_spawn_geoms.append((team, geom))

    def _team_at_point(self, point: Point, zone: str) -> Optional[str]:
        """Return the owning team for a point, based on which team region contains it."""
        if zone == ZONE_SPAWN:
            for team, geom in self._team_spawn_geoms:
                if geom.contains(point):
                    return team
        # For wool_room and defense, use wool room team regions (buffered for defense)
        for team, geom in self._team_wool_geoms:
            check_geom = geom.buffer(self._defense_buffer) if zone == ZONE_DEFENSE else geom
            if check_geom.contains(point):
                return team
        # Fallback for defense: check spawn regions with defense buffer
        if zone == ZONE_DEFENSE:
            for team, geom in self._team_spawn_geoms:
                if geom.buffer(self._defense_buffer).contains(point):
                    return team
        # Team assignment for near_spawn
        if zone == ZONE_NEAR_SPAWN:
            for team, geom in self._team_spawn_geoms:
                if geom.buffer(self._near_spawn_buffer).contains(point):
                    return team
        return None

    def classify(self, world_x: float, world_z: float) -> tuple[str, Optional[str]]:
        """
        Classify a 2D position into a zone and owning team.

        Args:
            world_x: Block X coordinate.
            world_z: Block Z coordinate.

        Returns:
            Tuple of (zone, team) where zone is one of
            'spawn' / 'wool_room' / 'defense' / 'field'
            and team is the owning team ID or None.
        """
        pt = Point(world_x, world_z)

        if self._spawn_geom is not None and self._spawn_geom.contains(pt):
            return ZONE_SPAWN, self._team_at_point(pt, ZONE_SPAWN)

        if self._wool_room_geom is not None and self._wool_room_geom.contains(pt):
            return ZONE_WOOL_ROOM, self._team_at_point(pt, ZONE_WOOL_ROOM)

        if self._defense_geom is not None and self._defense_geom.contains(pt):
            return ZONE_DEFENSE, self._team_at_point(pt, ZONE_DEFENSE)

        if self._near_spawn_geom is not None and self._near_spawn_geom.contains(pt):
            return ZONE_NEAR_SPAWN, self._team_at_point(pt, ZONE_NEAR_SPAWN)

        return ZONE_FIELD, None

    def classify_dataframe(
        self,
        df: 'pd.DataFrame',
        x_col: str = 'world_x',
        z_col: str = 'world_z',
    ) -> 'pd.DataFrame':
        """
        Add 'zone' and 'team' columns to a DataFrame with position columns.

        Args:
            df:    DataFrame with at least ``x_col`` and ``z_col`` columns.
            x_col: Name of the X coordinate column.
            z_col: Name of the Z coordinate column.

        Returns:
            Copy of ``df`` with 'zone' and 'team' columns appended.
        """
        import pandas as pd

        result = df.copy()
        zones: list[str] = []
        teams: list[Optional[str]] = []

        for _, row in df.iterrows():
            zone, team = self.classify(float(row[x_col]), float(row[z_col]))
            zones.append(zone)
            teams.append(team)

        result['zone'] = pd.Categorical(
            zones,
            categories=[ZONE_SPAWN, ZONE_NEAR_SPAWN, ZONE_WOOL_ROOM, ZONE_DEFENSE, ZONE_FIELD],
        )
        result['team'] = teams
        return result
