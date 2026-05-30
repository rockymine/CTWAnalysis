"""JSON exporter for map context.

Public API:
    to_dict(ctx)              — serialize MapContext to a plain dict
    save(ctx, output_path)    — write MapContext to a JSON file
"""

import logging

from common.json_export import save_json as _save_json

from map_analysis.datatypes import MapContext

logger = logging.getLogger('ctw')


def to_dict(ctx: MapContext) -> dict:
    """Convert MapContext to a JSON-serializable dictionary."""
    return {
        'map_name': ctx.map_name,
        'map_version': ctx.map_version,
        'objective': ctx.objective,
        'teams': ctx.teams,
        'bounding_box': list(ctx.bounding_box) if ctx.bounding_box else None,
        'map_center': list(ctx.map_center) if ctx.map_center else None,
        'total_blocks': ctx.total_blocks,
        'island_count': ctx.island_count,
        'islands': ctx.islands,
        'skeleton': {
            'total_nodes': ctx.total_nodes,
            'total_edges': ctx.total_edges,
            'total_endpoints': ctx.total_endpoints,
            'total_junctions': ctx.total_junctions,
            'unique_canonical_shapes': ctx.unique_canonical_shapes,
        },
        'poi_assignments': ctx.poi_assignments,
        'build_region': ctx.build_region,
    }


def save(ctx: MapContext, output_path: str) -> None:
    """Save MapContext to a JSON file."""
    _save_json(to_dict(ctx), output_path)
    logger.debug(f"  Saved: {output_path}")
