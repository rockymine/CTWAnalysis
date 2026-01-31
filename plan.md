# Plan: Merge Junction Blobs

## Problem
After skeletonization, junction pixels (degree >= 3) often cluster into blobs
of 2-6 adjacent pixels that logically represent a single junction. For example,
Segment Island 1 has 39 junction nodes when it should have ~10 after merging.

## Approach
Add a `merge_junctions` step to the pipeline that runs **after** node + edge
extraction. It will:

1. **Cluster adjacent junctions** using 8-connectivity flood fill on junction
   nodes only. Each connected component of junction pixels becomes one cluster.
2. **Pick a representative pixel** for each cluster — the pixel closest to the
   cluster centroid (ties broken by lexicographic (r,c) order).
3. **Create merged nodes** — one new `GraphNode` per cluster, replacing all the
   individual junction nodes. Endpoints remain untouched.
4. **Remap edges** — any edge whose `src` or `dst` was a junction in a cluster
   gets remapped to the cluster's representative node_id.
5. **Drop intra-cluster edges** — edges where both endpoints map to the same
   merged junction (these were the short 2-pixel edges between adjacent
   junction pixels).
6. **De-duplicate edges** — after remapping, multiple edges may connect the
   same pair of nodes. Keep only the shortest one per (src, dst) pair.
7. **Re-number** nodes and edges with sequential IDs starting from 0.

## Files to modify

### 1. New file: `layout_analysis/skeleton/merge.py`
- `merge_junction_blobs(nodes, edges, connectivity=8) -> (nodes, edges)`
- Internal: `_cluster_junctions(junctions, connectivity)` to find blobs
- Internal: `_pick_representative(cluster_pixels)` for centroid-nearest

### 2. `layout_analysis/skeleton/pipeline.py`
- Import `merge_junction_blobs` from merge
- Insert call between step 6 (edge walking) and step 7 (build graph):
  `nodes, edges = merge_junction_blobs(nodes, edges)`

No other files need changes — the merge produces the same `List[GraphNode]`
and `List[GraphEdge]` types, so visualization/export/report all work as-is.
