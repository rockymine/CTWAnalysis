"""
Unit tests for JSON exporter.

Tests JSON serialization of map data.
"""

import unittest
import json
import tempfile
import os
from pathlib import Path

from xml_analysis.parser import MapXMLParser
from xml_analysis.exporter import MapDataEncoder


class TestJSONExport(unittest.TestCase):
    """Test JSON export functionality."""

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
</spawns>
<wools>
    <wool team="red" color="cyan" location="5,10,5">
        <monument>
            <block>15,10,15</block>
        </monument>
    </wool>
</wools>
<regions>
    <rectangle id="test-region" min="0,0" max="20,20"/>
</regions>
<maxbuildheight>30</maxbuildheight>
</map>""")
        self.temp_xml.close()

    def tearDown(self):
        """Remove temporary XML file."""
        os.unlink(self.temp_xml.name)

    def test_json_is_valid(self):
        """Test that exported JSON is valid."""
        parser = MapXMLParser(self.temp_xml.name)
        data = parser.parse()
        categories = parser.identify_region_categories(data)

        json_str = MapDataEncoder.to_json(data, categories)

        # Should be valid JSON
        parsed = json.loads(json_str)
        self.assertIsInstance(parsed, dict)

    def test_json_contains_all_fields(self):
        """Test that JSON contains all expected fields."""
        parser = MapXMLParser(self.temp_xml.name)
        data = parser.parse()
        categories = parser.identify_region_categories(data)

        json_str = MapDataEncoder.to_json(data, categories)
        parsed = json.loads(json_str)

        # Check top-level fields
        self.assertIn('name', parsed)
        self.assertIn('version', parsed)
        self.assertIn('objective', parsed)
        self.assertIn('max_build_height', parsed)
        self.assertIn('teams', parsed)
        self.assertIn('spawns', parsed)
        self.assertIn('wools', parsed)
        self.assertIn('regions', parsed)
        self.assertIn('region_categories', parsed)

    def test_json_team_structure(self):
        """Test team JSON structure."""
        parser = MapXMLParser(self.temp_xml.name)
        data = parser.parse()

        json_str = MapDataEncoder.to_json(data)
        parsed = json.loads(json_str)

        self.assertEqual(len(parsed['teams']), 2)
        team = parsed['teams'][0]

        self.assertIn('id', team)
        self.assertIn('name', team)
        self.assertIn('color', team)
        self.assertIn('max_players', team)

    def test_json_spawn_structure(self):
        """Test spawn JSON structure."""
        parser = MapXMLParser(self.temp_xml.name)
        data = parser.parse()

        json_str = MapDataEncoder.to_json(data)
        parsed = json.loads(json_str)

        self.assertEqual(len(parsed['spawns']), 1)
        spawn = parsed['spawns'][0]

        self.assertIn('team', spawn)
        self.assertIn('kit', spawn)
        self.assertIn('yaw', spawn)
        self.assertIn('region', spawn)

        # Check region structure
        region = spawn['region']
        self.assertIn('type', region)
        self.assertEqual(region['type'], 'cuboid')

    def test_json_wool_structure(self):
        """Test wool JSON structure."""
        parser = MapXMLParser(self.temp_xml.name)
        data = parser.parse()

        json_str = MapDataEncoder.to_json(data)
        parsed = json.loads(json_str)

        self.assertEqual(len(parsed['wools']), 1)
        wool = parsed['wools'][0]

        self.assertIn('team', wool)
        self.assertIn('color', wool)
        self.assertIn('location', wool)
        self.assertIn('monument', wool)

        # Check coordinate structures
        self.assertIn('x', wool['location'])
        self.assertIn('y', wool['location'])
        self.assertIn('z', wool['location'])

    def test_json_region_structure(self):
        """Test region JSON structure."""
        parser = MapXMLParser(self.temp_xml.name)
        data = parser.parse()

        json_str = MapDataEncoder.to_json(data)
        parsed = json.loads(json_str)

        self.assertIn('test-region', parsed['regions'])
        region = parsed['regions']['test-region']

        self.assertIn('id', region)
        self.assertIn('type', region)
        self.assertIn('bounds_2d', region)
        self.assertEqual(region['type'], 'rectangle')

    def test_save_json_file(self):
        """Test saving JSON to file."""
        parser = MapXMLParser(self.temp_xml.name)
        data = parser.parse()

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            temp_json = f.name

        try:
            MapDataEncoder.save_json(data, temp_json)

            # Verify file exists and is valid JSON
            self.assertTrue(os.path.exists(temp_json))

            with open(temp_json, 'r') as f:
                parsed = json.load(f)

            self.assertIsInstance(parsed, dict)
            self.assertEqual(parsed['name'], 'Test Map')

        finally:
            os.unlink(temp_json)


class TestRealMapJSON(unittest.TestCase):
    """Test JSON export for real maps."""

    def test_tumbleweed_json(self):
        """Test JSON export for Tumbleweed map."""
        map_path = Path('map_folders/tumbleweed/map.xml')

        if not map_path.exists():
            self.skipTest(f"Tumbleweed map not found at {map_path}")

        parser = MapXMLParser(str(map_path))
        data = parser.parse()
        categories = parser.identify_region_categories(data)

        json_str = MapDataEncoder.to_json(data, categories)

        # Should be valid JSON
        parsed = json.loads(json_str)

        # Verify structure
        self.assertEqual(parsed['name'], 'Tumbleweed')
        self.assertEqual(len(parsed['teams']), 2)
        self.assertEqual(len(parsed['wools']), 4)
        self.assertEqual(parsed['max_build_height'], 29)

        print(f"\nTumbleweed JSON export successful:")
        print(f"  JSON size: {len(json_str)} bytes")
        print(f"  Teams: {len(parsed['teams'])}")
        print(f"  Spawns: {len(parsed['spawns'])}")
        print(f"  Wools: {len(parsed['wools'])}")
        print(f"  Regions: {len(parsed['regions'])}")


if __name__ == '__main__':
    unittest.main()
