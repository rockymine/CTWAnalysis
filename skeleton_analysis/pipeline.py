"""
Pipeline orchestrator: runs all skeleton analysis steps for islands.
"""

import numpy as np
from typing import List, Dict, Tuple, Optional
from collections import defaultdict

from ctw.core.models.skeleton import (
    IslandResult, SkeletonGraph, CanonicalTransform, CanonicalIsland
)
from ctw.core.math.d4 import canonicalize_island, compute_canonical_key
from .rasterize import rasterize_island
from .skeletonize import compute_skeleton
from .nodes import compute_pixel_degrees, extract_nodes
from .edges import extract_edges
from .merge import merge_junction_blobs
from .prune import prune_short_branches


def process_island(
    island_id: int,
    blocks: np.ndarray,
    skeleton_connectivity: int = 8,
    skeleton_method: str = 'thinning',
    padding: int = 1,
    enable_canonicalization: bool = True,
    allow_mirror: bool = True,
    prune_max_length: int = 5,
    prune_min_graph_nodes: int = 5,
) -> IslandResult:
    """
    Full skeleton pipeline for a single island.

    Steps:
      1. Canonicalize (or use identity transform)
      2. Rasterize canonical points to boolean mask
      3. Skeletonize mask
      4. Compute pixel degrees
      5. Extract nodes (endpoints + junctions)
      6. Walk edges deterministically
      7. Merge adjacent junction blobs into single nodes
      8. Prune short endpoint branches
      9. Return IslandResult

    Args:
        island_id: Island identifier
        blocks: Nx2 array of (x, z) world coordinates
        skeleton_connectivity: 4 or 8 for degree/edge computation
        skeleton_method: 'thinning' or 'medial_axis'
        padding: Mask padding (pixels)
        enable_canonicalization: If True, apply D4 canonicalization
        allow_mirror: If True, consider mirror transforms in canonicalization
        prune_max_length: Remove endpoint branches with <= this many pixels
            from a junction (0 = disabled)
        prune_min_graph_nodes: Only prune on graphs with more than this many nodes

    Returns:
        IslandResult with all pipeline outputs
    """
    # Step 1: Canonicalize
    if enable_canonicalization:
        canonical = canonicalize_island(island_id, blocks, allow_mirror=allow_mirror)
    else:
        canonical = _identity_canonical(island_id, blocks)

    # Step 2: Rasterize
    raster = rasterize_island(canonical.canonical_points, padding=padding)

    # Step 3: Skeletonize
    skeleton = compute_skeleton(raster, method=skeleton_method)

    # Step 4: Compute pixel degrees
    degree_map = compute_pixel_degrees(skeleton, connectivity=skeleton_connectivity)

    # Step 5: Extract nodes
    nodes = extract_nodes(skeleton, degree_map)

    # Step 6: Walk edges
    edges = extract_edges(skeleton, degree_map, nodes, connectivity=skeleton_connectivity)

    # Step 7: Merge junction blobs
    nodes, edges = merge_junction_blobs(nodes, edges, connectivity=skeleton_connectivity)

    # Step 8: Prune short endpoint branches
    nodes, edges = prune_short_branches(
        nodes, edges,
        max_length=prune_max_length,
        min_graph_nodes=prune_min_graph_nodes,
    )

    # Step 9: Build graph
    graph = SkeletonGraph(
        nodes=nodes,
        edges=edges,
        skeleton_pixels=skeleton
    )

    return IslandResult(
        island_id=island_id,
        canonical=canonical,
        raster=raster,
        skeleton=skeleton,
        graph=graph
    )


def process_all_islands(
    islands,
    skeleton_connectivity: int = 8,
    skeleton_method: str = 'thinning',
    padding: int = 1,
    enable_canonicalization: bool = True,
    allow_mirror: bool = True,
    min_island_size: int = 10,
    prune_max_length: int = 5,
    prune_min_graph_nodes: int = 5,
) -> Tuple[List[IslandResult], Dict[str, List[int]]]:
    """
    Process all islands through the skeleton pipeline.

    Args:
        islands: List of Island objects (must have .id and .blocks attributes)
        skeleton_connectivity: 4 or 8
        skeleton_method: 'thinning' or 'medial_axis'
        padding: Mask padding
        enable_canonicalization: Enable D4 canonicalization
        allow_mirror: Allow mirror in canonicalization
        min_island_size: Skip islands smaller than this
        prune_max_length: Remove endpoint branches with <= this many pixels
            from a junction (0 = disabled)
        prune_min_graph_nodes: Only prune on graphs with more than this many nodes

    Returns:
        Tuple of:
          - List of IslandResult (one per island)
          - Dict mapping canonical_key -> list of island_ids (for symmetry groups)
    """
    results = []
    canonical_groups: Dict[str, List[int]] = defaultdict(list)

    for island in islands:
        if island.area < min_island_size:
            continue

        result = process_island(
            island_id=island.id,
            blocks=island.blocks,
            skeleton_connectivity=skeleton_connectivity,
            skeleton_method=skeleton_method,
            padding=padding,
            enable_canonicalization=enable_canonicalization,
            allow_mirror=allow_mirror,
            prune_max_length=prune_max_length,
            prune_min_graph_nodes=prune_min_graph_nodes,
        )

        results.append(result)
        canonical_groups[result.canonical.canonical_key].append(island.id)

        # Attach result to island object
        island.skeleton_result = result

    return results, dict(canonical_groups)


def _identity_canonical(island_id: int, blocks: np.ndarray) -> CanonicalIsland:
    """Create a canonical island using identity transform (no rotation/mirror)."""
    pts = blocks.astype(int)
    min_vals = pts.min(axis=0)
    canonical_pts = pts - min_vals

    sorted_pts = canonical_pts[np.lexsort((canonical_pts[:, 1], canonical_pts[:, 0]))]
    key = compute_canonical_key(sorted_pts)

    transform = CanonicalTransform(
        rotation=0,
        mirror=False,
        translation=-min_vals.astype(float),
        world_center=np.zeros(2)
    )

    return CanonicalIsland(
        island_id=island_id,
        canonical_points=canonical_pts,
        canonical_key=key,
        transform=transform,
        world_blocks=blocks.astype(float)
    )
