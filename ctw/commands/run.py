"""'run' subcommand — full analysis pipeline."""

import argparse
from pathlib import Path

from ctw.common import collect_map_folders, resolve_output_dir


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
    from island_analysis.services import analyze_islands_step
    from layout_analysis.services import analyze_layout
    from xml_analysis.services import analyze_xml

    map_output_dir = resolve_output_dir(map_folder, output_override, create=True)

    print(f"\n{'=' * 70}")
    print(f"Processing: {map_folder.name}")
    print(f"Output: {map_output_dir}")
    print(f"{'=' * 70}")

    try:
        if not args.no_layout:
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
        else:
            print("\n[1/5] Layout Analysis: SKIPPED")

        if not args.no_islands:
            analyze_islands_step(
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
        else:
            print("\n[2/5] Island Analysis: SKIPPED")

        if not args.no_symmetry:
            _run_symmetry(map_output_dir)
        else:
            print("\n[3/5] Symmetry Analysis: SKIPPED")

        if not args.no_xml:
            analyze_xml(map_folder, force_rerun=args.force,
                        output_dir=map_output_dir)
        else:
            print("\n[4/5] XML Analysis: SKIPPED")

        if not args.no_matches:
            print(f"\n[5/5] Match Analysis: Currently not supported")
        else:
            print("\n[5/5] Match Analysis: Currently not supported")

        return map_folder.name, True, None

    except Exception as e:
        import traceback
        print(f"\n  ERROR processing {map_folder.name}: {e}")
        traceback.print_exc()
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
            print(f"Skipping {skipped} maps with existing output")

    print("=" * 70)
    print("CTW ANALYSIS WORKFLOW")
    print("=" * 70)
    print(f"Maps to analyze: {len(map_folders)}")
    if args.workers > 1:
        print(f"Workers: {args.workers}")
    for folder in map_folders:
        print(f"  - {folder.name}")
    print()

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

        # Summary
        succeeded = [r for r in results if r[1]]
        failed = [r for r in results if not r[1]]
        print(f"\n{'=' * 70}")
        print(f"WORKFLOW COMPLETE: {len(succeeded)} succeeded, {len(failed)} failed")
        if failed:
            for name, _, err in failed:
                print(f"  FAILED: {name}: {err}")
        print(f"{'=' * 70}\n")
    else:
        results = []
        for map_folder in map_folders:
            result = _process_single_map(map_folder, args, args.output)
            results.append(result)

        succeeded = [r for r in results if r[1]]
        failed = [r for r in results if not r[1]]
        print(f"\n{'=' * 70}")
        print(f"WORKFLOW COMPLETE: {len(succeeded)} succeeded, {len(failed)} failed")
        if failed:
            for name, _, err in failed:
                print(f"  FAILED: {name}: {err}")
        print(f"{'=' * 70}\n")


def _run_symmetry(map_output_dir: Path) -> None:
    """Run symmetry analysis on a map's preprocessed geometry."""
    from symmetry_analysis import detect_symmetry
    from symmetry_analysis import exporter as symmetry_exporter

    print(f"\n[3/5] Symmetry Analysis")
    print("=" * 70)

    ctx_path = map_output_dir / 'map_context.json'
    if not ctx_path.exists():
        print("  map_context.json not found — skipping symmetry analysis")
        return

    result = detect_symmetry(str(ctx_path))

    # Save results
    out_path = map_output_dir / 'symmetry.json'
    symmetry_exporter.save(result, out_path)

    # Print summary
    detected = [s for s in result['global_symmetry'] if s['detected']]
    if detected:
        primary = max(detected, key=lambda s: s['confidence'])
        print(f"  Global: {primary['description']} "
              f"(confidence: {primary['confidence']:.0%})")
    else:
        print("  Global: no symmetry detected")

    intra = result.get('intra_team_symmetry', [])
    sym_teams = [t['team'] for t in intra if t.get('symmetry_detected')]
    if sym_teams:
        print(f"  Intra-team: detected for {', '.join(sym_teams)}")
