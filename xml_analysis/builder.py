"""
Builder for map data from XML configuration.

Parses teams, spawns, wools, regions, and other map elements from XML files,
returning a populated MapData dataclass.
"""

import xml.etree.ElementTree as ET
import re
from typing import List, Dict, Tuple, Optional

from .datatypes import MapData, Team, Spawn, Wool, ApplyRule
from .regions import (
    Region, RectangleRegion, CuboidRegion, CylinderRegion, CircleRegion,
    SphereRegion, BlockRegion, PointRegion, UnionRegion, NegativeRegion,
    ComplementRegion, IntersectRegion, RegionReference, EverywhereRegion, AboveRegion,
    MirrorRegion, TranslateRegion,
)


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

        # Parse basic info
        data.name = self._get_text('name', '')
        data.version = self._get_text('version', '')
        data.objective = self._get_text('objective', '')

        # Parse teams
        data.teams = self._parse_teams()

        # Parse spawns
        data.spawns = self._parse_spawns()

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

    def _parse_teams(self) -> List[Team]:
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
                name=team_elem.text or '',
                dye_color=team_elem.get('dye-color', '')
            )
            teams.append(team)

        return teams

    def _parse_spawns(self) -> List[Spawn]:
        """Parse spawn elements."""
        spawns = []
        spawns_elem = self.root.find('spawns')
        if spawns_elem is None:
            return spawns

        for spawn_elem in spawns_elem.findall('spawn'):
            region = None
            # Check for region attribute (e.g. <spawn region="blue-spawn-point"/>)
            region_attr = spawn_elem.get('region', '')
            if region_attr:
                region = RegionReference(ref_id=region_attr)
            else:
                # Try singular <region> child first, then plural <regions>
                region_elem = spawn_elem.find('region')
                if region_elem is None:
                    region_elem = spawn_elem.find('regions')
                if region_elem is not None:
                    region = self._parse_region_element(region_elem)

            spawn = Spawn(
                team=spawn_elem.get('team', ''),
                kit=spawn_elem.get('kit', ''),
                yaw=float(spawn_elem.get('yaw', '0')),
                region=region
            )
            spawns.append(spawn)

        return spawns

    @staticmethod
    def _resolve_spawn_regions(data: MapData):
        """Resolve RegionReference objects on spawns now that regions are parsed."""
        for spawn in data.spawns:
            if isinstance(spawn.region, RegionReference) and spawn.region.ref_id in data.regions:
                spawn.region = data.regions[spawn.region.ref_id]

    def _parse_wools(self) -> List[Wool]:
        """Parse wool elements."""
        wools = []
        wools_elem = self.root.find('wools')
        if wools_elem is None:
            return wools

        for wool_elem, inherited_team in self._collect_wool_elements(wools_elem):
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

    def _collect_wool_elements(self, parent, inherited_team: str = '') -> list:
        """Collect (wool_element, team) pairs, resolving nested <wools team=...> grouping."""
        results = []
        for child in parent:
            if child.tag == 'wool':
                results.append((child, inherited_team))
            elif child.tag == 'wools':
                team = child.get('team', '') or inherited_team
                results.extend(self._collect_wool_elements(child, team))
        return results

    def _parse_regions(self) -> Tuple[Dict[str, Region], List[ApplyRule]]:
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
    def _register_nested_regions(regions: Dict[str, 'Region']):
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
            return int(elem.text)
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

    def _parse_coords(self, coord_str: str) -> Tuple[float, float, float]:
        """Parse coordinate string 'x,y,z'."""
        parts = coord_str.split(',')
        if len(parts) >= 3:
            return (
                Region.parse_value(parts[0]),
                Region.parse_value(parts[1]),
                Region.parse_value(parts[2])
            )
        return (0, 0, 0)

    def _parse_coords_2d(self, coord_str: str) -> Tuple[float, float]:
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

    def identify_region_categories(self, data: MapData) -> Dict[str, List[str]]:
        """
        Identify region categories using regex patterns on region IDs.

        Returns:
            Dictionary mapping category names to lists of region IDs
        """
        categories = {
            'spawn': [],
            'wool': [],
            'build': [],
            'other': []
        }

        # Regex patterns for categorization
        spawn_pattern = re.compile(r'spawn', re.IGNORECASE)
        wool_pattern = re.compile(r'wool', re.IGNORECASE)
        build_pattern = re.compile(r'build|height|limit', re.IGNORECASE)

        for region_id in data.regions.keys():
            if spawn_pattern.search(region_id):
                categories['spawn'].append(region_id)
            elif wool_pattern.search(region_id):
                categories['wool'].append(region_id)
            elif build_pattern.search(region_id):
                categories['build'].append(region_id)
            else:
                categories['other'].append(region_id)

        return categories
