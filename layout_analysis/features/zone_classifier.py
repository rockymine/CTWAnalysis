"""
Zone classifier for CTW map positions.

Classifies a (world_x, world_z) position into one of four zones:

    spawn       — inside a team's spawn region
    wool_room   — inside a team's wool room (vorum)
    defense     — outside a wool room but within ``defense_buffer`` blocks of it
    field       — everywhere else

A fifth zone, ``near_spawn``, is built by default (for resource-block plots) but
is intentionally excluded from **chest** classification — pass
``include_near_spawn=False`` to ``classify`` or ``classify_dataframe`` so those
positions fall through to ``field`` instead.

Also assigns the owning team where possible, using ``apply_rules`` deny entries
and keyword matching on region IDs as a fallback.

Reads from the ``regions`` and ``apply_rules`` keys in ``map_data.json``.
"""

import logging
import re
from pathlib import Path
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

# Candidate combined keys for the spawn geometry fast path
_SPAWN_COMBINED_KEYS = ('spawns',)

# Patterns that identify individual team wool-room regions
_WOOL_ROOM_PATTERN = re.compile(r'wool.?room|wr$', re.IGNORECASE)
# Patterns that identify individual team spawn regions (exclude sub-region noise)
_SPAWN_PATTERN = re.compile(r'spawn$|-spawn$', re.IGNORECASE)
_SPAWN_EXCLUDE = re.compile(r'wool.spawn|spawn.point|spawn.kit', re.IGNORECASE)

# Radius (blocks) used when building a zone from objective location points rather
# than named regions (last-resort fallback for maps with no usable regions).
_LOCATION_FALLBACK_RADIUS = 20.0

# Minecraft 1.8.9 wool damage value → wool color name (normalised to lower-case with spaces).
# Used to match <spawner> item damage values to wool objective colors.
_WOOL_DAMAGE_TO_COLOR: dict[int, str] = {
    0:  'white',
    1:  'orange',
    2:  'magenta',
    3:  'light blue',
    4:  'yellow',
    5:  'lime',
    6:  'pink',
    7:  'gray',
    8:  'silver',      # "light gray" in modern naming; stored as "silver" in older PGM maps
    9:  'cyan',
    10: 'purple',
    11: 'blue',
    12: 'brown',
    13: 'green',
    14: 'red',
    15: 'black',
}

# Reverse mapping: normalised color name → damage value.
# Handles both "light blue" (space) and "light_blue" (underscore) variants.
_WOOL_COLOR_TO_DAMAGE: dict[str, int] = {}
for _dmg, _name in _WOOL_DAMAGE_TO_COLOR.items():
    _WOOL_COLOR_TO_DAMAGE[_name] = _dmg
    _WOOL_COLOR_TO_DAMAGE[_name.replace(' ', '_')] = _dmg
# Extra aliases seen in the wild
_WOOL_COLOR_TO_DAMAGE['light gray'] = 8
_WOOL_COLOR_TO_DAMAGE['light_gray'] = 8


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


def _geom_from_positions(
    regions: dict,
    positions: list[tuple[float, float]],
) -> Optional[Any]:
    """
    Build a zone geometry from known objective positions rather than region names.

    For each position, find the **smallest** named region that contains it.
    Taking the minimum-area region per point avoids accidentally selecting
    large union/meta-regions (e.g. an ``all-wool-rooms`` bounding the whole
    base, or a ``playable`` rectangle covering the entire map) when tighter
    per-objective regions exist.  The per-point winners are unioned to form
    the final geometry; duplicate regions (two objectives in the same room)
    are included only once.

    Point regions (area == 0) and empty geometries are skipped.

    Falls back to a buffered circle of radius ``_LOCATION_FALLBACK_RADIUS``
    around each position when no qualifying named region is found — this covers
    maps like *twisted* where wool rooms are defined only as inline regions
    inside ``apply_rules`` and never appear in the top-level regions dict.
    """
    if not positions:
        return None

    pts = [Point(x, z) for x, z in positions]
    winner_geoms: list[Any] = []
    fallback_pts: list[Any] = []

    for pt in pts:
        best_geom: Optional[Any] = None
        best_area = float('inf')

        for region in regions.values():
            geom = _region_to_geometry(region)
            if geom is None or geom.is_empty or geom.area == 0:
                continue
            if geom.contains(pt) and geom.area < best_area:
                best_geom = geom
                best_area = geom.area

        if best_geom is not None:
            winner_geoms.append(best_geom)
        else:
            fallback_pts.append(pt)

    result_geoms: list[Any] = winner_geoms
    if fallback_pts:
        result_geoms = result_geoms + [
            pt.buffer(_LOCATION_FALLBACK_RADIUS) for pt in fallback_pts
        ]

    return unary_union(result_geoms) if result_geoms else None


def detect_wool_room_region_id(
    wool_x: float,
    wool_z: float,
    regions: dict,
) -> Optional[str]:
    """Return the ID of the smallest named region that spatially contains
    (wool_x, wool_z), or None if no qualifying region is found.

    Algorithm mirrors ``_geom_from_positions`` but tracks the winning region
    ID instead of unioning geometries.  Point/zero-area regions are skipped —
    they are spawn markers or item-frame anchors, not room boundaries.

    Args:
        wool_x:   World-space X coordinate of the wool block.
        wool_z:   World-space Z coordinate of the wool block.
        regions:  The top-level ``regions`` dict from ``map_data.json``.

    Returns:
        The region ID (str) with the smallest area that contains the wool
        location, or ``None`` when no named region qualifies.
    """
    pt = Point(wool_x, wool_z)
    best_id: Optional[str] = None
    best_area: float = float('inf')

    for region_id, region in regions.items():
        # Point and block regions are single-block spawn markers, not room boundaries.
        region_type = region.get('type', '')
        if region_type in ('point', 'block'):
            continue
        try:
            geom = _region_to_geometry(region)
        except (ValueError, TypeError):
            # Regions with infinite bounds (e.g. '-oo') or invalid coordinates
            # cannot be used for containment testing; skip them.
            continue
        if geom is None or geom.is_empty or geom.area == 0:
            continue
        if geom.contains(pt) and geom.area < best_area:
            best_id = region_id
            best_area = geom.area

    return best_id


def assign_wool_room_regions(
    wools: list[dict],
    regions: dict,
    spawners: list[dict],
    output_dir: Optional[Path] = None,
) -> None:
    """Assign ``wool_room_region`` to each wool dict in-place.

    Detection runs in three passes, stopping as soon as a region is found:

    1. **Spawner player_region** — each ``<spawner>`` whose items include a
       wool item whose damage value matches the wool's color is the most
       authoritative source.  The spawner's ``player_region`` is the room.

    2. **Chest spatial search** — if ``output_dir`` is given and
       ``layout_chest_contents.parquet`` exists there, find chests that
       contain wool of the matching color and run a spatial search from
       those chest coordinates.  Chests are physically inside the wool room,
       so their location reliably identifies it.

    3. **Wool location spatial search** — fall back to the wool's own
       ``location`` field.  This is the current default approach and works
       well for maps without spawners or chest data.

    Args:
        wools:      The ``wools`` list from ``map_data.json`` (dicts).
        regions:    The top-level ``regions`` dict from ``map_data.json``.
        spawners:   The ``spawners`` list from ``map_data.json`` (dicts).
        output_dir: Directory containing ``layout_chest_contents.parquet``.
                    If ``None`` or the file is absent, pass 2 is skipped.
    """
    # ── Pass 1: build spawner colour → player_region mapping ──────────────────
    # A spawner is matched to a wool when its items contain a wool item whose
    # damage value corresponds to the wool's colour.
    spawner_color_to_region: dict[str, str] = {}
    wool_materials = {'wool', 'minecraft:wool', '35'}

    for spawner in spawners:
        player_region = spawner.get('player_region', '')
        if not player_region:
            continue
        for item in spawner.get('items', []):
            material = (item.get('material') or '').lower().strip()
            if material not in wool_materials:
                continue
            damage = int(item.get('damage', 0))
            color_name = _WOOL_DAMAGE_TO_COLOR.get(damage)
            if color_name and color_name not in spawner_color_to_region:
                spawner_color_to_region[color_name] = player_region
                # Also register underscore variant
                spawner_color_to_region[color_name.replace(' ', '_')] = player_region

    # ── Pass 2: build colour → chest coordinates mapping ──────────────────────
    # Keyed by wool damage value; value is list of (x, z) chest positions.
    chest_coords_by_damage: dict[int, list[tuple[float, float]]] = {}

    if output_dir is not None:
        chest_parquet = Path(output_dir) / 'layout_chest_contents.parquet'
        if chest_parquet.exists():
            try:
                import pandas as pd
                chest_df = pd.read_parquet(
                    str(chest_parquet),
                    columns=['world_x', 'world_z', 'item_id', 'item_damage'],
                )
                wool_rows = chest_df[chest_df['item_id'].isin({'minecraft:wool', '35', 'wool'})]
                for damage_val, group in wool_rows.groupby('item_damage'):
                    coords = list(zip(
                        group['world_x'].astype(float),
                        group['world_z'].astype(float),
                    ))
                    chest_coords_by_damage[int(damage_val)] = coords
            except Exception:
                # Non-fatal: layout parquet may be absent or malformed
                pass

    # ── Main loop: assign each wool room in location-dedup order ──────────────
    seen_locations: set[str] = set()

    for wool in wools:
        color_raw = (wool.get('color') or '').lower().strip()
        loc = wool.get('location', {})
        wool_x = float(loc.get('x', 0))
        wool_z = float(loc.get('z', 0))
        loc_key = f"{wool_x:.1f},{wool_z:.1f}"

        # If a previous wool at this same location was already resolved, reuse
        # its result (multiple teams may share one wool room).
        if loc_key in seen_locations:
            continue
        seen_locations.add(loc_key)

        # Pass 1: spawner
        region_id = spawner_color_to_region.get(color_raw)

        # Pass 2: chest coordinates
        if region_id is None:
            damage_val = _WOOL_COLOR_TO_DAMAGE.get(color_raw)
            if damage_val is not None:
                chest_coords = chest_coords_by_damage.get(damage_val, [])
                for chest_x, chest_z in chest_coords:
                    candidate = detect_wool_room_region_id(chest_x, chest_z, regions)
                    if candidate is not None:
                        region_id = candidate
                        break

        # Pass 3: wool location spatial search
        if region_id is None:
            region_id = detect_wool_room_region_id(wool_x, wool_z, regions)

        wool['wool_room_region'] = region_id

    # Fill all remaining wools at the same location (multi-team shared rooms)
    location_to_region: dict[str, Optional[str]] = {
        w.get('wool_room_region') and f"{float(w['location']['x']):.1f},{float(w['location']['z']):.1f}": w.get('wool_room_region')
        for w in wools
        if w.get('location') and w.get('wool_room_region') is not None
    }
    for wool in wools:
        if wool.get('wool_room_region') is None:
            loc = wool.get('location', {})
            loc_key = f"{float(loc.get('x', 0)):.1f},{float(loc.get('z', 0)):.1f}"
            wool['wool_room_region'] = location_to_region.get(loc_key)


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
        wool_positions: Optional[list[tuple[float, float]]] = None,
    ):
        regions: dict = map_data.get('regions', {})
        apply_rules: list = map_data.get('apply_rules', [])

        self._defense_buffer = defense_buffer
        self._near_spawn_buffer = near_spawn_buffer

        # Build wool-room geometry: always use position-based detection.
        # Using a well-known combined key (e.g. 'wool-rooms') as a fast path is
        # unreliable: the combined region may cover only a subset of wool rooms
        # (as seen on factorio_mainbus where 'wool-rooms' contained one of four
        # rooms).  Position-based detection finds the smallest named region
        # containing each wool objective location, so it always returns individual
        # per-room geometries regardless of how the map author named them.
        #
        # ``wool_positions`` can be passed explicitly (e.g. from map_wool_locations
        # DB table) to override the XML-declared positions, which are sometimes
        # wrong (pointing to monument blocks rather than the wool room itself).
        # Falls back to map_data['wools'][*]['location'] when not provided.
        if wool_positions is None:
            wool_positions = [
                (float(w['location']['x']), float(w['location']['z']))
                for w in map_data.get('wools', [])
                if 'location' in w
            ]
        self._wool_room_geom = _geom_from_positions(regions, wool_positions)

        # Build spawn geometry: try the well-known combined key first (fast path),
        # then fall back to position-based detection using per-team spawn locations.
        self._spawn_geom = _first_matching_geometry(regions, _SPAWN_COMBINED_KEYS)
        if self._spawn_geom is None:
            spawn_positions = [
                (float(s['region']['position']['x']), float(s['region']['position']['z']))
                for s in map_data.get('spawns', [])
                if 'region' in s and 'position' in s.get('region', {})
            ]
            self._spawn_geom = _geom_from_positions(regions, spawn_positions)

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

    def classify(
        self,
        world_x: float,
        world_z: float,
        include_near_spawn: bool = True,
    ) -> tuple[str, Optional[str]]:
        """
        Classify a 2D position into a zone and owning team.

        Args:
            world_x:             Block X coordinate.
            world_z:             Block Z coordinate.
            include_near_spawn:  When False, the near_spawn zone is skipped and
                                 those positions are classified as ``field``.
                                 Use False for chest classification; True (default)
                                 for resource-block classification.

        Returns:
            Tuple of (zone, team) where zone is one of
            'spawn' / 'wool_room' / 'defense' / 'field' (and 'near_spawn' when
            ``include_near_spawn`` is True) and team is the owning team ID or None.
        """
        pt = Point(world_x, world_z)

        if self._spawn_geom is not None and self._spawn_geom.contains(pt):
            return ZONE_SPAWN, self._team_at_point(pt, ZONE_SPAWN)

        if self._wool_room_geom is not None and self._wool_room_geom.contains(pt):
            return ZONE_WOOL_ROOM, self._team_at_point(pt, ZONE_WOOL_ROOM)

        if self._defense_geom is not None and self._defense_geom.contains(pt):
            return ZONE_DEFENSE, self._team_at_point(pt, ZONE_DEFENSE)

        if (
            include_near_spawn
            and self._near_spawn_geom is not None
            and self._near_spawn_geom.contains(pt)
        ):
            return ZONE_NEAR_SPAWN, self._team_at_point(pt, ZONE_NEAR_SPAWN)

        return ZONE_FIELD, None

    def classify_dataframe(
        self,
        df: 'pd.DataFrame',
        x_col: str = 'world_x',
        z_col: str = 'world_z',
        include_near_spawn: bool = True,
    ) -> 'pd.DataFrame':
        """
        Add 'zone' and 'team' columns to a DataFrame with position columns.

        Args:
            df:                  DataFrame with at least ``x_col`` and ``z_col`` columns.
            x_col:               Name of the X coordinate column.
            z_col:               Name of the Z coordinate column.
            include_near_spawn:  When False, near_spawn is excluded from zone
                                 categories and those positions become ``field``.
                                 Pass False for chest DataFrames.

        Returns:
            Copy of ``df`` with 'zone' and 'team' columns appended.
        """
        import pandas as pd

        result = df.copy()
        zones: list[str] = []
        teams: list[Optional[str]] = []

        for _, row in df.iterrows():
            zone, team = self.classify(
                float(row[x_col]), float(row[z_col]),
                include_near_spawn=include_near_spawn,
            )
            zones.append(zone)
            teams.append(team)

        zone_categories = (
            [ZONE_SPAWN, ZONE_NEAR_SPAWN, ZONE_WOOL_ROOM, ZONE_DEFENSE, ZONE_FIELD]
            if include_near_spawn
            else [ZONE_SPAWN, ZONE_WOOL_ROOM, ZONE_DEFENSE, ZONE_FIELD]
        )
        result['zone'] = pd.Categorical(zones, categories=zone_categories)
        result['team'] = teams
        return result
