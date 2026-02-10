"""
Builder functions for MapContext and skeleton serialization dicts.

Dependency tier: imports from ctw.core.models (can import everything).
"""

import numpy as np
from typing import List, Dict, Optional, Tuple


def build_map_context(
    islands,
    skeleton_results,
    canonical_groups: Dict[str, List[int]],
    layout_df,
    map_data=None,
    map_center: Optional[Tuple[float, float]] = None,
    poi_assignments: Optional[Dict] = None,
):
    """Build a MapContext from all analysis results.

    Args:
        islands: List of Island objects.
        skeleton_results: List of IslandResult objects.
        canonical_groups: canonical_key -> island_ids mapping.
        layout_df: Layout DataFrame with world_x/world_z columns.
        map_data: Parsed MapData from XML (optional).
        map_center: Pre-computed map center (optional).
        poi_assignments: POI assignment results (optional).

    Returns:
        Populated MapContext.
    """
    from ctw.core.models import MapContext

    ctx = MapContext()

    # XML metadata
    if map_data is not None:
        ctx.map_name = map_data.name
        ctx.map_version = map_data.version
        ctx.objective = map_data.objective
        ctx.teams = [
            {'id': t.id, 'color': t.color, 'name': t.name, 'max_players': t.max_players}
            for t in map_data.teams
        ]

    # Layout info
    x_col = 'world_x' if 'world_x' in layout_df.columns else 'x'
    z_col = 'world_z' if 'world_z' in layout_df.columns else 'z'
    ctx.bounding_box = (
        float(layout_df[x_col].min()),
        float(layout_df[x_col].max()) + 1,
        float(layout_df[z_col].min()),
        float(layout_df[z_col].max()) + 1,
    )
    ctx.total_blocks = len(layout_df)
    ctx.map_center = map_center

    # Islands
    ctx.island_count = len(islands)
    for island in islands:
        island_info = {
            'id': island.id,
            'area': island.area,
            'center': list(island.center),
            'bounding_box': list(island.bounding_box),
            'has_spawn': island.has_spawn,
            'has_wool': island.has_wool,
            'has_center': island.has_center,
            'distance_to_center': round(island.distance_to_center, 2),
            'team': island.team,
            'triangle_count': len(island.triangles),
            'hole_count': len(island.holes),
            'simplified_polygon': island.simplified_polygon,
        }
        ctx.islands.append(island_info)

    # Skeleton
    ctx.total_nodes = sum(len(r.graph.nodes) for r in skeleton_results)
    ctx.total_edges = sum(len(r.graph.edges) for r in skeleton_results)
    ctx.total_endpoints = sum(
        sum(1 for n in r.graph.nodes if n.node_type == 'endpoint')
        for r in skeleton_results
    )
    ctx.total_junctions = sum(
        sum(1 for n in r.graph.nodes if n.node_type == 'junction')
        for r in skeleton_results
    )
    ctx.unique_canonical_shapes = len(canonical_groups)

    # POI
    if poi_assignments is not None:
        ctx.poi_assignments = poi_assignments

    return ctx


def build_skeleton_dicts(
    islands,
    skeleton_results,
) -> List[dict]:
    """Build per-island skeleton dicts for map_graph.json.

    Returns:
        List of dicts: [{"island_id": int, "team": str, "skeleton": {...}, ...}]
    """
    result_by_id = {r.island_id: r for r in skeleton_results}
    island_skeletons = []
    for island in islands:
        skel_result = result_by_id.get(island.id)
        island_skeletons.append({
            'island_id': island.id,
            'team': island.team,
            'skeleton': _build_skeleton_dict(skel_result) if skel_result else None,
            'pathfinding': None,
        })
    return island_skeletons


def _build_skeleton_dict(result) -> dict:
    """Convert IslandResult skeleton data to a JSON-serializable dict in world coords."""
    transform = result.canonical.transform
    raster = result.raster

    nodes = []
    for node in result.graph.nodes:
        cx, cz = raster.rc_to_canonical(node.rc[0], node.rc[1])
        canonical_pt = np.array([[cx, cz]], dtype=float)
        world_pt = transform.to_original(canonical_pt)[0]
        nodes.append({
            'node_id': node.node_id,
            'x': round(float(world_pt[0]), 1),
            'z': round(float(world_pt[1]), 1),
            'type': node.node_type,
            'degree': node.degree,
        })

    edges = []
    for edge in result.graph.edges:
        edges.append({
            'edge_id': edge.edge_id,
            'src': edge.src,
            'dst': edge.dst,
        })

    edge_pixels = {}
    for edge in result.graph.edges:
        path_canonical = np.array([
            raster.rc_to_canonical(r, c) for r, c in edge.pixel_path
        ], dtype=float)
        path_world = transform.to_original(path_canonical)
        edge_pixels[str(edge.edge_id)] = {
            'src': edge.src,
            'dst': edge.dst,
            'pixels': [[round(float(pt[0]), 1), round(float(pt[1]), 1)]
                        for pt in path_world],
        }

    return {
        'nodes': nodes,
        'edges': edges,
        'edge_pixels': edge_pixels,
    }
