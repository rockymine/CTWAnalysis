"""
Test script for skeleton pathfinding analysis.

Runs pathfinding on all available maps, prints summary, and generates
path grid visualizations.

Usage:
    python -m layout_analysis.skeleton.test_pathfinding
"""

import json
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from layout_analysis.skeleton.pathfinding import (
    run_pathfinding_analysis,
    load_edge_pixels,
    get_path_detail,
)
from layout_analysis.skeleton.visualize import plot_path_grid


def print_island_summary(result: dict) -> None:
    """Print summary for one island analysis result."""
    iid = result['island_id']
    team = result['team'] or 'neutral'
    spawn_count = result['spawn_count']
    wool_count = result['wool_count']
    ep_count = result['endpoint_count']

    print(f"  Island {iid} ({team}): {spawn_count} spawn, {wool_count} wools, {ep_count} endpoints")

    spawn_paths = [p for p in result['poi_to_endpoint_paths'] if p['poi_type'] == 'spawn']
    wool_paths = [p for p in result['poi_to_endpoint_paths'] if p['poi_type'] == 'wool']

    if spawn_paths:
        print(f"    - {len(spawn_paths)} spawn->endpoint paths")
    if wool_paths:
        print(f"    - {len(wool_paths)} wool->endpoint paths")

    defender = result.get('defender_paths')
    if defender:
        print(f"    - {len(defender)} defender paths (spawn->wool)")
        for dp in defender:
            print(f"      {dp['spawn_team']} spawn -> {dp['wool_color']} wool: "
                  f"{dp['length']} nodes, {dp['distance']} blocks")
    elif result['has_spawn'] and not result['has_wool']:
        print(f"    - No defender paths (no wools on island)")
    elif result['has_wool'] and not result['has_spawn']:
        print(f"    - No defender paths (no spawn on island)")


def test_map(map_name: str, map_folder: str) -> None:
    """Run and print pathfinding analysis for one map."""
    print(f"\nAnalyzing '{map_name}'...")
    print("=" * 50)

    results = run_pathfinding_analysis(map_folder)
    if results is None:
        print("  FAILED: Could not run analysis")
        return

    if results['islands_analyzed'] == 0:
        print("  No islands with POIs found")
        return

    # Reload map_graph.json for edge pixel data and visualization
    graph_path = os.path.join(map_folder, 'map_graph.json')
    with open(graph_path, 'r') as f:
        graph_data = json.load(f)
    islands_by_id = {ie['island_id']: ie for ie in graph_data.get('islands', [])}

    pathfinding_dir = os.path.join(map_folder, 'island_analysis', 'pathfinding')
    os.makedirs(pathfinding_dir, exist_ok=True)

    for island_result in results['island_results']:
        print_island_summary(island_result)

        iid = island_result['island_id']
        island_entry = islands_by_id.get(iid)
        if not island_entry:
            continue

        edge_px = load_edge_pixels(island_entry.get('skeleton'))

        # Test pixel path detail on first defender path (if any)
        if edge_px and island_result.get('defender_paths'):
            dp = island_result['defender_paths'][0]
            detail = get_path_detail(edge_px, dp['path_nodes'])
            if detail:
                print(f"    - Pixel detail for first defender path: {len(detail)} points")

        # Generate path grid visualization
        if edge_px:
            viz_path = os.path.join(pathfinding_dir, f"island_{iid}_paths.png")
            plot_path_grid(island_result, edge_px, viz_path)

    skipped = results['islands_skipped']
    if skipped > 0:
        print(f"  {skipped} island(s) skipped (no POIs)")

    print(f"\n  Summary: {results['islands_analyzed']} islands analyzed, "
          f"{results['total_poi_endpoint_paths']} POI->endpoint paths, "
          f"{results['total_defender_paths']} defender paths")


def main():
    map_folders_dir = os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))), 'map_folders')

    if not os.path.isdir(map_folders_dir):
        print(f"ERROR: map_folders directory not found at {map_folders_dir}")
        return

    # Find maps with map_context.json (i.e. fully analyzed)
    maps = []
    for name in sorted(os.listdir(map_folders_dir)):
        ctx_path = os.path.join(map_folders_dir, name, 'island_analysis', 'map_context.json')
        if os.path.exists(ctx_path):
            maps.append((name, os.path.join(map_folders_dir, name)))

    if not maps:
        print("No analyzed maps found (need map_context.json)")
        return

    print(f"Found {len(maps)} analyzed map(s): {', '.join(m[0] for m in maps)}")

    for map_name, map_folder in maps:
        test_map(map_name, map_folder)

    print("\nDone.")


if __name__ == '__main__':
    main()
