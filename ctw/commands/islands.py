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
        import os
        import pandas as pd
        from layout_analysis.islands import (
            detect_islands,
            triangulate_island_union,
            compute_island_statistics,
            classify_islands,
            create_island_report,
        )
        from layout_analysis.services.islands_service import LAYOUT_FILES

        layout_filename = LAYOUT_FILES.get(args.layout, 'layout_bedrock.parquet')
        layout_path = map_folder / layout_filename
        output_dir = str(map_folder / 'island_analysis')
        os.makedirs(output_dir, exist_ok=True)

        print("=" * 70)
        print("ISLAND DETECTION ANALYSIS")
        print("=" * 70)

        print(f"\n1. Loading bedrock data from: {layout_path}")
        df = pd.read_parquet(layout_path)
        print(f"   Loaded {len(df)} blocks")

        print(f"\n2. Detecting islands (connectivity={args.connectivity}, min_size={args.min_size})...")
        islands = detect_islands(
            df, x_col='world_x', z_col='world_z',
            connectivity=args.connectivity, min_island_size=args.min_size,
        )
        print(f"   Found {len(islands)} islands")
        if not islands:
            print("   No islands detected!")
            return

        for island in islands:
            print(f"     Island {island.id}: {island.area:,} blocks at ({island.center[0]:.1f}, {island.center[1]:.1f})")

        print(f"\n3. Triangulating islands (union mode, holes={not args.no_holes})...")
        total_triangles = 0
        for island in islands:
            triangles = triangulate_island_union(
                island, buffer_distance=args.buffer,
                simplify_tolerance=args.simplify, detect_holes=not args.no_holes,
            )
            total_triangles += len(triangles)
            print(f"     Island {island.id}: {len(triangles)} triangles, {len(island.holes)} holes")
        print(f"   Total triangles: {total_triangles}")

        print("\n4. Computing statistics...")
        stats = compute_island_statistics(islands)
        print(f"   Map center: ({stats['map_center'][0]:.1f}, {stats['map_center'][1]:.1f})")
        print(f"   Avg distance from center: {stats['avg_distance_from_center']:.1f} blocks")

        print("\n5. Classifying islands...")
        classifications = classify_islands(islands)
        for cls_name, cls_islands in classifications.items():
            if cls_islands:
                ids = [i.id for i in cls_islands]
                print(f"   {cls_name}: {ids}")

        print("\n6. Generating visualizations...")
        create_island_report(islands, stats, output_dir, map_folder.name)

        print("\n" + "=" * 70)
        print("ISLAND DETECTION COMPLETE")
        print("=" * 70)
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
