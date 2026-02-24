"""'xml' subcommand — parse map XML configuration."""

import logging
import sys

from pathlib import Path

logger = logging.getLogger('ctw')

from xml_analysis import MapXMLParser
from xml_analysis import exporter as map_data_exporter

from ctw.common import resolve_map_folder, resolve_output_dir


def register(subparsers, map_parent):
    p = subparsers.add_parser(
        'xml', parents=[map_parent],
        help='Parse map XML configuration',
    )
    p.add_argument('--visualize', action='store_true',
                   help='Generate visualization plots')
    p.add_argument('--category-plots', action='store_true',
                   help='Generate per-category region plots')
    p.add_argument('--no-summary', action='store_true', help='Skip text summary')
    p.add_argument('--no-json', action='store_true', help='Skip JSON output')
    p.set_defaults(func=handler)


def handler(args):
    map_folder = resolve_map_folder(args.map)
    xml_path = map_folder / 'map.xml'

    if not xml_path.exists():
        print(f"Error: No map.xml found at {xml_path}", file=sys.stderr)
        sys.exit(1)

    if args.visualize or args.category_plots:
        from xml_analysis import MapXMLParser, MapVisualizer
        from xml_analysis import exporter as map_data_exporter

        output_dir = resolve_output_dir(map_folder, create=True)
        parser = MapXMLParser(str(xml_path))
        map_data = parser.parse()
        categories = parser.identify_region_categories(map_data)

        visualizer = MapVisualizer(map_data)

        if not args.no_summary:
            visualizer.print_summary()

        if not args.no_json:
            json_path = output_dir / 'map_data.json'
            map_data_exporter.save(map_data, str(json_path), categories)

        map_name_safe = map_data.name.replace(' ', '_').lower()
        main_plot_path = output_dir / f'{map_name_safe}_layout.png'
        visualizer.plot_all(str(main_plot_path))

        if args.category_plots:
            visualizer.plot_by_category(str(output_dir), categories)

        logger.debug(f"  Visualizations saved to: {output_dir}")
    else:
        map_output_dir = resolve_output_dir(map_folder, create=True)
        analyze_xml(map_folder, force_rerun=args.force,
                    output_dir=map_output_dir)


def analyze_xml(map_folder: Path, force_rerun: bool = False, output_dir: Path = None):
    """Parse XML configuration and return a typed pipeline object.

    Always parses map.xml and returns a MapXmlContext for downstream
    pipeline stages.  The JSON artifact (map_data.json) is written as a
    side-effect only when it does not already exist or force_rerun is set;
    it is for human inspection and is not read back by any pipeline step.

    Args:
        map_folder: Path to map folder (read-only input).
        force_rerun: If True, overwrite map_data.json even if it exists.
        output_dir: Where to write map_data.json (default: map_folder).

    Returns:
        MapXmlContext on success, None if map.xml is missing or unparseable.
    """
    from xml_analysis.datatypes import MapXmlContext

    out = Path(output_dir) if output_dir else map_folder

    logger.debug(f"[4/6] XML Analysis: {map_folder.name}")

    xml_file = map_folder / 'map.xml'
    json_file = out / 'map_data.json'

    if not xml_file.exists():
        logger.debug(f"  No XML file found at {xml_file}")
        return None

    logger.debug(f"  Parsing XML: {xml_file.name}")

    try:
        parser = MapXMLParser(str(xml_file))
        map_data = parser.parse()
        categories = parser.identify_region_categories(map_data)
    except Exception as e:
        logger.warning(f"  Failed to parse XML: {e}")
        return None

    # Write JSON artifact (skip if already up-to-date)
    if force_rerun or not json_file.exists():
        map_data_exporter.save(map_data, str(json_file), categories)
        logger.debug(f"    Saved {json_file.name}")
    else:
        logger.debug(f"  Map data already exists: {json_file.name}")

    logger.debug(f"  Teams: {len(map_data.teams)}, Spawns: {len(map_data.spawns)}, "
                 f"Wools: {len(map_data.wools)}, Regions: {len(map_data.regions)}")

    return MapXmlContext(map_data=map_data, region_categories=categories)
