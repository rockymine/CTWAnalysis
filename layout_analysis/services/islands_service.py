"""Island detection and skeleton analysis orchestration."""

import json
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd


# ---------------------------------------------------------------------------
# Layout type → filename mapping
# ---------------------------------------------------------------------------

LAYOUT_FILES = {
    'bedrock': 'layout_bedrock.parquet',
    'y0': 'layout_y0.parquet',
    'top': 'layout_top_surface.parquet',
    'density': 'layout_vertical_density.parquet',
}


# ---------------------------------------------------------------------------
# Stage 1: Island detection
# ---------------------------------------------------------------------------

def _detect_and_label(
    layout_file: Path,
    df: pd.DataFrame,
    connectivity: int = 8,
    min_island_size: int = 10,
) -> Tuple[pd.DataFrame, list]:
    """Detect islands and write island_id back into the layout parquet.

    Returns the updated DataFrame and the list of Island objects.
    """
    from island_analysis import detect_islands

    print(f"  Detecting islands ({connectivity}-connectivity, min_size={min_island_size})...")
    islands = detect_islands(
        df,
        x_col='world_x',
        z_col='world_z',
        connectivity=connectivity,
        min_island_size=min_island_size,
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

    return df, islands


# ---------------------------------------------------------------------------
# Stage 2: Triangulation
# ---------------------------------------------------------------------------

def _triangulate(
    islands: list,
    canonical: bool = False,
    buffer_distance: float = 0.0,
    simplify_tolerance: float = 1.0,
    detect_holes: bool = True,
) -> int:
    """Triangulate all islands.  Returns total triangle count."""
    from island_analysis import (
        triangulate_island_union,
        triangulate_islands_canonical,
    )

    if canonical:
        print(f"  Triangulating islands (canonical mode, simplify={simplify_tolerance})...")
        total_triangles = triangulate_islands_canonical(
            islands,
            buffer_distance=buffer_distance,
            simplify_tolerance=simplify_tolerance,
            detect_holes=detect_holes,
        )
    else:
        print(f"  Triangulating islands (union mode, simplify={simplify_tolerance})...")
        total_triangles = 0
        for island in islands:
            triangles = triangulate_island_union(
                island,
                buffer_distance=buffer_distance,
                simplify_tolerance=simplify_tolerance,
                detect_holes=detect_holes,
            )
            total_triangles += len(triangles)

    print(f"    Total triangles: {total_triangles}")
    return total_triangles


# ---------------------------------------------------------------------------
# Stage 3: Skeleton computation
# ---------------------------------------------------------------------------

def _compute_skeletons(
    islands: list,
    enable_canonicalization: bool = True,
    skeleton_connectivity: int = 8,
) -> Tuple[list, dict]:
    """Compute skeleton graphs for all islands.

    Returns (skeleton_results, canonical_groups).
    """
    from skeleton_analysis import process_all_islands
    from island_analysis import compute_island_statistics, classify_islands

    stats = compute_island_statistics(islands)

    classifications = classify_islands(islands)
    print(f"  Island classifications:")
    for cls_name, cls_islands in classifications.items():
        if cls_islands:
            ids = [i.id for i in cls_islands]
            print(f"    {cls_name}: {ids}")

    print(f"  Computing skeleton graphs...")
    skeleton_results, canonical_groups = process_all_islands(
        islands,
        enable_canonicalization=enable_canonicalization,
        skeleton_connectivity=skeleton_connectivity,
    )
    total_nodes = sum(len(r.graph.nodes) for r in skeleton_results)
    total_edges = sum(len(r.graph.edges) for r in skeleton_results)
    total_ep = sum(
        sum(1 for n in r.graph.nodes if n.node_type == 'endpoint')
        for r in skeleton_results
    )
    total_jn = sum(
        sum(1 for n in r.graph.nodes if n.node_type == 'junction')
        for r in skeleton_results
    )
    print(f"    Nodes: {total_nodes} ({total_ep} endpoints, {total_jn} junctions)")
    print(f"    Edges: {total_edges}")
    print(f"    Unique canonical shapes: {len(canonical_groups)}")

    return skeleton_results, canonical_groups, stats


# ---------------------------------------------------------------------------
# Stage 4: Skeleton & island visualizations
# ---------------------------------------------------------------------------

def _generate_skeleton_visuals(
    islands: list,
    stats: dict,
    skeleton_results: list,
    canonical_groups: dict,
    island_output_dir: Path,
    map_name: str,
    plots: bool = True,
):
    """Write island reports, skeleton debug images, and overview plots.

    Essential outputs (always generated):
        - island_triangulation_detail.png
        - unique_islands.png
        - world_overview.png

    Debug outputs (only when plots=True):
        - island_comparison.png, island_statistics.png, island_report.txt
        - island_{id}_debug.png (per canonical shape)
        - skeleton_report.txt
    """
    from island_analysis.visualization import plot_triangulation_detail
    from skeleton_analysis.visualize import (
        plot_island_debug,
        plot_unique_islands,
        plot_world_overview,
        generate_skeleton_report,
    )

    print(f"  Generating visualizations...")

    # Essential: triangulation detail
    plot_triangulation_detail(
        islands,
        output_path=str(island_output_dir / 'island_triangulation_detail.png'),
    )

    if plots:
        # Debug: full island report (comparison, statistics, text report)
        from island_analysis import create_island_report
        create_island_report(islands, stats, str(island_output_dir), map_name)

    skeleton_output_dir = island_output_dir / 'skeleton'
    skeleton_output_dir.mkdir(exist_ok=True)

    if plots:
        # Debug: per-island skeleton debug images (one per unique canonical shape)
        result_by_id = {r.island_id: r for r in skeleton_results}
        for key, ids in canonical_groups.items():
            rep_id = min(ids)
            if rep_id in result_by_id:
                plot_island_debug(
                    result_by_id[rep_id],
                    str(skeleton_output_dir / f'island_{rep_id}_debug.png'),
                )

    # Essential: unique islands overview and world overview
    plot_unique_islands(
        skeleton_results, canonical_groups,
        str(skeleton_output_dir / 'unique_islands.png'),
    )

    plot_world_overview(
        skeleton_results,
        str(skeleton_output_dir / 'world_overview.png'),
    )

    if plots:
        # Debug: skeleton text report
        generate_skeleton_report(
            skeleton_results, canonical_groups,
            str(skeleton_output_dir / 'skeleton_report.txt'),
            map_name=map_name,
        )


# ---------------------------------------------------------------------------
# Stage 5: POI annotation (requires XML)
# ---------------------------------------------------------------------------

def _annotate_pois(
    map_folder: Path,
    islands: list,
    df: pd.DataFrame,
    skeleton_results: list,
    skeleton_output_dir: Path,
    plots: bool = True,
):
    """Parse XML and annotate skeleton POIs.

    Returns (map_data_obj, poi_assignments, map_center_pt).
    map_data_obj and poi_assignments are None when XML is absent.
    """
    from skeleton_analysis.poi_annotation import (
        annotate_skeleton_pois,
        compute_map_center,
        classify_island_center,
    )
    from skeleton_analysis.visualize import plot_island_poi_debug

    map_center_pt = compute_map_center(df)
    classify_island_center(islands, map_center_pt)

    xml_file = map_folder / 'map.xml'
    map_data_obj = None
    poi_assignments = None

    if xml_file.exists():
        try:
            from xml_analysis import MapXMLParser
            parser = MapXMLParser(str(xml_file))
            map_data_obj = parser.parse()

            print(f"  Annotating POIs from XML...")
            poi_assignments = annotate_skeleton_pois(
                islands, skeleton_results, map_data_obj,
            )
            n_spawn = sum(
                1 for s in poi_assignments.get('spawns', [])
                if s.get('node_id') is not None
            )
            n_wool = sum(
                1 for w in poi_assignments.get('wools', [])
                if w.get('node_id') is not None
            )
            print(f"    Spawns assigned: {n_spawn}, Wools assigned: {n_wool}")

            for w in poi_assignments.get('wools', []):
                fb = w.get('fallback')
                if fb:
                    color = w.get('wool_color', '?')
                    orig = f"({fb['original_x']:.1f}, {fb['original_z']:.1f})"
                    room = fb['room_region']
                    if w.get('island_id') is not None:
                        print(f"    [!] Wool '{color}' location {orig} outside map, "
                              f"used room '{room}' centroid -> island {w['island_id']}")
                    else:
                        print(f"    [!] Wool '{color}' location {orig} outside map, "
                              f"tried room '{room}' but still unmatched")
                elif w.get('island_id') is None:
                    color = w.get('wool_color', '?')
                    loc = f"({w['x']:.1f}, {w['z']:.1f})"
                    print(f"    [!] Wool '{color}' location {loc} outside map, "
                          f"no matching wool-room region found")

            if plots:
                for result in skeleton_results:
                    has_poi = any(n.poi_type is not None for n in result.graph.nodes)
                    if has_poi:
                        plot_island_poi_debug(
                            result,
                            str(skeleton_output_dir / f'island_{result.island_id}_poi.png'),
                        )
        except Exception as e:
            print(f"    [!] POI annotation failed: {e}")
    else:
        print(f"  No map.xml found, skipping POI annotation")

    return map_data_obj, poi_assignments, map_center_pt


# ---------------------------------------------------------------------------
# Stage 6: Build MapContext + initial map_graph.json
# ---------------------------------------------------------------------------

def _build_context(
    map_folder: Path,
    islands: list,
    df: pd.DataFrame,
    skeleton_results: list,
    canonical_groups: dict,
    map_data_obj,
    map_center_pt,
    poi_assignments,
    island_output_dir: Path,
    map_output_dir: Path,
):
    """Build and save MapContext (with build-region) and initial map_graph.json.

    Returns the MapContext instance.
    """
    from layout_analysis.map_context import build_map_context, build_skeleton_dicts

    map_ctx = build_map_context(
        islands, skeleton_results, canonical_groups, df,
        map_data=map_data_obj,
        map_center=map_center_pt,
        poi_assignments=poi_assignments,
    )

    # Y0 layer diagnostics
    y0_path = map_output_dir / 'layout_y0.parquet'
    if y0_path.exists():
        y0_df = pd.read_parquet(y0_path)
        if len(y0_df) == 0 or 'block_id' not in y0_df.columns:
            print(f"    Y0 layer: empty (0 blocks)")
        else:
            block_counts = y0_df['block_id'].value_counts()
            n_block36 = int(block_counts.get(36, 0))
            total = len(y0_df)
            if n_block36 > 0:
                other = total - n_block36
                if other == 0:
                    print(f"    Y0 layer: {total} blocks, ALL block36 (piston extension)")
                else:
                    other_ids = sorted(block_counts.drop(36, errors='ignore').index.tolist())
                    print(f"    Y0 layer: {total} blocks, {n_block36} block36 + "
                          f"{other} other (ids: {other_ids})")
            else:
                ids = sorted(block_counts.index.tolist())
                print(f"    Y0 layer: {total} blocks, no block36 (ids: {ids})")
    else:
        print(f"    Y0 layer: not found (skipped or not yet extracted)")

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
            build_result = extract_build_region(
                map_data=map_data_obj,
                map_bounds=map_ctx.bounding_box,
                y0_parquet_path=str(y0_path),
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

    island_skeletons = build_skeleton_dicts(islands, skeleton_results)
    _save_map_graph(island_skeletons, map_ctx.map_name, map_output_dir)

    return map_ctx


# ---------------------------------------------------------------------------
# map_graph.json writer (skeleton data only)
# ---------------------------------------------------------------------------

def _save_map_graph(
    island_skeletons: list,
    map_name: str,
    output_dir: Path,
) -> None:
    """Save map_graph.json containing island skeleton data.

    Downstream consumers (match analysis / PositionClassifier) read
    islands[].skeleton.edge_pixels from this file for spatial queries.
    """
    import numpy as np

    def _json_default(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    data = {
        'map_name': map_name,
        'islands': island_skeletons,
        'map_graph': {'nodes': [], 'edges': []},
    }

    output_path = output_dir / 'map_graph.json'
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, default=_json_default)
    print(f"  Map graph saved to: {output_path}")


# ---------------------------------------------------------------------------
# Legacy cleanup
# ---------------------------------------------------------------------------

def _cleanup_legacy(island_output_dir: Path):
    """Remove legacy per-island CSV/JSON exports."""
    legacy_exports = island_output_dir / 'skeleton' / 'exports'
    if legacy_exports.exists():
        shutil.rmtree(legacy_exports)
        print(f"    Removed legacy exports directory")
    legacy_paths = island_output_dir / 'pathfinding' / 'paths_analysis.json'
    if legacy_paths.exists():
        legacy_paths.unlink()
        print(f"    Removed legacy paths_analysis.json")


# ---------------------------------------------------------------------------
# Public orchestrator
# ---------------------------------------------------------------------------

def analyze_islands_step(
    map_folder: Path,
    force_rerun: bool = False,
    simplify_tolerance: float = 1.0,
    buffer_distance: float = 0.0,
    layout_type: str = 'bedrock',
    canonical_triangulation: bool = False,
    connectivity: int = 8,
    min_size: int = 10,
    detect_holes: bool = True,
    map_output_dir: Optional[Path] = None,
    output_dir: Optional[str] = None,
    plots: bool = False,
):
    """
    Step 2: Detect and triangulate islands from layout data.

    Args:
        map_folder: Path to map folder (read-only input).
        force_rerun: If True, regenerate even if output exists.
        simplify_tolerance: Simplification tolerance for union triangulation.
        buffer_distance: Buffer distance for smoothing.
        layout_type: Which layout file to use ('bedrock', 'y0', 'top', 'density').
        canonical_triangulation: If True, use canonical-consistent triangulation
            so that symmetrically identical islands share the same mesh.
        connectivity: Island detection connectivity (4 or 8).
        min_size: Minimum island block count.
        detect_holes: If True, detect holes in islands during triangulation.
        map_output_dir: Per-map output root (where layout parquets and
            map_graph.json live). Defaults to map_folder for backward compat.
        output_dir: Override island_analysis subdir specifically.
        plots: If True, generate debug plots (per-island debug, POI).

    Returns:
        Path: Path to island analysis output directory
    """
    print(f"\n[2/5] Island Analysis: {map_folder.name}")
    print("=" * 70)

    # Resolve directories
    _map_output_dir = Path(map_output_dir) if map_output_dir else map_folder
    layout_dir = _map_output_dir
    island_output_dir = Path(output_dir) if output_dir else _map_output_dir / 'island_analysis'

    # Resolve layout file
    layout_filename = LAYOUT_FILES.get(layout_type, 'layout_bedrock.parquet')
    layout_file = layout_dir / layout_filename
    if not layout_file.exists():
        print(f"  [X] Layout file not found: {layout_filename}. Run layout analysis first.")
        return None

    # Check for cached results
    report_file = island_output_dir / 'island_report.txt'
    if report_file.exists() and not force_rerun:
        print(f"  Island analysis already exists. Skipping.")
        print(f"    [OK] {island_output_dir.name}/")
        return island_output_dir

    island_output_dir.mkdir(parents=True, exist_ok=True)

    # Stage 1: Load and detect
    print(f"  Loading layout data: {layout_file.name}")
    df = pd.read_parquet(layout_file)
    print(f"    Loaded {len(df)} blocks")

    df, islands = _detect_and_label(
        layout_file, df, connectivity=connectivity, min_island_size=min_size,
    )

    if not islands:
        print("  [X] No islands detected!")
        return island_output_dir

    # Stage 2: Triangulate
    _triangulate(
        islands,
        canonical=canonical_triangulation,
        buffer_distance=buffer_distance,
        simplify_tolerance=simplify_tolerance,
        detect_holes=detect_holes,
    )

    # Stage 3: Skeleton computation
    skeleton_results, canonical_groups, stats = _compute_skeletons(islands)

    # Stage 4: Skeleton & island visualizations
    _generate_skeleton_visuals(
        islands, stats, skeleton_results, canonical_groups,
        island_output_dir, map_folder.name, plots=plots,
    )

    # Stage 5: POI annotation (reads map.xml from map_folder)
    skeleton_output_dir = island_output_dir / 'skeleton'
    map_data_obj, poi_assignments, map_center_pt = _annotate_pois(
        map_folder, islands, df, skeleton_results, skeleton_output_dir,
        plots=plots,
    )

    # Stage 6: Build MapContext + initial map_graph.json
    _build_context(
        map_folder, islands, df, skeleton_results, canonical_groups,
        map_data_obj, map_center_pt, poi_assignments, island_output_dir,
        map_output_dir=_map_output_dir,
    )

    # Cleanup
    _cleanup_legacy(island_output_dir)

    print(f"    [OK] Saved to: {island_output_dir.name}/")
    return island_output_dir
