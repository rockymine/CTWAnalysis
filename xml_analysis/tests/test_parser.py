"""
Unit tests for XML parser.

Tests parsing of teams, spawns, wools, regions, and region categorization.
"""

import unittest
import tempfile
import os
from pathlib import Path

from xml_analysis.parser import MapXMLParser
from xml_analysis.regions import (
    RectangleRegion, CuboidRegion, UnionRegion, BlockRegion,
    MirrorRegion, TranslateRegion,
)


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
        """XML rectangle uses corner coords; block regions expand to unit-square extents."""
        rect = RectangleRegion(min_x=0, min_z=0, max_x=2, max_z=3)
        rect_geom = rect.to_shapely_2d((0, 0, 0, 0))
        self.assertEqual(rect_geom.bounds, (0.0, 0.0, 2.0, 3.0))

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


class TestMirrorAndTranslateRegions(unittest.TestCase):
    """Test mirror and translate region parsing and geometry."""

    def _make_xml(self, regions_xml, wools_xml=""):
        f = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.xml')
        f.write(f"""<?xml version="1.0"?>
<map proto="1.5.0">
<name>Mirror Test</name>
<version>1.0.0</version>
<objective>Test</objective>
<teams>
    <team id="red" color="dark red" max="8">Red</team>
    <team id="blue" color="blue" max="8">Blue</team>
</teams>
<regions>
{regions_xml}
</regions>
{wools_xml}
</map>""")
        f.close()
        return f.name

    def test_parse_mirror_attribute_form(self):
        """Mirror with region= attribute referencing another region by ID."""
        path = self._make_xml("""
            <rectangle id="red-spawn" min="10,20" max="30,40"/>
            <mirror id="blue-spawn" region="red-spawn" origin="0,0,0" normal="1,0,0"/>
        """)
        try:
            data = MapXMLParser(path).parse()
            self.assertIn('blue-spawn', data.regions)
            region = data.regions['blue-spawn']
            self.assertIsInstance(region, MirrorRegion)
            self.assertEqual(region.ref_region_id, 'red-spawn')
            self.assertEqual(region.normal_x, 1.0)
            self.assertEqual(region.normal_z, 0.0)
        finally:
            os.unlink(path)

    def test_parse_mirror_child_form(self):
        """Mirror with inline child region."""
        path = self._make_xml("""
            <mirror id="mirrored" origin="0,0,0" normal="0,0,1">
                <rectangle min="10,20" max="30,40"/>
            </mirror>
        """)
        try:
            data = MapXMLParser(path).parse()
            self.assertIn('mirrored', data.regions)
            region = data.regions['mirrored']
            self.assertIsInstance(region, MirrorRegion)
            self.assertIsNotNone(region.source)
            self.assertIsInstance(region.source, RectangleRegion)
        finally:
            os.unlink(path)

    def test_mirror_x_geometry(self):
        """Mirror across X axis: x' = 2*origin_x - x, z unchanged."""
        rect = RectangleRegion(min_x=10, min_z=20, max_x=30, max_z=40)
        mirror = MirrorRegion(
            source=rect, origin_x=0, origin_z=0,
            normal_x=1, normal_y=0, normal_z=0,
        )
        bounds = (-100, -100, 100, 100)
        geom = mirror.to_shapely_2d(bounds)
        # rect (10,20)-(30,40) mirrored across x=0 → (-30,20)-(-10,40)
        self.assertAlmostEqual(geom.bounds[0], -30.0)
        self.assertAlmostEqual(geom.bounds[1], 20.0)
        self.assertAlmostEqual(geom.bounds[2], -10.0)
        self.assertAlmostEqual(geom.bounds[3], 40.0)

    def test_mirror_z_geometry(self):
        """Mirror across Z axis: z' = 2*origin_z - z, x unchanged."""
        rect = RectangleRegion(min_x=10, min_z=20, max_x=30, max_z=40)
        mirror = MirrorRegion(
            source=rect, origin_x=0, origin_z=0,
            normal_x=0, normal_y=0, normal_z=1,
        )
        bounds = (-100, -100, 100, 100)
        geom = mirror.to_shapely_2d(bounds)
        # z mirrored: (10,-40)-(30,-20)
        self.assertAlmostEqual(geom.bounds[0], 10.0)
        self.assertAlmostEqual(geom.bounds[1], -40.0)
        self.assertAlmostEqual(geom.bounds[2], 30.0)
        self.assertAlmostEqual(geom.bounds[3], -20.0)

    def test_mirror_xz_geometry(self):
        """Mirror across both X and Z axes."""
        rect = RectangleRegion(min_x=10, min_z=20, max_x=30, max_z=40)
        mirror = MirrorRegion(
            source=rect, origin_x=0, origin_z=0,
            normal_x=1, normal_y=0, normal_z=1,
        )
        bounds = (-100, -100, 100, 100)
        geom = mirror.to_shapely_2d(bounds)
        # both mirrored: (-30,-40)-(-10,-20)
        self.assertAlmostEqual(geom.bounds[0], -30.0)
        self.assertAlmostEqual(geom.bounds[1], -40.0)
        self.assertAlmostEqual(geom.bounds[2], -10.0)
        self.assertAlmostEqual(geom.bounds[3], -20.0)

    def test_mirror_with_nonzero_origin(self):
        """Mirror with origin not at (0,0)."""
        rect = RectangleRegion(min_x=0, min_z=0, max_x=10, max_z=10)
        mirror = MirrorRegion(
            source=rect, origin_x=20, origin_z=0,
            normal_x=1, normal_y=0, normal_z=0,
        )
        bounds = (-100, -100, 100, 100)
        geom = mirror.to_shapely_2d(bounds)
        # x' = 2*20 - x → (0,0)→40, (10,0)→30 → bounds (30,0)-(40,10)
        self.assertAlmostEqual(geom.bounds[0], 30.0)
        self.assertAlmostEqual(geom.bounds[1], 0.0)
        self.assertAlmostEqual(geom.bounds[2], 40.0)
        self.assertAlmostEqual(geom.bounds[3], 10.0)

    def test_mirror_ref_resolution(self):
        """Mirror resolves source via registry when using ref_region_id."""
        rect = RectangleRegion(id='src', min_x=10, min_z=20, max_x=30, max_z=40)
        mirror = MirrorRegion(
            ref_region_id='src', origin_x=0, origin_z=0,
            normal_x=1, normal_y=0, normal_z=0,
        )
        bounds = (-100, -100, 100, 100)
        registry = {'src': rect}
        geom = mirror.to_shapely_2d(bounds, registry)
        self.assertAlmostEqual(geom.bounds[0], -30.0)
        self.assertAlmostEqual(geom.bounds[2], -10.0)

    def test_parse_translate_child_form(self):
        """Translate with inline child region."""
        path = self._make_xml("""
            <rectangle id="base" min="10,20" max="30,40"/>
            <union id="shifted">
                <region id="base"/>
                <translate offset="5,0,10"><region id="base"/></translate>
            </union>
        """)
        try:
            data = MapXMLParser(path).parse()
            self.assertIn('shifted', data.regions)
            union = data.regions['shifted']
            self.assertEqual(len(union.children), 2)
            self.assertIsInstance(union.children[1], TranslateRegion)
        finally:
            os.unlink(path)

    def test_translate_geometry(self):
        """Translate shifts geometry by offset."""
        rect = RectangleRegion(min_x=10, min_z=20, max_x=30, max_z=40)
        translated = TranslateRegion(
            source=rect, offset_x=5, offset_y=0, offset_z=-10,
        )
        bounds = (-100, -100, 100, 100)
        geom = translated.to_shapely_2d(bounds)
        # (10,20)-(30,40) shifted by (5,-10) → (15,10)-(35,30)
        self.assertAlmostEqual(geom.bounds[0], 15.0)
        self.assertAlmostEqual(geom.bounds[1], 10.0)
        self.assertAlmostEqual(geom.bounds[2], 35.0)
        self.assertAlmostEqual(geom.bounds[3], 30.0)

    def test_parse_ad_astra_mirrors(self):
        """Ad Astra map should have mirror regions parsed inside unions."""
        xml_path = Path('xml_examples/ad_astra.xml')
        if not xml_path.exists():
            self.skipTest("ad_astra.xml not found")
        data = MapXMLParser(str(xml_path)).parse()
        # water-lanes union should contain mirror children
        water_lanes = data.regions['water-lanes']
        child_ids = [c.id for c in water_lanes.children]
        self.assertIn('yellow-water-lane', child_ids)
        yellow = next(c for c in water_lanes.children if c.id == 'yellow-water-lane')
        self.assertIsInstance(yellow, MirrorRegion)
        # blue-wool-rooms should now have mirror children (was empty before)
        wool_rooms = data.regions['wool-rooms']
        blue_rooms = next(c for c in wool_rooms.children if c.id == 'blue-wool-rooms')
        self.assertEqual(len(blue_rooms.children), 2)
        self.assertIsInstance(blue_rooms.children[0], MirrorRegion)

    def test_ad_astra_mirror_geometry(self):
        """Ad Astra mirrored water lanes should produce valid geometry."""
        xml_path = Path('xml_examples/ad_astra.xml')
        if not xml_path.exists():
            self.skipTest("ad_astra.xml not found")
        data = MapXMLParser(str(xml_path)).parse()
        bounds = (-300, -300, 100, 200)
        # Resolve via the water-lanes union and registry
        water_lanes = data.regions['water-lanes']
        orange = next(c for c in water_lanes.children if c.id == 'orange-water-lane')
        yellow = next(c for c in water_lanes.children if c.id == 'yellow-water-lane')
        orange_geom = orange.to_shapely_2d(bounds, data.regions)
        yellow_geom = yellow.to_shapely_2d(bounds, data.regions)
        # Both should be non-empty with same area
        self.assertFalse(orange_geom.is_empty)
        self.assertFalse(yellow_geom.is_empty)
        self.assertAlmostEqual(orange_geom.area, yellow_geom.area, places=1)


if __name__ == '__main__':
    unittest.main()
