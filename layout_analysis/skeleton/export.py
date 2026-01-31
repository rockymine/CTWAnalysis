"""
Export skeleton analysis results to CSV files and summary index.

All coordinate exports use world (x, z) coordinates.
"""

import csv
import os
from pathlib import Path
from typing import List, Dict

import numpy as np

from .datatypes import IslandResult


def export_island(result: IslandResult, output_dir: str) -> None:
    """
    Export per-island data files in world coordinates.

    Creates:
      - island_{id}_blocks.csv  (x, z)
      - island_{id}_nodes.csv   (node_id, x, z, type, degree)
      - island_{id}_edges.csv   (edge_id, src, dst)

    Args:
        result: IslandResult for one island
        output_dir: Directory to write files into
    """
    os.makedirs(output_dir, exist_ok=True)
    iid = result.island_id
    transform = result.canonical.transform
    raster = result.raster

    # --- blocks ---
    blocks_path = os.path.join(output_dir, f"island_{iid}_blocks.csv")
    with open(blocks_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['x', 'z'])
        # Use original world blocks
        for x, z in result.canonical.world_blocks:
            writer.writerow([int(round(x)), int(round(z))])

    # --- nodes ---
    nodes_path = os.path.join(output_dir, f"island_{iid}_nodes.csv")
    with open(nodes_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['node_id', 'x', 'z', 'type', 'degree'])
        for node in result.graph.nodes:
            # Convert (r, c) in mask space -> canonical (x, z) -> world (x, z)
            cx, cz = raster.rc_to_canonical(node.rc[0], node.rc[1])
            canonical_pt = np.array([[cx, cz]], dtype=float)
            world_pt = transform.to_original(canonical_pt)[0]
            writer.writerow([
                node.node_id,
                round(world_pt[0], 1),
                round(world_pt[1], 1),
                node.node_type,
                node.degree
            ])

    # --- edges ---
    edges_path = os.path.join(output_dir, f"island_{iid}_edges.csv")
    with open(edges_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['edge_id', 'src', 'dst'])
        for edge in result.graph.edges:
            writer.writerow([edge.edge_id, edge.src, edge.dst])


def export_index(
    results: List[IslandResult],
    canonical_groups: Dict[str, List[int]],
    output_dir: str
) -> None:
    """
    Export summary index.csv.

    Columns:
      island_id, canonical_key, area, num_nodes, num_edges,
      num_endpoints, num_junctions, is_canonical_representative

    Args:
        results: List of IslandResult
        canonical_groups: Dict mapping canonical_key -> list of island_ids
        output_dir: Directory to write index.csv into
    """
    os.makedirs(output_dir, exist_ok=True)

    # Determine canonical representatives (first island_id per group)
    representatives = set()
    for key, ids in canonical_groups.items():
        representatives.add(min(ids))

    index_path = os.path.join(output_dir, "index.csv")
    with open(index_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'island_id', 'canonical_key', 'area',
            'num_nodes', 'num_edges',
            'num_endpoints', 'num_junctions',
            'is_canonical_representative'
        ])
        for result in sorted(results, key=lambda r: r.island_id):
            num_endpoints = sum(1 for n in result.graph.nodes if n.node_type == 'endpoint')
            num_junctions = sum(1 for n in result.graph.nodes if n.node_type == 'junction')
            writer.writerow([
                result.island_id,
                result.canonical.canonical_key,
                len(result.canonical.canonical_points),
                len(result.graph.nodes),
                len(result.graph.edges),
                num_endpoints,
                num_junctions,
                result.island_id in representatives
            ])


def export_all(
    results: List[IslandResult],
    canonical_groups: Dict[str, List[int]],
    output_dir: str
) -> None:
    """
    Export all island data and summary index.

    Args:
        results: List of IslandResult
        canonical_groups: Canonical key -> island_ids mapping
        output_dir: Root output directory
    """
    for result in results:
        export_island(result, output_dir)

    export_index(results, canonical_groups, output_dir)
