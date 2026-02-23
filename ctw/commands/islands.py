"""'islands' subcommand — detect islands and compute skeleton graphs.

Runs the geometry pipeline only (island detection, polygon construction,
skeleton graphs, visualizations). Does not read map.xml or produce
map_context.json — run 'ctw run' for the full pipeline including assembly.
"""

from ctw.common import resolve_map_folder, resolve_output_dir


def register(subparsers, map_parent):
    p = subparsers.add_parser(
        'islands', parents=[map_parent],
        help='Detect islands and compute skeleton graphs',
    )
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


def handler(args):
    map_folder = resolve_map_folder(args.map)

    from map_analysis.pipeline import run_island_geometry
    map_output_dir = resolve_output_dir(map_folder, create=True)
    run_island_geometry(
        map_folder,
        force_rerun=args.force,
        simplify_tolerance=args.simplify,
        buffer_distance=args.buffer,
        layout_type=args.layout,
        canonical_polygons=args.canonical_polygons,
        map_output_dir=map_output_dir,
        output_dir=args.output,
        plots=args.plots,
    )
