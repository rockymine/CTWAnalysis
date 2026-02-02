"""
Main workflow script for CTW map and match analysis.

Orchestrates the complete analysis pipeline:
1. Layout extraction from world folders (if not already done)
2. XML parsing to extract map configuration
3. Match analysis using layout data and XML configuration
"""

import argparse
import sys
from pathlib import Path
import json
import os
from datetime import datetime

# Import analysis modules
from layout_analysis import RegionReader, Y0LayerExtractor, TopSurfaceExtractor, VerticalDensityExtractor, LowestBedrockExtractor
from xml_analysis import MapXMLParser, MapDataEncoder
from match_analysis import (
    load_map_data,
    load_match_data,
    detect_life_segments,
    assign_teams,
    render_map_tiles,
    setup_map_axes,
    calculate_player_stats,
    analyze_map_characteristics,
    classify_all_segments,
    EVENT_IDS,
    TEAM_COLORS,
    EVENT_MARKERS
)
from match_analysis.preprocessing import LifeSegment
from match_analysis.pdf_report import generate_match_summary_pdf, generate_classification_pdf
from classify_segments import generate_classification_report
from match_analysis.path_network import (
    create_density_heatmap,
    extract_skeleton_network,
    extract_graph_network,
    extract_corridors
)
from match_analysis.path_network_viz import plot_combined_network, plot_team_networks
from layout_analysis.islands import (
    detect_islands,
    triangulate_island_union,
    triangulate_islands_canonical,
    compute_island_statistics,
    classify_islands,
    create_island_report,
)
from layout_analysis.skeleton import process_all_islands
from layout_analysis.skeleton.visualize import (
    plot_island_debug,
    plot_unique_islands,
    plot_world_overview,
    generate_skeleton_report,
    plot_island_poi_debug,
)
from layout_analysis.skeleton.poi_annotation import (
    annotate_skeleton_pois,
    compute_map_center,
    classify_island_center,
)
from layout_analysis.map_context import build_map_context
from layout_analysis.skeleton.pathfinding import run_pathfinding_analysis, load_edge_pixels
from layout_analysis.skeleton.visualize import plot_path_grid
from layout_analysis.connectivity import build_map_graph, save_map_graph, plot_map_connectivity


def analyze_layout(map_folder: Path, force_rerun: bool = False):
    """
    Step 1: Extract layout data from world folder.

    Args:
        map_folder: Path to map folder (e.g., map_folders/tumbleweed)
        force_rerun: If True, regenerate even if parquet files exist

    Returns:
        dict: Paths to generated parquet files
    """
    print(f"\n[1/4] Layout Analysis: {map_folder.name}")
    print("=" * 70)

    # Define output paths
    parquet_files = {
        'y0_layer': map_folder / 'layout_y0.parquet',
        'top_surface': map_folder / 'layout_top_surface.parquet',
        'vertical_density': map_folder / 'layout_vertical_density.parquet',
        'bedrock': map_folder / 'layout_bedrock.parquet',
    }

    # Check if files already exist
    all_exist = all(p.exists() for p in parquet_files.values())
    if all_exist and not force_rerun:
        print("  Layout files already exist. Skipping extraction.")
        for name, path in parquet_files.items():
            print(f"    [OK] {path.name}")
        return parquet_files

    # Find region folder
    region_folder = map_folder / 'region'
    if not region_folder.exists():
        print(f"  [X] No region folder found at {region_folder}")
        return None

    print(f"  Extracting layout from: {region_folder}")

    # Initialize reader
    reader = RegionReader(str(region_folder))

    # Extract Y=0 layer
    if not parquet_files['y0_layer'].exists() or force_rerun:
        print("  Extracting Y=0 layer...")
        extractor = Y0LayerExtractor(reader)
        df = extractor.extract()
        df.to_parquet(parquet_files['y0_layer'])
        print(f"    [OK] Saved {parquet_files['y0_layer'].name} ({len(df)} blocks)")

    # Extract top surface
    if not parquet_files['top_surface'].exists() or force_rerun:
        print("  Extracting top surface...")
        extractor = TopSurfaceExtractor(reader)
        df = extractor.extract()
        df.to_parquet(parquet_files['top_surface'])
        print(f"    [OK] Saved {parquet_files['top_surface'].name} ({len(df)} blocks)")

    # Extract vertical density
    if not parquet_files['vertical_density'].exists() or force_rerun:
        print("  Extracting vertical density...")
        extractor = VerticalDensityExtractor(reader, threshold=10, mode='run')
        df = extractor.extract()
        df.to_parquet(parquet_files['vertical_density'])
        print(f"    [OK] Saved {parquet_files['vertical_density'].name} ({len(df)} columns)")

    # Extract bedrock
    if not parquet_files['bedrock'].exists() or force_rerun:
        print("  Extracting lowest bedrock...")
        extractor = LowestBedrockExtractor(reader)
        df = extractor.extract()
        df.to_parquet(parquet_files['bedrock'])
        print(f"    [OK] Saved {parquet_files['bedrock'].name} ({len(df)} blocks)")

    return parquet_files


def analyze_islands_step(
    map_folder: Path,
    force_rerun: bool = False,
    simplify_tolerance: float = 1.0,
    buffer_distance: float = 0.0,
    layout_type: str = 'bedrock',
    canonical_triangulation: bool = False,
):
    """
    Step 2: Detect and triangulate islands from layout data.

    Args:
        map_folder: Path to map folder (e.g., map_folders/tumbleweed)
        force_rerun: If True, regenerate even if output exists
        simplify_tolerance: Simplification tolerance for union triangulation
        buffer_distance: Buffer distance for smoothing
        layout_type: Which layout file to use ('bedrock', 'y0', 'top', 'density')
        canonical_triangulation: If True, use canonical-consistent triangulation
            so that symmetrically identical islands share the same mesh

    Returns:
        Path: Path to island analysis output directory
    """
    import pandas as pd

    # Map layout type to file name
    layout_files = {
        'bedrock': 'layout_bedrock.parquet',
        'y0': 'layout_y0.parquet',
        'top': 'layout_top_surface.parquet',
        'density': 'layout_vertical_density.parquet'
    }

    print(f"\n[2/4] Island Analysis: {map_folder.name}")
    print("=" * 70)

    # Check for layout file
    layout_filename = layout_files.get(layout_type, 'layout_bedrock.parquet')
    layout_file = map_folder / layout_filename
    if not layout_file.exists():
        print(f"  [X] Layout file not found: {layout_filename}. Run layout analysis first.")
        return None

    # Define output directory
    island_output_dir = map_folder / 'island_analysis'

    # Check if already exists
    report_file = island_output_dir / 'island_report.txt'
    if report_file.exists() and not force_rerun:
        print(f"  Island analysis already exists. Skipping.")
        print(f"    [OK] {island_output_dir.name}/")
        return island_output_dir

    # Create output directory
    island_output_dir.mkdir(exist_ok=True)

    print(f"  Loading layout data: {layout_file.name}")
    df = pd.read_parquet(layout_file)
    print(f"    Loaded {len(df)} blocks")

    # Detect islands
    print(f"  Detecting islands (8-connectivity, min_size=10)...")
    islands = detect_islands(
        df,
        x_col='world_x',
        z_col='world_z',
        connectivity=8,
        min_island_size=10
    )
    print(f"    Found {len(islands)} islands")

    # Add island_id column to layout parquet
    island_assignments = []
    for island in islands:
        for x, z in island.blocks:
            island_assignments.append({
                'world_x': int(round(x)),
                'world_z': int(round(z)),
                'island_id': island.id,
            })
    if island_assignments:
        island_df = pd.DataFrame(island_assignments)
        df = df.drop(columns=['island_id'], errors='ignore')
        df = df.merge(island_df, on=['world_x', 'world_z'], how='left')
        df['island_id'] = df['island_id'].fillna(0).astype(int)
        df.to_parquet(layout_file, index=False)
        print(f"    Updated {layout_file.name} with island_id column")

    if not islands:
        print("  [X] No islands detected!")
        return island_output_dir

    # Triangulate islands
    if canonical_triangulation:
        print(f"  Triangulating islands (canonical mode, simplify={simplify_tolerance})...")
        total_triangles = triangulate_islands_canonical(
            islands,
            buffer_distance=buffer_distance,
            simplify_tolerance=simplify_tolerance,
            detect_holes=True
        )
    else:
        print(f"  Triangulating islands (union mode, simplify={simplify_tolerance})...")
        total_triangles = 0
        for island in islands:
            triangles = triangulate_island_union(
                island,
                buffer_distance=buffer_distance,
                simplify_tolerance=simplify_tolerance,
                detect_holes=True
            )
            total_triangles += len(triangles)

    print(f"    Total triangles: {total_triangles}")

    # Compute statistics
    stats = compute_island_statistics(islands)

    # Classify islands
    classifications = classify_islands(islands)
    print(f"  Island classifications:")
    for cls_name, cls_islands in classifications.items():
        if cls_islands:
            ids = [i.id for i in cls_islands]
            print(f"    {cls_name}: {ids}")

    # Skeleton analysis (new pipeline)
    print(f"  Computing skeleton graphs...")
    skeleton_results, canonical_groups = process_all_islands(
        islands, enable_canonicalization=True, skeleton_connectivity=8
    )
    total_nodes = sum(len(r.graph.nodes) for r in skeleton_results)
    total_edges = sum(len(r.graph.edges) for r in skeleton_results)
    total_ep = sum(sum(1 for n in r.graph.nodes if n.node_type == 'endpoint') for r in skeleton_results)
    total_jn = sum(sum(1 for n in r.graph.nodes if n.node_type == 'junction') for r in skeleton_results)
    print(f"    Nodes: {total_nodes} ({total_ep} endpoints, {total_jn} junctions)")
    print(f"    Edges: {total_edges}")
    print(f"    Unique canonical shapes: {len(canonical_groups)}")

    # Generate report and visualizations
    print(f"  Generating visualizations...")
    create_island_report(islands, stats, str(island_output_dir), map_folder.name)

    # Skeleton visualizations
    skeleton_output_dir = island_output_dir / 'skeleton'
    skeleton_output_dir.mkdir(exist_ok=True)

    # Per-island debug images (one per unique canonical shape)
    result_by_id = {r.island_id: r for r in skeleton_results}
    for key, ids in canonical_groups.items():
        rep_id = min(ids)
        if rep_id in result_by_id:
            plot_island_debug(
                result_by_id[rep_id],
                str(skeleton_output_dir / f'island_{rep_id}_debug.png')
            )

    # Unique islands grid
    plot_unique_islands(
        skeleton_results, canonical_groups,
        str(skeleton_output_dir / 'unique_islands.png')
    )

    # World overview
    plot_world_overview(
        skeleton_results,
        str(skeleton_output_dir / 'world_overview.png')
    )

    # Text report
    generate_skeleton_report(
        skeleton_results, canonical_groups,
        str(skeleton_output_dir / 'skeleton_report.txt'),
        map_name=map_folder.name
    )

    # POI annotation and MapContext (requires XML)
    xml_file = map_folder / 'map.xml'
    map_data_obj = None
    poi_assignments = None
    map_center_pt = compute_map_center(df)

    # Classify island center distances
    classify_island_center(islands, map_center_pt)

    if xml_file.exists():
        try:
            from xml_analysis import MapXMLParser
            parser = MapXMLParser(str(xml_file))
            map_data_obj = parser.parse()

            print(f"  Annotating POIs from XML...")
            poi_assignments = annotate_skeleton_pois(
                islands, skeleton_results, map_data_obj
            )
            n_spawn = sum(1 for s in poi_assignments.get('spawns', []) if s.get('node_id') is not None)
            n_wool = sum(1 for w in poi_assignments.get('wools', []) if w.get('node_id') is not None)
            print(f"    Spawns assigned: {n_spawn}, Wools assigned: {n_wool}")

            # POI debug images for islands with any POI nodes
            for result in skeleton_results:
                has_poi = any(n.poi_type is not None for n in result.graph.nodes)
                if has_poi:
                    plot_island_poi_debug(
                        result,
                        str(skeleton_output_dir / f'island_{result.island_id}_poi.png')
                    )
        except Exception as e:
            print(f"    [!] POI annotation failed: {e}")
    else:
        print(f"  No map.xml found, skipping POI annotation")

    # Build and save MapContext
    map_ctx = build_map_context(
        islands, skeleton_results, canonical_groups, df,
        map_data=map_data_obj,
        map_center=map_center_pt,
        poi_assignments=poi_assignments,
    )
    map_ctx.save_json(str(island_output_dir / 'map_context.json'))

    # Run pathfinding analysis (reads skeleton from map_context.json)
    print(f"  Running pathfinding analysis...")
    pathfinding_results = run_pathfinding_analysis(str(map_folder))
    if pathfinding_results and pathfinding_results['islands_analyzed'] > 0:
        n_analyzed = pathfinding_results['islands_analyzed']
        n_paths = pathfinding_results['total_poi_endpoint_paths']
        n_defender = pathfinding_results['total_defender_paths']
        print(f"    Pathfinding: {n_analyzed} islands, {n_paths} POI paths, {n_defender} defender paths")

        # Generate path grid visualizations
        pathfinding_dir = island_output_dir / 'pathfinding'
        pathfinding_dir.mkdir(exist_ok=True)

        # Reload updated context (now has pathfinding results embedded)
        with open(str(island_output_dir / 'map_context.json'), 'r') as ctx_f:
            updated_ctx = json.load(ctx_f)
        islands_by_id = {i['id']: i for i in updated_ctx.get('islands', [])}

        for island_result in pathfinding_results['island_results']:
            iid = island_result['island_id']
            island_ctx = islands_by_id.get(iid)
            if island_ctx:
                edge_px = load_edge_pixels(island_ctx.get('skeleton'))
                if edge_px:
                    plot_path_grid(
                        island_result, edge_px,
                        str(pathfinding_dir / f'island_{iid}_paths.png')
                    )

    # Build inter-island connectivity graph
    print(f"  Building map connectivity graph...")
    context_path_for_graph = island_output_dir / 'map_context.json'
    if context_path_for_graph.exists():
        with open(str(context_path_for_graph), 'r') as ctx_f:
            graph_ctx = json.load(ctx_f)
        map_graph = build_map_graph(graph_ctx)
        save_map_graph(map_graph, map_folder)

        n_nodes = len(map_graph['nodes'])
        n_intra = sum(1 for e in map_graph['edges'] if e['edge_type'] == 'intra')
        n_void = sum(1 for e in map_graph['edges'] if e['edge_type'] == 'void_link')
        print(f"    Map Graph: {n_nodes} nodes, {n_intra} intra-island edges, {n_void} void links")

        viz_path = island_output_dir / 'map_connectivity.png'
        plot_map_connectivity(graph_ctx, map_graph, viz_path)

    # Cleanup legacy per-island CSV/JSON exports
    import shutil
    legacy_exports = island_output_dir / 'skeleton' / 'exports'
    if legacy_exports.exists():
        shutil.rmtree(legacy_exports)
        print(f"    Removed legacy exports directory")
    legacy_paths = island_output_dir / 'pathfinding' / 'paths_analysis.json'
    if legacy_paths.exists():
        legacy_paths.unlink()
        print(f"    Removed legacy paths_analysis.json")

    print(f"    [OK] Saved to: {island_output_dir.name}/")

    return island_output_dir


def analyze_xml(map_folder: Path, force_rerun: bool = False):
    """
    Step 3: Parse XML configuration and extract map data.

    Args:
        map_folder: Path to map folder (e.g., map_folders/tumbleweed)
        force_rerun: If True, regenerate even if JSON file exists

    Returns:
        Path: Path to generated JSON file
    """
    print(f"\n[3/4] XML Analysis: {map_folder.name}")
    print("=" * 70)

    # Define paths
    xml_file = map_folder / 'map.xml'
    json_file = map_folder / 'map_data.json'

    # Check if JSON already exists
    if json_file.exists() and not force_rerun:
        print(f"  Map data already exists: {json_file.name}")
        return json_file

    # Check if XML exists
    if not xml_file.exists():
        print(f"  [X] No XML file found at {xml_file}")
        return None

    print(f"  Parsing XML: {xml_file.name}")

    try:
        # Parse XML
        parser = MapXMLParser(str(xml_file))
        map_data = parser.parse()
        categories = parser.identify_region_categories(map_data)

        # Save JSON
        MapDataEncoder.save_json(map_data, str(json_file), categories)

        print(f"    [OK] Saved {json_file.name}")
        print(f"      - Teams: {len(map_data.teams)}")
        print(f"      - Spawns: {len(map_data.spawns)}")
        print(f"      - Wools: {len(map_data.wools)}")
        print(f"      - Regions: {len(map_data.regions)}")

        return json_file

    except Exception as e:
        print(f"  [X] Failed to parse XML: {e}")
        return None


def parse_match_history(match_history_file: Path, map_name: str):
    """
    Parse match history file to find all matches for a given map.

    Args:
        match_history_file: Path to match_history.txt
        map_name: Name of the map to filter for

    Returns:
        list: List of match file names for this map
    """
    if not match_history_file.exists():
        return []

    matches = []
    with open(match_history_file, 'r') as f:
        lines = [line.strip() for line in f.readlines()]

    # Parse alternating lines (map name, match file, map name, match file, ...)
    for i in range(0, len(lines) - 1, 2):
        file_map_name = lines[i]
        match_file = lines[i + 1]

        # Match by map name (case-insensitive, flexible matching)
        if file_map_name.lower().replace(' ', '') == map_name.lower().replace(' ', ''):
            matches.append(match_file)

    return matches


def analyze_single_match(map_name: str, match_file: str, bedrock_parquet: Path, output_dir: Path):
    """
    Analyze a single match and generate plots/reports.

    Args:
        map_name: Name of the map
        match_file: Match parquet filename
        bedrock_parquet: Path to bedrock layout parquet file
        output_dir: Directory to save results

    Returns:
        bool: True if successful, False otherwise
    """
    import matplotlib.pyplot as plt
    from collections import Counter
    import pandas as pd

    try:
        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)

        # Load map data directly from bedrock parquet
        map_data = pd.read_parquet(bedrock_parquet)

        # Rename columns to match expected format (world_x -> X, world_z -> Z)
        if 'world_x' in map_data.columns:
            map_data = map_data.rename(columns={'world_x': 'X', 'world_z': 'Z', 'y': 'Y'})
        elif 'x' in map_data.columns:
            map_data = map_data.rename(columns={'x': 'X', 'z': 'Z', 'y': 'Y'})

        print(f"      Loaded map bedrock: {len(map_data)} blocks")

        # Load match data
        match_data = load_match_data(match_file)

        # Process match data
        life_segments = detect_life_segments(match_data)
        life_segments = assign_teams(life_segments)

        if not life_segments:
            print(f"      [X] No life segments found in match")
            return False

        # Classify segments
        map_chars = analyze_map_characteristics(life_segments, match_data)
        classifications = classify_all_segments(life_segments, map_chars)

        # Calculate statistics
        player_stats = calculate_player_stats(life_segments)

        # Generate team plots
        plot_configs = [
            ('all_teams', None, 'All Teams'),
            ('red_team', 'red', 'Red Team'),
            ('blue_team', 'blue', 'Blue Team')
        ]

        for team_key, team_filter, team_title in plot_configs:
            fig, ax = plt.subplots(figsize=(14, 10))

            # Filter segments
            if team_filter:
                segments_to_plot = [seg for seg in life_segments if seg.team == team_filter]
            else:
                segments_to_plot = life_segments

            # Render map
            render_map_tiles(ax, map_data)

            # Plot segments
            labels_added = set()
            for segment in segments_to_plot:
                events = segment.events
                if events.empty:
                    continue

                color = TEAM_COLORS.get(segment.team, TEAM_COLORS['unknown'])

                # Position trace
                position_events = events[events['event_type'] == EVENT_IDS['POSITION']]
                if not position_events.empty:
                    ax.plot(position_events['x'], position_events['z'],
                           color=color, alpha=0.6, linewidth=2, zorder=1)

                # Spawn
                spawn_x, spawn_y, spawn_z = segment.spawn_coords
                spawn_marker = EVENT_MARKERS['spawn']
                ax.scatter([spawn_x], [spawn_z],
                          marker=spawn_marker['marker'], s=spawn_marker['size'],
                          c=spawn_marker['color'], edgecolors=spawn_marker['edgecolor'],
                          linewidths=spawn_marker['linewidth'], zorder=3,
                          label='Spawn' if 'Spawn' not in labels_added else '')
                labels_added.add('Spawn')

                # Deaths
                death_events = events[events['event_type'] == EVENT_IDS['DEATH']]
                if not death_events.empty:
                    death_marker = EVENT_MARKERS['death']
                    ax.scatter(death_events['x'], death_events['z'],
                              marker=death_marker['marker'], s=death_marker['size'],
                              c=death_marker['color'], linewidths=death_marker['linewidth'],
                              zorder=3, label='Death' if 'Death' not in labels_added else '')
                    labels_added.add('Death')

                # Wool captures
                wool_capture_events = events[events['event_type'] == EVENT_IDS['WOOL_CAPTURE']]
                if not wool_capture_events.empty:
                    capture_marker = EVENT_MARKERS['wool_capture']
                    ax.scatter(wool_capture_events['x'], wool_capture_events['z'],
                              marker=capture_marker['marker'], s=capture_marker['size'],
                              c=capture_marker['color'], edgecolors=capture_marker['edgecolor'],
                              linewidths=capture_marker['linewidth'], zorder=4,
                              label='Wool Capture' if 'Wool Capture' not in labels_added else '')
                    labels_added.add('Wool Capture')

            # Setup axes and legend
            setup_map_axes(ax, map_data, title=f"CTW Match - {map_name} - {team_title}")

            # Add team patches to legend
            from matplotlib.patches import Patch
            handles, labels_list = ax.get_legend_handles_labels()
            if team_filter is None or team_filter == 'red':
                handles.append(Patch(color=TEAM_COLORS['red'], label='Red Team'))
                labels_list.append('Red Team')
            if team_filter is None or team_filter == 'blue':
                handles.append(Patch(color=TEAM_COLORS['blue'], label='Blue Team'))
                labels_list.append('Blue Team')
            ax.legend(handles, labels_list, loc='upper right', fontsize=9, framealpha=0.9)

            # Save
            plot_path = output_dir / f'{team_key}.png'
            fig.savefig(plot_path, dpi=150, bbox_inches='tight')
            plt.close(fig)

        # Generate PDF summary
        pdf_path = output_dir / 'match_summary.pdf'
        config = {'data_files': {'map_name': map_name, 'match_file': match_file}}
        generate_match_summary_pdf(life_segments, player_stats, config, str(pdf_path))

        # Generate classification reports
        generate_classification_report(
            life_segments=life_segments,
            classifications=classifications,
            map_chars=map_chars,
            output_dir=str(output_dir)
        )

        classification_pdf_path = output_dir / 'classification_report.pdf'
        generate_classification_pdf(
            life_segments=life_segments,
            classifications=classifications,
            map_chars=map_chars,
            config=config,
            output_path=str(classification_pdf_path)
        )

        # Generate path network visualizations
        path_network_combined = output_dir / 'path_network_combined.png'
        plot_combined_network(
            life_segments=life_segments,
            map_data=map_data,
            output_path=str(path_network_combined),
            resolution=1.0,
            cluster_radius=5.0
        )

        # Generate team-specific path networks
        plot_team_networks(
            life_segments=life_segments,
            map_data=map_data,
            output_dir=str(output_dir),
            resolution=1.0
        )

        # Generate text summary
        summary_path = output_dir / 'match_summary.txt'
        with open(summary_path, 'w') as f:
            f.write("=" * 70 + "\n")
            f.write("CTW MATCH ANALYSIS SUMMARY\n")
            f.write("=" * 70 + "\n\n")
            f.write(f"Map: {map_name}\n")
            f.write(f"Match: {match_file}\n\n")
            f.write(f"Total Players: {len(set(seg.player_id for seg in life_segments))}\n")
            f.write(f"Total Life Segments: {len(life_segments)}\n\n")

            team_counts = Counter(seg.team for seg in life_segments)
            f.write("Team Distribution:\n")
            for team, count in team_counts.items():
                f.write(f"  {team.capitalize()}: {count} segments\n")

        return True

    except Exception as e:
        print(f"      [X] Error analyzing match: {e}")
        return False


def analyze_matches(map_folder: Path, match_history_file: Path):
    """
    Step 4: Analyze matches for this map.

    Args:
        map_folder: Path to map folder (e.g., map_folders/tumbleweed)
        match_history_file: Path to match history file

    Returns:
        list: Paths to generated match analysis folders
    """
    print(f"\n[4/4] Match Analysis: {map_folder.name}")
    print("=" * 70)

    # Check prerequisites
    json_file = map_folder / 'map_data.json'
    if not json_file.exists():
        print("  [X] Map data JSON not found. Run XML analysis first.")
        return []

    # Check for bedrock layout file (required for match analysis)
    bedrock_file = map_folder / 'layout_bedrock.parquet'
    if not bedrock_file.exists():
        print("  [X] Bedrock layout file not found. Run layout analysis first.")
        return []

    print(f"  Prerequisites satisfied:")
    print(f"    [OK] Map data: {json_file.name}")
    print(f"    [OK] Bedrock layout: {bedrock_file.name}")

    # Parse match history to find matches for this map
    with open(json_file, 'r') as f:
        map_data_json = json.load(f)
    map_name = map_data_json['name']

    matches = parse_match_history(match_history_file, map_name)

    if not matches:
        print(f"  No matches found for {map_name} in match history")
        return []

    print(f"  Found {len(matches)} match(es) for {map_name}")

    # Create matches directory
    matches_dir = map_folder / 'matches'
    matches_dir.mkdir(exist_ok=True)

    # Analyze each match
    results = []
    for i, match_file in enumerate(matches, 1):
        # Extract match ID from filename (remove .parquet extension)
        match_id = match_file.replace('.parquet', '')

        print(f"\n  [{i}/{len(matches)}] Analyzing match: {match_id}")

        # Create output directory for this match
        match_output_dir = matches_dir / match_id
        if match_output_dir.exists():
            print(f"      Match analysis already exists. Skipping.")
            results.append(match_output_dir)
            continue

        # Analyze match
        success = analyze_single_match(map_name, match_file, bedrock_file, match_output_dir)

        if success:
            print(f"      [OK] Saved to: {match_output_dir.relative_to(map_folder)}")
            results.append(match_output_dir)
        else:
            # Remove failed directory
            if match_output_dir.exists():
                import shutil
                shutil.rmtree(match_output_dir)

    print(f"\n  Successfully analyzed {len(results)}/{len(matches)} matches")

    return results


def main():
    parser = argparse.ArgumentParser(
        description='CTW Map and Match Analysis Workflow',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Workflow Steps:
  1. Layout Analysis - Extract block data from world folders
  2. Island Analysis - Detect and triangulate islands from bedrock
  3. XML Analysis - Parse map configuration from XML
  4. Match Analysis - Analyze matches using layout and XML data

Examples:
  # Analyze a single map (all steps)
  python run_analysis_workflow.py --map tumbleweed

  # Analyze specific map with force rerun
  python run_analysis_workflow.py --map kanto --force

  # Analyze all maps
  python run_analysis_workflow.py --all

  # Skip match analysis
  python run_analysis_workflow.py --map tumbleweed --no-matches

  # Skip island analysis
  python run_analysis_workflow.py --map tumbleweed --no-islands
        """
    )

    parser.add_argument(
        '--map',
        help='Map name to analyze (e.g., tumbleweed, kanto)'
    )

    parser.add_argument(
        '--all',
        action='store_true',
        help='Analyze all maps in map_folders directory'
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='Force regeneration of existing files'
    )

    parser.add_argument(
        '--no-layout',
        action='store_true',
        help='Skip layout analysis'
    )

    parser.add_argument(
        '--no-islands',
        action='store_true',
        help='Skip island detection and triangulation'
    )

    parser.add_argument(
        '--no-xml',
        action='store_true',
        help='Skip XML analysis'
    )

    parser.add_argument(
        '--no-matches',
        action='store_true',
        help='Skip match analysis'
    )

    parser.add_argument(
        '--match-history',
        default='match_logs/match_history.txt',
        help='Path to match history file (default: match_logs/match_history.txt)'
    )

    parser.add_argument(
        '--island-layout',
        choices=['bedrock', 'y0', 'top', 'density'],
        default='bedrock',
        help='Layout file to use for island analysis (default: bedrock)'
    )

    parser.add_argument(
        '--canonical-triangulation',
        action='store_true',
        help='Use canonical-consistent triangulation (identical islands share same mesh)'
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.map and not args.all:
        parser.print_help()
        print("\nError: Must specify either --map or --all", file=sys.stderr)
        sys.exit(1)

    # Find map folders
    map_folders_dir = Path('map_folders')
    if not map_folders_dir.exists():
        print(f"Error: Map folders directory not found: {map_folders_dir}", file=sys.stderr)
        sys.exit(1)

    # Determine which maps to analyze
    if args.all:
        map_folders = [f for f in map_folders_dir.iterdir() if f.is_dir()]
    else:
        map_folder = map_folders_dir / args.map
        if not map_folder.exists():
            print(f"Error: Map folder not found: {map_folder}", file=sys.stderr)
            sys.exit(1)
        map_folders = [map_folder]

    print("=" * 70)
    print("CTW ANALYSIS WORKFLOW")
    print("=" * 70)
    print(f"Maps to analyze: {len(map_folders)}")
    for folder in map_folders:
        print(f"  - {folder.name}")
    print()

    # Match history file
    match_history_path = Path(args.match_history)

    # Process each map
    for map_folder in map_folders:
        print(f"\n{'=' * 70}")
        print(f"Processing: {map_folder.name}")
        print(f"{'=' * 70}")

        # Step 1: Layout Analysis
        if not args.no_layout:
            layout_files = analyze_layout(map_folder, force_rerun=args.force)
        else:
            print("\n[1/4] Layout Analysis: SKIPPED")

        # Step 2: Island Analysis
        if not args.no_islands:
            island_dir = analyze_islands_step(
                map_folder, force_rerun=args.force,
                layout_type=args.island_layout,
                canonical_triangulation=args.canonical_triangulation,
            )
        else:
            print("\n[2/4] Island Analysis: SKIPPED")

        # Step 3: XML Analysis
        if not args.no_xml:
            json_file = analyze_xml(map_folder, force_rerun=args.force)
        else:
            print("\n[3/4] XML Analysis: SKIPPED")

        # Step 4: Match Analysis
        if not args.no_matches:
            if match_history_path.exists():
                match_results = analyze_matches(map_folder, match_history_path)
            else:
                print(f"\n[4/4] Match Analysis: SKIPPED (match history not found)")
        else:
            print("\n[4/4] Match Analysis: SKIPPED")

    print(f"\n{'=' * 70}")
    print("WORKFLOW COMPLETE")
    print(f"{'=' * 70}\n")


if __name__ == '__main__':
    main()
