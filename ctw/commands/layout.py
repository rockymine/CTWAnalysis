"""'layout' subcommand — extract layout data from Minecraft region files."""

import logging
import sys
from pathlib import Path

from ctw.common import resolve_map_folder, resolve_output_dir

logger = logging.getLogger('ctw')

from layout_analysis import (
    RegionReader,
    Y0LayerExtractor,
    TopSurfaceExtractor,
    VerticalDensityExtractor,
    LowestBedrockExtractor,
)

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
        from layout_analysis.visualization import save_all_plots

        region_folder = map_folder / 'region'
        if not region_folder.exists():
            print(f"Error: No region folder at {region_folder}", file=sys.stderr)
            sys.exit(1)

        output_dir = Path(args.output) if args.output else map_folder / 'layout_output'
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.debug(f"Layout extraction: {map_folder.name}")

        reader = RegionReader(str(region_folder))
        results = {}

        density_modes = []
        if not args.skip_density:
            for mode in args.density_mode.split(','):
                mode = mode.strip()
                if mode in ('run', 'count'):
                    density_modes.append(mode)

        if not args.skip_y0:
            logger.debug("  Extracting Y=0 layer...")
            df = Y0LayerExtractor(reader).extract()
            df.to_parquet(str(output_dir / 'y0_layer_points.parquet'))
            results['y0'] = df
        else:
            results['y0'] = pd.DataFrame()

        if not args.skip_surface:
            logger.debug("  Extracting top surface...")
            df = TopSurfaceExtractor(reader).extract()
            df.to_parquet(str(output_dir / 'top_surface_points.parquet'))
            results['top_surface'] = df
        else:
            results['top_surface'] = pd.DataFrame()

        density_results = {}
        for mode in density_modes:
            logger.debug(f"  Extracting density ({mode})...")
            df = VerticalDensityExtractor(reader, threshold=args.threshold, mode=mode).extract()
            name = f"{mode}_N{args.threshold}"
            df.to_parquet(str(output_dir / f'density_{name}_points.parquet'))
            density_results[name] = df

        if not args.skip_bedrock:
            logger.debug("  Extracting bedrock...")
            df = LowestBedrockExtractor(reader).extract()
            df.to_parquet(str(output_dir / 'lowest_bedrock_points.parquet'))
            results['bedrock'] = df
        else:
            results['bedrock'] = pd.DataFrame()

        if args.plots:
            logger.debug("  Generating plots...")
            save_all_plots(
                y0_df=results.get('y0', pd.DataFrame()),
                top_surface_df=results.get('top_surface', pd.DataFrame()),
                density_dfs=density_results,
                bedrock_df=results.get('bedrock', pd.DataFrame()),
                output_dir=str(output_dir),
            )

        logger.debug(f"  Output saved to: {output_dir}")
    else:
        # Simple workflow mode: parquets into output dir
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

def analyze_layout(
    map_folder: Path,
    force_rerun: bool = False,
    output_dir: Path = None,
    skip_y0: bool = False,
    skip_surface: bool = False,
    skip_density: bool = False,
    skip_bedrock: bool = False,
    threshold: int = 10,
    density_mode: str = 'run',
):
    """
    Step 1: Extract layout data from world folder.

    Args:
        map_folder: Path to map folder (read-only input).
        force_rerun: If True, regenerate even if parquet files exist.
        output_dir: Where to write parquet files (default: map_folder).
        skip_y0: Skip Y=0 layer extraction.
        skip_surface: Skip top surface extraction.
        skip_density: Skip vertical density extraction.
        skip_bedrock: Skip bedrock extraction.
        threshold: Density threshold for vertical density extractor.
        density_mode: Mode for vertical density extractor ('run' or 'count').

    Returns:
        dict: Paths to generated parquet files
    """
    out = Path(output_dir) if output_dir else map_folder
    out.mkdir(parents=True, exist_ok=True)

    logger.debug(f"[1/6] Layout Analysis: {map_folder.name}")

    # Define output paths for enabled extractors only
    parquet_files = {}
    if not skip_y0:
        parquet_files['y0_layer'] = out / 'layout_y0.parquet'
    if not skip_surface:
        parquet_files['top_surface'] = out / 'layout_top_surface.parquet'
    if not skip_density:
        parquet_files['vertical_density'] = out / 'layout_vertical_density.parquet'
    if not skip_bedrock:
        parquet_files['bedrock'] = out / 'layout_bedrock.parquet'

    if not parquet_files:
        logger.debug("  All extractors skipped.")
        return parquet_files

    # Check if files already exist
    all_exist = all(p.exists() for p in parquet_files.values())
    if all_exist and not force_rerun:
        logger.debug("  Layout files already exist. Skipping extraction.")
        for name, path in parquet_files.items():
            logger.debug(f"    {path.name}")
        return parquet_files

    # Find region folder
    region_folder = map_folder / 'region'
    if not region_folder.exists():
        logger.warning(f"  No region folder found at {region_folder}")
        return None

    logger.debug(f"  Extracting layout from: {region_folder}")

    # Initialize reader
    reader = RegionReader(str(region_folder))

    # Extract Y=0 layer
    if 'y0_layer' in parquet_files:
        if not parquet_files['y0_layer'].exists() or force_rerun:
            logger.debug("  Extracting Y=0 layer...")
            extractor = Y0LayerExtractor(reader)
            df = extractor.extract()
            df.to_parquet(parquet_files['y0_layer'])
            logger.debug(f"    Saved {parquet_files['y0_layer'].name} ({len(df)} blocks)")

    # Extract top surface
    if 'top_surface' in parquet_files:
        if not parquet_files['top_surface'].exists() or force_rerun:
            logger.debug("  Extracting top surface...")
            extractor = TopSurfaceExtractor(reader)
            df = extractor.extract()
            df.to_parquet(parquet_files['top_surface'])
            logger.debug(f"    Saved {parquet_files['top_surface'].name} ({len(df)} blocks)")

    # Extract vertical density
    if 'vertical_density' in parquet_files:
        if not parquet_files['vertical_density'].exists() or force_rerun:
            logger.debug(f"  Extracting vertical density (mode={density_mode}, threshold={threshold})...")
            extractor = VerticalDensityExtractor(reader, threshold=threshold, mode=density_mode)
            df = extractor.extract()
            df.to_parquet(parquet_files['vertical_density'])
            logger.debug(f"    Saved {parquet_files['vertical_density'].name} ({len(df)} columns)")

    # Extract bedrock
    if 'bedrock' in parquet_files:
        if not parquet_files['bedrock'].exists() or force_rerun:
            logger.debug("  Extracting lowest bedrock...")
            extractor = LowestBedrockExtractor(reader)
            df = extractor.extract()
            df.to_parquet(parquet_files['bedrock'])
            logger.debug(f"    Saved {parquet_files['bedrock'].name} ({len(df)} blocks)")

    return parquet_files
