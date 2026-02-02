"""
Map connectivity visualization.

Renders an overview of all islands with skeleton graphs, endpoints,
void links, and POI markers.
"""

import math
import os
from pathlib import Path
from typing import Dict, List, Optional

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np


def plot_map_connectivity(
    map_context: dict,
    map_graph: dict,
    output_path: Path,
) -> None:
    """
    Create map-level overview showing all islands and connections.

    Islands are drawn as filled bounding-box rectangles. Skeleton edges
    are shown as thin lines. Endpoints are blue circles. Void links are
    red dashed lines. POIs are marked with stars.

    Args:
        map_context: Full map_context dict.
        map_graph: Map graph dict from build_map_graph().
        output_path: Where to save the PNG.
    """
    output_path = Path(output_path)
    os.makedirs(output_path.parent, exist_ok=True)

    fig, ax = plt.subplots(figsize=(16, 10))
    map_name = map_context.get('map_name', 'Unknown')
    ax.set_title(f"{map_name} — Map Connectivity Graph", fontsize=14, fontweight='bold')

    # Build node lookup
    node_lookup = {}
    for node in map_graph.get('nodes', []):
        node_lookup[node['map_node_id']] = node

    # Draw islands as filled rectangles with skeleton edges
    for island in map_context.get('islands', []):
        iid = island['id']
        bbox = island.get('bounding_box')
        if bbox is None:
            continue
        min_x, max_x, min_z, max_z = bbox

        # Draw island fill
        rect = plt.Rectangle(
            (min_x - 0.5, min_z - 0.5),
            max_x - min_x + 1,
            max_z - min_z + 1,
            facecolor='#d0d0d0',
            edgecolor='#888888',
            linewidth=0.8,
            alpha=0.5,
            zorder=1,
        )
        ax.add_patch(rect)

        # Draw skeleton edges as thin light blue lines
        skeleton = island.get('skeleton')
        if skeleton is None:
            continue

        node_coords = {}
        for node in skeleton['nodes']:
            node_coords[node['node_id']] = (node['x'], node['z'])

        for edge in skeleton['edges']:
            src_c = node_coords.get(edge['src'])
            dst_c = node_coords.get(edge['dst'])
            if src_c and dst_c:
                ax.plot(
                    [src_c[0], dst_c[0]],
                    [src_c[1], dst_c[1]],
                    color='#7ec8e3',
                    linewidth=1.0,
                    alpha=0.6,
                    zorder=2,
                )

    # Draw intra-island edges (thicker, behind void links)
    for edge in map_graph.get('edges', []):
        if edge['edge_type'] != 'intra':
            continue
        src_node = node_lookup.get(edge['src'])
        dst_node = node_lookup.get(edge['dst'])
        if src_node and dst_node:
            ax.plot(
                [src_node['coords'][0], dst_node['coords'][0]],
                [src_node['coords'][1], dst_node['coords'][1]],
                color='#4a90d9',
                linewidth=1.8,
                alpha=0.4,
                zorder=3,
            )

    # Draw void links as red dashed lines (thicker for shorter gaps)
    max_dist = max(
        (e['distance'] for e in map_graph.get('edges', []) if e['edge_type'] == 'void_link'),
        default=1.0,
    )
    for edge in map_graph.get('edges', []):
        if edge['edge_type'] != 'void_link':
            continue
        src_c = edge.get('src_coords', node_lookup.get(edge['src'], {}).get('coords'))
        dst_c = edge.get('dst_coords', node_lookup.get(edge['dst'], {}).get('coords'))
        if src_c is None or dst_c is None:
            continue

        thickness = 1.0 + 2.0 * (1.0 - edge['distance'] / max_dist)
        ax.plot(
            [src_c[0], dst_c[0]],
            [src_c[1], dst_c[1]],
            color='#e63946',
            linestyle='--',
            linewidth=thickness,
            alpha=0.8,
            zorder=5,
        )

        # Distance label at midpoint
        mx = (src_c[0] + dst_c[0]) / 2
        mz = (src_c[1] + dst_c[1]) / 2
        ax.text(
            mx, mz, f"{edge['distance']:.1f}",
            fontsize=7, color='#e63946',
            ha='center', va='bottom',
            fontweight='bold',
            zorder=6,
        )

    # Draw endpoint nodes
    for node in map_graph.get('nodes', []):
        x, z = node['coords']
        ax.scatter(
            x, z,
            s=50,
            c='#1d3557',
            edgecolors='white',
            linewidths=0.8,
            zorder=7,
        )

    # Draw POIs
    poi_assignments = map_context.get('poi_assignments', {})
    for spawn in poi_assignments.get('spawns', []):
        color = '#2ecc71' if spawn.get('team_color') == 'blue' else '#e74c3c'
        ax.scatter(
            spawn['x'], spawn['z'],
            marker='*', s=200,
            c=color,
            edgecolors='black',
            linewidths=0.6,
            zorder=8,
            label=None,
        )

    for wool in poi_assignments.get('wools', []):
        ax.scatter(
            wool['x'], wool['z'],
            marker='*', s=150,
            c='#f1c40f',
            edgecolors='black',
            linewidths=0.6,
            zorder=8,
            label=None,
        )

    # Legend
    legend_handles = [
        mpatches.Patch(facecolor='#d0d0d0', edgecolor='#888888', label='Island'),
        plt.Line2D([0], [0], color='#7ec8e3', linewidth=1.0, label='Skeleton edge'),
        plt.Line2D([0], [0], color='#4a90d9', linewidth=1.8, alpha=0.5, label='Intra-island path'),
        plt.Line2D([0], [0], color='#e63946', linestyle='--', linewidth=2.0, label='Void link'),
        plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='#1d3557',
                    markersize=8, label='Endpoint'),
        plt.Line2D([0], [0], marker='*', color='w', markerfacecolor='#2ecc71',
                    markersize=12, label='Spawn'),
        plt.Line2D([0], [0], marker='*', color='w', markerfacecolor='#f1c40f',
                    markersize=12, label='Wool'),
    ]
    ax.legend(handles=legend_handles, loc='upper right', fontsize=9, framealpha=0.9)

    # Summary text
    n_nodes = len(map_graph.get('nodes', []))
    n_intra = sum(1 for e in map_graph.get('edges', []) if e['edge_type'] == 'intra')
    n_void = sum(1 for e in map_graph.get('edges', []) if e['edge_type'] == 'void_link')
    summary_text = f"Nodes: {n_nodes}  |  Intra edges: {n_intra}  |  Void links: {n_void}"
    ax.text(
        0.02, 0.02, summary_text,
        transform=ax.transAxes,
        fontsize=9, fontfamily='monospace',
        bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8),
        zorder=10,
    )

    ax.set_xlabel('X (blocks)')
    ax.set_ylabel('Z (blocks)')
    ax.set_aspect('equal')
    ax.grid(True, alpha=0.2)

    fig.savefig(str(output_path), dpi=200, bbox_inches='tight')
    plt.close(fig)
    print(f"  Map connectivity plot saved to: {output_path}")
