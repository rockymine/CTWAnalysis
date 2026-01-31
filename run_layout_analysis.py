"""
Main script for running layout analysis on Minecraft worlds.

Analyzes Minecraft Java Edition 1.8.9 world folders (Anvil format) and produces
datasets and visualizations for four extraction modes:
1. Y0 Layer - Non-air blocks at world y=0
2. Top Surface - Highest non-air block per column
3. Vertical Density - Columns meeting density threshold
4. Lowest Bedrock - Lowest bedrock block per column
"""

import argparse
import sys
from pathlib import Path
import pandas as pd

from layout_analysis import (
    RegionReader,
    Y0LayerExtractor,
    TopSurfaceExtractor,
    VerticalDensityExtractor,
    LowestBedrockExtractor,
)
from layout_analysis.plotting import save_all_plots


def save_csv_or_parquet(df: pd.DataFrame, base_path: str):
    """
    Save DataFrame as CSV (and Parquet if pyarrow is available).

    Args:
        df: DataFrame to save
        base_path: Base path without extension
    """
    # Always save CSV
    csv_path = f"{base_path}.csv"
    df.to_csv(csv_path, index=False)
    print(f"  Saved CSV: {csv_path}")

    # Try to save Parquet if available
    try:
        import pyarrow
        parquet_path = f"{base_path}.parquet"
        df.to_parquet(parquet_path, index=False)
        print(f"  Saved Parquet: {parquet_path}")
    except ImportError:
        pass


def main():
    parser = argparse.ArgumentParser(
        description='Analyze Minecraft world layout and generate visualizations',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_layout_analysis.py --world map_folders/tumbleweed/region
  python run_layout_analysis.py --world /path/to/world/region --threshold 15 --density-mode run,count
  python run_layout_analysis.py --world /path/to/world/region --output custom_output --threshold 20
        """
    )

    parser.add_argument(
        '--world',
        required=True,
        help='Path to Minecraft world region folder (e.g., map_folders/tumbleweed/region)'
    )

    parser.add_argument(
        '--output',
        default='output',
        help='Output directory for plots and data (default: output)'
    )

    parser.add_argument(
        '--threshold',
        type=int,
        default=10,
        help='Density threshold for vertical density extraction (default: 10)'
    )

    parser.add_argument(
        '--density-mode',
        default='run,count',
        help='Comma-separated density modes to run: run, count (default: run,count)'
    )

    parser.add_argument(
        '--skip-y0',
        action='store_true',
        help='Skip Y0 layer extraction'
    )

    parser.add_argument(
        '--skip-surface',
        action='store_true',
        help='Skip top surface extraction'
    )

    parser.add_argument(
        '--skip-density',
        action='store_true',
        help='Skip density extraction'
    )

    parser.add_argument(
        '--skip-bedrock',
        action='store_true',
        help='Skip lowest bedrock extraction'
    )

    args = parser.parse_args()

    # Validate world path
    world_path = Path(args.world)
    if not world_path.exists():
        print(f"Error: World path does not exist: {args.world}", file=sys.stderr)
        sys.exit(1)

    # Parse density modes
    density_modes = []
    if not args.skip_density:
        for mode in args.density_mode.split(','):
            mode = mode.strip()
            if mode not in ['run', 'count']:
                print(f"Error: Invalid density mode '{mode}'. Must be 'run' or 'count'.", file=sys.stderr)
                sys.exit(1)
            density_modes.append(mode)

    # Create output directory
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("MINECRAFT LAYOUT ANALYSIS")
    print("=" * 70)
    print(f"World: {args.world}")
    print(f"Output: {args.output}")
    print(f"Density threshold: {args.threshold}")
    print(f"Density modes: {', '.join(density_modes) if density_modes else 'None'}")
    print("=" * 70)

    # Initialize region reader
    try:
        reader = RegionReader(str(world_path))
        region_files = reader.get_region_files()
        print(f"\nFound {len(region_files)} region file(s)")
    except Exception as e:
        print(f"Error: Failed to initialize region reader: {e}", file=sys.stderr)
        sys.exit(1)

    # Track results
    results = {}

    # Extract Y0 layer
    if not args.skip_y0:
        print("\n" + "=" * 70)
        extractor = Y0LayerExtractor(reader)
        y0_df = extractor.extract()
        save_csv_or_parquet(y0_df, str(output_dir / 'y0_layer_points'))
        results['y0'] = y0_df
    else:
        print("\nSkipping Y0 layer extraction")
        results['y0'] = pd.DataFrame()

    # Extract top surface
    if not args.skip_surface:
        print("\n" + "=" * 70)
        extractor = TopSurfaceExtractor(reader)
        top_surface_df = extractor.extract()
        save_csv_or_parquet(top_surface_df, str(output_dir / 'top_surface_points'))
        results['top_surface'] = top_surface_df
    else:
        print("\nSkipping top surface extraction")
        results['top_surface'] = pd.DataFrame()

    # Extract density for each mode
    density_results = {}
    for mode in density_modes:
        print("\n" + "=" * 70)
        extractor = VerticalDensityExtractor(reader, threshold=args.threshold, mode=mode)
        density_df = extractor.extract()
        mode_name = f"{mode}_N{args.threshold}"
        save_csv_or_parquet(density_df, str(output_dir / f'density_{mode_name}_points'))
        density_results[mode_name] = density_df

    # Extract lowest bedrock
    if not args.skip_bedrock:
        print("\n" + "=" * 70)
        extractor = LowestBedrockExtractor(reader)
        bedrock_df = extractor.extract()
        save_csv_or_parquet(bedrock_df, str(output_dir / 'lowest_bedrock_points'))
        results['bedrock'] = bedrock_df
    else:
        print("\nSkipping lowest bedrock extraction")
        results['bedrock'] = pd.DataFrame()

    # Generate plots
    print("\n" + "=" * 70)
    save_all_plots(
        y0_df=results.get('y0', pd.DataFrame()),
        top_surface_df=results.get('top_surface', pd.DataFrame()),
        density_dfs=density_results,
        bedrock_df=results.get('bedrock', pd.DataFrame()),
        output_dir=str(output_dir)
    )

    # Summary
    print("\n" + "=" * 70)
    print("ANALYSIS COMPLETE")
    print("=" * 70)
    print("\nResults:")
    if not args.skip_y0:
        print(f"  Y0 Layer: {len(results['y0'])} points")
    if not args.skip_surface:
        print(f"  Top Surface: {len(results['top_surface'])} points")
    for mode_name, df in density_results.items():
        print(f"  Density ({mode_name}): {len(df)} points")
    if not args.skip_bedrock:
        print(f"  Lowest Bedrock: {len(results['bedrock'])} points")

    print(f"\nAll outputs saved to: {output_dir}")
    print("=" * 70)


if __name__ == '__main__':
    main()
