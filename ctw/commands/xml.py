"""'xml' subcommand — parse map XML configuration."""

import sys

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
        from xml_analysis import MapXMLParser, MapVisualizer, MapDataEncoder

        output_dir = resolve_output_dir(map_folder, create=True)
        parser = MapXMLParser(str(xml_path))
        map_data = parser.parse()
        categories = parser.identify_region_categories(map_data)

        visualizer = MapVisualizer(map_data)

        if not args.no_summary:
            visualizer.print_summary()

        if not args.no_json:
            map_name_safe = map_data.name.replace(' ', '_').lower()
            json_path = output_dir / f'map_data.json'
            MapDataEncoder.save_json(map_data, str(json_path), categories)

        map_name_safe = map_data.name.replace(' ', '_').lower()
        main_plot_path = output_dir / f'{map_name_safe}_layout.png'
        visualizer.plot_all(str(main_plot_path))

        if args.category_plots:
            visualizer.plot_by_category(str(output_dir), categories)

        print(f"  Visualizations saved to: {output_dir}")
    else:
        from xml_analysis.services import analyze_xml
        map_output_dir = resolve_output_dir(map_folder, create=True)
        analyze_xml(map_folder, force_rerun=args.force,
                    output_dir=map_output_dir)
