"""
Main script for analyzing Minecraft map XML files.

Parses XML configuration files and generates visualizations of map regions,
including spawns, wool rooms, and build restrictions.
"""

import argparse
import sys
from pathlib import Path

from xml_analysis import MapXMLParser, MapVisualizer, MapDataEncoder


def main():
    parser = argparse.ArgumentParser(
        description='Analyze Minecraft map XML configuration and generate visualizations',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_xml_analysis.py --xml map_folders/tumbleweed/map.xml
  python run_xml_analysis.py --xml map_folders/tumbleweed/map.xml --output custom_output
  python run_xml_analysis.py --xml map_folders/tumbleweed/map.xml --category-plots
        """
    )

    parser.add_argument(
        '--xml',
        required=True,
        help='Path to map XML file'
    )

    parser.add_argument(
        '--output',
        default='output',
        help='Output directory for plots (default: output)'
    )

    parser.add_argument(
        '--category-plots',
        action='store_true',
        help='Generate separate plots for each region category'
    )

    parser.add_argument(
        '--no-summary',
        action='store_true',
        help='Skip printing text summary'
    )

    parser.add_argument(
        '--no-json',
        action='store_true',
        help='Skip generating JSON output'
    )

    args = parser.parse_args()

    # Validate XML path
    xml_path = Path(args.xml)
    if not xml_path.exists():
        print(f"Error: XML file does not exist: {args.xml}", file=sys.stderr)
        sys.exit(1)

    # Create output directory
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("MINECRAFT MAP XML ANALYSIS")
    print("=" * 70)
    print(f"XML File: {args.xml}")
    print(f"Output: {args.output}")
    print("=" * 70)

    # Parse XML
    print("\nParsing XML file...")
    try:
        xml_parser = MapXMLParser(str(xml_path))
        map_data = xml_parser.parse()
    except Exception as e:
        print(f"Error: Failed to parse XML: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Successfully parsed: {map_data.name}")

    # Create visualizer
    visualizer = MapVisualizer(map_data)

    # Identify region categories
    categories = xml_parser.identify_region_categories(map_data)

    # Print summary
    if not args.no_summary:
        visualizer.print_summary()

    # Generate JSON output
    if not args.no_json:
        print("\nGenerating JSON output...")
        map_name_safe = map_data.name.replace(' ', '_').lower()
        json_path = output_dir / f'{map_name_safe}_data.json'
        MapDataEncoder.save_json(map_data, str(json_path), categories)

    # Generate main plot
    print("\nGenerating visualizations...")
    map_name_safe = map_data.name.replace(' ', '_').lower()
    main_plot_path = output_dir / f'{map_name_safe}_layout.png'
    visualizer.plot_all(str(main_plot_path))

    # Generate category plots if requested
    if args.category_plots:
        print("\nGenerating category-specific plots...")

        print(f"Categories found:")
        for cat, regions in categories.items():
            if regions:
                print(f"  - {cat}: {len(regions)} region(s)")

        visualizer.plot_by_category(str(output_dir), categories)

    # Summary
    print("\n" + "=" * 70)
    print("ANALYSIS COMPLETE")
    print("=" * 70)
    print(f"\nResults:")
    print(f"  Teams: {len(map_data.teams)}")
    print(f"  Spawns: {len(map_data.spawns)}")
    print(f"  Wools: {len(map_data.wools)}")
    print(f"  Named Regions: {len(map_data.regions)}")
    if map_data.max_build_height:
        print(f"  Max Build Height: {map_data.max_build_height}")

    print(f"\nAll outputs saved to: {output_dir}")
    print("=" * 70)


if __name__ == '__main__':
    main()
