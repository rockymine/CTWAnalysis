"""
Unit tests for XML parser.

Tests parsing of teams, spawns, wools, regions, and region categorization.
"""

import unittest
import tempfile
import os
from pathlib import Path

from xml_analysis.parser import MapXMLParser
from xml_analysis.regions import RectangleRegion, CuboidRegion, UnionRegion, BlockRegion


class TestRegionParsing(unittest.TestCase):
    """Test region value parsing."""

    def test_parse_normal_value(self):
        """Test parsing normal numeric values."""
        from xml_analysis.regions import Region
        self.assertEqual(Region.parse_value("123"), 123.0)
        self.assertEqual(Region.parse_value("-45.5"), -45.5)
        self.assertEqual(Region.parse_value("0"), 0.0)

    def test_parse_infinity(self):
        """Test parsing infinity values."""
        from xml_analysis.regions import Region
        self.assertTrue(Region.parse_value("oo") == float('inf'))
        self.assertTrue(Region.parse_value("OO") == float('inf'))
        self.assertTrue(Region.parse_value("-oo") == float('-inf'))

    def test_parse_variable(self):
        """Test parsing variable placeholders."""
        from xml_analysis.regions import Region
        self.assertEqual(Region.parse_value("$var"), 0.0)


class TestMapXMLParser(unittest.TestCase):
    """Test map XML parsing."""

    def setUp(self):
        """Create a temporary XML file for testing."""
        self.temp_xml = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.xml')
        self.temp_xml.write("""<?xml version="1.0"?>
<map proto="1.5.0">
<name>Test Map</name>
<version>1.0.0</version>
<objective>Test objective</objective>
<teams>
    <team id="red" color="dark red" max="16">Red Team</team>
    <team id="blue" color="blue" max="16">Blue Team</team>
</teams>
<spawns>
    <spawn team="red" kit="spawn-kit" yaw="90">
        <region>
            <cuboid min="10,5,10" max="12,5,12"/>
        </region>
    </spawn>
    <spawn team="blue" kit="spawn-kit" yaw="-90">
        <region>
            <cuboid min="-10,5,-10" max="-12,5,-12"/>
        </region>
    </spawn>
</spawns>
<wools>
    <wool team="red" color="cyan" location="5,10,5">
        <monument>
            <block>15,10,15</block>
        </monument>
    </wool>
    <wool team="blue" color="orange" location="-5,10,-5">
        <monument>
            <block>-15,10,-15</block>
        </monument>
    </wool>
</wools>
<regions>
    <rectangle id="red-spawn" min="0,0" max="20,20"/>
    <rectangle id="blue-spawn" min="-20,-20" max="0,0"/>
    <union id="wool-rooms">
        <rectangle id="red-wool-room" min="0,0" max="10,10"/>
        <rectangle id="blue-wool-room" min="-10,-10" max="0,0"/>
    </union>
</regions>
<maxbuildheight>30</maxbuildheight>
</map>""")
        self.temp_xml.close()

    def tearDown(self):
        """Remove temporary XML file."""
        os.unlink(self.temp_xml.name)

    def test_parse_basic_info(self):
        """Test parsing basic map information."""
        parser = MapXMLParser(self.temp_xml.name)
        data = parser.parse()

        self.assertEqual(data.name, "Test Map")
        self.assertEqual(data.version, "1.0.0")
        self.assertEqual(data.objective, "Test objective")

    def test_parse_teams(self):
        """Test parsing team elements."""
        parser = MapXMLParser(self.temp_xml.name)
        data = parser.parse()

        self.assertEqual(len(data.teams), 2)

        red_team = next((t for t in data.teams if t.id == 'red'), None)
        self.assertIsNotNone(red_team)
        self.assertEqual(red_team.color, 'dark red')
        self.assertEqual(red_team.max_players, 16)
        self.assertEqual(red_team.name, 'Red Team')

    def test_parse_spawns(self):
        """Test parsing spawn elements."""
        parser = MapXMLParser(self.temp_xml.name)
        data = parser.parse()

        self.assertEqual(len(data.spawns), 2)

        red_spawn = next((s for s in data.spawns if s.team == 'red'), None)
        self.assertIsNotNone(red_spawn)
        self.assertEqual(red_spawn.kit, 'spawn-kit')
        self.assertEqual(red_spawn.yaw, 90.0)
        self.assertIsNotNone(red_spawn.region)
        self.assertEqual(red_spawn.region.region_type, 'cuboid')

    def test_parse_wools(self):
        """Test parsing wool elements."""
        parser = MapXMLParser(self.temp_xml.name)
        data = parser.parse()

        self.assertEqual(len(data.wools), 2)

        red_wool = next((w for w in data.wools if w.team == 'red'), None)
        self.assertIsNotNone(red_wool)
        self.assertEqual(red_wool.color, 'cyan')
        self.assertEqual(red_wool.location, (5.0, 10.0, 5.0))
        self.assertEqual(red_wool.monument, (15.0, 10.0, 15.0))

    def test_parse_rectangle_region(self):
        """Test parsing rectangle regions."""
        parser = MapXMLParser(self.temp_xml.name)
        data = parser.parse()

        self.assertIn('red-spawn', data.regions)
        region = data.regions['red-spawn']

        self.assertIsInstance(region, RectangleRegion)
        self.assertEqual(region.min_x, 0.0)
        self.assertEqual(region.min_z, 0.0)
        self.assertEqual(region.max_x, 20.0)
        self.assertEqual(region.max_z, 20.0)

    def test_region_block_bounds_expand_to_unit_edges(self):
        """XML min/max block coords should expand to unit-square extents."""
        rect = RectangleRegion(min_x=0, min_z=0, max_x=2, max_z=3)
        rect_geom = rect.to_shapely_2d((0, 0, 0, 0))
        self.assertEqual(rect_geom.bounds, (0.0, 0.0, 3.0, 4.0))

        block = BlockRegion(x=5, z=7)
        block_geom = block.to_shapely_2d((0, 0, 0, 0))
        self.assertEqual(block_geom.bounds, (5.0, 7.0, 6.0, 8.0))

    def test_parse_union_region(self):
        """Test parsing union regions."""
        parser = MapXMLParser(self.temp_xml.name)
        data = parser.parse()

        self.assertIn('wool-rooms', data.regions)
        region = data.regions['wool-rooms']

        self.assertIsInstance(region, UnionRegion)
        self.assertEqual(len(region.children), 2)

        # Check that children have IDs
        child_ids = [child.id for child in region.children]
        self.assertIn('red-wool-room', child_ids)
        self.assertIn('blue-wool-room', child_ids)

    def test_parse_max_build_height(self):
        """Test parsing max build height."""
        parser = MapXMLParser(self.temp_xml.name)
        data = parser.parse()

        self.assertEqual(data.max_build_height, 30)

    def test_identify_region_categories(self):
        """Test region categorization."""
        parser = MapXMLParser(self.temp_xml.name)
        data = parser.parse()
        categories = parser.identify_region_categories(data)

        self.assertIn('spawn', categories)
        self.assertIn('wool', categories)

        # Check spawn regions
        self.assertIn('red-spawn', categories['spawn'])
        self.assertIn('blue-spawn', categories['spawn'])

        # Check wool regions
        self.assertIn('wool-rooms', categories['wool'])


class TestRealMapParsing(unittest.TestCase):
    """Test parsing real Tumbleweed map."""

    def setUp(self):
        """Set up path to Tumbleweed map."""
        self.map_path = Path('map_folders/tumbleweed/map.xml')

    def test_parse_tumbleweed(self):
        """Test parsing Tumbleweed map if it exists."""
        if not self.map_path.exists():
            self.skipTest(f"Tumbleweed map not found at {self.map_path}")

        parser = MapXMLParser(str(self.map_path))
        data = parser.parse()

        # Verify basic info
        self.assertEqual(data.name, "Tumbleweed")
        self.assertIsNotNone(data.version)

        # Verify teams
        self.assertEqual(len(data.teams), 2)
        team_ids = [t.id for t in data.teams]
        self.assertIn('red', team_ids)
        self.assertIn('blue', team_ids)

        # Verify spawns
        self.assertGreaterEqual(len(data.spawns), 2)

        # Verify wools
        self.assertEqual(len(data.wools), 4)

        # Verify regions
        self.assertGreater(len(data.regions), 0)

        # Verify max build height
        self.assertEqual(data.max_build_height, 29)

        print(f"\nTumbleweed map parsed successfully:")
        print(f"  Teams: {len(data.teams)}")
        print(f"  Spawns: {len(data.spawns)}")
        print(f"  Wools: {len(data.wools)}")
        print(f"  Regions: {len(data.regions)}")

    def test_tumbleweed_region_categories(self):
        """Test categorizing Tumbleweed regions."""
        if not self.map_path.exists():
            self.skipTest(f"Tumbleweed map not found at {self.map_path}")

        parser = MapXMLParser(str(self.map_path))
        data = parser.parse()
        categories = parser.identify_region_categories(data)

        # Should have spawn regions
        self.assertGreater(len(categories['spawn']), 0)

        # Should have wool regions
        self.assertGreater(len(categories['wool']), 0)

        print(f"\nTumbleweed region categories:")
        for cat, regions in categories.items():
            if regions:
                print(f"  {cat}: {regions}")


if __name__ == '__main__':
    unittest.main()
