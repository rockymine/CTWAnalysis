# Coordinate Systems — `common/geometry`

This package centralises all spatial coordinate math so that no caller
ever needs to write a raw `+ 1`, `+ 0.5`, or ad-hoc rotation formula.
Every coordinate conversion has exactly one implementation here, tested and
named after what it does.

---

## The Four Coordinate Spaces

### 1. World Space — integer block indices

The primary representation. Parquet files and DataFrames store block positions
as integer `(world_x, world_z)` pairs.

**The "+1 Rule":** block at integer index *x* occupies the continuous interval
`[x, x+1]`. A row of blocks from `x=10` to `x=12` has three blocks, width 3,
spanning `[10, 13]`. The width is `max_x - min_x + 1`, not `max_x - min_x`.

The `+1` is applied **exactly once**, inside `get_grid_extent()`. No other
code in the project should ever write `max_x + 1`:

```python
# Wrong — scattered raw +1 across callers
bbox   = (min_x, max_x + 1, min_z, max_z + 1)
center = (min_x + max_x + 1) / 2.0

# Right — one call, one place
min_x, max_x, min_z, max_z = get_grid_extent(xs, zs)
cx, cz = get_center_from_extent(min_x, max_x, min_z, max_z)
```

**Bounding box convention:** `(min_x, max_x, min_z, max_z)` where `max_x` and
`max_z` are the *extent* upper bounds — already `+1` relative to the highest
block index. Used in `Island.bounding_box`, `MapContext.bounding_box`, and all
JSON exports.

---

### 2. Canonical Space — D4-normalised integer indices

Each island is reduced to a canonical orientation so that two islands differing
only by a D4 symmetry (rotation and/or mirror) share the same canonical
representation and hence the same `canonical_key`.

The transform from world to canonical applies three steps in order, using exact
integer arithmetic throughout:

1. **Mirror** — optionally flip the X axis: `x → -x`
2. **Rotate** — by 0°, 90°, 180°, or 270°
3. **Translate** — shift so that the minimum coordinate in both axes is 0

The translation step means canonical blocks always satisfy `min_x = min_z = 0`.

`CanonicalTransform` stores the `(mirror, rotation, translation)` parameters:

```python
canonical_pts = transform.to_canonical(world_pts)    # world  → canonical
world_pts     = transform.to_original(canonical_pts)  # canonical → world
```

---

### 3. Raster Space — row/column mask array indices

A 2-D boolean array used for skeletonisation. Axis convention:

```
mask[r, c]   where   r ↔ z-axis,   c ↔ x-axis
```

Built by `rasterize_island()` in `skeleton_analysis/rasterize.py` from
canonical integer points with a padding border *p*:

```
r = z + p,   c = x + p
```

`RasterMask` stores the mask and its `origin` — the canonical-space coordinate
of `mask[0, 0]`, which equals `(-p, -p)`. The conversions are:

```
rc_to_canonical(r, c)  →  x = c + origin[0],  z = r + origin[1]
canonical_to_rc(x, z)  →  r = z − origin[1],  c = x − origin[0]
```

---

### 4. Shapely / Continuous Space — floating-point geometry

Two distinct variants exist in the codebase:

**a. Island polygons** — built from world-space block indices. Each block at
world `(x, z)` becomes the unit square `[x, x+1] × [z, z+1]` via Shapely's
`box()`. The union of all per-block squares gives the exact island boundary
including concavities and holes. Use `world_blocks_to_shapely()`.

**b. XML regions** — specified directly in continuous extent coordinates by
`<region>` elements in `map.xml`. These do *not* follow the "+1 Rule" at read
time; the XML already records extent bounds, not block indices.
`_expand_block_bounds` in `xml_analysis/regions.py` handles the one case
(`<block>`) where a single XML block index needs `+1` applied.

---

## Conversion Graph

```
                    CanonicalTransform.to_canonical()
                           ▲
                           │
    World Space ───────────┤
    (world_x, world_z)     │
                           │
                    CanonicalTransform.to_original()
                           │
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
                           │                   ← shortcut: raster_to_world_path
                           ▼                              raster_to_world_point
                      World Space

    World blocks ──world_blocks_to_shapely()──▶ Shapely polygon
    (integer indices)                           (continuous space)
```

---

## The "Rotation of Extent" Constraint

You **cannot** transform a Shapely polygon from canonical space to world space
by applying `CanonicalTransform.to_original()` to its vertices.

`to_original()` operates on **block indices** (integers), not on polygon
**boundary coordinates** (floats). The `+1` extent direction is axis-aligned in
world space, but that direction rotates with the coordinate system — so a
polygon transformed via vertices will cover the wrong region.

**Concrete example — 90° CCW rotation, no mirror, no shift:**

- Canonical block index `(5, 3)` maps to world block index `(10, 20)`.
  The correct world unit square is `(10,20)→(11,20)→(11,21)→(10,21)`. ✓
- Now apply `to_original()` to the canonical *corner* `(6, 4)`:
  rotate −90° (i.e. +270°): `(x,z) → (z, −x)`, giving `(4, −6)`.
  That's the lower-left corner of world block `(4, −6)` — a completely
  different block from the one we wanted. ✗

**Rule: always build Shapely polygons from world-space block indices.**

```python
# Wrong — polygon built in canonical space then "transformed back"
canonical_poly = world_blocks_to_shapely(canonical_pts)
world_poly = transform_vertices(canonical_poly, transform)  # BROKEN

# Right — build directly from world block indices
world_poly = world_blocks_to_shapely(island.world_blocks)
```

This is why `_build_union_polygon` in `island_analysis/polygon.py` receives
`island.blocks` (world indices), not `canonical.canonical_points`.

---

## Quick Reference

### Block extents and bounding boxes

| Function | Signature | Notes |
|---|---|---|
| `get_grid_extent` | `xs, zs → (min_x, max_x+1, min_z, max_z+1)` | Applies +1 rule |
| `get_center_from_extent` | `BBox → (cx, cz)` | Midpoint of adjusted extent |
| `get_block_centroid` | `xs, zs → (cx, cz)` | Weighted centroid, applies +0.5 |

### Block vertices for rendering

| Function | Signature | Notes |
|---|---|---|
| `block_unit_square` | `x, z → [(x,z),(x+1,z),(x+1,z+1),(x,z+1)]` | Single block, 4 corners |
| `blocks_to_unit_squares` | `xs, zs → ndarray (N, 4, 2)` | For `PolyCollection` |

### Block set to polygon

| Function | Signature |
|---|---|
| `world_blocks_to_shapely` | `[(x,z), …] → Shapely Polygon` |

### World ↔ Canonical

| Symbol | Method | Direction |
|---|---|---|
| `CanonicalTransform` | `.to_canonical(pts)` | world → canonical |
| `CanonicalTransform` | `.to_original(pts)` | canonical → world |

### Raster ↔ Canonical

| Symbol | Method | Direction |
|---|---|---|
| `RasterMask` | `.rc_to_canonical(r, c)` | raster → canonical |
| `RasterMask` | `.canonical_to_rc(x, z)` | canonical → raster |

### Raster → World (two-step shortcut)

| Function | Signature |
|---|---|
| `raster_to_world_path` | `pixel_path, raster, transform → ndarray (P, 2)` |
| `raster_to_world_point` | `(r, c), raster, transform → ndarray [x, z]` |

---

## Module Layout

```
common/geometry/
  __init__.py       public API, re-exports everything
  coordinates.py    get_grid_extent, get_block_centroid, block_unit_square,
                    blocks_to_unit_squares, world_blocks_to_shapely
  transforms.py     CanonicalTransform, RasterMask,
                    raster_to_world_path, raster_to_world_point
  tests/
    test_coordinates.py
    test_transforms.py
```
