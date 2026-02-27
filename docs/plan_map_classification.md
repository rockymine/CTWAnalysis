# Map Analysis: Feature Extraction, Comparison, and Classification

## Context

The pipeline currently analyzes each map in isolation and produces `map_context.json`
(island metadata, skeleton stats, symmetry) and `map_graph.json` (skeleton graph topology)
but performs **no cross-map analysis**. There are no feature vectors, no similarity
metrics, no clustering, and no comparison between maps.

The goal of this work is to:
1. Extract a rich structural/topological feature vector from each map's existing output
2. Build a cross-map canonical shape registry (the per-island `canonical_key` is computed
   in memory but never persisted or compared across maps)
3. Compute pairwise map similarity and cluster maps by structural profile
4. Persist a `map_features.json` per map and a corpus-level `corpus_analysis.json`

This classification layer is the necessary precursor to synthesis: to generate a novel
abstract map descriptor (`map_graph.json` + `map_context.json`), we first need to
understand the feature space maps occupy.

**Scale:** Designed for 50–500 maps. Feature vectors are small (~30 floats) so exhaustive
pairwise comparison is fine up to ~500 maps.

---

## Data Available Per Map (no new pipeline runs needed)

| Source | Key fields |
|---|---|
| `map_context.json` | island count, areas, centers, polygons, team assignments, POI assignments, bounding box, symmetry stats |
| `map_graph.json` | skeleton graph nodes (x,z,type,degree) + edges (src,dst) + node_annotations |
| `symmetry.json` | per-symmetry type (mirror_x/z, rot_180/90): confidence, pair_support, detected |
| `layout_bedrock.parquet` | block count per island (backup, not needed since area is in map_context) |

**Not needed:** region files, raw block data.

---

## Feature Vector: `MapFeatures`

All features are derivable from the three JSON files above.

### Layout features (from map_context.json)
- `bounding_box_area` — width × height of the map bounding box
- `bounding_box_aspect_ratio` — width / height
- `map_density` — total_blocks / bounding_box_area
- `island_count`
- `total_blocks`

### Island distribution features (from map_context.json islands[])
- `mean_island_area`, `std_island_area`
- `area_ratio_max_min` — largest island / smallest island (spread)
- `spawn_island_count`, `wool_island_count`, `neutral_island_count`
- `center_island_present` — bool (1/0): any island with has_center=True
- `mean_distance_to_center` — avg Euclidean distance of each island center to the map center

### Skeleton topology features (from map_context.json + map_graph.json)
- `total_nodes`, `total_edges`
- `endpoint_junction_ratio` — endpoints / (junctions + 1) — "tree-like" vs "hub-like"
- `mean_node_degree` — 2 × edges / nodes
- `unique_canonical_shapes` — already in map_context.json
- `shape_reuse_ratio` — fraction of islands whose canonical_key appears in ≥1 other map
  _(0.0 until corpus has ≥2 maps processed)_

### Graph metric features (computed via networkx from map_graph.json)
Each island's skeleton is a small graph. We compute per-island metrics and aggregate:
- `mean_graph_diameter` — mean over islands: longest shortest path (hop count)
- `max_graph_diameter` — maximum island diameter (most complex single island)
- `mean_betweenness_centrality` — mean over all nodes across all islands (chokepoint signal)
- `max_betweenness_centrality` — identifies the single most critical node in the map

### Symmetry features (from symmetry.json)
- `symmetry_mirror_x_confidence`, `symmetry_mirror_z_confidence`
- `symmetry_rot180_confidence`, `symmetry_rot90_confidence`
- `best_symmetry_confidence` — max of the four above
- `best_symmetry_type` — categorical: `mirror_x | mirror_z | rot_180 | rot_90 | none`
- `symmetric_pair_count` — island pairs confirmed as symmetric

### POI/spatial features (from map_context.json poi_assignments)
- `team_count` — number of teams
- `wools_per_team` — wool count / team count
- `mean_spawn_to_wool_distance` — mean Euclidean distance from each team's spawn to
  their own wool locations
- `mean_inter_team_spawn_distance` — mean distance between team spawn points (map scale)

---

## New Modules

### `map_analysis/features.py`
```
MapFeatures dataclass  — all fields above + map_name, source_dir
extract(map_output_dir: Path) -> MapFeatures
  — reads map_context.json, map_graph.json, symmetry.json
  — builds per-island networkx graphs for diameter/betweenness
  — returns populated MapFeatures
to_dict(f: MapFeatures) -> dict
from_dict(d: dict) -> MapFeatures
save(f: MapFeatures, path: Path)   — writes map_features.json
```
Uses: `networkx` (confirm in requirements.txt; add if missing)

### `map_analysis/corpus.py`
```
CanonicalRegistry  — dict[canonical_key, list[(map_name, island_id)]]
  build(map_output_dirs: list[Path]) -> CanonicalRegistry
  jaccard_similarity(map_a, map_b) -> float
  shape_reuse_ratio(map_name) -> float

MapCorpus
  maps: list[MapFeatures]
  registry: CanonicalRegistry
  similarity_matrix: np.ndarray  — pairwise cosine similarity on normalized feature vectors
  clusters: dict[str, int]       — map_name -> cluster_id

  build(output_root: Path) -> MapCorpus
    — discovers all map output dirs (those with map_context.json)
    — loads/extracts MapFeatures for each
    — builds CanonicalRegistry
    — updates shape_reuse_ratio in each MapFeatures
    — computes similarity matrix (cosine, after StandardScaler normalization)
    — runs k-means with k auto-selected by silhouette score over k=2..min(8, n_maps-1)

  save(output_root: Path)  — writes output/corpus_analysis.json
```

### `ctw/commands/analyze.py`  ← new CLI command
```
ctw analyze [--map MAP_NAME] [--all] [--output-root PATH]
  --map MAP_NAME   : extract features for one map, write map_features.json
  --all            : process all maps in output/, then run corpus analysis
```

---

## Output Files

### `output/{map_name}/map_features.json`
```json
{
  "map_name": "tumbleweed",
  "layout": {
    "bounding_box_area": 33075.0,
    "bounding_box_aspect_ratio": 1.23,
    "map_density": 0.065,
    "island_count": 9,
    "total_blocks": 21453
  },
  "islands": {
    "mean_area": 2383.7,
    "std_area": 1204.1,
    "area_ratio_max_min": 4.2,
    "spawn_island_count": 2,
    "wool_island_count": 4,
    "neutral_island_count": 3,
    "center_island_present": false,
    "mean_distance_to_center": 88.4
  },
  "skeleton": {
    "total_nodes": 47,
    "total_edges": 46,
    "endpoint_junction_ratio": 1.35,
    "mean_node_degree": 1.96,
    "unique_canonical_shapes": 3,
    "shape_reuse_ratio": 0.33,
    "mean_graph_diameter": 6.2,
    "max_graph_diameter": 10,
    "mean_betweenness_centrality": 0.12,
    "max_betweenness_centrality": 0.45
  },
  "symmetry": {
    "mirror_x_confidence": 0.92,
    "mirror_z_confidence": 0.11,
    "rot180_confidence": 0.89,
    "rot90_confidence": 0.08,
    "best_symmetry_type": "mirror_x",
    "best_symmetry_confidence": 0.92,
    "symmetric_pair_count": 4
  },
  "poi": {
    "team_count": 2,
    "wools_per_team": 2.0,
    "mean_spawn_to_wool_distance": 143.7,
    "mean_inter_team_spawn_distance": 198.3
  }
}
```

### `output/corpus_analysis.json`
```json
{
  "maps": ["tumbleweed", "annealing_iv", "outback_outback_edition"],
  "similarity_matrix": [[1.0, 0.82, 0.61], [0.82, 1.0, 0.73], [0.61, 0.73, 1.0]],
  "clusters": {
    "tumbleweed": 0,
    "annealing_iv": 0,
    "outback_outback_edition": 1
  },
  "cluster_count": 2,
  "canonical_registry": {
    "<sha256_key_16>": [
      {"map_name": "tumbleweed", "island_id": 3},
      {"map_name": "annealing_iv", "island_id": 5}
    ]
  }
}
```

---

## Prerequisite: Persist `canonical_key` in `map_graph.json`

Currently `canonical_groups` (canonical_key → island_ids) is computed in memory by
`skeleton_analysis/pipeline.py:process_all_islands()` and then discarded.

**Fix:** Add `canonical_key` to each island's entry in `map_graph.json` via
`skeleton_analysis/exporter.py`. The corpus builder then reads it directly from
`map_graph.json` — no re-running of the skeleton pipeline required.

This is a one-line addition to the island serialisation block in the exporter.

---

## Files to Create or Modify

| File | Change |
|---|---|
| `map_analysis/features.py` | **new** — `MapFeatures` dataclass + `extract()` + serialization |
| `map_analysis/corpus.py` | **new** — `CanonicalRegistry` + `MapCorpus` + clustering |
| `ctw/commands/analyze.py` | **new** — CLI command wiring |
| `ctw/cli.py` | **add** — `analyze` subcommand registration |
| `skeleton_analysis/exporter.py` | **add** — `canonical_key` field per island in `map_graph.json` |

---

## Dependencies

- `networkx` — graph diameter and betweenness centrality (confirm/add in `requirements.txt`)
- `scikit-learn` — `StandardScaler`, `KMeans`, `silhouette_score` (confirm/add)

---

## Verification Steps

1. `python ctw.py analyze --map tumbleweed`
   - `output/tumbleweed/map_features.json` is written with all fields populated
   - Graph metrics are non-zero and plausible

2. `python ctw.py analyze --all`
   - `output/corpus_analysis.json` is written
   - `similarity_matrix` is 3×3, symmetric, with 1.0 on diagonal
   - `canonical_registry` captures any cross-map shape reuse

3. `output/tumbleweed/map_graph.json` islands now include `canonical_key` field

4. Existing tests pass: `pytest symmetry_analysis/tests/ xml_analysis/tests/ match_analysis/tests/`
   (only `exporter.py` changes in existing code — one added field)
