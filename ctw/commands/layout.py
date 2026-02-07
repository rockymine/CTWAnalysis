"""'layout' subcommand — extract layout data from Minecraft region files."""

import sys
from pathlib import Path

from ctw.common import resolve_map_folder, resolve_output_dir


def register(subparsers, map_parent):
    p = subparsers.add_parser(
        'layout', parents=[map_parent],
        help='Extract layout data from Minecraft region files',
    )
    p.add_argument('--threshold', type=int, default=10,
                   help='Density threshold (default: 10)')
    p.add_argument('--density-mode', default='run,count',
                   metavar='{run,count}',
                   help='Comma-separated density modes (default: run,count)')
    p.add_argument('--skip-y0', action='store_true', help='Skip Y0 extraction')
    p.add_argument('--skip-surface', action='store_true', help='Skip top surface')
    p.add_argument('--skip-density', action='store_true', help='Skip density')
    p.add_argument('--skip-bedrock', action='store_true', help='Skip bedrock')
    p.add_argument('--output', help='Override output directory')
    p.add_argument('--plots', action='store_true',
                   help='Generate plots alongside data files')
    p.set_defaults(func=handler)


def handler(args):
    map_folder = resolve_map_folder(args.map)

    if args.plots or args.output:
        # Full standalone mode: CSV + Parquet + plots
        import pandas as pd
        from layout_analysis import (
            RegionReader, Y0LayerExtractor, TopSurfaceExtractor,
            VerticalDensityExtractor, LowestBedrockExtractor,
        )
        from layout_analysis.plotting import save_all_plots

        region_folder = map_folder / 'region'
        if not region_folder.exists():
            print(f"Error: No region folder at {region_folder}", file=sys.stderr)
            sys.exit(1)

        output_dir = Path(args.output) if args.output else map_folder / 'layout_output'
        output_dir.mkdir(parents=True, exist_ok=True)

        print("=" * 70)
        print(f"LAYOUT EXTRACTION: {map_folder.name}")
        print("=" * 70)

        reader = RegionReader(str(region_folder))
        results = {}

        density_modes = []
        if not args.skip_density:
            for mode in args.density_mode.split(','):
                mode = mode.strip()
                if mode in ('run', 'count'):
                    density_modes.append(mode)

        if not args.skip_y0:
            print("  Extracting Y=0 layer...")
            df = Y0LayerExtractor(reader).extract()
            df.to_parquet(str(output_dir / 'y0_layer_points.parquet'))
            results['y0'] = df
        else:
            results['y0'] = pd.DataFrame()

        if not args.skip_surface:
            print("  Extracting top surface...")
            df = TopSurfaceExtractor(reader).extract()
            df.to_parquet(str(output_dir / 'top_surface_points.parquet'))
            results['top_surface'] = df
        else:
            results['top_surface'] = pd.DataFrame()

        density_results = {}
        for mode in density_modes:
            print(f"  Extracting density ({mode})...")
            df = VerticalDensityExtractor(reader, threshold=args.threshold, mode=mode).extract()
            name = f"{mode}_N{args.threshold}"
            df.to_parquet(str(output_dir / f'density_{name}_points.parquet'))
            density_results[name] = df

        if not args.skip_bedrock:
            print("  Extracting bedrock...")
            df = LowestBedrockExtractor(reader).extract()
            df.to_parquet(str(output_dir / 'lowest_bedrock_points.parquet'))
            results['bedrock'] = df
        else:
            results['bedrock'] = pd.DataFrame()

        if args.plots:
            print("  Generating plots...")
            save_all_plots(
                y0_df=results.get('y0', pd.DataFrame()),
                top_surface_df=results.get('top_surface', pd.DataFrame()),
                density_dfs=density_results,
                bedrock_df=results.get('bedrock', pd.DataFrame()),
                output_dir=str(output_dir),
            )

        print(f"  Output saved to: {output_dir}")
    else:
        # Simple workflow mode: parquets into output dir
        from layout_analysis.services import analyze_layout
        map_output_dir = resolve_output_dir(map_folder, create=True)
        analyze_layout(
            map_folder,
            force_rerun=args.force,
            output_dir=map_output_dir,
            skip_y0=args.skip_y0,
            skip_surface=args.skip_surface,
            skip_density=args.skip_density,
            skip_bedrock=args.skip_bedrock,
            threshold=args.threshold,
            density_mode=args.density_mode,
        )
