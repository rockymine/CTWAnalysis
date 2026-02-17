"""'info' subcommand — show analysis status for a map."""

import json

from ctw.common import resolve_map_folder, resolve_output_dir


def register(subparsers, map_parent):
    p = subparsers.add_parser(
        'info', parents=[map_parent],
        help='Show analysis status for a map',
    )
    p.add_argument('--json', action='store_true',
                   help='Output raw JSON from map_context.json')
    p.set_defaults(func=handler)


def handler(args):
    map_folder = resolve_map_folder(args.map)
    map_output_dir = resolve_output_dir(map_folder, create=False)

    def _find_file(rel_path):
        """Check map_output_dir first, fall back to map_folder."""
        p = map_output_dir / rel_path
        if p.exists():
            return p
        p = map_folder / rel_path
        if p.exists():
            return p
        return None

    # Check output files
    files = {
        'layout_y0.parquet': 'Layout Y0',
        'layout_bedrock.parquet': 'Layout Bedrock',
        'layout_top_surface.parquet': 'Layout Top Surface',
        'layout_vertical_density.parquet': 'Layout Vertical Density',
        'map_data.json': 'XML Data',
        'map_graph.json': 'Map Graph',
        'map_context.json': 'Map Context',
        'island_analysis/island_report.txt': 'Island Report',
    }

    ctx_path = _find_file('map_context.json')
    ctx = None
    if ctx_path:
        with open(ctx_path) as f:
            ctx = json.load(f)

    if args.json:
        if ctx:
            print(json.dumps(ctx, indent=2))
        else:
            print("{}")
        return

    print(f"Map: {map_folder.name}")
    print(f"Path: {map_folder}")
    print(f"Output: {map_output_dir}")
    print()

    # File status
    print("Output files:")
    for rel_path, label in files.items():
        found = _find_file(rel_path)
        status = "OK" if found else "--"
        print(f"  [{status:2s}] {label}")

    # Matches
    matches_dir = map_output_dir / 'match_analysis'
    if not matches_dir.exists():
        matches_dir = map_folder / 'matches'
    if matches_dir.exists():
        match_files = list(matches_dir.glob('trace_*.png'))
        if match_files:
            print(f"\n  [{len(match_files):2d}] Match trace images")
    print()

    # Summary from map_context
    if ctx:
        print(f"Map name:    {ctx.get('map_name', 'N/A')}")
        print(f"Version:     {ctx.get('map_version', 'N/A')}")
        print(f"Objective:   {ctx.get('objective', 'N/A')}")
        print(f"Total blocks: {ctx.get('total_blocks', 0):,}")
        print(f"Islands:     {ctx.get('island_count', 0)}")

        teams = ctx.get('teams', [])
        if teams:
            team_str = ', '.join(f"{t['name']} ({t['color']})" for t in teams)
            print(f"Teams:       {team_str}")

        skel = ctx.get('skeleton', {})
        if skel:
            print(f"Skeleton:    {skel.get('total_nodes', 0)} nodes, "
                  f"{skel.get('total_edges', 0)} edges, "
                  f"{skel.get('unique_canonical_shapes', 0)} unique shapes")

        br = ctx.get('build_region')
        if br:
            print(f"Build region: source={br['source']}, "
                  f"void_area={br['buildable_void_area']}")

        bb = ctx.get('bounding_box')
        if bb:
            print(f"Bounding box: X[{bb[0]:.0f}, {bb[1]:.0f}] Z[{bb[2]:.0f}, {bb[3]:.0f}]")
    else:
        print("No map_context.json found. Run island analysis first.")
