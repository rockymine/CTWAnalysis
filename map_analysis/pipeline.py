"""Assembly pipeline for map analysis (Stages 3–7).

This module is the rightful home for everything that requires importing from
more than one analysis package.  It calls into island_analysis (Stages 1–2),
skeleton_analysis (Stage 3), visualization helpers (Stage 4), POI annotation
(Stage 5), MapContext + map_graph construction (Stage 6), and cleanup (Stage 7).

Public API:
    analyze_islands_step(map_folder, ...)  — drop-in replacement for the
        function that used to live in island_analysis/services/islands_service.py
"""

import shutil
from pathlib import Path
from typing import Optional

import pandas as pd

from island_analysis.pipeline import LAYOUT_FILES, detect_and_label, build_polygons


# ---------------------------------------------------------------------------
# Stage 3: Skeleton computation
# ---------------------------------------------------------------------------

def _compute_skeletons(
    islands: list,
    enable_canonicalization: bool = True,
    skeleton_connectivity: int = 8,
):
    """Compute skeleton graphs for all islands.

    Returns (skeleton_results, canonical_groups, stats).
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

    Always generated:
        - island_detail.png
        - unique_islands.png

    Only when plots=True (via create_island_report):
        - island_comparison.png, island_statistics.png, island_report.txt
        - island_{id}_debug.png (per canonical shape)
        - skeleton_report.txt

    Note: create_island_report already calls plot_island_detail, so the
    unconditional call is skipped in the plots=True path to avoid duplicates.
    """
    from island_analysis.visualization import plot_island_detail
    from skeleton_analysis.visualization import (
        plot_island_debug,
        plot_unique_islands,
        generate_skeleton_report,
    )

    print(f"  Generating visualizations...")

    if plots:
        # Debug: full island report (comparison, statistics, text report, island_detail)
        from island_analysis import create_island_report
        create_island_report(islands, stats, str(island_output_dir), map_name)
    else:
        # Essential: island polygon detail (create_island_report covers this when plots=True)
        plot_island_detail(
            islands,
            output_path=str(island_output_dir / 'island_detail.png'),
        )

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

    # Essential: unique islands overview
    plot_unique_islands(
        skeleton_results, canonical_groups,
        str(skeleton_output_dir / 'unique_islands.png'),
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
    from map_analysis.poi_annotation import (
        annotate_skeleton_pois,
        compute_map_center,
        classify_island_center,
    )
    from skeleton_analysis.visualization import plot_island_poi_debug

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
    from map_analysis.builder import build_map_context
    from map_analysis import exporter as map_context_exporter
    from skeleton_analysis.builder import build_skeleton_dicts
    from skeleton_analysis import exporter as map_graph_exporter

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

    map_context_exporter.save(map_ctx, str(map_output_dir / 'map_context.json'))

    island_skeletons = build_skeleton_dicts(islands, skeleton_results)
    map_graph_exporter.save(island_skeletons, map_ctx.map_name, map_output_dir)

    return map_ctx


# ---------------------------------------------------------------------------
# Stage 7: Legacy cleanup
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
    canonical_polygons: bool = False,
    connectivity: int = 8,
    min_size: int = 10,
    detect_holes: bool = True,
    map_output_dir: Optional[Path] = None,
    output_dir: Optional[str] = None,
    plots: bool = False,
):
    """
    Full island + map assembly pipeline (Stages 1–7).

    Args:
        map_folder: Path to map folder (read-only input).
        force_rerun: If True, regenerate even if output exists.
        simplify_tolerance: Simplification tolerance for polygon construction.
        buffer_distance: Buffer distance for smoothing.
        layout_type: Which layout file to use ('bedrock', 'y0', 'top', 'density').
        canonical_polygons: If True, use canonical-consistent polygon construction
            so that symmetrically identical islands are grouped.
        connectivity: Island detection connectivity (4 or 8).
        min_size: Minimum island block count.
        detect_holes: If True, detect holes in islands during polygon construction.
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

    df, islands = detect_and_label(
        layout_file, df, connectivity=connectivity, min_island_size=min_size,
    )

    if not islands:
        print("  [X] No islands detected!")
        return island_output_dir

    # Stage 2: Build polygons
    build_polygons(
        islands,
        canonical=canonical_polygons,
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
    map_ctx = _build_context(
        map_folder, islands, df, skeleton_results, canonical_groups,
        map_data_obj, map_center_pt, poi_assignments, island_output_dir,
        map_output_dir=_map_output_dir,
    )

    # Stage 7: Map overview (needs map_context for polygons + build regions)
    from skeleton_analysis.visualization import plot_map_overview
    from map_analysis import exporter as map_context_exporter
    plot_map_overview(
        skeleton_results,
        str(skeleton_output_dir / 'map_overview.png'),
        map_context=map_context_exporter.to_dict(map_ctx),
    )

    # Cleanup
    _cleanup_legacy(island_output_dir)

    print(f"    [OK] Saved to: {island_output_dir.name}/")
    return island_output_dir
