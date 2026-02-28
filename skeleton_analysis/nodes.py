"""
Node extraction from skeleton pixels.

Computes pixel degree and classifies skeleton pixels as endpoints or junctions.
"""

import numpy as np

from .datatypes import SkeletonPixels, GraphNode


# Neighbor offsets for 8-connectivity (clockwise from top-left)
NEIGHBOR_OFFSETS_8 = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
]

# Neighbor offsets for 4-connectivity
NEIGHBOR_OFFSETS_4 = [
    (-1, 0), (0, -1), (0, 1), (1, 0),
]


def compute_pixel_degrees(
    skeleton: SkeletonPixels,
    connectivity: int = 8
) -> np.ndarray:
    """
    Compute the degree of every skeleton pixel.

    For each True pixel in the skeleton mask, count how many neighbors
    (4 or 8 connectivity) are also True.

    Args:
        skeleton: SkeletonPixels with the skeleton mask
        connectivity: 4 or 8

    Returns:
        degree_map: same shape as skeleton.mask, 0 for non-skeleton pixels
    """
    offsets = NEIGHBOR_OFFSETS_8 if connectivity == 8 else NEIGHBOR_OFFSETS_4
    mask = skeleton.mask
    h, w = mask.shape
    degree_map = np.zeros((h, w), dtype=np.int32)

    for r, c in skeleton.pixel_coords:
        count = 0
        for dr, dc in offsets:
            nr, nc = r + dr, c + dc
            if 0 <= nr < h and 0 <= nc < w and mask[nr, nc]:
                count += 1
        degree_map[r, c] = count

    return degree_map


def extract_nodes(
    skeleton: SkeletonPixels,
    degree_map: np.ndarray
) -> list[GraphNode]:
    """
    Extract graph nodes from skeleton pixels.

    - endpoint: degree == 1
    - junction: degree >= 3

    In minimal mode: every qualifying pixel becomes its own node.
    No blob collapsing, no merging.

    Args:
        skeleton: SkeletonPixels
        degree_map: Degree map from compute_pixel_degrees

    Returns:
        List of GraphNode, sorted by (r, c) for determinism
    """
    nodes = []
    node_id = 0

    # Collect all node pixels, sorted by (r, c) for determinism
    node_pixels = []
    for r, c in skeleton.pixel_coords:
        deg = degree_map[r, c]
        if deg == 1:
            node_pixels.append((r, c, deg, 'endpoint'))
        elif deg >= 3:
            node_pixels.append((r, c, deg, 'junction'))

    # Sort by (r, c) for deterministic ordering
    node_pixels.sort(key=lambda x: (x[0], x[1]))

    for r, c, deg, node_type in node_pixels:
        nodes.append(GraphNode(
            node_id=node_id,
            rc=(r, c),
            degree=deg,
            node_type=node_type
        ))
        node_id += 1

    return nodes
