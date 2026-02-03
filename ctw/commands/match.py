"""'match' subcommand — analyze a single match."""

import json
import sys
from pathlib import Path

from ctw.common import resolve_map_folder


def register(subparsers, map_parent):
    p = subparsers.add_parser(
        'match', parents=[map_parent],
        help='Analyze a single match',
    )
    p.add_argument('--match', required=True,
                   help='Match parquet filename')
    p.add_argument('--output', help='Override output directory')
    p.add_argument('--no-team-networks', action='store_true',
                   help='Skip team-specific path networks')
    p.add_argument('--no-pdf', action='store_true',
                   help='Skip PDF report generation')
    p.add_argument('--no-classification', action='store_true',
                   help='Skip segment classification')
    p.add_argument('--resolution', type=float, default=1.0,
                   help='Grid resolution for path networks (default: 1.0)')
    p.add_argument('--cluster-radius', type=float, default=5.0,
                   help='Waypoint clustering radius (default: 5.0)')
    p.set_defaults(func=handler)


def handler(args):
    map_folder = resolve_map_folder(args.map)
    bedrock_path = map_folder / 'layout_bedrock.parquet'

    if not bedrock_path.exists():
        print(f"Error: Bedrock layout not found at {bedrock_path}", file=sys.stderr)
        print("  Run layout extraction first: python ctw.py layout --map " + args.map)
        sys.exit(1)

    match_id = args.match.replace('.parquet', '')
    output_dir = Path(args.output) if args.output else map_folder / 'matches' / match_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load map name from map_data.json if available
    json_file = map_folder / 'map_data.json'
    if json_file.exists():
        with open(json_file) as f:
            map_name = json.load(f).get('name', map_folder.name)
    else:
        map_name = map_folder.name

    from match_analysis.services import analyze_single_match
    success = analyze_single_match(map_name, args.match, bedrock_path, output_dir)

    if not success:
        print("Match analysis failed.", file=sys.stderr)
        sys.exit(1)

    # Path networks with custom params
    if not args.no_team_networks:
        try:
            from generate_path_networks import generate_path_networks
            generate_path_networks(
                match_file=args.match,
                bedrock_parquet=str(bedrock_path),
                output_dir=str(output_dir),
                resolution=args.resolution,
                cluster_radius=args.cluster_radius,
                generate_team_networks=True,
            )
        except Exception as e:
            print(f"  [!] Path network generation failed: {e}")

    print(f"  Match analysis saved to: {output_dir}")
