"""Builder for MapContext from analysis results.

Takes islands, skeleton results, layout data, and XML metadata
and populates a MapContext dataclass.
"""

from typing import Dict, List, Optional, Tuple

from ..map_analysis.datatypes import MapContext
from common.geometry import get_grid_extent


def build_map_context(
    islands,
    skeleton_results,
    canonical_groups: Dict[str, List[int]],
    layout_df,
    map_data=None,
    map_center: Optional[Tuple[float, float]] = None,
    poi_assignments: Optional[Dict] = None,
) -> MapContext:
    """Populate a MapContext from all analysis results.

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
    ctx.bounding_box = get_grid_extent(layout_df[x_col], layout_df[z_col])
    ctx.total_blocks = len(layout_df)
    ctx.map_center = map_center

    # Islands (geometry only; skeleton/pathfinding live in map_graph.json)
    ctx.island_count = len(islands)
    for island in islands:
        ctx.islands.append({
            'id': island.id,
            'area': island.area,
            'center': list(island.center),
            'bounding_box': list(island.bounding_box),
            'has_spawn': island.has_spawn,
            'has_wool': island.has_wool,
            'has_center': island.has_center,
            'distance_to_center': round(island.distance_to_center, 2),
            'team': island.team,
            'hole_count': len(island.holes),
            'simplified_polygon': island.simplified_polygon,
        })

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
