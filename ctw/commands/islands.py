"""'islands' subcommand — detect islands and compute skeleton graphs."""

from ctw.common import resolve_map_folder


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
    p.add_argument('--canonical-triangulation', action='store_true',
                   help='Use canonical-consistent triangulation')
    p.add_argument('--basic', action='store_true',
                   help='Basic mode: detection + triangulation only (no skeleton/POI)')
    p.set_defaults(func=handler)


def handler(args):
    map_folder = resolve_map_folder(args.map)

    if args.basic:
        from analyze_islands import analyze_map_islands

        layout_map = {
            'bedrock': 'layout_bedrock.parquet',
            'y0': 'layout_y0.parquet',
            'top': 'layout_top_surface.parquet',
            'density': 'layout_vertical_density.parquet',
        }
        bedrock_path = str(map_folder / layout_map.get(args.layout, 'layout_bedrock.parquet'))
        output_dir = str(map_folder / 'island_analysis')

        analyze_map_islands(
            bedrock_parquet=bedrock_path,
            output_dir=output_dir,
            map_name=map_folder.name,
            connectivity=args.connectivity,
            min_island_size=args.min_size,
            buffer_distance=args.buffer,
            simplify_tolerance=args.simplify,
            detect_holes=not args.no_holes,
        )
    else:
        from layout_analysis.services import analyze_islands_step
        analyze_islands_step(
            map_folder,
            force_rerun=args.force,
            simplify_tolerance=args.simplify,
            buffer_distance=args.buffer,
            layout_type=args.layout,
            canonical_triangulation=args.canonical_triangulation,
        )
