"""
Skeleton visualization: debug images and overview plots.

Generates:
1. Per-island 4-panel debug images (mask, skeleton, nodes, edges)
2. Unique islands grid (one per canonical_key)
3. World overview (all islands in world orientation)
"""

import os
import math
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.collections import LineCollection
from typing import List, Dict, Optional

from .datatypes import IslandResult


def plot_island_debug(
    result: IslandResult,
    output_path: str
) -> None:
    """
    4-panel debug image for one island.

    Panels:
      Top-left: Boolean mask
      Top-right: Skeleton overlay on mask
      Bottom-left: Nodes on skeleton (green=endpoint, red=junction)
      Bottom-right: Edges with pixel paths (colored)

    Args:
        result: IslandResult for one island
        output_path: Path to save the image
    """
    fig, axes = plt.subplots(2, 2, figsize=(14, 14))
    fig.suptitle(
        f"Island {result.island_id} "
        f"(key: {result.canonical.canonical_key[:8]}...)",
        fontsize=14
    )

    mask = result.raster.mask
    skel_mask = result.skeleton.mask

    # Panel 1: Island mask
    ax = axes[0, 0]
    ax.imshow(mask, cmap='Greys', interpolation='nearest', origin='upper')
    ax.set_title(f"Island mask ({mask.sum()} blocks)")
    ax.set_xlabel("c (x)")
    ax.set_ylabel("r (z)")

    # Panel 2: Skeleton overlay
    ax = axes[0, 1]
    ax.imshow(mask, cmap='Greys', interpolation='nearest', alpha=0.3, origin='upper')
    skel_display = np.zeros((*mask.shape, 4))
    skel_display[skel_mask] = [1, 0, 0, 1]  # Red skeleton
    ax.imshow(skel_display, interpolation='nearest', origin='upper')
    ax.set_title(f"Skeleton ({skel_mask.sum()} pixels)")
    ax.set_xlabel("c (x)")
    ax.set_ylabel("r (z)")

    # Panel 3: Nodes on skeleton
    ax = axes[0 + 1, 0]
    ax.imshow(mask, cmap='Greys', interpolation='nearest', alpha=0.3, origin='upper')
    ax.imshow(skel_display, interpolation='nearest', origin='upper', alpha=0.5)

    endpoints = [(n.rc[1], n.rc[0]) for n in result.graph.nodes if n.node_type == 'endpoint']
    junctions = [(n.rc[1], n.rc[0]) for n in result.graph.nodes if n.node_type == 'junction']

    if endpoints:
        ep_x, ep_y = zip(*endpoints)
        ax.scatter(ep_x, ep_y, c='lime', s=40, zorder=5, edgecolors='black',
                   linewidths=0.5, label=f"Endpoints ({len(endpoints)})")
    if junctions:
        jn_x, jn_y = zip(*junctions)
        ax.scatter(jn_x, jn_y, c='red', s=50, zorder=5, marker='s',
                   edgecolors='black', linewidths=0.5,
                   label=f"Junctions ({len(junctions)})")

    ax.legend(fontsize=8, loc='upper right')
    ax.set_title(f"Nodes ({len(result.graph.nodes)} total)")
    ax.set_xlabel("c (x)")
    ax.set_ylabel("r (z)")

    # Panel 4: Edges
    ax = axes[1, 1]
    ax.imshow(mask, cmap='Greys', interpolation='nearest', alpha=0.3, origin='upper')

    # Color edges distinctly
    cmap = plt.cm.tab20
    for i, edge in enumerate(result.graph.edges):
        path = edge.pixel_path
        color = cmap(i % 20)
        ax.plot(path[:, 1], path[:, 0], color=color, linewidth=1.5, alpha=0.8)

    # Draw nodes on top
    if endpoints:
        ep_x, ep_y = zip(*endpoints)
        ax.scatter(ep_x, ep_y, c='lime', s=30, zorder=5, edgecolors='black', linewidths=0.5)
    if junctions:
        jn_x, jn_y = zip(*junctions)
        ax.scatter(jn_x, jn_y, c='red', s=40, zorder=5, marker='s',
                   edgecolors='black', linewidths=0.5)

    ax.set_title(f"Edges ({len(result.graph.edges)} total)")
    ax.set_xlabel("c (x)")
    ax.set_ylabel("r (z)")

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"Island debug image saved to: {output_path}")


def plot_unique_islands(
    results: List[IslandResult],
    canonical_groups: Dict[str, List[int]],
    output_path: str
) -> None:
    """
    Grid of unique canonical islands (one per canonical_key).

    Shows skeleton graph with nodes and edges for each unique island shape.

    Args:
        results: List of IslandResult
        canonical_groups: canonical_key -> list of island_ids
        output_path: Path to save the image
    """
    # Pick one representative per canonical key
    result_by_id = {r.island_id: r for r in results}
    unique_results = []
    for key, ids in sorted(canonical_groups.items()):
        rep_id = min(ids)
        if rep_id in result_by_id:
            unique_results.append(result_by_id[rep_id])

    if not unique_results:
        return

    n = len(unique_results)
    cols = min(4, n)
    rows = math.ceil(n / cols)

    fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 5 * rows))
    if rows == 1 and cols == 1:
        axes = np.array([[axes]])
    elif rows == 1:
        axes = axes.reshape(1, -1)
    elif cols == 1:
        axes = axes.reshape(-1, 1)

    for idx, result in enumerate(unique_results):
        r, c = divmod(idx, cols)
        ax = axes[r, c]

        mask = result.raster.mask
        ax.imshow(mask, cmap='Greys', interpolation='nearest', alpha=0.3, origin='upper')

        # Draw edges
        for edge in result.graph.edges:
            path = edge.pixel_path
            ax.plot(path[:, 1], path[:, 0], color='steelblue', linewidth=1.5, alpha=0.8)

        # Draw nodes
        for node in result.graph.nodes:
            color = 'lime' if node.node_type == 'endpoint' else 'red'
            marker = 'o' if node.node_type == 'endpoint' else 's'
            ax.scatter(node.rc[1], node.rc[0], c=color, s=30, zorder=5,
                       marker=marker, edgecolors='black', linewidths=0.5)

        key = result.canonical.canonical_key[:8]
        group_ids = canonical_groups.get(result.canonical.canonical_key, [])
        ax.set_title(
            f"Key: {key}...\n"
            f"Islands: {group_ids}\n"
            f"N={len(result.graph.nodes)} E={len(result.graph.edges)}",
            fontsize=9
        )
        ax.set_aspect('equal')

    # Hide unused axes
    for idx in range(n, rows * cols):
        r, c = divmod(idx, cols)
        axes[r, c].set_visible(False)

    fig.suptitle("Unique Islands (by canonical key)", fontsize=14)
    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"Unique islands overview saved to: {output_path}")


def plot_world_overview(
    results: List[IslandResult],
    output_path: str
) -> None:
    """
    Full map with all islands in world orientation.
    Skeleton graphs transformed back to world coordinates.

    Args:
        results: List of IslandResult
        output_path: Path to save the image
    """
    if not results:
        return

    fig, ax = plt.subplots(figsize=(16, 12))

    # Collect all world blocks for background
    all_blocks_x = []
    all_blocks_z = []

    # Generate distinct colors per island
    cmap = plt.cm.Set2
    n_islands = len(results)

    for idx, result in enumerate(results):
        color = cmap(idx % 8)
        transform = result.canonical.transform
        raster = result.raster

        # Draw island blocks in world coords
        world_blocks = result.canonical.world_blocks
        ax.scatter(
            world_blocks[:, 0], world_blocks[:, 1],
            c=[color], s=1, alpha=0.2, rasterized=True
        )
        all_blocks_x.extend(world_blocks[:, 0])
        all_blocks_z.extend(world_blocks[:, 1])

        # Transform skeleton edges to world coords and draw
        for edge in result.graph.edges:
            # Convert pixel path (r,c) -> canonical (x,z) -> world (x,z)
            path_canonical = np.array([
                raster.rc_to_canonical(r, c) for r, c in edge.pixel_path
            ], dtype=float)
            path_world = transform.to_original(path_canonical)
            ax.plot(path_world[:, 0], path_world[:, 1],
                    color=color, linewidth=1.5, alpha=0.8)

        # Transform nodes to world coords and draw
        for node in result.graph.nodes:
            cx, cz = raster.rc_to_canonical(node.rc[0], node.rc[1])
            world_pt = transform.to_original(np.array([[cx, cz]], dtype=float))[0]
            marker_color = 'lime' if node.node_type == 'endpoint' else 'red'
            marker = 'o' if node.node_type == 'endpoint' else 's'
            ax.scatter(world_pt[0], world_pt[1], c=marker_color, s=20,
                       zorder=5, marker=marker, edgecolors='black', linewidths=0.3)

    ax.set_aspect('equal')
    ax.set_xlabel("X (world)")
    ax.set_ylabel("Z (world)")
    ax.set_title(f"World Overview - {n_islands} islands")
    ax.invert_yaxis()

    # Legend
    legend_elements = [
        mpatches.Patch(color='lime', label='Endpoints'),
        mpatches.Patch(color='red', label='Junctions'),
    ]
    ax.legend(handles=legend_elements, loc='upper right', fontsize=9)

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"World overview saved to: {output_path}")


def generate_skeleton_report(
    results: List[IslandResult],
    canonical_groups: Dict[str, List[int]],
    output_path: str,
    map_name: str = "Unknown"
) -> None:
    """
    Generate a text report summarizing skeleton analysis results.

    Args:
        results: List of IslandResult
        canonical_groups: canonical_key -> island_ids mapping
        output_path: Path to save the report
        map_name: Name of the map
    """
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    with open(output_path, 'w') as f:
        f.write("=" * 70 + "\n")
        f.write(f"SKELETON ANALYSIS REPORT - {map_name}\n")
        f.write("=" * 70 + "\n\n")

        # Canonical groups summary
        f.write("CANONICAL GROUPS (symmetric islands)\n")
        f.write("-" * 70 + "\n")
        for key, ids in sorted(canonical_groups.items()):
            f.write(f"  Key {key[:12]}...: Islands {ids}")
            if len(ids) > 1:
                f.write(" (symmetric)")
            f.write("\n")
        f.write("\n")

        # Per-island details
        f.write("ISLAND DETAILS\n")
        f.write("-" * 70 + "\n\n")

        for result in sorted(results, key=lambda r: r.island_id):
            num_ep = sum(1 for n in result.graph.nodes if n.node_type == 'endpoint')
            num_jn = sum(1 for n in result.graph.nodes if n.node_type == 'junction')

            f.write(f"Island {result.island_id}:\n")
            f.write(f"  Canonical key: {result.canonical.canonical_key[:12]}...\n")
            f.write(f"  Transform: rot={result.canonical.transform.rotation}, "
                    f"mirror={result.canonical.transform.mirror}\n")
            f.write(f"  Area: {len(result.canonical.canonical_points):,} blocks\n")
            f.write(f"  Skeleton pixels: {result.skeleton.mask.sum():,}\n")
            f.write(f"  Nodes: {len(result.graph.nodes)} "
                    f"({num_ep} endpoints, {num_jn} junctions)\n")
            f.write(f"  Edges: {len(result.graph.edges)}\n")

            # Node details
            f.write(f"  Node locations (mask r,c):\n")
            for node in result.graph.nodes:
                prefix = "E" if node.node_type == 'endpoint' else "J"
                f.write(f"    {prefix}{node.node_id}: ({node.rc[0]}, {node.rc[1]}) "
                        f"deg={node.degree}\n")

            # Edge connections
            f.write(f"  Edge connections:\n")
            node_label = {}
            ep_count = jn_count = 0
            for node in result.graph.nodes:
                if node.node_type == 'endpoint':
                    ep_count += 1
                    node_label[node.node_id] = f"E{ep_count}"
                else:
                    jn_count += 1
                    node_label[node.node_id] = f"J{jn_count}"
            for edge in result.graph.edges:
                src_label = node_label.get(edge.src, f"?{edge.src}")
                dst_label = node_label.get(edge.dst, f"?{edge.dst}")
                f.write(f"    {src_label} <-> {dst_label} "
                        f"({len(edge.pixel_path)} pixels)\n")

            f.write("\n")

        # Summary
        f.write("-" * 70 + "\n")
        f.write("SUMMARY\n")
        f.write("-" * 70 + "\n")
        f.write(f"Total islands: {len(results)}\n")
        f.write(f"Unique canonical shapes: {len(canonical_groups)}\n")
        total_nodes = sum(len(r.graph.nodes) for r in results)
        total_edges = sum(len(r.graph.edges) for r in results)
        total_ep = sum(sum(1 for n in r.graph.nodes if n.node_type == 'endpoint') for r in results)
        total_jn = sum(sum(1 for n in r.graph.nodes if n.node_type == 'junction') for r in results)
        f.write(f"Total nodes: {total_nodes} ({total_ep} endpoints, {total_jn} junctions)\n")
        f.write(f"Total edges: {total_edges}\n")
        f.write("=" * 70 + "\n")

    print(f"Skeleton report saved to: {output_path}")


# Minecraft color name -> matplotlib color mapping
_MC_COLORS = {
    'dark red': '#AA0000', 'red': '#FF5555',
    'dark blue': '#0000AA', 'blue': '#5555FF',
    'dark green': '#00AA00', 'green': '#55FF55',
    'dark aqua': '#00AAAA', 'aqua': '#55FFFF',
    'gold': '#FFAA00', 'yellow': '#FFFF55',
    'dark purple': '#AA00AA', 'light purple': '#FF55FF',
    'white': '#FFFFFF', 'gray': '#AAAAAA',
    'dark gray': '#555555', 'black': '#000000',
    'pink': '#FF69B4', 'magenta': '#FF00FF',
    'lime': '#00FF00', 'orange': '#FFA500',
}


def _mc_color(color_name: str, fallback: str = 'gray') -> str:
    """Convert a Minecraft color name to a matplotlib color string."""
    if not color_name:
        return fallback
    return _MC_COLORS.get(color_name.lower(), fallback)


def plot_island_poi_debug(
    result: IslandResult,
    output_path: str,
) -> None:
    """
    Single-panel debug image showing POI-annotated skeleton nodes.

    - Island mask background (gray)
    - Skeleton edges (muted)
    - Spawn nodes: star marker with team color
    - Wool nodes: diamond marker, gold/orange
    - Regular endpoints: lime circles, junctions: red squares
    - All nodes labeled with ID text

    Args:
        result: IslandResult for one island
        output_path: Path to save the image
    """
    fig, ax = plt.subplots(figsize=(12, 12))

    mask = result.raster.mask
    skel_mask = result.skeleton.mask

    # Background mask
    ax.imshow(mask, cmap='Greys', interpolation='nearest', alpha=0.3, origin='upper')

    # Skeleton overlay (muted gray)
    skel_display = np.zeros((*mask.shape, 4))
    skel_display[skel_mask] = [0.5, 0.5, 0.5, 0.5]
    ax.imshow(skel_display, interpolation='nearest', origin='upper')

    # Draw edges
    for edge in result.graph.edges:
        path = edge.pixel_path
        ax.plot(path[:, 1], path[:, 0], color='steelblue', linewidth=1.5, alpha=0.6)

    # Draw nodes with POI classification
    poi_spawn_nodes = []
    poi_wool_nodes = []

    for node in result.graph.nodes:
        c, r = node.rc[1], node.rc[0]

        if node.poi_type == 'spawn':
            color = _mc_color(node.poi_color, 'cyan')
            ax.scatter([c], [r], c=color, s=200, zorder=6, marker='*',
                       edgecolors='black', linewidths=1.0)
            bg_color = color
            poi_spawn_nodes.append(node)
        elif node.poi_type == 'wool':
            color = _mc_color(node.poi_color, 'gold')
            ax.scatter([c], [r], c=color, s=150, zorder=6, marker='D',
                       edgecolors='black', linewidths=1.0)
            bg_color = color
            poi_wool_nodes.append(node)
        elif node.node_type == 'endpoint':
            ax.scatter([c], [r], c='lime', s=60, zorder=5, marker='o',
                       edgecolors='black', linewidths=0.5)
            bg_color = '#2d6a2d'
        else:
            ax.scatter([c], [r], c='red', s=70, zorder=5, marker='s',
                       edgecolors='black', linewidths=0.5)
            bg_color = '#8b0000'

        # Node ID label
        label = str(node.node_id)
        if node.poi_type:
            label = f"{node.node_id} ({node.poi_type})"

        ax.text(c + 1.5, r - 1.5, label, fontsize=7, ha='left', va='bottom',
                color='white', fontweight='bold', zorder=7,
                bbox=dict(boxstyle='round,pad=0.15',
                          facecolor=bg_color if bg_color.startswith('#') else 'gray',
                          alpha=0.85, edgecolor='none'))

    # Legend
    legend_handles = [
        mpatches.Patch(color='lime', label='Endpoints'),
        mpatches.Patch(color='red', label='Junctions'),
    ]
    if poi_spawn_nodes:
        legend_handles.append(mpatches.Patch(color='cyan', label='Spawn (star)'))
    if poi_wool_nodes:
        legend_handles.append(mpatches.Patch(color='gold', label='Wool (diamond)'))

    ax.legend(handles=legend_handles, fontsize=9, loc='upper right')

    n_poi = len(poi_spawn_nodes) + len(poi_wool_nodes)
    ax.set_title(
        f"Island {result.island_id} POI Skeleton "
        f"({len(result.graph.nodes)} nodes, {n_poi} POIs)",
        fontsize=13
    )
    ax.set_xlabel("c (x)")
    ax.set_ylabel("r (z)")

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"POI debug image saved to: {output_path}")


def plot_path_grid(
    island_result: dict,
    edge_pixels: dict,
    output_path: str,
    max_panels: int = 15,
) -> None:
    """
    Grid visualization of pathfinding results for one island.

    Each panel shows one path in world (x, z) coordinate space with
    colored segments between nodes. Defender paths are shown first,
    then POI->endpoint paths.

    Args:
        island_result: Single island dict from pathfinding analysis.
        edge_pixels: Dict from load_edge_pixels() for this island.
        output_path: Path to save the image.
        max_panels: Maximum number of path panels to draw.
    """
    if edge_pixels is None:
        print(f"  WARNING: No edge pixel data for island {island_result['island_id']}")
        return

    # Collect paths to plot: defender paths first, then POI->endpoint
    paths_to_plot = []

    for dp in (island_result.get('defender_paths') or []):
        paths_to_plot.append({
            'title': f"{dp['spawn_team']} spawn -> {dp['wool_color']} wool",
            'category': 'defender',
            'path_nodes': dp['path_nodes'],
            'distance': dp['distance'],
        })

    for pp in island_result.get('poi_to_endpoint_paths', []):
        paths_to_plot.append({
            'title': f"{pp['poi_id']} {pp['poi_type']} -> ep{pp['endpoint_node']}",
            'category': pp['poi_type'],
            'path_nodes': pp['path_nodes'],
            'distance': pp['distance'],
        })

    if not paths_to_plot:
        return

    paths_to_plot = paths_to_plot[:max_panels]
    n = len(paths_to_plot)
    cols = min(4, n)
    rows = math.ceil(n / cols)

    fig, axes = plt.subplots(rows, cols, figsize=(4.5 * cols, 4 * rows))
    if rows == 1 and cols == 1:
        axes = np.array([[axes]])
    elif rows == 1:
        axes = axes.reshape(1, -1)
    elif cols == 1:
        axes = axes.reshape(-1, 1)

    iid = island_result['island_id']
    team = island_result.get('team') or 'neutral'

    # Color scheme per category
    category_cmap = {
        'defender': 'Reds',
        'spawn': 'Blues',
        'wool': 'Oranges',
    }

    for idx, path_info in enumerate(paths_to_plot):
        r, c = divmod(idx, cols)
        ax = axes[r, c]

        path_nodes = path_info['path_nodes']
        cmap_name = category_cmap.get(path_info['category'], 'Greys')
        cmap = plt.cm.get_cmap(cmap_name)

        from .pathfinding import get_edge_detail

        # Draw each edge segment with incrementing color
        n_segments = max(len(path_nodes) - 1, 1)
        for i in range(len(path_nodes) - 1):
            src_n, dst_n = path_nodes[i], path_nodes[i + 1]
            segment = get_edge_detail(edge_pixels, src_n, dst_n)
            if segment is None:
                continue
            xs = [p[0] for p in segment]
            zs = [p[1] for p in segment]
            # Color from 0.3 to 0.9 across segments
            color = cmap(0.3 + 0.6 * i / n_segments)
            ax.plot(xs, zs, color=color, linewidth=2.0, solid_capstyle='round')

        # Mark nodes along the path
        if len(path_nodes) < 2:
            continue
        for i, nid in enumerate(path_nodes):
            # Get coords from the pixel data edges
            # First node: start of first edge, last node: end of last edge
            if i == 0:
                seg = get_edge_detail(edge_pixels, path_nodes[0], path_nodes[1])
                if seg:
                    nx_, nz_ = seg[0]
                else:
                    continue
            elif i == len(path_nodes) - 1:
                seg = get_edge_detail(edge_pixels, path_nodes[-2], path_nodes[-1])
                if seg:
                    nx_, nz_ = seg[-1]
                else:
                    continue
            else:
                # Junction: end of previous segment
                seg = get_edge_detail(edge_pixels, path_nodes[i - 1], path_nodes[i])
                if seg:
                    nx_, nz_ = seg[-1]
                else:
                    continue

            if i == 0 or i == len(path_nodes) - 1:
                marker = '*' if i == 0 else 'D'
                ax.scatter([nx_], [nz_], c='black', s=60, zorder=5,
                           marker=marker, edgecolors='white', linewidths=0.5)
            else:
                ax.scatter([nx_], [nz_], c='gray', s=25, zorder=5,
                           marker='s', edgecolors='black', linewidths=0.3)

            ax.annotate(str(nid), (nx_, nz_), fontsize=6,
                        textcoords='offset points', xytext=(3, 3),
                        color='black', fontweight='bold')

        ax.set_aspect('equal')
        ax.invert_yaxis()
        ax.set_title(f"{path_info['title']}\n{path_info['distance']} blocks",
                     fontsize=8)
        ax.tick_params(labelsize=6)

    # Hide unused axes
    for idx in range(n, rows * cols):
        r, c = divmod(idx, cols)
        axes[r, c].set_visible(False)

    fig.suptitle(f"Island {iid} ({team}) - Paths", fontsize=13)
    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"Path grid saved to: {output_path}")
