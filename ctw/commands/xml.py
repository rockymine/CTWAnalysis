"""'xml' subcommand — parse map XML configuration."""

import logging
import sys

from pathlib import Path

logger = logging.getLogger('ctw')

from xml_analysis.pipeline import analyze_xml
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
        parser.inject_anonymous_region_ids(map_data)
        categories = parser.identify_region_categories(map_data)

        visualizer = MapVisualizer(map_data)

        if not args.no_summary:
            visualizer.print_summary()

        if not args.no_json:
            json_path = output_dir / 'map_data.json'
            map_data_exporter.save(map_data, str(json_path), categories)

        images_dir = output_dir / 'images'
        images_dir.mkdir(exist_ok=True)
        map_name_safe = map_data.name.replace(' ', '_').lower()
        main_plot_path = images_dir / f'{map_name_safe}_layout.png'
        visualizer.plot_all(str(main_plot_path))

        if args.category_plots:
            visualizer.plot_by_category(str(images_dir), categories)

        logger.debug(f"  Visualizations saved to: {images_dir}")
    else:
        map_output_dir = resolve_output_dir(map_folder, create=True)
        analyze_xml(map_folder, force_rerun=args.force,
                    output_dir=map_output_dir)
