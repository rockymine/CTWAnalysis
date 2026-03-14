"""'layout' subcommand — extract layout data from Minecraft region files."""

import logging
import sys
from pathlib import Path

from ctw.common import collect_map_folders, resolve_map_folder, resolve_output_dir

logger = logging.getLogger('ctw')

from layout_analysis import (
    RegionReader,
    Y0LayerExtractor,
    TopSurfaceExtractor,
    VerticalDensityExtractor,
    LowestBedrockExtractor,
    LowestSolidLayerExtractor,
    ResourceBlockExtractor,
    ChestExtractor,
)

def register(subparsers):
    p = subparsers.add_parser(
        'layout',
        help='Extract layout data from Minecraft region files',
    )
    map_group = p.add_mutually_exclusive_group(required=True)
    map_group.add_argument(
        '--map', default=None,
        help='Map name or path (e.g. tumbleweed, or /path/to/map)',
    )
    map_group.add_argument(
        '--all', action='store_true', dest='all',
        help='Process all maps found in --map-dir',
    )
    map_group.add_argument(
        '--all-matches', action='store_true', dest='all_matches',
        help='Process only maps that have match data in the database',
    )
    p.add_argument(
        '--map-dir', default=None,
        help='Directory to scan for map folders when using --all '
             '(default: map_folders/). Use this to target CommunityMaps, '
             'PublicMaps, or any other external collection.',
    )
    p.add_argument('--force', action='store_true',
                   help='Force regeneration of existing outputs')
    p.add_argument('--output', default=None,
                   help='Output root directory (default: output/). Each map '
                        'writes to <output>/<map_name>/.')
    p.add_argument('--threshold', type=int, default=10,
                   help='Density threshold (default: 10)')
    p.add_argument('--density-mode', default='run,count',
                   metavar='{run,count}',
                   help='Comma-separated density modes (default: run,count)')
    p.add_argument('--skip-y0', action='store_true', help='Skip Y0 extraction')
    p.add_argument('--skip-surface', action='store_true', help='Skip top surface')
    p.add_argument('--skip-density', action='store_true', help='Skip density')
    p.add_argument('--skip-bedrock', action='store_true', help='Skip bedrock')
    p.add_argument('--skip-lowest-solid', action='store_true',
                   help='Skip lowest-solid-layer extraction')
    p.add_argument('--skip-features', action='store_true',
                   help='Skip feature extraction (resource blocks and chests)')
    p.add_argument('--plots', action='store_true',
                   help='Generate plots alongside data files')
    p.add_argument('--workers', type=int, default=1,
                   help='Number of maps to process in parallel (default: 1)')
    p.set_defaults(func=handler)


def _run_layout_worker(map_folder: Path, output_override: str | None, kwargs: dict):
    """Top-level worker function for ProcessPoolExecutor (must be picklable)."""
    map_output_dir = resolve_output_dir(map_folder, output_override, create=True)
    return analyze_layout(map_folder, output_dir=map_output_dir, **kwargs)


def handler(args):
    map_folders = collect_map_folders(args)

    if args.plots and len(map_folders) > 1:
        print("Error: --plots is only supported for a single map (--map NAME)", file=sys.stderr)
        sys.exit(1)

    if args.plots:
        # Standalone plot mode (single map only)
        import pandas as pd
        from layout_analysis.visualization import save_all_plots

        map_folder = map_folders[0]
        region_folder = map_folder / 'region'
        if not region_folder.exists():
            print(f"Error: No region folder at {region_folder}", file=sys.stderr)
            sys.exit(1)

        output_dir = Path(args.output) / map_folder.name if args.output else map_folder / 'layout_output'
        output_dir.mkdir(parents=True, exist_ok=True)

        reader = RegionReader(str(region_folder))
        results = {}
        density_results = {}

        if not args.skip_y0:
            df = Y0LayerExtractor(reader).extract()
            df.to_parquet(str(output_dir / 'y0_layer_points.parquet'))
            results['y0'] = df
        else:
            results['y0'] = pd.DataFrame()

        if not args.skip_surface:
            df = TopSurfaceExtractor(reader).extract()
            df.to_parquet(str(output_dir / 'top_surface_points.parquet'))
            results['top_surface'] = df
        else:
            results['top_surface'] = pd.DataFrame()

        if not args.skip_density:
            for mode in (m.strip() for m in args.density_mode.split(',') if m.strip() in ('run', 'count')):
                df = VerticalDensityExtractor(reader, threshold=args.threshold, mode=mode).extract()
                name = f"{mode}_N{args.threshold}"
                df.to_parquet(str(output_dir / f'density_{name}_points.parquet'))
                density_results[name] = df

        if not args.skip_bedrock:
            df = LowestBedrockExtractor(reader).extract()
            df.to_parquet(str(output_dir / 'lowest_bedrock_points.parquet'))
            results['bedrock'] = df
        else:
            results['bedrock'] = pd.DataFrame()

        save_all_plots(
            y0_df=results.get('y0', pd.DataFrame()),
            top_surface_df=results.get('top_surface', pd.DataFrame()),
            density_dfs=density_results,
            bedrock_df=results.get('bedrock', pd.DataFrame()),
            output_dir=str(output_dir),
        )
        logger.debug(f"  Output saved to: {output_dir}")
        return

    # Standard workflow mode: parquets into output/<map_name>/
    layout_kwargs = dict(
        force_rerun=args.force,
        skip_y0=args.skip_y0,
        skip_surface=args.skip_surface,
        skip_density=args.skip_density,
        skip_bedrock=args.skip_bedrock,
        skip_lowest_solid=args.skip_lowest_solid,
        skip_features=args.skip_features,
        threshold=args.threshold,
        density_mode=args.density_mode,
    )

    if args.workers > 1 and len(map_folders) > 1:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        results = []
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(_run_layout_worker, mf, args.output, layout_kwargs): mf
                       for mf in map_folders}
            for future in as_completed(futures):
                results.append(future.result())
    else:
        results = [_run_layout_worker(mf, args.output, layout_kwargs) for mf in map_folders]

    n_ok = sum(1 for r in results if r is not None)
    n_fail = len(results) - n_ok
    if len(map_folders) > 1:
        logger.info(f"Layout extraction complete: {n_ok} succeeded, {n_fail} failed")

def analyze_layout(
    map_folder: Path,
    force_rerun: bool = False,
    output_dir: Path = None,
    skip_y0: bool = False,
    skip_surface: bool = False,
    skip_density: bool = False,
    skip_bedrock: bool = False,
    skip_lowest_solid: bool = False,
    skip_features: bool = False,
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
        skip_features: Skip feature extraction (resource blocks and chests).
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
    if not skip_lowest_solid:
        parquet_files['lowest_solid'] = out / 'layout_lowest_solid.parquet'
    if not skip_features:
        parquet_files['resource_blocks'] = out / 'layout_resource_blocks.parquet'
        parquet_files['chest_contents'] = out / 'layout_chest_contents.parquet'

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

    # Extract lowest solid layer (first non-air, non-void block from below)
    if 'lowest_solid' in parquet_files:
        if not parquet_files['lowest_solid'].exists() or force_rerun:
            logger.debug("  Extracting lowest solid layer...")
            extractor = LowestSolidLayerExtractor(reader)
            df = extractor.extract()
            df.to_parquet(parquet_files['lowest_solid'])
            logger.debug(f"    Saved {parquet_files['lowest_solid'].name} ({len(df)} blocks)")

    # Extract resource blocks (iron, gold, diamond blocks at all Y levels)
    if 'resource_blocks' in parquet_files:
        if not parquet_files['resource_blocks'].exists() or force_rerun:
            logger.debug("  Extracting resource blocks...")
            extractor = ResourceBlockExtractor(reader)
            df = extractor.extract()
            df.to_parquet(parquet_files['resource_blocks'])
            logger.debug(
                f"    Saved {parquet_files['resource_blocks'].name} ({len(df)} blocks)"
            )

    # Extract chest contents (tile entities)
    if 'chest_contents' in parquet_files:
        if not parquet_files['chest_contents'].exists() or force_rerun:
            logger.debug("  Extracting chest contents...")
            extractor = ChestExtractor(reader)
            df = extractor.extract()
            df.to_parquet(parquet_files['chest_contents'])
            unique_chests = df[['world_x', 'world_z', 'y']].drop_duplicates()
            logger.debug(
                f"    Saved {parquet_files['chest_contents'].name} "
                f"({len(unique_chests)} chests, {len(df)} item slots)"
            )

    return parquet_files
