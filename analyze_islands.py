"""
Island Detection Analysis Script

Detects and analyzes connected islands in map layouts.
"""

import argparse
import os
import pandas as pd
from pathlib import Path

from layout_analysis.islands import (
    detect_islands,
    triangulate_island_union,
    compute_island_statistics,
    classify_islands,
    create_island_report,
)


def analyze_map_islands(
    bedrock_parquet: str,
    output_dir: str = 'output',
    map_name: str = None,
    connectivity: int = 8,
    min_island_size: int = 10,
    buffer_distance: float = 0.0,
    simplify_tolerance: float = 3.0,
    detect_holes: bool = True
):
    """
    Analyze islands in a map's bedrock layout.

    Args:
        bedrock_parquet: Path to bedrock parquet file
        output_dir: Output directory
        map_name: Name of the map
        connectivity: Island connectivity (4 or 8)
        min_island_size: Minimum blocks for an island
        buffer_distance: Buffer distance for union mode smoothing
        simplify_tolerance: Simplification tolerance for union mode
        detect_holes: Whether to detect internal holes
    """
    print("=" * 70)
    print("ISLAND DETECTION ANALYSIS")
    print("=" * 70)

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)

    # Load bedrock data
    print(f"\n1. Loading bedrock data from: {bedrock_parquet}")
    df = pd.read_parquet(bedrock_parquet)
    print(f"   Loaded {len(df)} blocks")

    # Get map name from path if not provided
    if map_name is None:
        map_name = Path(bedrock_parquet).parent.name

    # Detect islands
    print(f"\n2. Detecting islands (connectivity={connectivity}, min_size={min_island_size})...")
    islands = detect_islands(
        df,
        x_col='world_x',
        z_col='world_z',
        connectivity=connectivity,
        min_island_size=min_island_size
    )
    print(f"   Found {len(islands)} islands")

    if not islands:
        print("   No islands detected!")
        return

    # Print island summary
    print("\n   Island summary:")
    for island in islands:
        print(f"     Island {island.id}: {island.area:,} blocks at ({island.center[0]:.1f}, {island.center[1]:.1f})")

    # Triangulate islands
    print(f"\n3. Triangulating islands (union mode, holes={detect_holes})...")
    total_triangles = 0
    for island in islands:
        triangles = triangulate_island_union(
            island,
            buffer_distance=buffer_distance,
            simplify_tolerance=simplify_tolerance,
            detect_holes=detect_holes
        )
        total_triangles += len(triangles)
        print(f"     Island {island.id}: {len(triangles)} triangles, {len(island.holes)} holes")

    print(f"   Total triangles: {total_triangles}")

    # Compute statistics
    print("\n4. Computing statistics...")
    stats = compute_island_statistics(islands)
    print(f"   Map center: ({stats['map_center'][0]:.1f}, {stats['map_center'][1]:.1f})")
    print(f"   Avg distance from center: {stats['avg_distance_from_center']:.1f} blocks")

    # Classify islands
    print("\n5. Classifying islands...")
    classifications = classify_islands(islands)
    for cls_name, cls_islands in classifications.items():
        if cls_islands:
            ids = [i.id for i in cls_islands]
            print(f"   {cls_name}: {ids}")

    # Generate visualizations
    print("\n6. Generating visualizations...")
    create_island_report(islands, stats, output_dir, map_name)

    print("\n" + "=" * 70)
    print("ISLAND DETECTION COMPLETE")
    print("=" * 70)
    print(f"\nOutput directory: {output_dir}")
    print(f"  - island_comparison.png")
    print(f"  - island_statistics.png")
    print(f"  - island_report.txt")
    print("=" * 70 + "\n")

    return islands, stats


def main():
    parser = argparse.ArgumentParser(
        description='Detect and analyze islands in map layouts',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze tumbleweed map
  python analyze_islands.py --bedrock map_folders/tumbleweed/layout_bedrock.parquet

  # With custom parameters
  python analyze_islands.py --bedrock map.parquet --connectivity 4 --min-size 20

  # Specify output directory
  python analyze_islands.py --bedrock map.parquet --output results/islands
        """
    )

    parser.add_argument(
        '--bedrock',
        required=True,
        help='Path to bedrock parquet file'
    )

    parser.add_argument(
        '--output',
        default='output',
        help='Output directory (default: output)'
    )

    parser.add_argument(
        '--map-name',
        help='Name of the map (default: derived from path)'
    )

    parser.add_argument(
        '--connectivity',
        type=int,
        default=8,
        choices=[4, 8],
        help='Island connectivity: 4 or 8 (default: 8)'
    )

    parser.add_argument(
        '--min-size',
        type=int,
        default=10,
        help='Minimum blocks for an island (default: 10)'
    )

    parser.add_argument(
        '--buffer',
        type=float,
        default=0.0,
        help='Buffer distance for smoothing (default: 0.0, no smoothing)'
    )

    parser.add_argument(
        '--simplify',
        type=float,
        default=3.0,
        help='Simplification tolerance (default: 3.0)'
    )

    parser.add_argument(
        '--no-holes',
        action='store_true',
        help='Disable hole detection'
    )

    args = parser.parse_args()

    analyze_map_islands(
        bedrock_parquet=args.bedrock,
        output_dir=args.output,
        map_name=args.map_name,
        connectivity=args.connectivity,
        min_island_size=args.min_size,
        buffer_distance=args.buffer,
        simplify_tolerance=args.simplify,
        detect_holes=not args.no_holes
    )


if __name__ == '__main__':
    main()
