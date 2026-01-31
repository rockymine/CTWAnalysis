"""
CTW Path Network Generator

Generates path network visualizations from match data showing the "highway system"
that players create through their movement patterns.
"""

import argparse
import os
import json
import pandas as pd
from pathlib import Path

from match_analysis import (
    load_match_data,
    detect_life_segments,
    assign_teams
)
from match_analysis.path_network import (
    create_density_heatmap,
    extract_skeleton_network,
    extract_graph_network,
    extract_corridors,
    calculate_path_statistics
)
from match_analysis.path_network_viz import (
    plot_combined_network,
    plot_team_networks
)


def load_config(config_path: str = 'config.json') -> dict:
    """Load configuration from JSON file."""
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            return json.load(f)
    return {}


def generate_path_networks(
    match_file: str,
    map_name: str = None,
    bedrock_parquet: str = None,
    output_dir: str = 'output',
    resolution: float = 1.0,
    cluster_radius: float = 5.0,
    generate_team_networks: bool = True
):
    """
    Generate path network visualizations from match data.

    Args:
        match_file: Match parquet filename
        map_name: Optional map name for bedrock data
        bedrock_parquet: Optional direct path to bedrock parquet
        output_dir: Output directory for plots
        resolution: Grid resolution for heatmap (blocks)
        cluster_radius: Clustering radius for waypoint extraction (blocks)
        generate_team_networks: Whether to generate separate team networks
    """
    print("="*70)
    print("CTW PATH NETWORK GENERATOR")
    print("="*70)

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)

    # Load match data
    print(f"\n1. Loading match data...")
    match_data = load_match_data(match_file)

    # Detect life segments
    print("\n2. Detecting life segments...")
    life_segments = detect_life_segments(match_data)
    life_segments = assign_teams(life_segments)
    print(f"   Found {len(life_segments)} life segments")

    # Calculate path statistics
    print("\n3. Calculating path statistics...")
    stats = calculate_path_statistics(life_segments)
    print(f"   Total paths: {stats['total_paths']}")
    print(f"   Total distance: {stats['total_distance']:.1f} blocks")
    print(f"   Average path length: {stats['avg_path_length']:.1f} blocks")
    print(f"   Median path length: {stats['median_path_length']:.1f} blocks")
    print(f"   Max path length: {stats['max_path_length']:.1f} blocks")

    # Load map data if available
    map_data = None
    if bedrock_parquet and os.path.exists(bedrock_parquet):
        print(f"\n4. Loading map data from: {bedrock_parquet}")
        map_data = pd.read_parquet(bedrock_parquet)
        # Rename columns if needed
        if 'world_x' in map_data.columns:
            map_data = map_data.rename(columns={'world_x': 'X', 'world_z': 'Z', 'y': 'Y'})
        elif 'x' in map_data.columns:
            map_data = map_data.rename(columns={'x': 'X', 'z': 'Z', 'y': 'Y'})
        print(f"   Loaded {len(map_data)} bedrock blocks")
    elif map_name:
        try:
            from match_analysis import load_map_data
            print(f"\n4. Loading map data: {map_name}")
            map_data = load_map_data(map_name)
        except:
            print(f"\n4. Could not load map data for {map_name}")

    # Extract network components
    print("\n5. Extracting path networks...")

    print("   - Creating density heatmap...")
    heatmap, bounds = create_density_heatmap(life_segments, resolution=resolution)

    print("   - Extracting skeleton network...")
    skeleton, skeleton_points = extract_skeleton_network(
        heatmap, bounds, resolution=resolution, sigma=2.0, threshold_percentile=70
    )
    print(f"     Found {len(skeleton_points)} skeleton points")

    print("   - Extracting waypoint graph...")
    graph = extract_graph_network(life_segments, cluster_radius=cluster_radius)
    print(f"     Found {graph.number_of_nodes()} waypoints, {graph.number_of_edges()} connections")

    print("   - Extracting high-traffic corridors...")
    corridors = extract_corridors(life_segments, resolution=2.0, min_corridor_density=5.0)
    print(f"     Found {len(corridors)} corridors")

    # Generate combined visualization
    print("\n6. Generating combined network visualization...")
    combined_path = os.path.join(output_dir, 'path_network_combined.png')
    plot_combined_network(
        life_segments,
        map_data=map_data,
        output_path=combined_path,
        resolution=resolution,
        cluster_radius=cluster_radius
    )

    # Generate team-specific networks
    if generate_team_networks:
        print("\n7. Generating team-specific networks...")
        plot_team_networks(
            life_segments,
            map_data=map_data,
            output_dir=output_dir,
            resolution=resolution
        )

    # Save statistics
    stats_path = os.path.join(output_dir, 'path_network_stats.txt')
    with open(stats_path, 'w') as f:
        f.write("="*70 + "\n")
        f.write("CTW PATH NETWORK STATISTICS\n")
        f.write("="*70 + "\n\n")
        f.write(f"Match: {match_file}\n")
        if map_name:
            f.write(f"Map: {map_name}\n")
        f.write(f"\nAnalysis Parameters:\n")
        f.write(f"  Resolution: {resolution} blocks\n")
        f.write(f"  Cluster radius: {cluster_radius} blocks\n")
        f.write(f"\nPath Statistics:\n")
        f.write(f"  Total paths: {stats['total_paths']}\n")
        f.write(f"  Total distance: {stats['total_distance']:.1f} blocks\n")
        f.write(f"  Average path length: {stats['avg_path_length']:.1f} blocks\n")
        f.write(f"  Median path length: {stats['median_path_length']:.1f} blocks\n")
        f.write(f"  Max path length: {stats['max_path_length']:.1f} blocks\n")
        f.write(f"\nNetwork Components:\n")
        f.write(f"  Skeleton points: {len(skeleton_points)}\n")
        f.write(f"  Waypoints: {graph.number_of_nodes()}\n")
        f.write(f"  Connections: {graph.number_of_edges()}\n")
        f.write(f"  Corridors: {len(corridors)}\n")
        f.write("\n" + "="*70 + "\n")

    print(f"\nStatistics saved to: {stats_path}")

    print("\n" + "="*70)
    print("PATH NETWORK GENERATION COMPLETE")
    print("="*70)
    print(f"\nOutput directory: {output_dir}")
    print(f"  - path_network_combined.png (6 visualization methods)")
    if generate_team_networks:
        print(f"  - path_network_red_team.png")
        print(f"  - path_network_blue_team.png")
    print(f"  - path_network_stats.txt")
    print("="*70 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description='Generate path network visualizations from CTW match data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Use config.json settings
  python generate_path_networks.py

  # Specify match file directly
  python generate_path_networks.py --match 2026-01-24_22-24-17_75.parquet

  # With map data for background
  python generate_path_networks.py --match 2026-01-24_22-24-17_75.parquet --map-bedrock map_folders/tumbleweed/layout_bedrock.parquet

  # Adjust analysis parameters
  python generate_path_networks.py --match 2026-01-24_22-24-17_75.parquet --resolution 0.5 --cluster-radius 3.0

  # Skip team-specific networks
  python generate_path_networks.py --match 2026-01-24_22-24-17_75.parquet --no-team-networks
        """
    )

    parser.add_argument(
        '--match',
        help='Match parquet file (default: from config.json)'
    )

    parser.add_argument(
        '--map-name',
        help='Map name for loading bedrock data (default: from config.json)'
    )

    parser.add_argument(
        '--map-bedrock',
        help='Direct path to bedrock parquet file'
    )

    parser.add_argument(
        '--output',
        default='output',
        help='Output directory (default: output)'
    )

    parser.add_argument(
        '--resolution',
        type=float,
        default=1.0,
        help='Grid resolution in blocks (default: 1.0)'
    )

    parser.add_argument(
        '--cluster-radius',
        type=float,
        default=5.0,
        help='Waypoint clustering radius in blocks (default: 5.0)'
    )

    parser.add_argument(
        '--no-team-networks',
        action='store_true',
        help='Skip generating team-specific network plots'
    )

    parser.add_argument(
        '--config',
        default='config.json',
        help='Config file path (default: config.json)'
    )

    args = parser.parse_args()

    # Load config
    config = load_config(args.config)

    # Determine match file
    match_file = args.match
    if not match_file:
        match_file = config.get('data_files', {}).get('match_file')
        if not match_file:
            print("Error: No match file specified. Use --match or configure in config.json")
            return

    # Determine map name
    map_name = args.map_name
    if not map_name and not args.map_bedrock:
        map_name = config.get('data_files', {}).get('map_name')

    # Generate networks
    generate_path_networks(
        match_file=match_file,
        map_name=map_name,
        bedrock_parquet=args.map_bedrock,
        output_dir=args.output,
        resolution=args.resolution,
        cluster_radius=args.cluster_radius,
        generate_team_networks=not args.no_team_networks
    )


if __name__ == '__main__':
    main()
