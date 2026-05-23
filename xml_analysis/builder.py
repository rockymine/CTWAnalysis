"""
Builder for map data from XML configuration.

Parses teams, spawns, wools, regions, and other map elements from XML files,
returning a populated MapData dataclass.
"""

import xml.etree.ElementTree as ET
import re
from typing import Optional

from .datatypes import MapData, Team, Author, Kit, KitItem, KitArmor, Spawn, Wool, ApplyRule
from .regions import (
    Region, RectangleRegion, CuboidRegion, CylinderRegion, CircleRegion,
    SphereRegion, BlockRegion, PointRegion, UnionRegion, NegativeRegion,
    ComplementRegion, IntersectRegion, RegionReference, EverywhereRegion, AboveRegion,
    MirrorRegion, TranslateRegion,
)


def _safe_float(value: str, default: float = 0.0) -> float:
    """Convert string to float, returning default for template variables like ${...}."""
    value = value.strip()
    if '$' in value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _safe_int(value: str, default: Optional[int] = None) -> Optional[int]:
    """Convert string to int, returning default for template variables like ${...}."""
    value = value.strip()
    if '$' in value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _inject_anonymous_child_ids(region: Region, parent_id: str) -> None:
    """Recursively assign synthetic ``{parent_id}__{index}`` ids to anonymous children.

    Composite regions (union, negative, complement, intersect) may contain inline
    child regions that have no ``id`` attribute in the XML.  Without an id these
    children are invisible to the editor: ``_encode_node`` marks them
    ``synthetic_id: true`` and the browser disables editing for them.

    Assigning ids here — at pipeline time — ensures the children receive real ids
    in ``map_data.json``, so ``_encode_node`` sees a non-empty id, sets
    ``synthetic_id: false``, and the browser permits editing.

    The naming scheme ``parent__0``, ``parent__1``, … is identical to what
    ``_encode_node`` would generate ephemerally at serve time, keeping the ids
    stable and predictable.  Underscores are valid in PGM region ids, so the
    generated ids can also be round-tripped through the XML export endpoint.

    Children that already have an XML-defined id are left untouched.  Recursion
    uses the child's final id (assigned or pre-existing) as the ``parent_id`` for
    the next level.
    """
    for index, child in enumerate(getattr(region, 'children', [])):
        if not child.id:
            child.id = f"{parent_id}__{index}"
        _inject_anonymous_child_ids(child, child.id)


class MapXMLParser:
    """Parser for Minecraft map XML files."""

    def __init__(self, xml_path: str):
        """
        Initialize parser with XML file path.

        Args:
            xml_path: Path to the XML file
        """
        self.xml_path = xml_path
        self.tree = ET.parse(xml_path)
        self.root = self.tree.getroot()

    def parse(self) -> MapData:
        """
        Parse the entire XML file.

        Returns:
            MapData object containing all parsed information
        """
        data = MapData()

        # Resolve <if>/<unless> variant conditionals before parsing
        self._resolve_variants(self.root)

        # Resolve <constant> definitions — must run after variants so that
        # conditional constants (e.g. <if variant="halloween"><constant ...>) are
        # already inlined or removed before we collect the final constant values.
        self._resolve_constants(self.root)

        # Parse basic info
        data.name = self._get_text('name', '')
        data.version = self._get_text('version', '')
        data.gamemode = self._get_text('gamemode', '')
        data.objective = self._get_text('objective', '')

        # Parse authors and contributors
        data.authors = self._parse_authors()

        # Parse teams
        data.teams = self._parse_teams()

        # Parse kits
        data.kits = self._parse_kits()

        # Parse spawns (team spawns + optional observer default spawn)
        data.spawns, data.observer_spawn = self._parse_spawns()

        # Parse wools
        data.wools = self._parse_wools()

        # Parse regions and apply rules
        data.regions, data.apply_rules = self._parse_regions()

        # Resolve spawn region references now that regions are available
        self._resolve_spawn_regions(data)

        # Parse max build height
        data.max_build_height = self._parse_max_build_height()

        return data

    def _get_text(self, tag: str, default: str = '') -> str:
        """Get text content of a tag."""
        elem = self.root.find(tag)
        return elem.text if elem is not None and elem.text else default

    def _resolve_variants(self, element):
        """Resolve <if>/<unless> variant conditionals in-place for the default variant.

        - <if variant="default">      → inline children (we are default)
        - <if variant="halloween">    → remove (we are not halloween)
        - <unless variant="halloween"> → inline children (default != halloween)
        - <unless variant="default">   → remove (we are default)
        """
        # Recurse into children first (bottom-up) so nested conditionals resolve
        for child in list(element):
            self._resolve_variants(child)

        # Now process this element's direct <if>/<unless> children
        new_children = []
        changed = False
        for child in list(element):
            if child.tag in ('if', 'unless'):
                changed = True
                variants = {v.strip() for v in child.get('variant', '').split(',')}
                include = (child.tag == 'if' and 'default' in variants) or \
                          (child.tag == 'unless' and 'default' not in variants)
                if include:
                    new_children.extend(child)
            else:
                new_children.append(child)

        if changed:
            for child in list(element):
                element.remove(child)
            for child in new_children:
                element.append(child)

    def _resolve_constants(self, root: ET.Element) -> None:
        """Resolve <constant id="...">value</constant> references in attribute values.

        Collects all <constant> elements from the tree (after variant resolution
        has already run, so conditional constants are already inlined or removed),
        then walks every element and substitutes ``${id}`` patterns in attribute
        values.  Element text is left unchanged — constants are only used in
        attribute positions in practice.
        """
        constants: dict[str, str] = {}
        for elem in root.iter('constant'):
            cid = elem.get('id', '').strip()
            value = (elem.text or '').strip()
            if cid:
                constants[cid] = value

        if not constants:
            return

        pattern = re.compile(r'\$\{([^}]+)\}')

        def _sub(value: str) -> str:
            return pattern.sub(lambda m: constants.get(m.group(1), m.group(0)), value)

        for elem in root.iter():
            for attr, val in list(elem.attrib.items()):
                if '${' in val:
                    elem.set(attr, _sub(val))

    def _parse_teams(self) -> list[Team]:
        """Parse team elements."""
        teams = []
        teams_elem = self.root.find('teams')
        if teams_elem is None:
            return teams

        for team_elem in teams_elem.findall('team'):
            team = Team(
                id=team_elem.get('id', ''),
                color=team_elem.get('color', ''),
                max_players=int(team_elem.get('max', '0')),
                min_players=int(team_elem.get('min', '0')),
                name=team_elem.text or '',
                dye_color=team_elem.get('dye-color', '')
            )
            teams.append(team)

        return teams

    def _parse_authors(self) -> list[Author]:
        """Parse <authors> and <contributors> blocks into Author entries.

        Only uuid and contribution attributes are read — names live in XML
        comments and are intentionally ignored here.
        """
        authors: list[Author] = []
        authors_elem = self.root.find('authors')
        if authors_elem is not None:
            for elem in authors_elem.findall('author'):
                uuid = elem.get('uuid', '')
                if uuid:
                    authors.append(Author(
                        uuid=uuid,
                        role='author',
                        contribution=elem.get('contribution', ''),
                    ))
        contributors_elem = self.root.find('contributors')
        if contributors_elem is not None:
            for elem in contributors_elem.findall('contributor'):
                uuid = elem.get('uuid', '')
                if uuid:
                    authors.append(Author(
                        uuid=uuid,
                        role='contributor',
                        contribution=elem.get('contribution', ''),
                    ))
        return authors

    def _parse_kits(self) -> list[Kit]:
        """Parse <kits> block into Kit dataclasses."""
        kits: list[Kit] = []
        kits_elem = self.root.find('kits')
        if kits_elem is None:
            return kits

        for kit_elem in kits_elem.findall('kit'):
            kit_id = kit_elem.get('id', '')
            if not kit_id:
                continue

            items: list[KitItem] = []
            for item_elem in kit_elem.findall('item'):
                material = item_elem.get('material', '').strip()
                if not material:
                    continue
                slot_str = item_elem.get('slot', '0')
                try:
                    slot = int(slot_str)
                except ValueError:
                    continue
                items.append(KitItem(
                    slot=slot,
                    material=material,
                    amount=int(item_elem.get('amount', '1')),
                    item_damage=int(item_elem.get('damage', '0')),
                    unbreakable=item_elem.get('unbreakable', '').lower() in ('true', '1', 'yes'),
                    team_color=item_elem.get('team-color', '').lower() in ('true', '1', 'yes'),
                    enchantments=self._collect_enchantments(item_elem),
                ))

            armor: list[KitArmor] = []
            for slot_name in ('helmet', 'chestplate', 'leggings', 'boots'):
                armor_elem = kit_elem.find(slot_name)
                if armor_elem is None:
                    continue
                material = armor_elem.get('material', '').strip()
                if not material:
                    continue
                armor.append(KitArmor(
                    slot_name=slot_name,
                    material=material,
                    unbreakable=armor_elem.get('unbreakable', '').lower() in ('true', '1', 'yes'),
                    team_color=armor_elem.get('team-color', '').lower() in ('true', '1', 'yes'),
                    enchantments=self._collect_enchantments(armor_elem),
                ))

            if items or armor:
                kits.append(Kit(id=kit_id, items=items, armor=armor))

        return kits

    @staticmethod
    def _collect_enchantments(elem: ET.Element) -> str:
        """Return a comma-joined 'name:level' string of all enchantments on an item/armor element."""
        parts: list[str] = []
        attr = elem.get('enchantment', '').strip()
        if attr:
            for token in attr.split(';'):
                token = token.strip()
                if not token:
                    continue
                if ':' in token:
                    raw_name, _, raw_level = token.rpartition(':')
                    name = raw_name.strip().replace(' ', '_')
                    try:
                        level = int(raw_level.strip())
                    except ValueError:
                        level = 1
                else:
                    name = token.replace(' ', '_')
                    level = 1
                parts.append(f"{name}:{level}")
        for child in elem:
            if child.tag == 'enchantment':
                name = (child.text or '').strip().replace(' ', '_')
                try:
                    level = int(child.get('level', '1'))
                except ValueError:
                    level = 1
                if name:
                    parts.append(f"{name}:{level}")
        return ','.join(parts)

    def _parse_spawns(self) -> tuple[list[Spawn], Optional[Spawn]]:
        """Parse spawn and default (observer) elements.

        Handles maps with nested <spawns kit="..."> groups (e.g. empire) by
        using _collect_spawn_elements to recursively walk the tree.

        Returns:
            Tuple of (team_spawns, observer_spawn).  observer_spawn is None
            when no <default> element is present.
        """
        spawns: list[Spawn] = []
        observer_spawn: Optional[Spawn] = None
        spawns_elem = self.root.find('spawns')
        if spawns_elem is None:
            return spawns, observer_spawn

        spawn_elements, default_elem = self._collect_spawn_elements(spawns_elem)
        for spawn_elem, inherited_kit in spawn_elements:
            spawns.append(self._parse_spawn_element(spawn_elem, inherited_kit))

        if default_elem is not None:
            observer_spawn = self._parse_spawn_element(default_elem)

        return spawns, observer_spawn

    def _collect_spawn_elements(
        self, parent: ET.Element, inherited_kit: str = ''
    ) -> tuple[list[tuple[ET.Element, str]], Optional[ET.Element]]:
        """Collect (spawn_element, kit) pairs from potentially nested <spawns> groups.

        Walks direct children recursively into nested <spawns> elements,
        passing down the inherited kit attribute so that <spawn> children
        without their own kit attribute still receive the correct kit.
        Also returns the first <default> element found (observer spawn).
        """
        spawn_results: list[tuple[ET.Element, str]] = []
        default_elem: Optional[ET.Element] = None
        for child in parent:
            if child.tag == 'spawn':
                spawn_results.append((child, inherited_kit))
            elif child.tag == 'default':
                if default_elem is None:
                    default_elem = child
            elif child.tag == 'spawns':
                kit = child.get('kit', '') or inherited_kit
                nested_spawns, nested_default = self._collect_spawn_elements(child, kit)
                spawn_results.extend(nested_spawns)
                if nested_default is not None and default_elem is None:
                    default_elem = nested_default
        return spawn_results, default_elem

    def _parse_spawn_element(self, elem: ET.Element, inherited_kit: str = '') -> 'Spawn':
        """Parse a single <spawn> or <default> element into a Spawn."""
        region = None
        region_attr = elem.get('region', '')
        if region_attr:
            region = RegionReference(ref_id=region_attr)
        else:
            region_elem = elem.find('region')
            if region_elem is None:
                region_elem = elem.find('regions')
            if region_elem is not None:
                region = self._parse_region_element(region_elem)

        return Spawn(
            team=elem.get('team', ''),
            kit=elem.get('kit', '') or inherited_kit,
            yaw=_safe_float(elem.get('yaw', '0')),
            region=region,
        )

    @staticmethod
    def _resolve_spawn_regions(data: MapData):
        """Resolve RegionReference objects on spawns now that regions are parsed."""
        for spawn in data.spawns:
            if isinstance(spawn.region, RegionReference) and spawn.region.ref_id in data.regions:
                spawn.region = data.regions[spawn.region.ref_id]
        if (
            data.observer_spawn is not None
            and isinstance(data.observer_spawn.region, RegionReference)
            and data.observer_spawn.region.ref_id in data.regions
        ):
            data.observer_spawn.region = data.regions[data.observer_spawn.region.ref_id]

    def _parse_wools(self) -> list[Wool]:
        """Parse wool elements.

        Handles maps with multiple top-level <wools team="..."> blocks (one per
        team) by iterating all of them with findall().  The team attribute on the
        outer <wools> element is passed as inherited_team so that <wool> children
        without their own team attribute still receive the correct team.
        """
        wools = []
        wools_elems = self.root.findall('wools')
        if not wools_elems:
            return wools

        for wools_elem in wools_elems:
            outer_team = wools_elem.get('team', '')
            for wool_elem, inherited_team in self._collect_wool_elements(
                wools_elem, outer_team
            ):
                location = self._parse_coords(wool_elem.get('location', '0,0,0'))
                monument_elem = wool_elem.find('monument/block')
                monument = (0, 0, 0)
                if monument_elem is not None and monument_elem.text:
                    monument = self._parse_coords(monument_elem.text)

                wool = Wool(
                    team=wool_elem.get('team', '') or inherited_team,
                    color=wool_elem.get('color', ''),
                    location=location,
                    monument=monument
                )
                wools.append(wool)

        return wools

    def _collect_wool_elements(self, parent: ET.Element, inherited_team: str = '') -> list[tuple[ET.Element, str]]:
        """Collect (wool_element, team) pairs, resolving nested <wools team=...> grouping."""
        results = []
        for child in parent:
            if child.tag == 'wool':
                results.append((child, inherited_team))
            elif child.tag == 'wools':
                team = child.get('team', '') or inherited_team
                results.extend(self._collect_wool_elements(child, team))
        return results

    def _parse_regions(self) -> tuple[dict[str, Region], list[ApplyRule]]:
        """Parse regions and apply elements."""
        regions = {}
        apply_rules = []
        regions_elem = self.root.find('regions')
        if regions_elem is None:
            return regions, apply_rules

        for child in regions_elem:
            if child.tag == 'apply':
                apply_rules.append(self._parse_apply(child))
            else:
                region = self._parse_region_node(child)
                if region and region.id:
                    regions[region.id] = region

        # Build a flat registry of ALL named regions (including children
        # of unions, etc.) so mirror/translate refs can resolve them.
        self._register_nested_regions(regions)

        return regions, apply_rules

    @staticmethod
    def _register_nested_regions(regions: dict[str, Region]) -> None:
        """Walk region tree and register all named sub-regions into the flat dict."""
        def walk(region):
            if region.id and region.id not in regions:
                regions[region.id] = region
            if hasattr(region, 'children'):
                for child in region.children:
                    walk(child)
            if hasattr(region, 'source') and region.source:
                walk(region.source)
        for region in list(regions.values()):
            walk(region)

    def _parse_max_build_height(self) -> Optional[int]:
        """Parse max build height."""
        elem = self.root.find('maxbuildheight')
        if elem is not None and elem.text:
            return _safe_int(elem.text)
        return None

    def _parse_region_element(self, parent_elem: ET.Element) -> Optional[Region]:
        """Parse a region from a parent element (first child)."""
        for child in parent_elem:
            return self._parse_region_node(child)
        return None

    def _parse_region_node(self, elem: ET.Element) -> Optional[Region]:
        """Parse a single region node."""
        tag = elem.tag
        region_id = elem.get('id', '')

        if tag == 'rectangle':
            return self._parse_rectangle(elem, region_id)
        elif tag == 'cuboid':
            return self._parse_cuboid(elem, region_id)
        elif tag == 'cylinder':
            return self._parse_cylinder(elem, region_id)
        elif tag == 'circle':
            return self._parse_circle(elem, region_id)
        elif tag == 'sphere':
            return self._parse_sphere(elem, region_id)
        elif tag == 'block':
            return self._parse_block(elem, region_id)
        elif tag == 'point':
            return self._parse_point(elem, region_id)
        elif tag == 'union':
            return self._parse_union(elem, region_id)
        elif tag == 'negative':
            return self._parse_negative(elem, region_id)
        elif tag == 'complement':
            return self._parse_complement(elem, region_id)
        elif tag == 'intersect':
            return self._parse_intersect(elem, region_id)
        elif tag == 'everywhere':
            return EverywhereRegion(id=region_id)
        elif tag == 'above':
            return AboveRegion(id=region_id, y=float(elem.get('y', '0')))
        elif tag == 'mirror':
            return self._parse_mirror(elem, region_id)
        elif tag == 'translate':
            return self._parse_translate(elem, region_id)
        elif tag == 'region':
            # <region id="ref-id"/> — reference to a named region
            ref_id = elem.get('id', '')
            if ref_id and len(elem) == 0:
                return RegionReference(ref_id=ref_id)
            # If it has children, treat as a container (inline region)
            return self._parse_region_element(elem)

        return None

    def _parse_coords(self, coord_str: str) -> tuple[float, float, float]:
        """Parse coordinate string 'x,y,z'."""
        parts = coord_str.split(',')
        if len(parts) >= 3:
            return (
                Region.parse_value(parts[0]),
                Region.parse_value(parts[1]),
                Region.parse_value(parts[2])
            )
        return (0, 0, 0)

    def _parse_coords_2d(self, coord_str: str) -> tuple[float, float]:
        """Parse 2D coordinate string 'x,z'."""
        parts = coord_str.split(',')
        if len(parts) >= 2:
            return (
                Region.parse_value(parts[0]),
                Region.parse_value(parts[1])
            )
        return (0, 0)

    def _parse_rectangle(self, elem: ET.Element, region_id: str) -> RectangleRegion:
        """Parse rectangle region."""
        min_coords = self._parse_coords_2d(elem.get('min', '0,0'))
        max_coords = self._parse_coords_2d(elem.get('max', '0,0'))

        return RectangleRegion(
            id=region_id,
            min_x=min_coords[0],
            min_z=min_coords[1],
            max_x=max_coords[0],
            max_z=max_coords[1]
        )

    def _parse_cuboid(self, elem: ET.Element, region_id: str) -> CuboidRegion:
        """Parse cuboid region.

        Supports three forms:
          <cuboid min="X1,Y1,Z1" max="X2,Y2,Z2"/>
          <cuboid min="X1,Y1,Z1" size="W,H,D"/>   → max = min + size
          <cuboid max="X2,Y2,Z2" size="W,H,D"/>   → min = max - size
        """
        size_str = elem.get('size', '')
        has_min = elem.get('min') is not None
        has_max = elem.get('max') is not None

        if size_str and has_min and not has_max:
            min_coords = self._parse_coords(elem.get('min'))
            size = self._parse_coords(size_str)
            max_coords = (min_coords[0] + size[0], min_coords[1] + size[1], min_coords[2] + size[2])
        elif size_str and has_max and not has_min:
            max_coords = self._parse_coords(elem.get('max'))
            size = self._parse_coords(size_str)
            min_coords = (max_coords[0] - size[0], max_coords[1] - size[1], max_coords[2] - size[2])
        else:
            min_coords = self._parse_coords(elem.get('min', '0,0,0'))
            max_coords = self._parse_coords(elem.get('max', '0,0,0'))

        return CuboidRegion(
            id=region_id,
            min_x=min_coords[0],
            min_y=min_coords[1],
            min_z=min_coords[2],
            max_x=max_coords[0],
            max_y=max_coords[1],
            max_z=max_coords[2]
        )

    def _parse_cylinder(self, elem: ET.Element, region_id: str) -> CylinderRegion:
        """Parse cylinder region."""
        base = self._parse_coords(elem.get('base', '0,0,0'))
        radius = float(elem.get('radius', '0'))
        height = Region.parse_value(elem.get('height', '0'))

        return CylinderRegion(
            id=region_id,
            base_x=base[0],
            base_y=base[1],
            base_z=base[2],
            radius=radius,
            height=height
        )

    def _parse_circle(self, elem: ET.Element, region_id: str) -> CircleRegion:
        """Parse circle region."""
        center = self._parse_coords_2d(elem.get('center', '0,0'))
        radius = float(elem.get('radius', '0'))

        return CircleRegion(
            id=region_id,
            center_x=center[0],
            center_z=center[1],
            radius=radius
        )

    def _parse_sphere(self, elem: ET.Element, region_id: str) -> SphereRegion:
        """Parse sphere region."""
        origin = self._parse_coords(elem.get('origin', '0,0,0'))
        radius = float(elem.get('radius', '0'))

        return SphereRegion(
            id=region_id,
            origin_x=origin[0],
            origin_y=origin[1],
            origin_z=origin[2],
            radius=radius
        )

    def _parse_block(self, elem: ET.Element, region_id: str) -> BlockRegion:
        """Parse block region."""
        coords = self._parse_coords(elem.text or '0,0,0')

        return BlockRegion(
            id=region_id,
            x=coords[0],
            y=coords[1],
            z=coords[2]
        )

    def _parse_point(self, elem: ET.Element, region_id: str) -> PointRegion:
        """Parse point region."""
        coords = self._parse_coords(elem.text or '0,0,0')

        return PointRegion(
            id=region_id,
            x=coords[0],
            y=coords[1],
            z=coords[2]
        )

    def _parse_union(self, elem: ET.Element, region_id: str) -> UnionRegion:
        """Parse union region (contains multiple children)."""
        children = []
        for child in elem:
            region = self._parse_region_node(child)
            if region:
                children.append(region)

        return UnionRegion(
            id=region_id,
            children=children
        )

    def _parse_negative(self, elem: ET.Element, region_id: str) -> NegativeRegion:
        """Parse negative region."""
        children = []
        for child in elem:
            region = self._parse_region_node(child)
            if region:
                children.append(region)

        return NegativeRegion(
            id=region_id,
            children=children
        )

    def _parse_complement(self, elem: ET.Element, region_id: str) -> ComplementRegion:
        """Parse complement region."""
        children = []
        for child in elem:
            region = self._parse_region_node(child)
            if region:
                children.append(region)

        return ComplementRegion(
            id=region_id,
            children=children
        )

    def _parse_intersect(self, elem: ET.Element, region_id: str) -> IntersectRegion:
        """Parse intersect region."""
        children = []
        for child in elem:
            region = self._parse_region_node(child)
            if region:
                children.append(region)

        return IntersectRegion(
            id=region_id,
            children=children
        )

    def _parse_mirror(self, elem: ET.Element, region_id: str) -> MirrorRegion:
        """Parse mirror region.

        Supports both attribute form (<mirror region="id" .../>)
        and child form (<mirror ...><region id="id"/></mirror>).
        """
        origin = self._parse_coords(elem.get('origin', '0,0,0'))
        normal = self._parse_coords(elem.get('normal', '0,0,0'))
        ref_region_id = elem.get('region', '')
        source = None
        if not ref_region_id:
            source = self._parse_region_element(elem)

        return MirrorRegion(
            id=region_id,
            source=source,
            ref_region_id=ref_region_id,
            origin_x=origin[0], origin_y=origin[1], origin_z=origin[2],
            normal_x=normal[0], normal_y=normal[1], normal_z=normal[2],
        )

    def _parse_translate(self, elem: ET.Element, region_id: str) -> TranslateRegion:
        """Parse translate region.

        Supports both attribute form (<translate region="id" .../>)
        and child form (<translate ...><region id="id"/></translate>).
        """
        offset = self._parse_coords(elem.get('offset', '0,0,0'))
        ref_region_id = elem.get('region', '')
        source = None
        if not ref_region_id:
            source = self._parse_region_element(elem)

        return TranslateRegion(
            id=region_id,
            source=source,
            ref_region_id=ref_region_id,
            offset_x=offset[0], offset_y=offset[1], offset_z=offset[2],
        )

    def _parse_apply(self, elem: ET.Element) -> ApplyRule:
        """Parse an <apply> element."""
        rule = ApplyRule(
            block_filter=elem.get('block', ''),
            block_place_filter=elem.get('block-place', ''),
            block_break_filter=elem.get('block-break', ''),
            use_filter=elem.get('use', ''),
            region_id=elem.get('region', ''),
            message=elem.get('message', ''),
        )
        # Check for inline region children
        for child in elem:
            region = self._parse_region_node(child)
            if region:
                rule.inline_region = region
                break
        return rule

    def inject_anonymous_region_ids(self, data: MapData) -> None:
        """Assign synthetic IDs to all anonymous regions and register them in data.regions.

        Handles two categories of anonymous region:

        **Objective-level anonymous regions** — Some objectives (most commonly ``<spawn>``
        elements) define their region inline rather than referencing a named top-level
        region.  These have no ``id`` attribute and are absent from ``data.regions``,
        making them invisible to the categoriser and to JSON consumers of
        ``map_data.json``.  Each such region is assigned a ``__spawn_<team>`` /
        ``__observer_spawn`` id and inserted into ``data.regions``.

        **Anonymous children of composite regions** — Composite regions (union, negative,
        complement, intersect) may contain inline child regions without ids.  Without an
        id the browser editor marks them as non-editable (``synthetic_id: true``).  Each
        is assigned a ``{parent_id}__{index}`` id in place so the editor can address and
        edit them.

        Both mutations happen in place on *data*.  Call this *before*
        ``identify_region_categories`` so that all injected regions are present in
        ``data.regions`` and objective-level spawn regions land in ``team_spawn_ids``.

        Extension point: if future objective types (e.g. monuments) also embed anonymous
        inline regions at the objective level, add analogous handling in the first block.
        """
        # ── Objective-level anonymous spawn regions ───────────────────────────
        for spawn in data.spawns:
            if spawn.region and not spawn.region.id:
                synthetic_id = f"__spawn_{spawn.team}"
                spawn.region.id = synthetic_id
                if synthetic_id not in data.regions:
                    data.regions[synthetic_id] = spawn.region

        if (data.observer_spawn
                and data.observer_spawn.region
                and not data.observer_spawn.region.id):
            synthetic_id = "__observer_spawn"
            data.observer_spawn.region.id = synthetic_id
            if synthetic_id not in data.regions:
                data.regions[synthetic_id] = data.observer_spawn.region

        # ── Anonymous children of composite regions ───────────────────────────
        for region_id, region in data.regions.items():
            _inject_anonymous_child_ids(region, region_id)

    def identify_region_categories(self, data: MapData) -> dict[str, list[str]]:
        """Identify region categories using structured XML data and regex patterns.

        Uses ground-truth anchoring, wool-before-spawn priority, and structural
        filtering to correctly classify all named regions in ``data.regions``.

        Call ``inject_anonymous_region_ids`` first to ensure that anonymous inline
        spawn regions are present in ``data.regions`` and included in the output.

        Categorisation rules (applied in priority order):

        1. Ground-truth anchoring: region IDs explicitly referenced by ``<spawn>``
           and ``<default>`` elements (including synthetic ids assigned by
           ``inject_anonymous_region_ids``) are always placed in the ``spawn`` bucket,
           regardless of how they are named.

        2. Wool-before-spawn priority: the ``wool`` pattern is tested *before* the
           ``spawn`` pattern so that item-spawner drop regions whose IDs contain both
           keywords (e.g. ``cyan-wool-spawn``) land in ``wool`` rather than ``spawn``.

        3. Structural filtering: ``negative``/``complement`` regions whose IDs match
           the spawn pattern are placed in ``other`` rather than ``spawn``, since they
           represent the *complement* of spawn areas (e.g. ``not-spawns`` used for
           kit-reset rules) and are not meaningful team-spawn configuration items.

        Returns:
            Dictionary mapping category names (``spawn``, ``wool``, ``build``,
            ``other``) to lists of region IDs.
        """
        # Collect definitive player / observer spawn region IDs from structured data
        team_spawn_ids: set[str] = set()
        for spawn in data.spawns:
            if spawn.region and spawn.region.id:
                team_spawn_ids.add(spawn.region.id)
        if (data.observer_spawn
                and data.observer_spawn.region
                and data.observer_spawn.region.id):
            team_spawn_ids.add(data.observer_spawn.region.id)

        spawn_pattern = re.compile(r'spawn', re.IGNORECASE)
        wool_pattern  = re.compile(r'wool',  re.IGNORECASE)
        build_pattern = re.compile(r'build|height|limit', re.IGNORECASE)

        categories: dict[str, list[str]] = {
            'spawn': [],
            'wool':  [],
            'build': [],
            'other': [],
        }

        for region_id, region in data.regions.items():
            if region_id in team_spawn_ids:
                # Definitive player / observer spawn — always in spawn regardless of name
                categories['spawn'].append(region_id)
            elif wool_pattern.search(region_id):
                # Wool checked BEFORE spawn: catches *-wool-spawn naming patterns
                categories['wool'].append(region_id)
            elif spawn_pattern.search(region_id):
                if region.region_type in ('negative', 'complement'):
                    # Complement utility regions (e.g. not-spawns) are not team-spawn
                    # configuration items; exclude them from the spawn bucket
                    categories['other'].append(region_id)
                else:
                    # Protection rectangles, unions, etc. → shown in Teams
                    categories['spawn'].append(region_id)
            elif build_pattern.search(region_id):
                categories['build'].append(region_id)
            else:
                categories['other'].append(region_id)

        return categories
