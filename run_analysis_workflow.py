"""
Main workflow script for CTW map and match analysis.

Orchestrates the complete analysis pipeline:
1. Layout extraction from world folders (if not already done)
2. XML parsing to extract map configuration
3. Match analysis using layout data and XML configuration

This script is a thin wrapper that delegates to the services layer.
The canonical implementations live in:
  - layout_analysis.services.layout_service
  - layout_analysis.services.islands_service
  - xml_analysis.services.xml_service
  - match_analysis.services.match_service
"""

import argparse
import sys
from pathlib import Path

# Re-export service functions so existing imports continue to work.
from layout_analysis.services.layout_service import analyze_layout
from layout_analysis.services.islands_service import analyze_islands_step
from xml_analysis.services.xml_service import analyze_xml
from match_analysis.services.match_service import (
    parse_match_history,
    analyze_single_match,
    analyze_matches,
)


def main():
    parser = argparse.ArgumentParser(
        description='CTW Map and Match Analysis Workflow',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Workflow Steps:
  1. Layout Analysis - Extract block data from world folders
  2. Island Analysis - Detect and triangulate islands from bedrock
  3. XML Analysis - Parse map configuration from XML
  4. Match Analysis - Analyze matches using layout and XML data

Examples:
  # Analyze a single map (all steps)
  python run_analysis_workflow.py --map tumbleweed

  # Analyze specific map with force rerun
  python run_analysis_workflow.py --map kanto --force

  # Analyze all maps
  python run_analysis_workflow.py --all

  # Skip match analysis
  python run_analysis_workflow.py --map tumbleweed --no-matches

  # Skip island analysis
  python run_analysis_workflow.py --map tumbleweed --no-islands
        """
    )

    parser.add_argument(
        '--map',
        help='Map name to analyze (e.g., tumbleweed, kanto)'
    )

    parser.add_argument(
        '--all',
        action='store_true',
        help='Analyze all maps in map_folders directory'
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='Force regeneration of existing files'
    )

    parser.add_argument(
        '--no-layout',
        action='store_true',
        help='Skip layout analysis'
    )

    parser.add_argument(
        '--no-islands',
        action='store_true',
        help='Skip island detection and triangulation'
    )

    parser.add_argument(
        '--no-xml',
        action='store_true',
        help='Skip XML analysis'
    )

    parser.add_argument(
        '--no-matches',
        action='store_true',
        help='Skip match analysis'
    )

    parser.add_argument(
        '--match-history',
        default='match_logs/match_history.txt',
        help='Path to match history file (default: match_logs/match_history.txt)'
    )

    parser.add_argument(
        '--island-layout',
        choices=['bedrock', 'y0', 'top', 'density'],
        default='bedrock',
        help='Layout file to use for island analysis (default: bedrock)'
    )

    parser.add_argument(
        '--canonical-triangulation',
        action='store_true',
        help='Use canonical-consistent triangulation (identical islands share same mesh)'
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.map and not args.all:
        parser.print_help()
        print("\nError: Must specify either --map or --all", file=sys.stderr)
        sys.exit(1)

    # Find map folders
    map_folders_dir = Path('map_folders')
    if not map_folders_dir.exists():
        print(f"Error: Map folders directory not found: {map_folders_dir}", file=sys.stderr)
        sys.exit(1)

    # Determine which maps to analyze
    if args.all:
        map_folders = [f for f in map_folders_dir.iterdir() if f.is_dir()]
    else:
        map_folder = map_folders_dir / args.map
        if not map_folder.exists():
            print(f"Error: Map folder not found: {map_folder}", file=sys.stderr)
            sys.exit(1)
        map_folders = [map_folder]

    print("=" * 70)
    print("CTW ANALYSIS WORKFLOW")
    print("=" * 70)
    print(f"Maps to analyze: {len(map_folders)}")
    for folder in map_folders:
        print(f"  - {folder.name}")
    print()

    # Match history file
    match_history_path = Path(args.match_history)

    # Process each map
    for map_folder in map_folders:
        print(f"\n{'=' * 70}")
        print(f"Processing: {map_folder.name}")
        print(f"{'=' * 70}")

        # Step 1: Layout Analysis
        if not args.no_layout:
            layout_files = analyze_layout(map_folder, force_rerun=args.force)
        else:
            print("\n[1/4] Layout Analysis: SKIPPED")

        # Step 2: Island Analysis
        if not args.no_islands:
            island_dir = analyze_islands_step(
                map_folder, force_rerun=args.force,
                layout_type=args.island_layout,
                canonical_triangulation=args.canonical_triangulation,
            )
        else:
            print("\n[2/4] Island Analysis: SKIPPED")

        # Step 3: XML Analysis
        if not args.no_xml:
            json_file = analyze_xml(map_folder, force_rerun=args.force)
        else:
            print("\n[3/4] XML Analysis: SKIPPED")

        # Step 4: Match Analysis
        if not args.no_matches:
            if match_history_path.exists():
                match_results = analyze_matches(map_folder, match_history_path)
            else:
                print(f"\n[4/4] Match Analysis: SKIPPED (match history not found)")
        else:
            print("\n[4/4] Match Analysis: SKIPPED")

    print(f"\n{'=' * 70}")
    print("WORKFLOW COMPLETE")
    print(f"{'=' * 70}\n")


if __name__ == '__main__':
    main()
