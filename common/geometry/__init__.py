"""Shared spatial coordinate utilities for the CTW analysis pipeline.

See COORDINATE_SYSTEMS.md in this directory for the full reference:
four coordinate spaces, conversion graph, the +1 Rule, and the
Rotation of Extent constraint.
"""

from .coordinates import (
    get_grid_extent,
    get_center_from_extent,
    get_block_centroid,
    block_unit_square,
    blocks_to_unit_squares,
    world_blocks_to_shapely,
)
from .transforms import (
    CanonicalTransform,
    RasterMask,
    raster_to_world_path,
    raster_to_world_point,
)

__all__ = [
    # Block coordinate utilities
    "get_grid_extent",
    "get_center_from_extent",
    "get_block_centroid",
    "block_unit_square",
    "blocks_to_unit_squares",
    "world_blocks_to_shapely",
    # Coordinate-space transforms
    "CanonicalTransform",
    "RasterMask",
    "raster_to_world_path",
    "raster_to_world_point",
]
