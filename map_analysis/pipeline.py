"""Assembly pipeline for map analysis.

Layer responsibilities
----------------------
run_island_geometry()  — Layer 2+3: pure geometry.
    Detect islands, build polygons, compute skeleton graphs, generate
    visualizations, classify island centers relative to the map center.
    Does NOT read map.xml.  Writes islands.json.
    Returns IslandAnalysis with islands: list[IslandPolygon] (no XML fields).

assemble_map()         — Layer 4: semantic enrichment + final assembly.
    Combines island geometry (IslandAnalysis), symmetry results
    (symmetry.json), and XML data (map.xml) into the complete map model.
    Constructs fully contextualized Island objects from IslandPolygon + XML.
    Writes map_context.json and map_graph.json.

Public API:
    run_island_geometry(map_folder, ...)  — geometry pipeline
    assemble_map(map_folder, analysis, ...) — assembly pipeline
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from island_analysis.datatypes import Island, IslandPolygon
from island_analysis.pipeline import LAYOUT_FILES, detect_and_enrich, build_polygons
from map_analysis.datatypes import IslandAnalysis, IslandGeometryResult, MapContext
from skeleton_analysis.datatypes import IslandSkeleton
from symmetry_analysis.datatypes import SymmetryResult
from xml_analysis.datatypes import MapData, MapXmlContext

logger = logging.getLogger('ctw')


# ---------------------------------------------------------------------------
# Skeleton computation
# ---------------------------------------------------------------------------

def _log_skeleton_stats(skeleton_results: list[IslandSkeleton], canonical_groups: dict[str, list[int]]) -> None:
    """Log a summary of skeleton graph metrics across all islands."""
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
    logger.debug(f"    Nodes: {total_nodes} ({total_ep} endpoints, {total_jn} junctions)")
    logger.debug(f"    Edges: {total_edges}")
    logger.debug(f"    Unique canonical shapes: {len(canonical_groups)}")


def _compute_skeletons(
    islands: list[IslandPolygon],
    enable_canonicalization: bool = True,
    skeleton_connectivity: int = 8,
) -> tuple[list[IslandSkeleton], dict[str, list[int]]]:
    """Compute skeleton graphs for all islands.

    Returns (skeletons, canonical_groups).
    """
    from skeleton_analysis import process_all_islands

    logger.debug("  Computing skeleton graphs...")
    skeletons, canonical_groups = process_all_islands(
        islands,
        enable_canonicalization=enable_canonicalization,
        skeleton_connectivity=skeleton_connectivity,
    )
    _log_skeleton_stats(skeletons, canonical_groups)

    return skeletons, canonical_groups


# ---------------------------------------------------------------------------
# Island & skeleton visualizations
# ---------------------------------------------------------------------------

def _generate_skeleton_visuals(
    islands: list[IslandPolygon],
    skeletons: list[IslandSkeleton],
    canonical_groups: dict[str, list[int]],
    island_output_dir: Path,
    map_name: str,
    plots: bool = True,
) -> None:
    """Write island and skeleton debug images.

    Always generated (in images/):
        - island_detail.png
        - unique_islands.png

    Only when plots=True:
        - images/island_{id}_debug.png (per canonical shape)
        - skeleton_report.txt (at output root)
    """
    from island_analysis.visualization import plot_island_detail
    from skeleton_analysis.visualization import (
        plot_island_debug,
        plot_unique_islands,
        generate_skeleton_report,
    )

    logger.debug("  Generating visualizations...")

    images_dir = island_output_dir / 'images'
    images_dir.mkdir(exist_ok=True)

    plot_island_detail(
        islands,
        output_path=str(images_dir / 'island_detail.png'),
    )

    if plots:
        result_by_id = {r.island_id: r for r in skeletons}
        for key, ids in canonical_groups.items():
            rep_id = min(ids)
            if rep_id in result_by_id:
                plot_island_debug(
                    result_by_id[rep_id],
                    str(images_dir / f'island_{rep_id}_debug.png'),
                )

    plot_unique_islands(
        skeletons, canonical_groups,
        str(images_dir / 'unique_islands.png'),
    )

    if plots:
        generate_skeleton_report(
            skeletons, canonical_groups,
            str(island_output_dir / 'skeleton_report.txt'),
            map_name=map_name,
        )


# ---------------------------------------------------------------------------
# islands.json serialization (debug artifact + symmetry step input)
# ---------------------------------------------------------------------------

def _save_islands_json(
    islands: list[IslandPolygon],
    df: pd.DataFrame,
    map_name: str,
    island_output_dir: Path,
) -> None:
    """Write islands.json with geometry data.

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
    logger.debug(f"  Saved islands.json ({len(island_dicts)} islands)")


# ---------------------------------------------------------------------------
# POI annotation
# ---------------------------------------------------------------------------

def _log_poi_annotations(poi_assignments: dict[str, list]) -> None:
    """Log POI assignment summary and any wool fallback warnings."""
    n_spawn = sum(
        1 for s in poi_assignments.get('spawns', [])
        if s.get('node_id') is not None
    )
    n_wool = sum(
        1 for w in poi_assignments.get('wools', [])
        if w.get('node_id') is not None
    )
    logger.debug(f"    Spawns assigned: {n_spawn}, Wools assigned: {n_wool}")

    for w in poi_assignments.get('wools', []):
        fb = w.get('fallback')
        if fb:
            color = w.get('wool_color', '?')
            orig = f"({fb['original_x']:.1f}, {fb['original_z']:.1f})"
            room = fb['room_region']
            if w.get('island_id') is not None:
                logger.warning(f"    [!] Wool '{color}' location {orig} outside map, "
                               f"used room '{room}' centroid -> island {w['island_id']}")
            else:
                logger.warning(f"    [!] Wool '{color}' location {orig} outside map, "
                               f"tried room '{room}' but still unmatched")
        elif w.get('island_id') is None:
            color = w.get('wool_color', '?')
            loc = f"({w['x']:.1f}, {w['z']:.1f})"
            logger.warning(f"    [!] Wool '{color}' location {loc} outside map, "
                           f"no matching wool-room region found")


def _annotate_pois(
    map_folder: Path,
    islands: list[IslandPolygon],
    skeletons: list[IslandSkeleton],
    skeleton_output_dir: Path,
    plots: bool = True,
    xml_context: Optional[MapXmlContext] = None,
) -> tuple[Optional[MapData], dict, dict, Optional[dict]]:
    """Annotate skeleton POIs from XML data.

    Uses xml_context.map_data when provided by the pipeline (avoids a
    second parse of map.xml).  Falls back to parsing map.xml from disk
    when called standalone (e.g. ctw islands without a prior xml step).

    Returns (map_data_obj, island_annotations, node_annotations_by_island, poi_assignments).
    island_annotations: {island_id: {'has_spawn': bool, 'has_wool': bool, 'team': str|None}}
    node_annotations_by_island: {island_id: {node_id: NodeAnnotation}}
    poi_assignments: {'spawns': [...], 'wools': [...]} with x/z/team_color etc. for rendering
    All are empty dicts / None when XML is absent.
    """
    from map_analysis.poi_annotation import annotate_skeleton_pois
    from skeleton_analysis.visualization import plot_island_poi_debug

    xml_file = map_folder / 'map.xml'
    map_data_obj = None
    island_annotations: dict = {}
    node_annotations: dict = {}
    poi_assignments: Optional[dict] = None

    if xml_context is not None:
        map_data_obj = xml_context.map_data
    elif xml_file.exists():
        try:
            from xml_analysis import MapXMLParser
            parser = MapXMLParser(str(xml_file))
            map_data_obj = parser.parse()
        except Exception as e:
            logger.warning(f"    [!] XML parse failed: {e}")

    if map_data_obj is not None:
        try:
            logger.debug("  Annotating POIs from XML...")
            island_annotations, node_annotations, poi_assignments = annotate_skeleton_pois(
                islands, skeletons, map_data_obj,
            )
            _log_poi_annotations(poi_assignments)

            if plots:
                for skel in skeletons:
                    island_node_anns = node_annotations.get(skel.island_id, {})
                    if island_node_anns:
                        plot_island_poi_debug(
                            skel,
                            island_node_anns,
                            str(skeleton_output_dir / f'island_{skel.island_id}_poi.png'),
                        )
        except Exception as e:
            logger.warning(f"    [!] POI annotation failed: {e}")
    else:
        logger.debug("  No XML data available, skipping POI annotation")

    return map_data_obj, island_annotations, node_annotations, poi_assignments


# ---------------------------------------------------------------------------
# Team assignment
# ---------------------------------------------------------------------------

def _build_island_dicts(islands: list[Island]) -> list[dict[str, Any]]:
    """Build island attribute dicts for team assignment and symmetry detection.

    Reflects the current state of island.team (including any XML-set values).
    """
    return [
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


def _assign_teams(
    islands: list[Island],
    map_data_obj: Optional[MapData],
    map_output_dir: Path,
    symmetry: Optional[SymmetryResult] = None,
    poi_assignments: Optional[dict] = None,
) -> None:
    """Assign islands to teams using symmetry + XML data.

    Mutates island.team in-place.
    Uses a SymmetryResult when available (in-memory, no disk read), otherwise
    falls back to reading symmetry.json from map_output_dir.
    """
    from map_analysis.team_assignment import assign_islands_to_teams

    if map_data_obj is None:
        return

    teams = [
        {'id': t.id, 'color': t.color, 'name': t.name, 'max_players': t.max_players}
        for t in map_data_obj.teams
    ]
    if not teams:
        return

    if symmetry is not None:
        global_symmetries = symmetry.global_symmetry
        center_x = symmetry.center_x
        center_z = symmetry.center_z
    else:
        sym_path = map_output_dir / 'symmetry.json'
        if not sym_path.exists():
            logger.debug("  No symmetry.json found, skipping team assignment")
            return
        with open(sym_path) as f:
            sym_data = json.load(f)
        global_symmetries = sym_data.get('global_symmetry', [])
        center_info = sym_data.get('center', {})
        center_x = center_info.get('center_x', 0.0)
        center_z = center_info.get('center_z', 0.0)

    detected = [s for s in global_symmetries if s.get('detected')]
    if not detected:
        logger.debug("  No global symmetry detected, skipping geometric team assignment")
        return

    primary_global = max(detected, key=lambda s: s['confidence'])
    island_dicts = _build_island_dicts(islands)

    # Extract spawn positions from POI data — includes spawns not on any
    # detected island (island_id=None), which are used to anchor the
    # side→team mapping in the geometric fallback.
    spawn_positions: dict[str, tuple[float, float]] = {}
    if poi_assignments:
        for s in poi_assignments.get('spawns', []):
            if s.get('x') is not None and s.get('z') is not None:
                spawn_positions[s['team']] = (s['x'], s['z'])

    team_islands = assign_islands_to_teams(
        island_dicts, teams, center_x, center_z, primary_global,
        spawn_positions=spawn_positions or None,
    )

    # Propagate assignments back to Island objects
    assigned_map = {
        isl_dict['id']: tid
        for tid, t_isls in team_islands.items()
        for isl_dict in t_isls
    }
    for island in islands:
        if island.team is None and island.id in assigned_map:
            island.team = assigned_map[island.id]


def _update_intra_team_symmetry(
    islands: list[Island],
    map_data_obj: Optional[MapData],
    map_output_dir: Path,
    symmetry: Optional[SymmetryResult] = None,
) -> None:
    """Detect intra-team symmetry and append the result to symmetry.json.

    Builds island dicts from the current state of islands (reflecting team
    assignments already applied by _assign_teams). Reads symmetry data from
    the in-memory SymmetryResult when available, otherwise falls back to
    reading symmetry.json from map_output_dir.
    """
    from map_analysis.team_assignment import detect_intra_team_symmetry

    if map_data_obj is None:
        return

    teams = [
        {'id': t.id, 'color': t.color, 'name': t.name, 'max_players': t.max_players}
        for t in map_data_obj.teams
    ]
    if not teams:
        return

    sym_path = map_output_dir / 'symmetry.json'

    if symmetry is not None:
        global_symmetries = symmetry.global_symmetry
        center_info = symmetry.center
        center_x = symmetry.center_x
        center_z = symmetry.center_z
        sym_data = symmetry.to_dict()
    else:
        if not sym_path.exists():
            return
        with open(sym_path) as f:
            sym_data = json.load(f)
        global_symmetries = sym_data.get('global_symmetry', [])
        center_info = sym_data.get('center', {})
        center_x = center_info.get('center_x', 0.0)
        center_z = center_info.get('center_z', 0.0)

    island_dicts = _build_island_dicts(islands)
    intra_team = detect_intra_team_symmetry(
        island_dicts, center_x, center_z, center_info, global_symmetries, teams,
    )

    if intra_team:
        sym_data['intra_team_symmetry'] = intra_team
        with open(sym_path, 'w') as f:
            json.dump(sym_data, f, indent=2)
        sym_teams = [t['team'] for t in intra_team if t.get('symmetry_detected')]
        if sym_teams:
            logger.debug(f"  Intra-team symmetry detected for: {', '.join(sym_teams)}")


# ---------------------------------------------------------------------------
# Stage 7: MapContext enrichment helpers
# ---------------------------------------------------------------------------

def _log_y0_diagnostics(y0_df: Optional[pd.DataFrame]) -> None:
    """Print a summary of the Y0 layer DataFrame for build-region debugging."""
    if y0_df is None:
        logger.debug("    Y0 layer: not found (skipped or not yet extracted)")
        return
    if len(y0_df) == 0 or 'block_id' not in y0_df.columns:
        logger.debug("    Y0 layer: empty (0 blocks)")
        return
    block_counts = y0_df['block_id'].value_counts()
    n_block36 = int(block_counts.get(36, 0))
    total = len(y0_df)
    if n_block36 > 0:
        other = total - n_block36
        if other == 0:
            logger.debug(f"    Y0 layer: {total} blocks, ALL block36 (piston extension)")
        else:
            other_ids = sorted(block_counts.drop(36, errors='ignore').index.tolist())
            logger.debug(f"    Y0 layer: {total} blocks, {n_block36} block36 + "
                         f"{other} other (ids: {other_ids})")
    else:
        ids = sorted(block_counts.index.tolist())
        logger.debug(f"    Y0 layer: {total} blocks, no block36 (ids: {ids})")


# ---------------------------------------------------------------------------

def _attach_build_region(
    map_ctx: MapContext,
    map_data_obj: Optional[MapData],
    islands: list[Island],
    y0_df: Optional[pd.DataFrame],
) -> None:
    """Extract build region from XML + Y0 data and attach it to map_ctx.

    Modifies map_ctx.build_region in-place. No-ops when map_data_obj is None.

    Args:
        y0_df: Pre-loaded Y=0 layout DataFrame, or None if unavailable.
            Used as fallback for block-36 build region detection.
    """
    if map_data_obj is None:
        return
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
            island_polygons=island_shapely,
            y0_df=y0_df,
        )
        if build_result:
            map_ctx.build_region = build_result
            logger.debug(f"    Build region: source={build_result['source']}, "
                         f"void_area={build_result['buildable_void_area']}")
        else:
            logger.debug("    No build region detected")
    except Exception as e:
        logger.warning(f"    [!] Build region extraction failed: {e}")


# ---------------------------------------------------------------------------
# Public API: symmetry pipeline
# ---------------------------------------------------------------------------

def run_symmetry(
    map_output_dir: Path,
    geometry: Optional[IslandAnalysis] = None,
) -> Optional[SymmetryResult]:
    """Symmetry analysis pipeline (Stage 3).

    Detects global geometric symmetry from island data and writes
    symmetry.json to map_output_dir.

    When geometry is provided (the normal case in the full pipeline),
    island data is read directly from the in-memory IslandAnalysis —
    no disk round-trip through islands.json.

    When geometry is None (islands step was skipped, e.g. --no-islands),
    falls back to reading islands.json from disk.

    Args:
        map_output_dir: Per-map output root (symmetry.json written here).
        geometry: IslandAnalysis from run_island_geometry. When
            provided, uses in-memory data; falls back to disk when None.

    Returns:
        SymmetryResult on success, None if island data is unavailable.
    """
    from symmetry_analysis import detect_symmetry, detect_symmetry_from_data
    from symmetry_analysis import exporter as symmetry_exporter

    logger.debug("[3/6] Symmetry Analysis")

    if geometry is not None:
        # Use in-memory island data — no disk round-trip through islands.json
        from common.geometry import get_grid_extent
        df = geometry.df
        x_col = 'world_x' if 'world_x' in df.columns else 'x'
        z_col = 'world_z' if 'world_z' in df.columns else 'z'
        bbox = list(get_grid_extent(df[x_col], df[z_col]))
        island_dicts = [
            {
                'id': isl.id,
                'area': isl.area,
                'center': list(isl.center),
                'simplified_polygon': isl.simplified_polygon,
            }
            for isl in geometry.islands
        ]
        data = {
            'map_name': map_output_dir.name,
            'bounding_box': bbox,
            'islands': island_dicts,
        }
        result = detect_symmetry_from_data(data)
    else:
        # Fallback: islands step was skipped — read cached islands.json from disk
        islands_path = map_output_dir / 'islands.json'
        if not islands_path.exists():
            logger.debug("  islands.json not found — skipping symmetry analysis")
            return None
        result = detect_symmetry(str(islands_path))

    symmetry_exporter.save(result, map_output_dir / 'symmetry.json')

    if result.primary:
        logger.debug(f"  Global: {result.primary['description']} "
                     f"(confidence: {result.primary['confidence']:.0%})")
    else:
        logger.debug("  Global: no symmetry detected")

    return result


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
    output_dir: Optional[Path] = None,
    plots: bool = False,
) -> Optional[IslandAnalysis]:
    """Island geometry pipeline (Stages 1–4).

    Detects islands, builds polygons, computes skeleton graphs, generates
    visualizations, and classifies island centers relative to the map center.

    Does NOT read map.xml and does NOT produce map_context.json.
    Writes islands.json for downstream steps.
    Returns IslandAnalysis with islands: list[IslandPolygon] (pure geometry).

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
        output_dir: Override output directory path (defaults to map_output_dir).
        plots: If True, generate debug plots.

    Returns:
        IslandAnalysis on success, None on failure (missing layout or no islands).
    """
    logger.debug(f"[2/6] Island Analysis: {map_folder.name}")

    _map_output_dir = map_output_dir or map_folder
    layout_dir = _map_output_dir
    island_output_dir = output_dir or _map_output_dir

    layout_filename = LAYOUT_FILES.get(layout_type, 'layout_bedrock.parquet')
    layout_file = layout_dir / layout_filename
    if not layout_file.exists():
        if layout_type == 'decided':
            fallback_file = layout_dir / 'layout_bedrock.parquet'
            if fallback_file.exists():
                logger.warning(
                    f"  layout_decided.parquet not found — falling back to layout_bedrock.parquet. "
                    f"Re-run layout step to generate the decided layer."
                )
                layout_file = fallback_file
            else:
                logger.warning(f"  Layout file not found: {layout_filename}. Run layout analysis first.")
                return None
        else:
            logger.warning(f"  Layout file not found: {layout_filename}. Run layout analysis first.")
            return None

    island_output_dir.mkdir(parents=True, exist_ok=True)

    # Determine whether to write debug outputs (JSON, images).
    # Computation always runs — JSON files are debug artifacts, not pipeline inputs.
    islands_json = island_output_dir / 'islands.json'
    write_outputs = not islands_json.exists() or force_rerun
    if not write_outputs:
        logger.debug("  Cached — recomputing in-memory, skipping file writes")

    # Load layout and detect islands
    logger.debug(f"  Loading layout: {layout_file.name}")
    df = pd.read_parquet(layout_file)
    if df.empty or 'world_x' not in df.columns:
        logger.warning(f"  Layout file is empty: {layout_filename}. Try a different --island-layout.")
        return None
    if 'block_id' in df.columns:
        n_before = len(df)
        df = df[df['block_id'] != 36]
        removed = n_before - len(df)
        if removed:
            logger.debug(f"    Excluded {removed} block-36 rows (void marker)")
    logger.debug(f"    {len(df)} blocks")

    df, islands = detect_and_enrich(
        df, connectivity=connectivity, min_island_size=min_size,
    )
    if write_outputs:
        df.to_parquet(layout_file, index=False)
        logger.debug(f"    Updated {layout_file.name} with island_id")

    if not islands:
        logger.warning("  No islands detected")
        return None

    # Build polygons
    build_polygons(
        islands,
        canonical=canonical_polygons,
        buffer_distance=buffer_distance,
        simplify_tolerance=simplify_tolerance,
        detect_holes=detect_holes,
    )

    # Classify islands (island-level diagnostic, no XML)
    from island_analysis import classify_islands
    classifications = classify_islands(islands)
    logger.debug("  Island classifications:")
    for cls_name, cls_islands in classifications.items():
        if cls_islands:
            logger.debug(f"    {cls_name}: {[i.id for i in cls_islands]}")

    # Compute skeleton graphs
    skeletons, canonical_groups = _compute_skeletons(islands)

    # Debug outputs (visualizations + islands.json) — skipped on cache hit
    if write_outputs:
        _generate_skeleton_visuals(
            islands, skeletons, canonical_groups,
            island_output_dir, map_folder.name, plots=plots,
        )

    # Classify island centers (geometry-only, no XML)
    from map_analysis.poi_annotation import compute_map_center, classify_island_center
    map_center_pt = compute_map_center(df)
    classify_island_center(islands, map_center_pt)

    if write_outputs:
        _save_islands_json(islands, df, map_folder.name, island_output_dir)
        logger.debug(f"    Saved to {island_output_dir.name}/")

    return IslandAnalysis(
        islands=islands,
        skeletons=skeletons,
        canonical_groups=canonical_groups,
        df=df,
        island_output_dir=island_output_dir,
        map_center_pt=map_center_pt,
    )


# ---------------------------------------------------------------------------
# Observer island helpers
# ---------------------------------------------------------------------------

def _find_observer_island(map_data_obj: Optional[MapData], df: pd.DataFrame) -> Optional[int]:
    """Return the island_id that contains the observer (default) spawn, or None.

    Uses the centroid of the observer spawn region's 2D bounding box.  If the
    centroid block is not found in the layout dataframe the closest island
    center is used as a fallback.
    """
    if map_data_obj is None or map_data_obj.observer_spawn is None:
        return None
    region = map_data_obj.observer_spawn.region
    if region is None:
        return None
    bounds = region.get_bounds_2d()
    if bounds is None:
        return None

    (min_x, min_z), (max_x, max_z) = bounds
    centroid_x = (min_x + max_x) / 2.0
    centroid_z = (min_z + max_z) / 2.0

    if 'island_id' not in df.columns:
        return None

    # Primary: look up the block at the centroid coordinate
    block_x = int(round(centroid_x))
    block_z = int(round(centroid_z))
    hit = df.loc[(df['world_x'] == block_x) & (df['world_z'] == block_z), 'island_id']
    if not hit.empty:
        island_id = int(hit.iloc[0])
        if island_id > 0:
            return island_id

    # Fallback: search a small neighbourhood (±2 blocks) around the centroid
    for dx in range(-2, 3):
        for dz in range(-2, 3):
            hit = df.loc[
                (df['world_x'] == block_x + dx) & (df['world_z'] == block_z + dz),
                'island_id',
            ]
            if not hit.empty:
                island_id = int(hit.iloc[0])
                if island_id > 0:
                    return island_id

    logger.debug(
        f"  Observer spawn centroid ({block_x}, {block_z}) not found in layout — "
        "observer island will not be marked"
    )
    return None


def _rerun_symmetry_without_observer(
    final_islands: list[Island],
    df: pd.DataFrame,
    map_output_dir: Path,
    symmetry: Optional[SymmetryResult],
) -> Optional[SymmetryResult]:
    """Re-run symmetry analysis excluding observer islands and update symmetry.json.

    Returns the updated SymmetryResult (or the original if no observer islands
    exist or symmetry was not run).
    """
    if symmetry is None:
        return symmetry
    if not any(isl.is_observer_island for isl in final_islands):
        return symmetry

    from symmetry_analysis import detect_symmetry_from_data
    from symmetry_analysis import exporter as symmetry_exporter
    from common.geometry import get_grid_extent

    x_col = 'world_x' if 'world_x' in df.columns else 'x'
    z_col = 'world_z' if 'world_z' in df.columns else 'z'
    bbox = list(get_grid_extent(df[x_col], df[z_col]))

    island_dicts = [
        {
            'id': isl.id,
            'area': isl.area,
            'center': list(isl.center),
            'simplified_polygon': isl.simplified_polygon,
        }
        for isl in final_islands
        if not isl.is_observer_island
    ]
    data = {
        'map_name': map_output_dir.name,
        'bounding_box': bbox,
        'islands': island_dicts,
    }
    updated = detect_symmetry_from_data(data)
    symmetry_exporter.save(updated, map_output_dir / 'symmetry.json')

    if updated.primary:
        logger.debug(
            f"  Symmetry (no observer): {updated.primary['description']} "
            f"({updated.primary['confidence']:.0%})"
        )
    else:
        logger.debug("  Symmetry (no observer): none detected")

    return updated


# ---------------------------------------------------------------------------
# Public API: assembly pipeline
# ---------------------------------------------------------------------------

def assemble_map(
    map_folder: Path,
    geometry: IslandAnalysis,
    map_output_dir: Path,
    symmetry: Optional[SymmetryResult] = None,
    xml_context: Optional[MapXmlContext] = None,
    plots: bool = False,
    exclude_observer_island: bool = False,
    additional_observer_islands: Optional[list[int]] = None,
) -> MapContext:
    """Map assembly pipeline (Stages 5–7).

    Combines island geometry, symmetry results, and XML data into the
    complete map model. Requires run_island_geometry() to have been called
    first and its IslandAnalysis passed in.

    Reads from xml_context when provided (preferred), otherwise falls back
    to parsing map.xml from map_folder directly.  Reads symmetry.json from
    map_output_dir when symmetry is None (--no-symmetry + cached file).

    Constructs fully contextualized Island objects from the IslandPolygon
    objects in geometry.islands combined with XML annotation data.

    Writes:
        - map_context.json
        - map_graph.json
        - Updates symmetry.json with intra_team_symmetry (if applicable)

    Returns:
        MapContext instance.

    Args:
        map_folder: Path to map folder (for map.xml fallback).
        geometry: IslandAnalysis from run_island_geometry().
        map_output_dir: Per-map output root (where map_context.json is written).
        symmetry: SymmetryResult from the symmetry step. When supplied team
            assignment uses the in-memory object; otherwise falls back to
            reading symmetry.json from map_output_dir.
        xml_context: MapXmlContext from the XML analysis step. When supplied
            the assembly step uses map_data directly without re-parsing map.xml.
        plots: If True, generate POI debug plots.
    """
    island_polygons = geometry.islands
    skeletons = geometry.skeletons
    canonical_groups = geometry.canonical_groups
    df = geometry.df
    island_output_dir = geometry.island_output_dir
    map_center_pt = geometry.map_center_pt

    logger.debug(f"[5/6] Map Assembly: {map_folder.name}")

    skeleton_output_dir = island_output_dir / 'images'

    if map_center_pt is None:
        from map_analysis.poi_annotation import compute_map_center
        map_center_pt = compute_map_center(df)

    # POI annotation — returns annotation dicts, does NOT mutate geometry
    map_data_obj, island_annotations, node_annotations, poi_assignments = _annotate_pois(
        map_folder, island_polygons, skeletons, skeleton_output_dir,
        plots=plots,
        xml_context=xml_context,
    )

    # Construct fully contextualized Island objects from IslandPolygon + annotations
    final_islands = []
    for ip in island_polygons:
        ann = island_annotations.get(ip.id, {})
        final_islands.append(Island(
            id=ip.id,
            blocks=ip.blocks,
            center=ip.center,
            area=ip.area,
            bounding_box=ip.bounding_box,
            hull_vertices=ip.hull_vertices,
            simplified_polygon=ip.simplified_polygon,
            holes=ip.holes,
            has_center=ip.has_center,
            distance_to_center=ip.distance_to_center,
            has_spawn=ann.get('has_spawn', False),
            has_wool=ann.get('has_wool', False),
            team=ann.get('team'),
            is_observer_island=False,
        ))

    # Mark observer island(s) and re-run symmetry excluding them.
    # Only applies to maps where the observer spawn produces spurious islands
    # that must be excluded from symmetry analysis.
    _extra_obs = set(additional_observer_islands or [])
    if exclude_observer_island or _extra_obs:
        observer_ids: set[int] = set(_extra_obs)
        if exclude_observer_island:
            auto_id = _find_observer_island(map_data_obj, df)
            if auto_id is not None:
                observer_ids.add(auto_id)
        if observer_ids:
            for isl in final_islands:
                if isl.id in observer_ids:
                    isl.is_observer_island = True
            marked = sorted(isl.id for isl in final_islands if isl.is_observer_island)
            logger.debug(f"  Observer islands: {marked}")
            symmetry = _rerun_symmetry_without_observer(
                final_islands, df, map_output_dir, symmetry,
            )

    # Team assignment + intra-team symmetry (mutates final_islands[].team)
    _assign_teams(final_islands, map_data_obj, map_output_dir,
                  symmetry=symmetry, poi_assignments=poi_assignments)
    _update_intra_team_symmetry(final_islands, map_data_obj, map_output_dir, symmetry=symmetry)

    # Build MapContext
    from map_analysis.builder import build_map_context
    from map_analysis import exporter as map_context_exporter
    from skeleton_analysis.builder import build_island_graphs
    from skeleton_analysis import exporter as map_graph_exporter

    logger.debug("  Building map context...")
    map_ctx = build_map_context(
        final_islands, skeletons, canonical_groups, df,
        map_data=map_data_obj,
        map_center=map_center_pt,
        poi_assignments=poi_assignments,
    )

    y0_path = map_output_dir / 'layout_y0.parquet'
    y0_df = pd.read_parquet(y0_path) if y0_path.exists() else None
    _log_y0_diagnostics(y0_df)
    _attach_build_region(map_ctx, map_data_obj, final_islands, y0_df)

    map_context_exporter.save(map_ctx, str(map_output_dir / 'map_context.json'))

    island_graphs = build_island_graphs(final_islands, skeletons, node_annotations)
    map_graph_exporter.save(island_graphs, map_ctx.map_name, map_output_dir)

    # Map overview plot (needs map_context for polygons + build regions)
    from skeleton_analysis.visualization import plot_map_overview
    plot_map_overview(
        skeletons,
        str(skeleton_output_dir / 'map_overview.png'),
        map_context=map_context_exporter.to_dict(map_ctx),
    )

    logger.debug("  map_context.json written")
    return map_ctx
