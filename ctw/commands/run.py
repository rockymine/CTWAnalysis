"""'run' subcommand — full analysis pipeline."""

import argparse
from pathlib import Path

from ctw.common import collect_map_folders


def register(subparsers):
    p = subparsers.add_parser(
        'run', help='Run the full analysis pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument('--map', help='Map name to analyze')
    p.add_argument('--all', action='store_true', help='Analyze all maps')
    p.add_argument('--force', action='store_true', help='Force regeneration')
    p.add_argument('--no-layout', action='store_true', help='Skip layout analysis')
    p.add_argument('--no-islands', action='store_true', help='Skip island analysis')
    p.add_argument('--no-xml', action='store_true', help='Skip XML analysis')
    p.add_argument('--no-matches', action='store_true', help='Skip match analysis')
    p.add_argument('--match-history', default='match_logs/match_history.txt',
                   help='Path to match history file')
    p.add_argument('--island-layout', choices=['bedrock', 'y0', 'top', 'density'],
                   default='bedrock', help='Layout file for island analysis')
    p.add_argument('--canonical-triangulation', action='store_true',
                   help='Use canonical-consistent triangulation')
    p.set_defaults(func=handler)


def handler(args):
    from layout_analysis.services import analyze_layout, analyze_islands_step
    from xml_analysis.services import analyze_xml

    map_folders = collect_map_folders(args)
    match_history_path = Path(args.match_history)

    print("=" * 70)
    print("CTW ANALYSIS WORKFLOW")
    print("=" * 70)
    print(f"Maps to analyze: {len(map_folders)}")
    for folder in map_folders:
        print(f"  - {folder.name}")
    print()

    for map_folder in map_folders:
        print(f"\n{'=' * 70}")
        print(f"Processing: {map_folder.name}")
        print(f"{'=' * 70}")

        if not args.no_layout:
            analyze_layout(map_folder, force_rerun=args.force)
        else:
            print("\n[1/4] Layout Analysis: SKIPPED")

        if not args.no_islands:
            analyze_islands_step(
                map_folder, force_rerun=args.force,
                layout_type=args.island_layout,
                canonical_triangulation=args.canonical_triangulation,
            )
        else:
            print("\n[2/4] Island Analysis: SKIPPED")

        if not args.no_xml:
            analyze_xml(map_folder, force_rerun=args.force)
        else:
            print("\n[3/4] XML Analysis: SKIPPED")

        if not args.no_matches:
            print(f"\n[4/4] Match Analysis: Currently not supported")
        else:
            print("\n[4/4] Match Analysis: Currently not supported")

    print(f"\n{'=' * 70}")
    print("WORKFLOW COMPLETE")
    print(f"{'=' * 70}\n")
