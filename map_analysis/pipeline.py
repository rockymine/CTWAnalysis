"""Assembly pipeline for map analysis.

Layer responsibilities
----------------------
run_island_geometry()  — Layer 2+3: pure geometry.
    Detect islands, build polygons, compute skeleton graphs, generate
    visualizations, classify island centers relative to the map center.
    Does NOT read map.xml.  Writes island_analysis/islands.json.

assemble_map()         — Layer 4: semantic enrichment + final assembly.
    Combines island geometry (islands.json), symmetry results
    (symmetry.json), and XML data (map.xml) into the complete map model.
    Writes map_context.json and map_graph.json.

Public API:
    run_island_geometry(map_folder, ...)  — geometry pipeline
    assemble_map(map_folder, islands, ...) — assembly pipeline
"""

import json
import shutil
from pathlib import Path
from typing import Optional, Tuple

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
    """
    from island_analysis.visualization import plot_island_detail
    from skeleton_analysis.visualization import (
        plot_island_debug,
        plot_unique_islands,
        generate_skeleton_report,
    )

    print(f"  Generating visualizations...")

    if plots:
        from island_analysis import create_island_report
        create_island_report(islands, stats, str(island_output_dir), map_name)
    else:
        plot_island_detail(
            islands,
            output_path=str(island_output_dir / 'island_detail.png'),
        )

    skeleton_output_dir = island_output_dir / 'skeleton'
    skeleton_output_dir.mkdir(exist_ok=True)

    if plots:
        result_by_id = {r.island_id: r for r in skeleton_results}
        for key, ids in canonical_groups.items():
            rep_id = min(ids)
            if rep_id in result_by_id:
                plot_island_debug(
                    result_by_id[rep_id],
                    str(skeleton_output_dir / f'island_{rep_id}_debug.png'),
                )

    plot_unique_islands(
        skeleton_results, canonical_groups,
        str(skeleton_output_dir / 'unique_islands.png'),
    )

    if plots:
        generate_skeleton_report(
            skeleton_results, canonical_groups,
            str(skeleton_output_dir / 'skeleton_report.txt'),
            map_name=map_name,
        )


# ---------------------------------------------------------------------------
# Stage 4b: Write islands.json (bridge to symmetry + assembly steps)
# ---------------------------------------------------------------------------

def _save_islands_json(
    islands: list,
    df: pd.DataFrame,
    map_name: str,
    island_output_dir: Path,
) -> None:
    """Write island_analysis/islands.json with geometry data.

    This file is the input for the symmetry step (detect_symmetry) and
    provides the island list for the assembly step (assemble_map).

    Contains: map_name, bounding_box, map_center, and per-island geometry
    (id, area, center, bounding_box, simplified_polygon, has_center,
    distance_to_center). XML-dependent fields (team, has_spawn, has_wool)
    are not included — they are added by assemble_map().
    """
    from common.geometry import get_grid_extent
    from map_analysis.poi_annotation import compute_map_center

    x_col = 'world_x' if 'world_x' in df.columns else 'x'
    z_col = 'world_z' if 'world_z' in df.columns else 'z'
    bbox = list(get_grid_extent(df[x_col], df[z_col]))
    map_center = list(compute_map_center(df))

    island_dicts = []
    for island in islands:
        island_dicts.append({
            'id': island.id,
            'area': island.area,
            'center': list(island.center),
            'bounding_box': list(island.bounding_box),
            'has_center': island.has_center,
            'distance_to_center': round(island.distance_to_center, 2),
            'hole_count': len(island.holes),
            'simplified_polygon': island.simplified_polygon,
        })

    data = {
        'map_name': map_name,
        'bounding_box': bbox,
        'map_center': map_center,
        'islands': island_dicts,
    }

    out_path = island_output_dir / 'islands.json'
    with open(out_path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"  Saved islands.json ({len(island_dicts)} islands)")


# ---------------------------------------------------------------------------
# Stage 5: POI annotation (requires XML)
# ---------------------------------------------------------------------------

def _annotate_pois(
    map_folder: Path,
    islands: list,
    skeleton_results: list,
    skeleton_output_dir: Path,
    plots: bool = True,
    xml_context=None,
):
    """Annotate skeleton POIs from XML data.

    Uses xml_context.map_data when provided by the pipeline (avoids a
    second parse of map.xml).  Falls back to parsing map.xml from disk
    when called standalone (e.g. ctw islands without a prior xml step).

    Returns (map_data_obj, poi_assignments).
    map_data_obj and poi_assignments are None when XML is absent.
    """
    from map_analysis.poi_annotation import annotate_skeleton_pois
    from skeleton_analysis.visualization import plot_island_poi_debug

    xml_file = map_folder / 'map.xml'
    map_data_obj = None
    poi_assignments = None

    if xml_context is not None:
        map_data_obj = xml_context.map_data
    elif xml_file.exists():
        try:
            from xml_analysis import MapXMLParser
            parser = MapXMLParser(str(xml_file))
            map_data_obj = parser.parse()
        except Exception as e:
            print(f"    [!] XML parse failed: {e}")

    if map_data_obj is not None:
        try:
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
        print(f"  No XML data available, skipping POI annotation")

    return map_data_obj, poi_assignments


# ---------------------------------------------------------------------------
# Stage 6: Team assignment (requires symmetry.json + XML teams)
# ---------------------------------------------------------------------------

def _assign_teams(
    islands: list,
    island_dicts: list,
    map_data_obj,
    map_output_dir: Path,
) -> Tuple[list, list]:
    """Assign islands to teams using symmetry + XML data.

    Reads symmetry.json for the primary global symmetry type, then uses
    the team assignment heuristics from map_analysis.team_assignment.

    Also calls detect_intra_team_symmetry and appends the result to
    symmetry.json.

    Returns (teams, intra_team_symmetry).
    """
    from map_analysis.team_assignment import assign_islands_to_teams, detect_intra_team_symmetry

    if map_data_obj is None:
        return [], []

    teams = [
        {'id': t.id, 'color': t.color, 'name': t.name, 'max_players': t.max_players}
        for t in map_data_obj.teams
    ]
    if not teams:
        return teams, []

    # Load symmetry results for team assignment
    sym_path = map_output_dir / 'symmetry.json'
    if not sym_path.exists():
        print(f"  No symmetry.json found, skipping team assignment")
        return teams, []

    with open(sym_path) as f:
        sym_data = json.load(f)

    global_symmetries = sym_data.get('global_symmetry', [])
    center_info = sym_data.get('center', {})
    center_x = center_info.get('center_x', 0.0)
    center_z = center_info.get('center_z', 0.0)

    detected = [s for s in global_symmetries if s.get('detected')]
    if not detected:
        print(f"  No global symmetry detected, skipping geometric team assignment")
        return teams, []

    primary_global = max(detected, key=lambda s: s['confidence'])

    # Assign unassigned islands geometrically
    team_islands = assign_islands_to_teams(
        island_dicts, teams, center_x, center_z, primary_global,
    )

    # Propagate geometric assignments back to Island objects
    assigned_map = {}
    for tid, t_isls in team_islands.items():
        for isl_dict in t_isls:
            assigned_map[isl_dict['id']] = tid

    for island in islands:
        if island.team is None and island.id in assigned_map:
            island.team = assigned_map[island.id]
            # Also update the dict used for intra-team check
            for isl_dict in island_dicts:
                if isl_dict['id'] == island.id:
                    isl_dict['team'] = island.team

    # Rebuild team_islands with updated assignments
    team_islands = assign_islands_to_teams(
        island_dicts, teams, center_x, center_z, primary_global,
    )

    # Detect intra-team symmetry
    intra_team = detect_intra_team_symmetry(
        island_dicts, center_x, center_z, center_info, global_symmetries, teams,
    )

    if intra_team:
        sym_data['intra_team_symmetry'] = intra_team
        with open(sym_path, 'w') as f:
            json.dump(sym_data, f, indent=2)
        sym_teams = [t['team'] for t in intra_team if t.get('symmetry_detected')]
        if sym_teams:
            print(f"  Intra-team symmetry detected for: {', '.join(sym_teams)}")

    return teams, intra_team


# ---------------------------------------------------------------------------
# Stage 7: Build MapContext + map_graph.json
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
    """Build and save MapContext (with build-region) and map_graph.json.

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
# Public API: geometry pipeline
# ---------------------------------------------------------------------------

def run_island_geometry(
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
    """Island geometry pipeline (Stages 1–4).

    Detects islands, builds polygons, computes skeleton graphs, generates
    visualizations, and classifies island centers relative to the map center.

    Does NOT read map.xml and does NOT produce map_context.json.
    Writes island_analysis/islands.json for downstream steps.

    Args:
        map_folder: Path to map folder (read-only input).
        force_rerun: If True, regenerate even if output exists.
        simplify_tolerance: Simplification tolerance for polygon construction.
        buffer_distance: Buffer distance for smoothing.
        layout_type: Which layout file to use ('bedrock', 'y0', 'top', 'density').
        canonical_polygons: If True, use canonical-consistent polygon construction.
        connectivity: Island detection connectivity (4 or 8).
        min_size: Minimum island block count.
        detect_holes: If True, detect holes in islands during polygon construction.
        map_output_dir: Per-map output root. Defaults to map_folder.
        output_dir: Override island_analysis subdir specifically.
        plots: If True, generate debug plots.

    Returns:
        tuple: (islands, skeleton_results, canonical_groups, df,
                island_output_dir, map_center_pt)
        or (None, None, None, None, None, None) on failure.
    """
    print(f"\n[2/6] Island Analysis: {map_folder.name}")
    print("=" * 70)

    _map_output_dir = Path(map_output_dir) if map_output_dir else map_folder
    layout_dir = _map_output_dir
    island_output_dir = Path(output_dir) if output_dir else _map_output_dir / 'island_analysis'

    layout_filename = LAYOUT_FILES.get(layout_type, 'layout_bedrock.parquet')
    layout_file = layout_dir / layout_filename
    if not layout_file.exists():
        print(f"  [X] Layout file not found: {layout_filename}. Run layout analysis first.")
        return None, None, None, None, None, None

    # Check for cached results
    islands_json = island_output_dir / 'islands.json'
    if islands_json.exists() and not force_rerun:
        print(f"  Island analysis already exists. Skipping.")
        print(f"    [OK] {island_output_dir.name}/")
        return None, None, None, None, island_output_dir, None

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
        return None, None, None, None, island_output_dir, None

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

    # Classify island centers (geometry-only, no XML)
    from map_analysis.poi_annotation import compute_map_center, classify_island_center
    map_center_pt = compute_map_center(df)
    classify_island_center(islands, map_center_pt)

    # Write islands.json for symmetry + assembly steps
    _save_islands_json(islands, df, map_folder.name, island_output_dir)

    print(f"    [OK] Saved to: {island_output_dir.name}/")
    return islands, skeleton_results, canonical_groups, df, island_output_dir, map_center_pt


# ---------------------------------------------------------------------------
# Public API: assembly pipeline
# ---------------------------------------------------------------------------

def assemble_map(
    map_folder: Path,
    islands: list,
    skeleton_results: list,
    canonical_groups: dict,
    df: pd.DataFrame,
    island_output_dir: Path,
    map_output_dir: Path,
    map_center_pt=None,
    xml_context=None,
    plots: bool = False,
):
    """Map assembly pipeline (Stages 5–7).

    Combines island geometry, symmetry results, and XML data into the
    complete map model. Requires run_island_geometry() to have been called
    first (either in this session or a previous one, with results on disk).

    Reads:
        - symmetry.json (from map_output_dir, for team assignment)

    Reads from xml_context when provided (preferred), otherwise falls back
    to parsing map.xml from map_folder directly.

    Writes:
        - map_context.json
        - map_graph.json
        - Updates symmetry.json with intra_team_symmetry (if applicable)

    Args:
        map_folder: Path to map folder (for map.xml fallback).
        islands: In-memory list of Island objects from run_island_geometry().
        skeleton_results: In-memory skeleton results from run_island_geometry().
        canonical_groups: Canonical group mapping from run_island_geometry().
        df: Layout DataFrame from run_island_geometry().
        island_output_dir: Path to island_analysis/ output directory.
        map_output_dir: Per-map output root (where map_context.json is written).
        map_center_pt: Pre-computed map center from run_island_geometry().
        xml_context: MapXmlContext from the XML analysis step. When supplied
            the assembly step uses map_data directly without re-parsing map.xml.
        plots: If True, generate POI debug plots.
    """
    print(f"\n[5/6] Map Assembly: {map_folder.name}")
    print("=" * 70)

    skeleton_output_dir = island_output_dir / 'skeleton'

    # Recompute map center if not provided
    if map_center_pt is None:
        from map_analysis.poi_annotation import compute_map_center
        map_center_pt = compute_map_center(df)

    # Stage 5: POI annotation
    map_data_obj, poi_assignments = _annotate_pois(
        map_folder, islands, skeleton_results, skeleton_output_dir,
        plots=plots,
        xml_context=xml_context,
    )

    # Build island dicts for team assignment (includes XML-set island.team)
    island_dicts = [
        {
            'id': island.id,
            'area': island.area,
            'center': list(island.center),
            'has_spawn': island.has_spawn,
            'has_wool': island.has_wool,
            'has_center': island.has_center,
            'team': island.team,
            'simplified_polygon': island.simplified_polygon,
        }
        for island in islands
    ]

    # Stage 6: Team assignment (reads symmetry.json, updates island objects)
    _assign_teams(islands, island_dicts, map_data_obj, map_output_dir)

    # Stage 7: Build MapContext + map_graph.json
    print(f"  Building map context...")
    map_ctx = _build_context(
        map_folder, islands, df, skeleton_results, canonical_groups,
        map_data_obj, map_center_pt, poi_assignments, island_output_dir,
        map_output_dir=map_output_dir,
    )

    # Map overview plot (needs map_context for polygons + build regions)
    from skeleton_analysis.visualization import plot_map_overview
    from map_analysis import exporter as map_context_exporter
    plot_map_overview(
        skeleton_results,
        str(skeleton_output_dir / 'map_overview.png'),
        map_context=map_context_exporter.to_dict(map_ctx),
    )

    # Cleanup legacy files
    _cleanup_legacy(island_output_dir)

    print(f"    [OK] map_context.json written")
