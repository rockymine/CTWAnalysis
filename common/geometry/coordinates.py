"""Canonical spatial coordinate utilities for the CTW analysis pipeline.

Coordinate Systems
------------------
World Space (Integer Indices):
    Raw block positions as stored in Parquet/DataFrames.
    Block at integer index (x, z) occupies the continuous interval
    [x, x+1] x [z, z+1] with its physical centre at (x+0.5, z+0.5).

World Extent (Continuous):
    The physical volume occupied by a set of blocks.
    For blocks spanning integer indices [min_x, max_x], the world extent
    is [min_x, max_x + 1] because the rightmost block at max_x occupies
    [max_x, max_x + 1].

The "+1 Rule":
    Never compute width as ``max_x - min_x``.  A layout containing only
    the block at x=10 has width 1, not 0.  The "+1" adjustment must be
    applied *exactly once*, inside ``get_grid_extent``.  No caller should
    ever write ``+ 1`` or ``+ 0.5`` when computing bounding boxes or
    centres — they should call the functions below instead.

Bounding Box Convention:
    ``(min_x, max_x, min_z, max_z)`` where ``max_x`` and ``max_z`` are
    the *extent* upper bounds, i.e. already +1 relative to the highest
    block index.  This is the convention used throughout the pipeline in
    ``Island.bounding_box``, ``MapContext.bounding_box``, and the JSON
    exports.
"""

from __future__ import annotations

import numpy as np
from typing import Sequence, Tuple, Union

# Type aliases for readability
_Array = Union[Sequence, np.ndarray]
BBox = Tuple[float, float, float, float]   # (min_x, max_x, min_z, max_z)
Point2D = Tuple[float, float]              # (x, z)


def get_grid_extent(xs: _Array, zs: _Array) -> BBox:
    """Compute the world-extent bounding box for a set of block indices.

    A block at integer index *x* occupies the continuous interval
    ``[x, x+1]``.  Therefore the full spatial extent of a layout whose
    block x-indices span ``[min_x, max_x]`` is ``[min_x, max_x + 1]``.
    This function applies the "+1 rule" exactly once so callers never need
    to hard-code it.

    Args:
        xs: Block x-indices (integer world coordinates).
        zs: Block z-indices (integer world coordinates).

    Returns:
        ``(min_x, max_x + 1, min_z, max_z + 1)`` — world-extent bounding
        box as Python floats.

    Examples::

        >>> get_grid_extent([10], [10])
        (10.0, 11.0, 10.0, 11.0)

        >>> get_grid_extent([0, 1, 2], [0, 1, 2])
        (0.0, 3.0, 0.0, 3.0)
    """
    xs_arr = np.asarray(xs, dtype=float)
    zs_arr = np.asarray(zs, dtype=float)
    return (
        float(xs_arr.min()),
        float(xs_arr.max()) + 1.0,
        float(zs_arr.min()),
        float(zs_arr.max()) + 1.0,
    )


def get_center_from_extent(
    min_x: float, max_x: float, min_z: float, max_z: float
) -> Point2D:
    """Compute the geometric centre of a world-extent bounding box.

    Args:
        min_x: Lower x bound of the extent.
        max_x: Upper x bound of the extent (*already* +1 adjusted, as
               returned by :func:`get_grid_extent`).
        min_z: Lower z bound of the extent.
        max_z: Upper z bound of the extent (*already* +1 adjusted).

    Returns:
        ``(centre_x, centre_z)`` — the midpoint of the extent.

    Examples::

        >>> get_center_from_extent(0.0, 11.0, 0.0, 7.0)
        (5.5, 3.5)

        # Composed with get_grid_extent for a single block at (10, 10):
        >>> get_center_from_extent(*get_grid_extent([10], [10]))
        (10.5, 10.5)
    """
    return ((min_x + max_x) / 2.0, (min_z + max_z) / 2.0)


def get_block_centroid(xs: _Array, zs: _Array) -> Point2D:
    """Compute the geometric centroid of a set of blocks.

    Since each block at integer index *x* has its physical centre at
    ``x + 0.5``, the centroid of a collection of blocks is::

        centre_x = mean(xs) + 0.5
        centre_z = mean(zs) + 0.5

    This is distinct from :func:`get_center_from_extent`: the centroid
    weights every block equally and equals the extent centre only for
    uniformly filled rectangular layouts.

    Args:
        xs: Block x-indices (integer world coordinates).
        zs: Block z-indices (integer world coordinates).

    Returns:
        ``(centre_x, centre_z)`` — centroid in continuous world space.

    Examples::

        >>> get_block_centroid([5], [3])
        (5.5, 3.5)

        >>> get_block_centroid([0, 1], [0, 0])
        (1.0, 0.5)
    """
    xs_arr = np.asarray(xs, dtype=float)
    zs_arr = np.asarray(zs, dtype=float)
    return (float(xs_arr.mean()) + 0.5, float(zs_arr.mean()) + 0.5)
