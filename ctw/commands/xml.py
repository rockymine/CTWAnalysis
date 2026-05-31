"""'xml' subcommand — parse map XML configuration."""

import logging
import sys

logger = logging.getLogger('ctw')

from xml_analysis.pipeline import analyze_xml
from ctw.common import resolve_map_folder, resolve_output_dir


def register(subparsers, map_parent):
    p = subparsers.add_parser(
        'xml', parents=[map_parent],
        help='Parse map XML configuration',
    )
    p.set_defaults(func=handler)


def handler(args):
    map_folder = resolve_map_folder(args.map)
    xml_path = map_folder / 'map.xml'

    if not xml_path.exists():
        print(f"Error: No map.xml found at {xml_path}", file=sys.stderr)
        sys.exit(1)

    map_output_dir = resolve_output_dir(map_folder, create=True)
    analyze_xml(map_folder, force_rerun=args.force, output_dir=map_output_dir)
