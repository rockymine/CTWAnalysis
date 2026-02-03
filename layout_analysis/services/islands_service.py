"""Island detection, skeleton, pathfinding, and connectivity orchestration."""

import json
from pathlib import Path


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
    from layout_analysis.map_context import build_map_context, build_skeleton_dicts
    from layout_analysis.skeleton.pathfinding import run_pathfinding_analysis, load_edge_pixels
    from layout_analysis.skeleton.visualize import plot_path_grid
    from layout_analysis.connectivity import (
        build_map_graph,
        save_map_graph,
        save_initial_map_graph,
        plot_map_connectivity,
    )

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

    # Build and save MapContext (metadata + island geometry, no skeleton)
    map_ctx = build_map_context(
        islands, skeleton_results, canonical_groups, df,
        map_data=map_data_obj,
        map_center=map_center_pt,
        poi_assignments=poi_assignments,
    )

    # Build region extraction
    if map_data_obj is not None:
        try:
            from xml_analysis.build_regions import extract_build_region
            from shapely.geometry import Polygon as ShapelyPolygon

            island_shapely = []
            for island in islands:
                if island.simplified_polygon:
                    ext = island.simplified_polygon['exterior']
                    holes = island.simplified_polygon.get('holes', [])
                    try:
                        poly = ShapelyPolygon(ext, holes)
                        if poly.is_valid:
                            island_shapely.append(poly)
                    except Exception:
                        pass

            y0_path = str(map_folder / 'layout_y0.parquet')
            build_result = extract_build_region(
                map_data=map_data_obj,
                map_bounds=map_ctx.bounding_box,
                y0_parquet_path=y0_path,
                island_polygons=island_shapely,
            )
            if build_result:
                map_ctx.build_region = build_result
                print(f"    Build region: source={build_result['source']}, "
                      f"void_area={build_result['buildable_void_area']}")
            else:
                print(f"    No build region detected")
        except Exception as e:
            print(f"    [!] Build region extraction failed: {e}")

    map_ctx.save_json(str(island_output_dir / 'map_context.json'))

    # Build skeleton dicts and save initial map_graph.json (skeleton data lives here)
    island_skeletons = build_skeleton_dicts(islands, skeleton_results)
    save_initial_map_graph(island_skeletons, map_ctx.map_name, map_folder)

    # Run pathfinding analysis (reads skeleton from map_graph.json, POIs from map_context.json)
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

        # Reload map_graph.json (now has pathfinding + skeleton)
        with open(str(map_folder / 'map_graph.json'), 'r') as f:
            graph_data = json.load(f)
        islands_by_id = {ie['island_id']: ie for ie in graph_data.get('islands', [])}

        for island_result in pathfinding_results['island_results']:
            iid = island_result['island_id']
            island_entry = islands_by_id.get(iid)
            if island_entry:
                edge_px = load_edge_pixels(island_entry.get('skeleton'))
                if edge_px:
                    plot_path_grid(
                        island_result, edge_px,
                        str(pathfinding_dir / f'island_{iid}_paths.png')
                    )

    # Build inter-island connectivity graph
    print(f"  Building map connectivity graph...")
    graph_path = map_folder / 'map_graph.json'
    if graph_path.exists():
        with open(str(graph_path), 'r') as f:
            graph_data = json.load(f)
        map_graph_result = build_map_graph(graph_data)
        save_map_graph(map_graph_result, map_folder)

        n_nodes = len(map_graph_result['nodes'])
        n_intra = sum(1 for e in map_graph_result['edges'] if e['edge_type'] == 'intra')
        n_void = sum(1 for e in map_graph_result['edges'] if e['edge_type'] == 'void_link')
        print(f"    Map Graph: {n_nodes} nodes, {n_intra} intra-island edges, {n_void} void links")

        # Reload final map_graph.json for visualization
        with open(str(graph_path), 'r') as f:
            final_graph_data = json.load(f)
        with open(str(island_output_dir / 'map_context.json'), 'r') as f:
            ctx_for_viz = json.load(f)

        viz_path = island_output_dir / 'map_connectivity.png'
        plot_map_connectivity(ctx_for_viz, final_graph_data, viz_path)

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
