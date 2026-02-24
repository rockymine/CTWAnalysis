"""'run' subcommand — full analysis pipeline.

Pipeline steps (in order):
    [1/6] Layout        — extract blocks, produce parquets
    [2/6] Islands       — detect islands, build polygons, compute skeletons
                          (pure geometry, no XML) → islands.json
    [3/6] Symmetry      — detect global symmetry from island geometry
                          → symmetry.json
    [4/6] XML Analysis  — parse map.xml → map_data.json
    [5/6] Assembly      — combine geometry + symmetry + XML into the full
                          map model → map_context.json, map_graph.json
    [6/6] Match Analysis (not yet implemented)
"""

import argparse
import logging
from pathlib import Path
from typing import Optional

from ctw.common import collect_map_folders, resolve_output_dir
from map_analysis.datatypes import IslandGeometryResult
from symmetry_analysis.datatypes import SymmetryResult

logger = logging.getLogger('ctw')


def register(subparsers):
    p = subparsers.add_parser(
        'run', help='Run the full analysis pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument('--map', help='Map name to analyze')
    p.add_argument('--all', action='store_true', help='Analyze all maps')
    p.add_argument('--map-dir',
                   help='Directory containing map folders (default: map_folders/). '
                        'Used with --all to scan an external map collection.')
    p.add_argument('--force', action='store_true', help='Force regeneration')
    p.add_argument('--output', help='Output root directory (default: output/)')
    p.add_argument('--no-layout', action='store_true', help='Skip layout analysis')
    p.add_argument('--no-islands', action='store_true', help='Skip island analysis')
    p.add_argument('--no-symmetry', action='store_true', help='Skip symmetry analysis')
    p.add_argument('--no-xml', action='store_true', help='Skip XML analysis')
    p.add_argument('--no-assembly', action='store_true', help='Skip map assembly')
    p.add_argument('--no-matches', action='store_true', help='Skip match analysis')
    p.add_argument('--match-history', default='match_logs/match_history.txt',
                   help='Path to match history file')
    p.add_argument('--plots', action='store_true',
                   help='Generate debug plots for layout and island analysis')

    # Layout settings (also settable via layout: section in config)
    p.add_argument('--skip-y0', action='store_true', help='Skip Y0 extraction')
    p.add_argument('--skip-surface', action='store_true', help='Skip top surface')
    p.add_argument('--skip-density', action='store_true', help='Skip density')
    p.add_argument('--skip-bedrock', action='store_true', help='Skip bedrock')
    p.add_argument('--threshold', type=int, default=10,
                   help='Density threshold (default: 10)')
    p.add_argument('--density-mode', default='run', metavar='{run,count}',
                   help='Density mode (default: run)')

    # Island settings (also settable via islands: section in config)
    p.add_argument('--island-layout', choices=['bedrock', 'y0', 'top', 'density'],
                   default='bedrock', help='Layout file for island analysis')
    p.add_argument('--canonical-polygons', action='store_true',
                   help='Use canonical-consistent polygon construction')
    p.add_argument('--simplify', type=float, default=1.0,
                   help='Simplification tolerance for islands (default: 1.0)')
    p.add_argument('--buffer', type=float, default=0.0,
                   help='Buffer distance for island smoothing (default: 0.0)')
    p.add_argument('--connectivity', type=int, default=8, choices=[4, 8],
                   help='Island connectivity (default: 8)')
    p.add_argument('--min-size', type=int, default=10,
                   help='Minimum island block count (default: 10)')
    p.add_argument('--no-holes', action='store_true', help='Disable hole detection')
    p.add_argument('--workers', type=int, default=1,
                   help='Number of maps to process in parallel (default: 1)')
    p.add_argument('--skip-existing', action='store_true',
                   help='Skip maps that already have output (map_context.json exists)')
    p.set_defaults(func=handler)

def _process_single_map(map_folder, args, output_override=None):
    """Run the full pipeline for a single map. Safe for multiprocessing."""
    import traceback
    from ctw.log import setup_map_file_logging
    from map_analysis.pipeline import run_island_geometry, run_symmetry, assemble_map
    from ctw.commands.layout import analyze_layout
    from ctw.commands.xml import analyze_xml

    map_output_dir = resolve_output_dir(map_folder, output_override, create=True)
    setup_map_file_logging(map_output_dir)

    logger.info(f"Processing: {map_folder.name}")

    try:
        # [1/6] Layout
        if not args.no_layout:
            parquet_files = analyze_layout(
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
            n = len(parquet_files) if parquet_files else 0
            logger.info(f"  [1/6] Layout: {n} parquet files")
        else:
            logger.info("  [1/6] Layout: skipped")

        # [2/6] Islands + Skeletons (geometry only)
        geometry = None
        if not args.no_islands:
            geometry = run_island_geometry(
                map_folder,
                force_rerun=args.force,
                layout_type=args.island_layout,
                canonical_polygons=args.canonical_polygons,
                simplify_tolerance=args.simplify,
                buffer_distance=args.buffer,
                connectivity=args.connectivity,
                min_size=args.min_size,
                detect_holes=not args.no_holes,
                map_output_dir=map_output_dir,
                plots=args.plots,
            )
            if geometry:
                logger.info(f"  [2/6] Islands: {len(geometry.islands)} islands")
            else:
                logger.info("  [2/6] Islands: failed (check log)")
        else:
            logger.info("  [2/6] Islands: skipped")

        # [3/6] Symmetry (geometric only — reads islands.json)
        symmetry = None
        if not args.no_symmetry:
            symmetry = run_symmetry(map_output_dir)
            if symmetry and symmetry.primary:
                logger.info(f"  [3/6] Symmetry: {symmetry.primary['description']} "
                            f"({symmetry.primary['confidence']:.0%})")
            else:
                logger.info("  [3/6] Symmetry: none detected")
        else:
            logger.info("  [3/6] Symmetry: skipped")

        # [4/6] XML Analysis
        xml_context = None
        if not args.no_xml:
            xml_context = analyze_xml(map_folder, force_rerun=args.force,
                                      output_dir=map_output_dir)
            if xml_context:
                md = xml_context.map_data
                logger.info(f"  [4/6] XML: {len(md.teams)} teams, {len(md.wools)} wools")
            else:
                logger.info("  [4/6] XML: no map.xml")
        else:
            logger.info("  [4/6] XML: skipped")

        # [5/6] Map Assembly (combines geometry + symmetry + XML)
        if not args.no_assembly:
            if geometry is not None:
                assemble_map(map_folder, geometry, map_output_dir,
                             symmetry=symmetry, xml_context=xml_context, plots=args.plots)
                logger.info("  [5/6] Assembly: done")
            else:
                logger.info("  [5/6] Assembly: skipped (no geometry)")
        else:
            logger.info("  [5/6] Assembly: skipped")

        logger.info("  [6/6] Match analysis: not supported")

        return map_folder.name, True, None

    except Exception as e:
        logger.error(f"  Error: {e}")
        logger.debug(traceback.format_exc())
        return map_folder.name, False, str(e)


def handler(args):
    map_folders = collect_map_folders(args)

    if args.skip_existing:
        total = len(map_folders)
        map_folders = [
            mf for mf in map_folders
            if not (resolve_output_dir(mf, args.output) / 'map_context.json').exists()
        ]
        skipped = total - len(map_folders)
        if skipped:
            logger.info(f"Skipping {skipped} maps with existing output")

    logger.info(f"Maps to analyze: {len(map_folders)}")
    if args.workers > 1:
        logger.info(f"Workers: {args.workers}")
    for folder in map_folders:
        logger.debug(f"  - {folder.name}")

    if args.workers > 1 and len(map_folders) > 1:
        from concurrent.futures import ProcessPoolExecutor, as_completed

        results = []
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(_process_single_map, mf, args, args.output): mf
                for mf in map_folders
            }
            for future in as_completed(futures):
                results.append(future.result())
    else:
        results = []
        for map_folder in map_folders:
            result = _process_single_map(map_folder, args, args.output)
            results.append(result)

    succeeded = [r for r in results if r[1]]
    failed = [r for r in results if not r[1]]
    logger.info(f"Complete: {len(succeeded)} succeeded, {len(failed)} failed")
    if failed:
        for name, _, err in failed:
            logger.warning(f"  Failed: {name}: {err}")
