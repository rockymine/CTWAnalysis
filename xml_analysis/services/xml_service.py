"""XML parsing orchestration."""

from pathlib import Path

from xml_analysis import MapXMLParser, MapDataEncoder


def analyze_xml(map_folder: Path, force_rerun: bool = False, output_dir: Path = None):
    """
    Step 3: Parse XML configuration and extract map data.

    Args:
        map_folder: Path to map folder (read-only input).
        force_rerun: If True, regenerate even if JSON file exists.
        output_dir: Where to write map_data.json (default: map_folder).

    Returns:
        Path: Path to generated JSON file
    """
    out = Path(output_dir) if output_dir else map_folder

    print(f"\n[4/5] XML Analysis: {map_folder.name}")
    print("=" * 70)

    # Define paths
    xml_file = map_folder / 'map.xml'
    json_file = out / 'map_data.json'

    # Check if JSON already exists
    if json_file.exists() and not force_rerun:
        print(f"  Map data already exists: {json_file.name}")
        return json_file

    # Check if XML exists
    if not xml_file.exists():
        print(f"  [X] No XML file found at {xml_file}")
        return None

    print(f"  Parsing XML: {xml_file.name}")

    try:
        # Parse XML
        parser = MapXMLParser(str(xml_file))
        map_data = parser.parse()
        categories = parser.identify_region_categories(map_data)

        # Save JSON
        MapDataEncoder.save_json(map_data, str(json_file), categories)

        print(f"    [OK] Saved {json_file.name}")
        print(f"      - Teams: {len(map_data.teams)}")
        print(f"      - Spawns: {len(map_data.spawns)}")
        print(f"      - Wools: {len(map_data.wools)}")
        print(f"      - Regions: {len(map_data.regions)}")

        return json_file

    except Exception as e:
        print(f"  [X] Failed to parse XML: {e}")
        return None
