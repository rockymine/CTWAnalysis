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

**Bounding box convention:** `BoundingBox(min_x, max_x, min_z, max_z)` where
`max_x` and `max_z` are the *extent* upper bounds — already `+1` relative to
the highest block index. Used in `Island.bounding_box`, `MapContext.bounding_box`,
and all JSON exports. `BBox` is a backward-compat alias for `BoundingBox`.

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

## Data Invariants (Authoritative Definitions)

This section gives precise, implementation-verified definitions of every
implicit invariant that the pipeline relies on.  When adding code that
touches any of these types, check here first.

---

### GraphNode.rc

| Property | Value |
|---|---|
| Python type | `Tuple[int, int]` |
| Shape | 2-tuple `(r, c)` |
| Dtype | Non-negative Python `int` |
| Semantics | **Cell indices** — raster row and column of the skeleton pixel |
| Axis order | `rc[0]` = row `r` ↔ z-axis; `rc[1]` = column `c` ↔ x-axis |
| Domain | `r ∈ [0, H)`, `c ∈ [0, W)` where `mask.shape == (H, W)` |

`rc` identifies a **cell by its index**, not its centre.  The pixel occupies
the unit square `[c, c+1] × [r, r+1]` in raster data coordinates.
Use `block_centers([node.rc[1], node.rc[0]])` to get `(c+0.5, r+0.5)` for
plotting.

---

### GraphEdge.pixel_path

| Property | Value |
|---|---|
| NumPy shape | `(P, 2)`, P ≥ 2 |
| NumPy dtype | `int32` |
| Column order | `path[i] = (r, c)` — same axis order as `GraphNode.rc` |
| Domain | All values are valid raster indices within the mask bounds |
| Connectivity | 8-connected: `max(|Δr|, |Δc|) == 1` for all consecutive pairs |
| Endpoints | `path[0]` and `path[-1]` are node pixels (degree ≠ 2) |
| Interior pixels | `path[1:-1]` are degree-2 skeleton pixels |

**`src`/`dst` vs path direction.**  `GraphEdge.src` is the lower `node_id`
and `GraphEdge.dst` is the higher `node_id` — this is an arbitrary canonical
ordering chosen for de-duplication, **not** the walk direction.  `path[0]`
is the raster position of whichever of the two nodes happened to initiate
the walk; it may correspond to either `src` or `dst`.  Treat every edge as
**undirected**: never rely on `path[0] == node(src).rc`.

---

### CanonicalTransform — Rotation Convention

**Rotation direction:** CCW (counter-clockwise) in mathematical convention,
treating `(x, z)` as a standard right-hand 2-D plane where `z` is the
second axis.  The exact formulas:

| Degrees | Formula |
|---|---|
| 0° | `(x, z) → (x, z)` |
| 90° | `(x, z) → (−z, x)` |
| 180° | `(x, z) → (−x, −z)` |
| 270° | `(x, z) → (z, −x)` |

**Visual note:** Minecraft maps are displayed with `+z` pointing south
(downward).  Because of this, a 90° CCW rotation in the mathematical
sense *appears* as 90° **CW** on the rendered map.

**Order of operations (forward, `to_canonical`):**

1. Mirror — if `mirror=True`: `x → −x`
2. Rotate — by `rotation` degrees CCW (formula above)
3. Translate — add `translation` so that `min(x) = min(z) = 0`

**Reverse (`to_original`)** applies the inverse in reverse order:
subtract translation, rotate by `−rotation`, un-mirror.

**Integer guarantees:** both `to_canonical` and `to_original` round all
results to integers.  Intermediate arithmetic uses float, but inputs and
outputs are treated as exact integer block indices.

---

### Axis Orientation — Domain Table

| Space | Horiz. coord | Vert. coord | +horiz direction | +vert direction (data) | matplotlib setup |
|---|---|---|---|---|---|
| **World** | `world_x` | `world_z` | East (right) | South (down on map) | `ax.invert_yaxis()` |
| **Canonical** | `can_x` | `can_z` | Right (post D4) | Down (post D4) | `ax.invert_yaxis()` |
| **Raster** | `c` (column) | `r` (row) | Right | Down | `origin='upper'` |
| **Shapely** | `x` | `y` (= z in our use) | Right | ↑ in math, ↓ in our data | `ax.invert_yaxis()` |

**Why `invert_yaxis()` / `origin='upper'`:** In all four spaces the vertical
axis (`z` or `r`) increases *southward / downward*.  Matplotlib's default y-axis
increases upward, so world- and canonical-space axes need `invert_yaxis()`.
Raster-space `imshow` uses `origin='upper'` instead, which has the same effect:
row 0 is drawn at the visual top, row H−1 at the bottom.

**Relationship between raster and canonical:**

```
c  ↔  can_x   (both increase rightward / eastward)
r  ↔  can_z   (both increase downward / southward)
mask[0, 0]  ↔  canonical origin  (−padding, −padding)
```

---

## Plotting Recipes

Every plot in the pipeline falls into one of two modes depending on which
coordinate space the axes use.  The rules below are mandatory — violating
either rule in isolation produces a 0.5-block shift.

---

### World-Space Plots

Axes show `world_x` (horizontal) and `world_z` (vertical, inverted with
`ax.invert_yaxis()`).  Polygon outlines from `map_context.json` and from
`world_blocks_to_shapely()` already use extent coordinates and need no
adjustment.

**Scatter / line coordinates must go through `block_centers`:**

```python
# Wrong — integer index is the lower-left corner of the block unit square;
#          marker appears 0.5 blocks away from the polygon outline.
ax.scatter(blocks[:, 0], blocks[:, 1])

# Right — block_centers adds 0.5 to land on the block centre.
bc = block_centers(blocks)          # shape (N, 2)
ax.scatter(bc[:, 0], bc[:, 1])

# For a single world point produced by raster_to_world_point:
pt_c = block_centers(world_pt)      # shape (2,)
ax.scatter(pt_c[0], pt_c[1])

# For a path produced by raster_to_world_path (shape P×2, columns x/z):
path_c = block_centers(path_world)
ax.plot(path_c[:, 0], path_c[:, 1])
```

---

### Raster-Space Plots

Axes show raster column `c` (horizontal) and raster row `r` (vertical,
increasing downward because `origin='upper'`).

**Rule 1 — always set `extent` on every `imshow` call:**

```python
# Wrong — default extent centres pixel (r,c) at (c, r);
#          that is the lower-left corner of the block, not its centre.
ax.imshow(mask, origin='upper')

# Right — extent=[0, W, H, 0] makes pixel (r,c) occupy [c,c+1]×[r,r+1].
ax.imshow(mask, origin='upper', extent=raster_imshow_extent(mask.shape))
```

`raster_imshow_extent(shape)` returns `[0, W, H, 0]` which maps to
matplotlib's `[left, right, bottom, top]`.  With `origin='upper'`, row 0
is at the visual top (`top=0`) and the last row is at the visual bottom
(`bottom=H`).

**Rule 2 — scatter / line coordinates must go through `block_centers`:**

```python
# Wrong — (col, row) is the pixel's data-coordinate after the extent shift,
#          which is still the lower-left corner.
ax.scatter(node.rc[1], node.rc[0])

# Right — block_centers adds 0.5 to each dimension.
nc = block_centers([node.rc[1], node.rc[0]])   # [col+0.5, row+0.5]
ax.scatter(nc[0], nc[1])

# For a pixel path (shape P×2, columns [row, col]):
path_c = block_centers(path)
ax.plot(path_c[:, 1], path_c[:, 0])            # plot(x=col+0.5, y=row+0.5)
```

The two rules are inseparable.  Applying only `extent` leaves scatter at
pixel corners; applying only `block_centers` without `extent` shifts scatter
to centres but the image is still half a pixel off.

---

## Quick Reference

### Block extents and bounding boxes

| Function | Signature | Notes |
|---|---|---|
| `get_grid_extent` | `xs, zs → BoundingBox` | Applies +1 rule |
| `get_center_from_extent` | `min_x, max_x, min_z, max_z → Point2D` | Midpoint of adjusted extent |
| `get_block_centroid` | `xs, zs → Point2D` | Weighted centroid, applies +0.5 |

### Plotting helpers

| Function | Signature | Notes |
|---|---|---|
| `block_centers` | `block_indices → ndarray (+0.5)` | World & raster scatter/lines |
| `raster_imshow_extent` | `(H, W) → [0, W, H, 0]` | `extent=` arg for `imshow` |

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
  coordinates.py    BoundingBox, Point2D, BBox (alias),
                    get_grid_extent, get_block_centroid, block_centers,
                    raster_imshow_extent, block_unit_square,
                    blocks_to_unit_squares, world_blocks_to_shapely
  transforms.py     CanonicalTransform, RasterMask,
                    raster_to_world_path, raster_to_world_point
  tests/
    test_coordinates.py
    test_transforms.py
```
