"""Coordinate system utilities for the CTW analysis pipeline.

This package centralises all spatial coordinate math so that no caller
ever needs to write a raw ``+ 1``, ``+ 0.5``, or ad-hoc rotation formula.
Every coordinate conversion has exactly one implementation here, tested and
documented, named after what it does.

===========================================================================
The Four Coordinate Spaces
===========================================================================

1. World Space (integer block indices)
---------------------------------------
The primary representation.  Parquet files and DataFrames store block
positions as integer ``(world_x, world_z)`` pairs.

Key fact — the "+1 Rule":
  Block at integer index *x* occupies the continuous interval [x, x+1].
  A row of blocks from x=10 to x=12 has three blocks, width 3, spanning
  [10, 13].  The width is ``max_x - min_x + 1``, not ``max_x - min_x``.

  The "+1" is applied **exactly once**, inside :func:`get_grid_extent`.
  No other code in the project should ever write ``max_x + 1``::

      xs, zs = df['world_x'], df['world_z']
      min_x, max_x, min_z, max_z = get_grid_extent(xs, zs)
      # max_x and max_z are already +1 adjusted

2. Canonical Space (D4-normalised integer indices)
---------------------------------------------------
Each island is reduced to a canonical orientation so that two islands
differing only by a D4 symmetry (rotation and/or mirror) share the same
canonical representation and hence the same ``canonical_key``.

The transform from world to canonical is exact integer arithmetic:

  1. Optionally mirror the X axis: ``x → -x``
  2. Rotate by 0°, 90°, 180°, or 270°
  3. Translate so that the minimum coordinate in both axes is 0

The translation step means canonical blocks always have ``min_x = min_z = 0``.

:class:`CanonicalTransform` stores the (mirror, rotation, translation)
parameters and provides the round-trips::

    canonical_pts = transform.to_canonical(world_pts)   # world  → canonical
    world_pts     = transform.to_original(canonical_pts) # canonical → world

3. Raster (Mask) Space (row/column array indices)
--------------------------------------------------
A 2-D boolean array used for skeletonisation.  Convention::

    mask[r, c]   where   r ↔ z-axis,   c ↔ x-axis

Built by ``rasterize_island()`` (in ``skeleton_analysis/rasterize.py``) from
canonical integer points with a padding border *p*::

    r = z + p,   c = x + p   (padding shifts everything by p)

:class:`RasterMask` stores the mask and its ``origin`` — the canonical-space
coordinate of ``mask[0, 0]``, which equals ``(-p, -p)``::

    rc_to_canonical(r, c)  →  (x = c + origin[0],  z = r + origin[1])
    canonical_to_rc(x, z)  →  (r = z - origin[1],  c = x - origin[0])

4. Shapely / Continuous Space (floating-point geometry)
-------------------------------------------------------
Two distinct variants exist in the codebase:

  a. Island polygons — built from world-space block indices.
     Each block at world (x, z) becomes the unit square [x, x+1]×[z, z+1]
     via Shapely's ``box()``.  The union of all per-block squares gives the
     exact island boundary including concavities and holes.
     Use :func:`world_blocks_to_shapely`.

  b. XML regions — specified directly in continuous extent coordinates by
     ``<region>`` elements in ``map.xml``.  These do NOT follow the "+1 Rule"
     at read time; the XML already records extent bounds, not block indices.
     ``_expand_block_bounds`` in ``xml_analysis/regions.py`` handles the one
     case (``<block>``) where a single XML block index needs +1 applied.

===========================================================================
Conversion Graph
===========================================================================

::

                       CanonicalTransform
                      .to_canonical()  ↑
                                       │
    World Space  ──────────────────────┤
    (world_x, world_z)                 │
                      .to_original()  ↓
                       CanonicalTransform
                             │
                             │  rasterize_island()
                             ▼
                       Canonical Space
                       (can_x, can_z)
                             │
                   RasterMask.canonical_to_rc()
                             │
                             ▼
                       Raster Space
                       mask[r, c]
                             │
                   RasterMask.rc_to_canonical()
                             │
                             ▼
                       Canonical Space
                             │
                   CanonicalTransform.to_original()
                             │
                             ▼
                       World Space
                     (or use the convenience helpers:
                      raster_to_world_path / raster_to_world_point)

    World blocks  ──world_blocks_to_shapely()──▶  Shapely polygon
    (integer indices)                             (continuous space)

===========================================================================
The "+1 Rule" — applied exactly once
===========================================================================

Wrong::

    # Scattered across callers — each one independently adds +1
    bbox = (min_x, max_x + 1, min_z, max_z + 1)   # layout/builder.py
    center = (min_x + max_x + 1) / 2.0             # poi_annotation.py

Right::

    # One call, one place
    min_x, max_x, min_z, max_z = get_grid_extent(xs, zs)
    cx, cz = get_center_from_extent(min_x, max_x, min_z, max_z)

Functions that embody the rule:
  - :func:`get_grid_extent`         — bounding box (applies +1 to max)
  - :func:`get_center_from_extent`  — midpoint of an already-adjusted extent
  - :func:`get_block_centroid`      — weighted centroid (applies +0.5 per block)
  - :func:`block_unit_square`       — single block → 4 corner vertices
  - :func:`blocks_to_unit_squares`  — many blocks → (N, 4, 2) vertex array
  - :func:`world_blocks_to_shapely` — blocks → Shapely polygon (applies +1 via box())

===========================================================================
The "Rotation of Extent" Constraint
===========================================================================

You cannot transform a Shapely polygon from canonical space to world space
by applying :meth:`CanonicalTransform.to_original` to its vertices.

Why: ``to_original()`` operates on **block indices** (integers), not on
polygon **boundary coordinates** (floats).  The "+1 extent" is axis-aligned
in world space but its direction changes under rotation.

Concrete example — 90° counter-clockwise rotation, no mirror, no shift:

  Suppose canonical block index (5, 3).
  Its unit square in canonical space has corners at (5,3), (6,3), (6,4), (5,4).

  ``to_original()`` maps block index (5, 3) → world block index (10, 20).
  The world unit square for that block is (10,20)→(11,20)→(11,21)→(10,21). ✓

  Now apply ``to_original()`` to the canonical *corner* (6, 4):
    - rotate -90° (i.e., +270°): (x,z) → (z, -x), so (6,4) → (4, -6)
    - this lands at world coordinates (4, -6), which is the lower-left
      corner of world block (4, -6) — a completely different block!

  The polygon built from transformed canonical vertices covers the wrong
  world region.

Rule: **Always build Shapely polygons from world-space block indices.**

  Wrong::

      # Build polygon in canonical space then transform back — BROKEN
      canonical_poly = world_blocks_to_shapely(canonical_pts)
      world_poly = transform_vertices(canonical_poly, transform)

  Right::

      # Build directly from world block indices
      world_poly = world_blocks_to_shapely(island.world_blocks)

This is why :func:`world_blocks_to_shapely` takes world-space blocks and
why ``_build_union_polygon`` in ``island_analysis/polygon.py`` receives
``island.blocks`` (world), not ``canonical.canonical_points``.

===========================================================================
Quick Reference
===========================================================================

Block extents / bounding boxes
  :func:`get_grid_extent`          xs, zs → (min_x, max_x+1, min_z, max_z+1)
  :func:`get_center_from_extent`   BBox   → (cx, cz)
  :func:`get_block_centroid`       xs, zs → weighted centroid (mean+0.5)

Block vertices for rendering
  :func:`block_unit_square`        x, z   → [(x,z),(x+1,z),(x+1,z+1),(x,z+1)]
  :func:`blocks_to_unit_squares`   xs, zs → ndarray (N, 4, 2)

Block set to polygon
  :func:`world_blocks_to_shapely`  [(x,z),...] → Shapely Polygon

World ↔ Canonical transforms
  :class:`CanonicalTransform`
    .to_canonical(pts)   world pts  → canonical pts
    .to_original(pts)    canonical  → world pts

Raster ↔ Canonical
  :class:`RasterMask`
    .rc_to_canonical(r, c)  → (x, z)  canonical
    .canonical_to_rc(x, z)  → (r, c)  raster

Raster → World (two-step shortcut)
  :func:`raster_to_world_path`   pixel_path, raster, transform → world Px2 array
  :func:`raster_to_world_point`  (r, c),     raster, transform → world [x, z]

Module layout
  coordinates.py  — block extent / vertex / polygon utilities
  transforms.py   — CanonicalTransform, RasterMask, raster-to-world helpers
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
