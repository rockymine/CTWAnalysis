"""Block extent, vertex, and polygon utilities. See COORDINATE_SYSTEMS.md."""

from __future__ import annotations

import numpy as np
from typing import List, Sequence, Tuple, Union

# Type aliases for readability
_Array = Union[Sequence, np.ndarray]
BBox = Tuple[float, float, float, float]         # (min_x, max_x, min_z, max_z)
Point2D = Tuple[float, float]                    # (x, z)
UnitSquareVerts = List[Tuple[float, float]]      # 4 (x, z) corner pairs


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


def block_unit_square(x: float, z: float) -> UnitSquareVerts:
    """Return the four corner vertices of a single block's unit square.

    Block at integer index ``(x, z)`` occupies ``[x, x+1] × [z, z+1]``.
    The four corners are returned in counter-clockwise order starting from
    the bottom-left, matching the convention expected by matplotlib's
    ``PolyCollection``.

    Args:
        x: Block x-index (integer world coordinate).
        z: Block z-index (integer world coordinate).

    Returns:
        ``[(x, z), (x+1, z), (x+1, z+1), (x, z+1)]`` as Python floats.

    Examples::

        >>> block_unit_square(3, 5)
        [(3.0, 5.0), (4.0, 5.0), (4.0, 6.0), (3.0, 6.0)]
    """
    fx, fz = float(x), float(z)
    return [(fx, fz), (fx + 1.0, fz), (fx + 1.0, fz + 1.0), (fx, fz + 1.0)]


def blocks_to_unit_squares(xs: _Array, zs: _Array) -> np.ndarray:
    """Build unit-square vertex arrays for a collection of blocks.

    Each block at integer index ``(x, z)`` occupies ``[x, x+1] × [z, z+1]``.
    Returns a shape ``(N, 4, 2)`` array suitable for direct use with
    matplotlib's ``PolyCollection``.

    Vertex layout per block::

        [:, 0, :] = (x,     z)     bottom-left
        [:, 1, :] = (x+1,   z)     bottom-right
        [:, 2, :] = (x+1,   z+1)   top-right
        [:, 3, :] = (x,     z+1)   top-left

    Args:
        xs: Block x-indices (integer world coordinates).
        zs: Block z-indices (integer world coordinates).

    Returns:
        ``ndarray`` of shape ``(N, 4, 2)``.

    Examples::

        >>> blocks_to_unit_squares([0, 1], [0, 0]).shape
        (2, 4, 2)
    """
    xs_arr = np.asarray(xs, dtype=float)
    zs_arr = np.asarray(zs, dtype=float)
    return np.stack([
        np.column_stack([xs_arr,         zs_arr]),
        np.column_stack([xs_arr + 1.0,   zs_arr]),
        np.column_stack([xs_arr + 1.0,   zs_arr + 1.0]),
        np.column_stack([xs_arr,         zs_arr + 1.0]),
    ], axis=1)


def block_centers(block_indices: _Array) -> np.ndarray:
    """Convert block index coordinates to block center coordinates.

    Block at integer index ``x`` occupies ``[x, x+1]``; its center is at
    ``x + 0.5``.  Works on any array shape: pass ``(2,)`` for a single
    ``(x, z)`` point, or ``(N, 2)`` for a collection.

    Use this whenever scatter or line plots must be centred on blocks rather
    than placed at the lower-left corner that integer indices represent.

    Args:
        block_indices: Array-like of integer block index coordinates.

    Returns:
        Float array of the same shape with every element incremented by 0.5.

    Examples::

        >>> block_centers([10, 5])
        array([10.5,  5.5])

        >>> block_centers([[0, 0], [1, 0]])
        array([[0.5, 0.5],
               [1.5, 0.5]])
    """
    return np.asarray(block_indices, dtype=float) + 0.5


def world_blocks_to_shapely(blocks: _Array):
    """Build a Shapely polygon from world-space block indices.

    Each block at integer index ``(x, z)`` occupies ``[x, x+1] × [z, z+1]``.
    This function converts each block to its unit-square polygon and returns
    their union, giving the exact boundary of the block layout (including
    concavities and holes).

    The "+1 extent" is applied here in world space — the one authoritative
    place where ``x+1`` and ``z+1`` appear for block-to-polygon conversion.
    Callers must **never** apply a spatial transform (rotation, mirror) to the
    result and expect it to remain block-accurate; polygons must always be
    built in world space.  See the module docstring of
    :mod:`common.geometry.transforms` for details.

    Args:
        blocks: Nx2 array-like of ``(x, z)`` integer block indices.

    Returns:
        A :class:`shapely.geometry.base.BaseGeometry` (``Polygon`` or
        ``MultiPolygon``) representing the union of all block unit squares.
        Returns an empty ``Polygon`` if *blocks* is empty.

    Examples::

        >>> from common.geometry import world_blocks_to_shapely
        >>> p = world_blocks_to_shapely([[0, 0], [1, 0]])
        >>> p.bounds   # (minx, miny, maxx, maxy) in shapely convention
        (0.0, 0.0, 2.0, 1.0)
    """
    from shapely.geometry import box, Polygon
    from shapely.ops import unary_union

    blocks_arr = np.asarray(blocks, dtype=float)
    if blocks_arr.size == 0:
        return Polygon()

    squares = [
        box(float(x), float(z), float(x) + 1.0, float(z) + 1.0)
        for x, z in blocks_arr
    ]
    return unary_union(squares)
