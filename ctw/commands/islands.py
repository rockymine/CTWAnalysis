"""'islands' subcommand — detect islands and compute skeleton graphs.

Runs the geometry pipeline only (island detection, polygon construction,
skeleton graphs, visualizations). Does not read map.xml or produce
map_context.json — run 'ctw run' for the full pipeline including assembly.

Sub-actions
-----------
(default)         Detect islands and compute skeleton graphs
profile           Compute island spatial profiles from cached JSON
profile-inspect   Print per-island feature table and classification details
profile-canonical Show canonical groupings (unique shapes + instance counts)
"""

import argparse
from pathlib import Path

from ctw.common import resolve_map_folder, resolve_output_dir, DEFAULT_OUTPUT_ROOT


def register(subparsers, map_parent):
    # Note: we do NOT use parents=[map_parent] here because profile sub-actions
    # allow --map to be optional (all maps).  --map and --force are defined
    # directly on the islands parser as optional; the detect handler validates
    # that --map is provided for the default (detect) action.
    p = subparsers.add_parser(
        'islands',
        help='Detect islands, skeleton graphs, and spatial profiling',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Sub-actions (default: detect):
  (none)            Detect islands and compute skeleton graphs
  profile           Compute/re-run island spatial profiles from cached JSON
  profile-inspect   Print feature table and classification details per island
  profile-canonical Show canonical groupings for a map

Examples:
  python ctw.py islands --map tumbleweed
  python ctw.py islands profile --map tumbleweed
  python ctw.py islands profile --map tumbleweed --plot
  python ctw.py islands profile                      # all maps
  python ctw.py islands profile-inspect --map tumbleweed
  python ctw.py islands profile-canonical --map tumbleweed
""",
    )
    # Shared flags (--map optional here; detect handler validates it)
    p.add_argument('--map', default=None,
                   help='Map name (e.g., tumbleweed) or path to map folder')
    p.add_argument('--force', action='store_true',
                   help='Force regeneration of existing outputs')
    islands_sub = p.add_subparsers(dest='islands_action', metavar='<action>')

    # Default (detect) action — keep original params on the top-level parser
    p.add_argument('--connectivity', type=int, default=8, choices=[4, 8],
                   help='Island connectivity (default: 8)')
    p.add_argument('--min-size', type=int, default=10,
                   help='Minimum island block count (default: 10)')
    p.add_argument('--buffer', type=float, default=0.0,
                   help='Buffer distance for smoothing (default: 0.0)')
    p.add_argument('--simplify', type=float, default=1.0,
                   help='Simplification tolerance (default: 1.0)')
    p.add_argument('--no-holes', action='store_true', help='Disable hole detection')
    p.add_argument('--layout', choices=['bedrock', 'y0', 'top', 'density'],
                   default='bedrock', help='Layout file to use')
    p.add_argument('--canonical-polygons', action='store_true',
                   help='Use canonical-consistent polygon construction')
    p.add_argument('--output', help='Override output directory')
    p.add_argument('--plots', action='store_true',
                   help='Generate debug plots (per-island debug, POI, pathfinding)')
    p.set_defaults(func=handler)

    # islands profile
    p_profile = islands_sub.add_parser(
        'profile',
        help='Compute island spatial profiles from cached map_context.json + map_graph.json',
    )
    p_profile.add_argument('--map', default=None,
                           help='Map slug (default: all maps with map_context.json)')
    p_profile.add_argument('--output', default=None,
                           help='Output root directory (default: output/)')
    p_profile.add_argument('--plot', action='store_true',
                           help='Also emit island_profiles.png visualization')
    p_profile.add_argument('--force', action='store_true',
                           help='Overwrite existing island_profiles.json')
    p_profile.set_defaults(func=handle_profile)

    # islands profile-inspect
    p_inspect = islands_sub.add_parser(
        'profile-inspect',
        help='Print feature table and classification details for one map',
    )
    p_inspect.add_argument('--map', required=True,
                           help='Map slug to inspect')
    p_inspect.add_argument('--output', default=None,
                           help='Output root directory (default: output/)')
    p_inspect.set_defaults(func=handle_profile_inspect)

    # islands profile-canonical
    p_canonical = islands_sub.add_parser(
        'profile-canonical',
        help='Show canonical groupings (unique shapes + instance counts) for a map',
    )
    p_canonical.add_argument('--map', required=True,
                             help='Map slug to inspect')
    p_canonical.add_argument('--output', default=None,
                             help='Output root directory (default: output/)')
    p_canonical.set_defaults(func=handle_profile_canonical)


def handler(args):
    # If a sub-action was dispatched, don't run the default detect handler
    if getattr(args, 'islands_action', None) is not None:
        return

    if not args.map:
        print('Error: --map is required for island detection')
        return

    import logging
    from ctw.log import setup_map_file_logging

    map_folder = resolve_map_folder(args.map)

    from map_analysis.pipeline import run_island_geometry
    map_output_dir = resolve_output_dir(map_folder, create=True)
    setup_map_file_logging(map_output_dir)
    run_island_geometry(
        map_folder,
        force_rerun=args.force,
        simplify_tolerance=args.simplify,
        buffer_distance=args.buffer,
        layout_type=args.layout,
        canonical_polygons=args.canonical_polygons,
        map_output_dir=map_output_dir,
        output_dir=Path(args.output) if args.output else None,
        plots=args.plots,
    )


# ---------------------------------------------------------------------------
# Profile sub-action handlers
# ---------------------------------------------------------------------------


def _resolve_profile_map_dirs(args) -> list[Path]:
    """Resolve output directories from --map and --output args."""
    output_root = Path(args.output) if args.output else DEFAULT_OUTPUT_ROOT
    map_name = getattr(args, 'map', None)
    if map_name:
        return [output_root / map_name]
    return sorted(d for d in output_root.iterdir() if d.is_dir())


def handle_profile(args) -> None:
    """Re-run island profiling on cached map_context.json + map_graph.json."""
    import json
    from island_analysis.profile import (
        profile_islands, save_profiles, plot_island_profiles, load_profiles,
    )
    from map_analysis.grid_base import _adaptive_grid_size

    map_dirs = _resolve_profile_map_dirs(args)
    processed = 0
    skipped = 0

    for map_dir in map_dirs:
        context_path = map_dir / 'map_context.json'
        graph_path = map_dir / 'map_graph.json'
        profiles_path = map_dir / 'island_profiles.json'

        if not context_path.exists() or not graph_path.exists():
            skipped += 1
            continue

        if profiles_path.exists() and not getattr(args, 'force', False):
            print(f'  [skip] {map_dir.name}: island_profiles.json exists (use --force to overwrite)')
            skipped += 1
            continue

        try:
            with open(context_path, encoding='utf-8') as fh:
                map_context = json.load(fh)
            with open(graph_path, encoding='utf-8') as fh:
                map_graph = json.load(fh)

            base_grid_size = _adaptive_grid_size(map_context.get('total_blocks', 1000))
            profiles = profile_islands(map_context, map_graph, base_grid_size)
            save_profiles(profiles, profiles_path)
            print(f'  [OK] {map_dir.name}: {len(profiles)} canonical shapes')

            if getattr(args, 'plot', False) and profiles:
                images_dir = map_dir / 'images'
                images_dir.mkdir(exist_ok=True)
                plot_island_profiles(
                    map_context, profiles,
                    str(images_dir / 'island_profiles.png'),
                )
            processed += 1
        except Exception as exc:
            print(f'  [ERR] {map_dir.name}: {exc}')
            skipped += 1

    print(f'\nDone: {processed} profiled, {skipped} skipped.')


def handle_profile_inspect(args) -> None:
    """Print detailed feature table and classification info for one map."""
    import json
    from island_analysis.profile import (
        profile_islands, load_profiles,
    )
    from map_analysis.grid_base import _adaptive_grid_size

    output_root = Path(args.output) if args.output else DEFAULT_OUTPUT_ROOT
    map_dir = output_root / args.map
    context_path = map_dir / 'map_context.json'
    graph_path = map_dir / 'map_graph.json'
    profiles_path = map_dir / 'island_profiles.json'

    if not context_path.exists():
        print(f'Error: map_context.json not found for {args.map}')
        return

    # Load or recompute profiles
    profiles = load_profiles(profiles_path)
    if profiles is None:
        if not graph_path.exists():
            print(f'Error: map_graph.json not found for {args.map}')
            return
        with open(context_path, encoding='utf-8') as fh:
            map_context = json.load(fh)
        with open(graph_path, encoding='utf-8') as fh:
            map_graph = json.load(fh)
        base_grid_size = _adaptive_grid_size(map_context.get('total_blocks', 1000))
        profiles = profile_islands(map_context, map_graph, base_grid_size)

    print(f'\nIsland profile inspection — {args.map}')
    print(f'{"-" * 80}')

    for profile in profiles:
        feat = profile.features
        strat = profile.raster_strategy
        print(f'\n  canonical_key : {profile.canonical_key}')
        print(f'  island_type   : {profile.island_type}')
        print(f'  raw_island_ids: {profile.raw_island_ids}')
        print(f'  grid_override : {strat.grid_size_override}')
        print(f'  align_angle   : {strat.alignment_angle_deg}')
        print()
        print(f'    aspect_ratio   = {feat.aspect_ratio:.4f}')
        print(f'    compactness    = {feat.compactness:.4f}')
        print(f'    convexity      = {feat.convexity:.4f}')
        print(f'    pca_elongation = {feat.pca_elongation:.4f}')
        print(f'    pca_angle_deg  = {feat.pca_angle_deg:.2f}°')
        print(f'    hole_ratio     = {feat.hole_ratio:.6f}')
        print(f'    bbox_width     = {feat.bbox_width:.1f}')
        print(f'    bbox_height    = {feat.bbox_height:.1f}')

        if feat.skeleton_topology is not None:
            print(f'    skeleton_topology    = {feat.skeleton_topology}')
            print(f'    skeleton_endpoints   = {feat.skeleton_endpoint_count}')
            print(f'    skeleton_junctions   = {feat.skeleton_junction_count}')
            print(f'    skeleton_total_len   = {feat.skeleton_total_length:.1f}')
        else:
            print(f'    skeleton             = [unavailable]')

        # Skeleton reliability warning: high hole_ratio + low compactness suggests ring
        if feat.hole_ratio > 0.3 and feat.compactness < 0.3:
            print(f'    ⚠ skeleton may be unreliable (ring/donut topology suspected)')

    print(f'\n{"-" * 80}')
    print(f'Total: {len(profiles)} canonical shapes\n')


def handle_profile_canonical(args) -> None:
    """Show canonical groupings for a map."""
    import json
    from island_analysis.profile import load_profiles, profile_islands
    from map_analysis.grid_base import _adaptive_grid_size

    output_root = Path(args.output) if args.output else DEFAULT_OUTPUT_ROOT
    map_dir = output_root / args.map
    context_path = map_dir / 'map_context.json'
    profiles_path = map_dir / 'island_profiles.json'

    if not context_path.exists():
        print(f'Error: map_context.json not found for {args.map}')
        return

    # Read island canonical_key groupings directly from map_context.json
    with open(context_path, encoding='utf-8') as fh:
        map_context = json.load(fh)

    all_islands = map_context.get('islands', [])
    playable = [isl for isl in all_islands if not isl.get('is_observer_island', False)]
    observer = [isl for isl in all_islands if isl.get('is_observer_island', False)]

    groups: dict[str, list[int]] = {}
    for isl in playable:
        key = isl.get('canonical_key') or f'_solo_{isl["id"]}'
        groups.setdefault(key, []).append(isl['id'])

    print(f'\nCanonical groupings — {args.map}')
    print(f'{"-" * 60}')
    print(f'Total islands: {len(all_islands)} '
          f'({len(playable)} playable, {len(observer)} observer/excluded)\n')
    print(f'  {"canonical_key":<20}  {"instances":>9}  {"island_ids"}')
    print(f'  {"-" * 18}  {"-" * 9}  {"-" * 20}')
    for key, ids in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print(f'  {key:<20}  {len(ids):>9}  {ids}')
    print(f'\n{len(groups)} unique shapes\n')
