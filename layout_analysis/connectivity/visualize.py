"""
Map connectivity visualization.

Renders an overview of all islands with polygon boundaries, skeleton
pixel paths, endpoints, void links, and POI markers.
"""

import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from visualization import (
    draw_build_region,
    draw_island_outlines,
    draw_pois,
    map_base_legend_handles,
)


def plot_map_connectivity(
    map_context: dict,
    map_graph_data: dict,
    output_path: Path,
) -> None:
    """
    Create map-level overview showing all islands and connections.

    Layers (back to front):
      1. Island polygon boundaries (from map_context simplified_polygon)
      2. Skeleton edges with pixel-path detail (from map_graph_data)
      3. Skeleton nodes and POIs
      4. Void links (dashed red with distance labels)
      5. Map-level endpoint nodes (small orange dots)

    Args:
        map_context: Full map_context dict (island geometry, POIs).
        map_graph_data: Full map_graph.json dict (skeleton, connectivity).
        output_path: Where to save the PNG.
    """
    output_path = Path(output_path)
    os.makedirs(output_path.parent, exist_ok=True)

    fig, ax = plt.subplots(figsize=(16, 10))
    map_name = map_context.get('map_name', 'Unknown')
    ax.set_title(f"{map_name} — Map Connectivity Graph", fontsize=14, fontweight='bold')

    # Build lookups
    graph_islands_by_id = {
        ie['island_id']: ie for ie in map_graph_data.get('islands', [])
    }

    graph_section = map_graph_data.get('map_graph', {})
    node_lookup = {}
    for node in graph_section.get('nodes', []):
        node_lookup[node['map_node_id']] = node

    # ── Layers 0–1: Build region + island outlines (shared) ──────────
    has_build = draw_build_region(ax, map_context)
    draw_island_outlines(ax, map_context)

    # ── Layer 2: Skeleton edges with pixel detail ───────────────────
    for island in map_context.get('islands', []):
        iid = island['id']
        graph_island = graph_islands_by_id.get(iid, {})
        skeleton = graph_island.get('skeleton')
        if skeleton is None:
            continue

        edge_pixels = skeleton.get('edge_pixels', {})
        for edge_key, ep_data in edge_pixels.items():
            pixels = ep_data.get('pixels', [])
            if len(pixels) < 2:
                continue
            px = np.array(pixels)
            ax.plot(
                px[:, 0], px[:, 1],
                color='lightblue',
                linewidth=1,
                alpha=0.8,
                zorder=2,
            )

    # ── Layer 3: Skeleton nodes ──────────────────────────────────────
    for island in map_context.get('islands', []):
        iid = island['id']
        graph_island = graph_islands_by_id.get(iid, {})
        skeleton = graph_island.get('skeleton')
        if skeleton is None:
            continue

        for node in skeleton['nodes']:
            if node['type'] == 'endpoint':
                ax.scatter(
                    node['x'], node['z'],
                    s=30,
                    c='#1d3557',
                    edgecolors='white',
                    linewidths=0.6,
                    zorder=7,
                )
            else:
                ax.scatter(
                    node['x'], node['z'],
                    s=12,
                    c='#555555',
                    alpha=0.5,
                    zorder=3,
                )

    # ── Layer 3 continued: POIs (shared) ─────────────────────────────
    draw_pois(ax, map_context)

    # ── Layer 4: Void links ─────────────────────────────────────────
    void_edges = [e for e in graph_section.get('edges', []) if e['edge_type'] == 'void_link']
    max_dist = max((e['distance'] for e in void_edges), default=1.0)
    for edge in void_edges:
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

    # ── Layer 5: Map-level endpoint nodes ───────────────────────────
    for node in graph_section.get('nodes', []):
        x, z = node['coords']
        ax.scatter(
            x, z,
            s=20,
            c='orange',
            edgecolors='black',
            linewidths=0.4,
            zorder=9,
        )

    # ── Legend ───────────────────────────────────────────────────────
    legend_handles = map_base_legend_handles(has_build_region=has_build)
    legend_handles += [
        plt.Line2D([0], [0], color='lightblue', linewidth=1, label='Skeleton path'),
        plt.Line2D([0], [0], color='#e63946', linestyle='--', linewidth=2.0, label='Void link'),
        plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='#1d3557',
                    markersize=6, label='Endpoint'),
        plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='orange',
                    markeredgecolor='black', markersize=5, label='Map node'),
    ]
    ax.legend(handles=legend_handles, loc='upper right', fontsize=9, framealpha=0.9)

    # ── Summary text ────────────────────────────────────────────────
    n_nodes = len(graph_section.get('nodes', []))
    n_intra = sum(1 for e in graph_section.get('edges', []) if e['edge_type'] == 'intra')
    n_void = len(void_edges)
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
