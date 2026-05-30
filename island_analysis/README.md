# Island Analysis Package

Computes spatial profiles for every canonical island shape found in a CTW map.
Starting from the polygon geometry in `map_context.json` and the skeleton data in
`map_graph.json`, the package extracts a rich feature set, runs a priority-ordered
rule cascade to classify each island into one of twelve shape types, and stores the
results in `island_profiles.json`.

An interactive web review server (`profile_review.py`) allows manual inspection and
correction of classifications; overrides are persisted to
`output/_debug/island_profile_overrides.json` and applied on the next profile run.

Detection and polygon construction live in `island_analysis/detection.py` and
`island_analysis/polygon.py`. Skeletonization and connectivity live in
`skeleton_analysis/`. This package consumes their outputs — it does not re-run them.

---

## Package Structure

```
island_analysis/
├── __init__.py           # Package marker
├── datatypes.py          # IslandBlocks, IslandPolygon, Island dataclasses
├── detection.py          # detect_islands(), find_island_holes()
├── polygon.py            # build_polygons(), triangulate_island_union()
├── canonicalize.py       # canonical_key helpers (thin wrapper over skeleton_analysis)
├── pipeline.py           # High-level orchestration called by layout_analysis
├── profile.py            # Feature extraction, classification, override handling,
│                         #   save/load profiles, cross-map visualizations
├── profile_review.py     # Interactive HTTP review server
├── statistics.py         # Aggregate statistics helpers
├── visualization.py      # Per-map island visualization helpers
└── test_profile_classify.py  # Unit tests for classify_island()
```

---

## Profiling Workflow

### 1. Prerequisites

`island_profiles.json` is written as Stage 8 of the full pipeline:

```bash
python ctw.py run --map tumbleweed
```

To re-run profiling only (from cached JSON, without re-detecting islands):

```bash
python ctw.py islands profile --map tumbleweed --force
python ctw.py islands profile --force   # all maps
```

Overrides from `output/_debug/island_profile_overrides.json` are applied automatically
if the file exists.

### 2. Inspect a map

```bash
python ctw.py islands profile-inspect --map tumbleweed
```

Prints a feature table for every canonical island: both `island_type` (effective,
after any override) and `auto_profile` (algorithm result), along with all numeric
features and skeleton metrics.

### 3. Review and correct classifications

```bash
python ctw.py islands profile-review              # all maps, browser opens
python ctw.py islands profile-review --type shard # shard islands only
python ctw.py islands profile-review --map tumbleweed --port 8080
```

The review page shows one cell per canonical shape. Each cell has an SVG thumbnail,
a copyable canonical key, key metrics, a reclassify dropdown, and a notes textarea.
Changes are saved immediately to `island_profile_overrides.json`.
After reviewing, re-run `ctw islands profile --force` to regenerate profiles with
the updated overrides applied.

### 4. Check canonical groupings

```bash
python ctw.py islands profile-canonical --map tumbleweed
```

Shows which raw island IDs share each canonical shape (same block arrangement under
D4 symmetry).

---

## Feature Extraction

Features are computed by `extract_island_features()` in `profile.py` from the
`simplified_polygon` geometry in `map_context.json` and optional skeleton data
from `map_graph.json`.

### Tier A — Polygon-derived (always available)

| Feature | Formula / Source | Notes |
|---|---|---|
| `aspect_ratio` | `max(w, h) / min(w, h)` | 1.0 = square bbox, higher = elongated |
| `compactness` | `4π·area / perimeter²` | 1.0 = perfect circle |
| `convexity` | `area / convex_hull_area` | 1.0 = fully convex |
| `pca_elongation` | `sqrt(λ₁/λ₂)` from PCA of exterior vertices | 1.0 = isotropic |
| `pca_angle_deg` | Dominant eigenvector angle | Degrees, −180..180 |
| `hole_count` | Interior polygon ring count | 0 for solid, 1 for donut |
| `hole_ratio` | `hole_count / area` | |
| `bbox_fill_ratio` | `area / (bbox_w × bbox_h)` | 1.0 = perfect rectangle |
| `rugosity` | `perimeter / bbox_perimeter` | 1.0 = rectangle, >1.0 = jagged |
| `circle_fit_residual` | Algebraic circle fit RMS/radius | 0 = perfect circle |
| `ellipse_residual` | PCA-normalised radial residual | 0 = perfect ellipse |
| `bbox_cutout_count` | Corner-touching rectangular negative-space regions | None if 0 |
| `bbox_cutout_min_fill` | Min fill ratio among qualifying cutouts | None if 0 |
| `bbox_cutout_coverage` | `corner_area / total_negative_area` | 1.0 = all gap is in corners |

### Tier B — Skeleton-derived (Optional)

Present only when skeleton data is available and reliable. May be `None` for
very small islands, ring-shaped islands (high `hole_ratio` + low `compactness`),
or maps where skeletonization failed.

| Feature | Description |
|---|---|
| `skeleton_endpoint_count` | Leaf nodes (degree 1) |
| `skeleton_junction_count` | Branch nodes (degree ≥ 3) |
| `skeleton_total_length` | Sum of Euclidean edge-pixel path lengths |
| `skeleton_topology` | `'line'` / `'tree'` / `'mesh'` / `'none'` |
| `skeleton_path_bends` | Direction changes in a line-topology path (0=straight, 1=L, 2+=Z) |

---

## Classification Rule Cascade

`classify_island()` applies rules in priority order; the first match wins.
All twelve types are listed in `_ALL_TYPES` and coloured in `_TYPE_COLORS`.

| # | Type | Key Conditions |
|---|---|---|
| 1 | `square` | `bbox_fill ≥ 0.85` AND `ar ≤ 1.3` AND `convexity ≥ 0.85` |
| 2 | `rectangle` | `bbox_fill ≥ 0.85` AND `ar > 1.3` AND `convexity ≥ 0.85` |
| 3 | `donut` | `hole_count == 1` AND `convexity ≥ 0.92` AND `rugosity ≤ 1.1` |
| 4 | `circle` | `convexity ≥ 0.88` AND `hole_count == 0` AND good elliptic fit† |
| 4.5 | `L_shape` | `bbox_cutout_count == 1` AND `bbox_cutout_coverage ≥ 0.70` |
| 4.6 | `Z_shape` | `bbox_cutout_count == 2` AND `bbox_cutout_coverage ≥ 0.70` |
| 5 | `shard` | `topo == 'line'` AND `convexity ≥ 0.87` AND NOT good elliptic fit |
| 6 | `plus` | `topo == 'tree'` AND `junctions == 1` AND `endpoints ≥ 3` |
| 7 | `fork` | `junctions ≥ 2` AND `convexity < 0.70` |
| 8 | `L_shape` | `topo == 'line'` AND `path_bends == 1` (fallback) |
| 9 | `Z_shape` | `topo == 'line'` AND `path_bends ≥ 2` (fallback) |
| 10 | `rugged` | `rugosity ≥ 1.2` |
| 11 | `linear` | `ar ≥ 2.5` |
| 12 | `blob` | default |

† Circle fit: `ar ≤ 1.2 → cfr < 0.12`; `ar > 1.2 → ellipse_residual < 0.10 AND bbox_fill ≥ 0.72`

**Bbox-cutout rules (4.5 / 4.6)** fire before the shard rule, preventing
line-topology L/Z shapes from being intercepted by the shard gate. A corner
cutout qualifies when it touches exactly two adjacent bbox edges, has a per-corner
fill ratio ≥ 0.68, and together all qualifying corners cover ≥ 70 % of the total
negative space — this last condition (coverage) is what distinguishes a genuine
"rectangle with corner removed" from a shard whose tail happens to leave one
empty corner.

---

## Override System

`island_profile_overrides.json` maps `canonical_key → {profile, note}`:

```json
{
  "2871fdd9d634e3fd": {
    "profile": "L_shape",
    "note": "a rectangle with top right corner rectangle cut out"
  },
  "1670cdd9207c492a": {
    "profile": "manual",
    "note": "looks like a key hole of a door. top circle plus bottom rectangle."
  }
}
```

- `profile`: override classification string (any value from `_ALL_TYPES` or `"manual"`)
- `note`: free-text annotation for your reasoning
- Empty `profile` with a non-empty `note` keeps the algorithm result but preserves the note

`IslandProfile` stores both `island_type` (effective) and `auto_profile` (algorithm).
`profile-inspect` shows both and flags overridden shapes.
`profile-review` shows `auto: X` in green for algorithmic results and `→ X` in orange
for overrides.

---

## Output Files

| File | Description |
|---|---|
| `output/<map>/island_profiles.json` | One profile per canonical shape |
| `output/<map>/images/island_profiles.png` | Per-map type+scatter plot (with `--plot`) |
| `output/_debug/island_profile_overrides.json` | Manual classification overrides (shared across all maps) |

### `island_profiles.json` schema

```json
{
  "profiles": [
    {
      "canonical_key": "2871fdd9d634e3fd",
      "island_type": "L_shape",
      "auto_profile": "L_shape",
      "raw_island_ids": [3, 7],
      "features": {
        "canonical_key": "2871fdd9d634e3fd",
        "aspect_ratio": 1.25,
        "bbox_fill_ratio": 0.63,
        "convexity": 0.74,
        "rugosity": 1.18,
        "bbox_cutout_count": 1,
        "bbox_cutout_min_fill": 1.0,
        "bbox_cutout_coverage": 1.0,
        "skeleton_topology": "line",
        "skeleton_path_bends": 1,
        "..."
      },
      "raster_strategy": {
        "grid_size_override": null,
        "alignment_angle_deg": null,
        "anchor_x": null,
        "anchor_z": null
      }
    }
  ]
}
```

---

## Dataclass Hierarchy

Island objects are built up in layers as the pipeline progresses:

| Class | Produced by | Contents |
|---|---|---|
| `IslandBlocks` | `detect_islands()` | `.blocks` (Nx2), `.area`, `.bounding_box` |
| `IslandPolygon` | `+ build_polygons()` | `+ .simplified_polygon`, `.holes` |
| `Island` | `+ assemble_map()` | `+ .has_spawn`, `.has_wool`, `.team`, `.is_observer_island` |

`IslandProfile` (from `profile.py`) is separate — it is computed per *canonical* shape
(one representative per unique geometry), not per raw island instance.

---

## Testing

```bash
python -m unittest island_analysis/test_profile_classify.py -v
```

Tests cover the full classification cascade with known inputs, including shapes that
sit near rule boundaries and cases where skeleton data is absent.
