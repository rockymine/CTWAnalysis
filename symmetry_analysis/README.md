# Symmetry Detection

Analyzes the geometric layout of a CTW (Capture the Wool) map to determine
which symmetry types are present — both globally across the entire map and
within each team's territory.

## Usage

```bash
python ctw.py debug symmetry --map <map_name>
```

The command reads preprocessed island geometry from
`output/<map_name>/island_analysis/map_context.json`, which must be generated
first by the island analysis pipeline:

```bash
python ctw.py --config ctw_config.yaml run --map <map_name> --no-matches
```

## How it works

The analysis runs in four stages:

1. **Center classification** — determine the geometric center of the map
2. **Island pair analysis** — test how island centroids relate to each other
   under candidate transforms
3. **Global symmetry detection** — combine pair evidence with polygon-level
   verification to score each symmetry type
4. **Intra-team symmetry** — check whether each team's own territory is
   internally symmetric

---

## Report sections explained

### Map Center

Every symmetry operation (mirror, rotation) needs a center point to operate
around.  The center is derived from the map's bounding box, which spans all
island blocks.

In Minecraft, a block at integer coordinate `(x, z)` occupies the area
`[x, x+1) x [z, z+1)`.  The center point falls at the bounding box midpoint.
Whether that midpoint lands on a single block or between blocks depends on
whether each dimension spans an odd or even number of blocks:

| X dimension | Z dimension | Center type    | Center size |
|:-----------:|:-----------:|----------------|:-----------:|
| odd         | odd         | `single_block` | 1 block     |
| even        | odd         | `2x1_line`     | 2 blocks    |
| odd         | even        | `1x2_line`     | 2 blocks    |
| even        | even        | `2x2_area`     | 4 blocks    |

The center type matters for intra-team symmetry splitting (see below).

**Example output:**
```
Map Center
----------------------------------------------------------------------
  Map dimensions:  230 x 230 blocks
  Center point:    (0.0, 0.0)
  Center type:     2x2 center area
  Center blocks:   (-1, -1), (0, -1), (-1, 0), (0, 0)
```

### Island Pair Analysis

Islands with the same area are grouped as **canonical pairs** — candidates for
being symmetrically related.  For each pair, the detector tests whether
applying a transform to island A's centroid lands on island B's centroid
(within a tolerance of 3 blocks).

The tested transforms are:

| Transform    | Operation                                  | Formula                              |
|--------------|-------------------------------------------|--------------------------------------|
| `mirror_x`   | Reflect across the vertical axis X=center | `(x, z) -> (2*cx - x, z)`           |
| `mirror_z`   | Reflect across the horizontal axis Z=center | `(x, z) -> (x, 2*cz - z)`        |
| `rot_180`    | 180-degree rotation around center         | `(x, z) -> (2*cx - x, 2*cz - z)`   |
| `rot_90`     | 90-degree CCW rotation around center      | `(x, z) -> (cx + (z-cz), cz - (x-cx))` |
| `rot_270`    | 270-degree CCW (= 90 CW) rotation        | `(x, z) -> (cx - (z-cz), cz + (x-cx))` |

A single pair can match multiple transforms (e.g. two islands on opposite sides
of center satisfy both `mirror_z` and `rot_180` simultaneously).

For groups of 4 same-area islands (typical of 4-team maps), all `C(4,2) = 6`
pairwise combinations are tested.

The **transform vote tally** counts how many pairs support each transform type.

**Example output:**
```
Island Pair Analysis
----------------------------------------------------------------------
  Canonical pairs found: 18
    Island  1 <->  2  (area= 2478)  transforms: rot_270
    Island  1 <->  3  (area= 2478)  transforms: rot_90
    ...

  Transform vote tally:
    mirror_x     3 pair(s)
    rot_90       7 pair(s)
    rot_180      6 pair(s)
```

### Global Symmetry

Each candidate symmetry type is scored using two independent signals:

1. **Pair support** — what fraction of island pairs' centroids are consistent
   with this transform.  For `rot_90`, both `rot_90` and `rot_270` pairs count
   as evidence (they are inverses of the same symmetry), but both directions
   must be present.

2. **Polygon IoU** — all island polygons are unioned into a single shape, the
   transform is applied, and Intersection-over-Union is computed between the
   original and transformed shapes.  This catches shape-level asymmetry that
   centroid tests miss.

The **confidence** score combines them as a weighted average:

```
confidence = 0.4 * pair_support + 0.6 * polygon_iou
```

A symmetry type is marked **[DETECTED]** when confidence >= 60%.

#### Why pair support can be below 100%

For `rot_90` with groups of 4 islands, 2 out of every 6 pairs in each group
are diametrically opposite — the centroid test labels those `rot_180`, not
`rot_90`.  This structurally caps pair support at 4/6 = 66.7% even for a
perfectly 90-degree-symmetric map.  The polygon IoU (which measures actual
shape overlap) will still read 100%, so the combined confidence reflects the
true geometry.

#### Consistency indicator

The summary maps confidence to a human-readable label:

| Confidence   | Consistency |
|:------------:|-------------|
| >= 90%       | **HIGH** — geometry is highly symmetric |
| >= 75%       | **MEDIUM** — geometry is mostly symmetric |
| >= 60%       | **LOW** — some symmetry present but imperfect |
| < 60%        | **NONE** — no clear symmetry |

**Example output:**
```
Global Symmetry
----------------------------------------------------------------------
  [DETECTED]  90-degree rotational symmetry
              pair support: 66.7%  polygon IoU: 100.0%  confidence: 86.7%
  [DETECTED]  180-degree rotational symmetry
              pair support: 33.3%  polygon IoU: 100.0%  confidence: 73.3%

  [   ---  ]  Mirror across vertical axis (X = center)
              pair support: 16.7%  polygon IoU: 45.0%  confidence: 33.7%
```

Note that 180-degree rotation is always a consequence of 90-degree rotation,
so both are typically detected together on 4-team maps.

### Intra-Team Symmetry

After determining global symmetry, the detector checks whether each team's
own set of islands is internally symmetric.  The approach differs based on the
global symmetry type:

#### 2-team maps (rot_180 / mirror): Mirror split

Each team's islands are split along the **intra-team axis** — the axis that
runs *through* the team's territory, perpendicular to the axis that separates
the two teams.  For example, if teams are separated by Z=center (`mirror_z`),
the intra-team axis is X=center (`mirror_x`).

All of a team's island polygons (including the spawn island) are clipped into
two halves along this axis.  The negative half is reflected to overlay the
positive half, and IoU is computed.

The split respects the center type:
- **Even dimension** along the split axis (e.g. `2x2_area`): the split falls
  cleanly between two block columns.
- **Odd dimension** (e.g. `single_block`): the center column/row is excluded
  from both halves to keep them equal-sized.

Intra-team symmetry is **[DETECTED]** when IoU >= 60%.

**Example output (2-team map):**
```
Intra-Team Symmetry
----------------------------------------------------------------------
  Team: yellow-team  (3 islands: [1, 5, 6])
    [DETECTED]  mirror_x  (IoU: 100.0%, split axis: X=0.0)
```

#### 4-team maps (rot_90): Canonical coverage

For maps with 90-degree rotational symmetry (typically 4 teams), mirror-split
analysis is not meaningful.  Island shapes on these maps are often abstract and
team territories don't fill neat axis-aligned quadrants.

Instead, the detector validates **canonical coverage**: each team should receive
exactly one island from each canonical group.  Canonical groups are sets of
islands with the same area (and therefore the same D4-canonical shape).  Only
groups whose size equals the number of teams are considered.

Islands are assigned to teams by:
1. Explicit team field (spawn/wool islands already have a team)
2. Proximity — unassigned islands go to the nearest team spawn

Canonical coverage is **[DETECTED]** when every team has exactly 1 island from
every canonical group.

**Example output (4-team map):**
```
Intra-Team Symmetry
----------------------------------------------------------------------
  Team: blue-team  (3 islands: [1, 5, 9])
    [DETECTED]  canonical coverage: 3/3 groups
  Team: red-team  (3 islands: [4, 7, 12])
    [DETECTED]  canonical coverage: 3/3 groups
```

### Summary

The summary section reports:
- **Primary symmetry**: the detected global symmetry type with the highest
  confidence
- **Confidence**: the confidence score of the primary symmetry
- **Consistency**: human-readable quality label (see table above)
- **Intra-team symmetry**: which teams (if any) have internal symmetry

**Example output:**
```
Summary
----------------------------------------------------------------------
  Primary symmetry: 90-degree rotational symmetry
  Confidence:       86.7%
  Consistency:      MEDIUM - geometry is mostly symmetric
  Intra-team symmetry: detected for blue-team, red-team, green-team, yellow-team
```

---

## Glossary

| Term | Definition |
|------|-----------|
| **Bounding box** | `(min_x, max_x, min_z, max_z)` where max values are +1 from the outermost block coordinate (so width = max - min). |
| **Canonical group** | A set of islands that share the same D4-canonical shape (identified by area). Under perfect symmetry, each group has exactly one island per team. |
| **Canonical pair** | Two islands with the same area, tested as candidates for a symmetric relationship. |
| **Center point** | The geometric midpoint of the bounding box, `((min_x + max_x) / 2, (min_z + max_z) / 2)`. All transforms operate around this point. |
| **Confidence** | Weighted combination of pair support (40%) and polygon IoU (60%). Ranges from 0% to 100%. |
| **D4 symmetry group** | The 8 symmetries of a square (4 rotations x 2 mirror states). Used upstream to canonicalize island shapes so that rotated/reflected copies share the same canonical key. |
| **Intra-team axis** | The mirror axis that runs through a team's territory, used to split and compare the two halves. Perpendicular to the axis that separates the teams. |
| **IoU (Intersection over Union)** | `area(A intersect B) / area(A union B)`. Measures how well two shapes overlap. 1.0 = perfect match, 0.0 = no overlap. |
| **Pair support** | Fraction of canonical pairs whose centroids are consistent with a given transform. |
| **Polygon IoU** | IoU computed on the union of all island polygons after applying a transform to the whole set. |
| **Simplified polygon** | A Shapely polygon representing an island's outline, stored in `map_context.json`. |
| **Transform** | A geometric operation (mirror or rotation) applied around the map center point. |
