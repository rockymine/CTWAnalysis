"""
Path Network Visualization

Visualization functions for displaying movement networks extracted from player paths.
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.collections import LineCollection
from typing import List, Tuple, Dict
import networkx as nx


def plot_density_heatmap(
    ax,
    heatmap: np.ndarray,
    bounds: Tuple[float, float, float, float],
    title: str = "Movement Density Heatmap",
    cmap: str = 'hot'
):
    """
    Plot density heatmap on axes.

    Args:
        ax: Matplotlib axes
        heatmap: 2D density array
        bounds: (min_x, max_x, min_z, max_z)
        title: Plot title
        cmap: Colormap name
    """
    min_x, max_x, min_z, max_z = bounds

    # Plot heatmap
    im = ax.imshow(
        heatmap,
        extent=[min_x, max_x, min_z, max_z],
        origin='lower',
        cmap=cmap,
        alpha=0.7,
        interpolation='bilinear'
    )

    ax.set_xlabel('X Coordinate (blocks)')
    ax.set_ylabel('Z Coordinate (blocks)')
    ax.set_title(title)
    ax.grid(True, alpha=0.3)

    # Add colorbar
    plt.colorbar(im, ax=ax, label='Traffic Density')


def plot_skeleton_network(
    ax,
    skeleton_points: List[Tuple[float, float]],
    map_data=None,
    title: str = "Path Network Skeleton",
    show_map: bool = True
):
    """
    Plot skeleton network on axes.

    Args:
        ax: Matplotlib axes
        skeleton_points: List of (x, z) points forming skeleton
        map_data: Optional map bedrock data for background
        title: Plot title
        show_map: Whether to show map background
    """
    if show_map and map_data is not None:
        # Render map as background
        from match_analysis_DEPRECATED import render_map_tiles
        render_map_tiles(ax, map_data, alpha=0.3)

    if skeleton_points:
        skeleton_array = np.array(skeleton_points)
        ax.scatter(
            skeleton_array[:, 0],
            skeleton_array[:, 1],
            c='red',
            s=2,
            alpha=0.8,
            label='Path Network',
            zorder=3
        )

    ax.set_xlabel('X Coordinate (blocks)')
    ax.set_ylabel('Z Coordinate (blocks)')
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend()
    ax.axis('equal')


def plot_graph_network(
    ax,
    graph: nx.Graph,
    map_data=None,
    title: str = "Waypoint Network Graph",
    show_map: bool = True,
    min_edge_weight: int = 1
):
    """
    Plot graph network with nodes and edges.

    Args:
        ax: Matplotlib axes
        graph: NetworkX graph with waypoints and paths
        map_data: Optional map bedrock data for background
        title: Plot title
        show_map: Whether to show map background
        min_edge_weight: Minimum edge weight to display
    """
    if show_map and map_data is not None:
        from match_analysis_DEPRECATED import render_map_tiles
        render_map_tiles(ax, map_data, alpha=0.3)

    if graph.number_of_nodes() == 0:
        ax.text(0.5, 0.5, 'No waypoints found',
                ha='center', va='center', transform=ax.transAxes)
        ax.set_title(title)
        return

    # Get node positions
    pos = nx.get_node_attributes(graph, 'pos')
    visits = nx.get_node_attributes(graph, 'visits')

    # Draw edges with varying thickness based on traffic
    edge_weights = []
    edge_coords = []
    for u, v, data in graph.edges(data=True):
        weight = data.get('weight', 1)
        if weight >= min_edge_weight:
            edge_weights.append(weight)
            edge_coords.append([pos[u], pos[v]])

    if edge_coords:
        # Normalize weights for line width
        max_weight = max(edge_weights)
        min_weight = min(edge_weights)

        if max_weight > min_weight:
            normalized_weights = [(w - min_weight) / (max_weight - min_weight)
                                 for w in edge_weights]
        else:
            normalized_weights = [1.0] * len(edge_weights)

        # Create line collection with varying widths
        for i, coords in enumerate(edge_coords):
            linewidth = 0.5 + normalized_weights[i] * 4.5  # 0.5 to 5.0
            ax.plot([coords[0][0], coords[1][0]],
                   [coords[0][1], coords[1][1]],
                   color='blue', alpha=0.6, linewidth=linewidth, zorder=2)

    # Draw nodes with size based on visits
    if pos:
        node_positions = np.array(list(pos.values()))
        node_visits = np.array([visits.get(node, 1) for node in pos.keys()])

        # Normalize node sizes
        max_visits = node_visits.max() if len(node_visits) > 0 else 1
        node_sizes = 20 + (node_visits / max_visits) * 180  # 20 to 200

        ax.scatter(
            node_positions[:, 0],
            node_positions[:, 1],
            s=node_sizes,
            c='red',
            alpha=0.8,
            edgecolors='darkred',
            linewidths=1,
            zorder=3,
            label='Waypoints'
        )

    ax.set_xlabel('X Coordinate (blocks)')
    ax.set_ylabel('Z Coordinate (blocks)')
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend()
    ax.axis('equal')


def plot_corridors(
    ax,
    corridors: List[Dict],
    map_data=None,
    title: str = "High-Traffic Corridors",
    show_map: bool = True,
    max_corridors: int = 10
):
    """
    Plot high-traffic corridors.

    Args:
        ax: Matplotlib axes
        corridors: List of corridor dictionaries
        map_data: Optional map bedrock data for background
        title: Plot title
        show_map: Whether to show map background
        max_corridors: Maximum number of corridors to display
    """
    if show_map and map_data is not None:
        from match_analysis_DEPRECATED import render_map_tiles
        render_map_tiles(ax, map_data, alpha=0.3)

    if not corridors:
        ax.text(0.5, 0.5, 'No corridors found',
                ha='center', va='center', transform=ax.transAxes)
        ax.set_title(title)
        return

    # Plot top corridors
    cmap = plt.cm.Reds
    max_density = max(c['avg_density'] for c in corridors[:max_corridors])

    for i, corridor in enumerate(corridors[:max_corridors]):
        points = np.array(corridor['points'])
        density = corridor['avg_density']

        # Color based on density
        color_intensity = density / max_density if max_density > 0 else 1.0
        color = cmap(0.3 + 0.7 * color_intensity)

        ax.scatter(
            points[:, 0],
            points[:, 1],
            c=[color],
            s=10,
            alpha=0.7,
            zorder=3
        )

    # Create legend
    legend_elements = [
        mpatches.Patch(color=cmap(0.3), label='Low Traffic'),
        mpatches.Patch(color=cmap(0.65), label='Medium Traffic'),
        mpatches.Patch(color=cmap(1.0), label='High Traffic')
    ]
    ax.legend(handles=legend_elements, loc='upper right')

    ax.set_xlabel('X Coordinate (blocks)')
    ax.set_ylabel('Z Coordinate (blocks)')
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.axis('equal')


def plot_major_routes(
    ax,
    routes: List[List[Tuple[float, float]]],
    map_data=None,
    title: str = "Major Routes",
    show_map: bool = True
):
    """
    Plot major routes between regions.

    Args:
        ax: Matplotlib axes
        routes: List of routes (each route is a list of points)
        map_data: Optional map bedrock data for background
        title: Plot title
        show_map: Whether to show map background
    """
    if show_map and map_data is not None:
        from match_analysis_DEPRECATED import render_map_tiles
        render_map_tiles(ax, map_data, alpha=0.3)

    if not routes:
        ax.text(0.5, 0.5, 'No routes found',
                ha='center', va='center', transform=ax.transAxes)
        ax.set_title(title)
        return

    # Color palette for different routes
    colors = plt.cm.Set2(np.linspace(0, 1, len(routes)))

    for i, route in enumerate(routes):
        route_array = np.array(route)
        ax.plot(
            route_array[:, 0],
            route_array[:, 1],
            color=colors[i],
            linewidth=2,
            alpha=0.7,
            label=f'Route {i+1}',
            zorder=3
        )

        # Mark start and end
        ax.scatter(route_array[0, 0], route_array[0, 1],
                  color=colors[i], s=100, marker='o',
                  edgecolors='black', linewidths=2, zorder=4)
        ax.scatter(route_array[-1, 0], route_array[-1, 1],
                  color=colors[i], s=100, marker='s',
                  edgecolors='black', linewidths=2, zorder=4)

    ax.set_xlabel('X Coordinate (blocks)')
    ax.set_ylabel('Z Coordinate (blocks)')
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend()
    ax.axis('equal')


def plot_combined_network(
    life_segments,
    map_data=None,
    output_path: str = None,
    resolution: float = 1.0,
    cluster_radius: float = 5.0
):
    """
    Create a comprehensive visualization with multiple network extraction methods.

    Args:
        life_segments: List of LifeSegment objects
        map_data: Optional map bedrock data for background
        output_path: Path to save figure
        resolution: Grid resolution for heatmap
        cluster_radius: Clustering radius for graph extraction
    """
    from match_analysis_DEPRECATED.path_network import (
        create_density_heatmap,
        extract_skeleton_network,
        extract_graph_network,
        extract_corridors
    )

    # Create figure with subplots
    fig = plt.figure(figsize=(20, 15))
    gs = fig.add_gridspec(3, 2, hspace=0.3, wspace=0.3)

    # 1. Density Heatmap
    ax1 = fig.add_subplot(gs[0, 0])
    heatmap, bounds = create_density_heatmap(life_segments, resolution=resolution)
    plot_density_heatmap(ax1, heatmap, bounds, title="1. Movement Density Heatmap")

    # 2. Skeleton Network
    ax2 = fig.add_subplot(gs[0, 1])
    skeleton, skeleton_points = extract_skeleton_network(
        heatmap, bounds, resolution=resolution, sigma=2.0, threshold_percentile=70
    )
    plot_skeleton_network(ax2, skeleton_points, map_data,
                         title="2. Path Network Skeleton (Centerlines)")

    # 3. Graph Network
    ax3 = fig.add_subplot(gs[1, 0])
    graph = extract_graph_network(life_segments, cluster_radius=cluster_radius)
    plot_graph_network(ax3, graph, map_data,
                      title=f"3. Waypoint Network Graph ({graph.number_of_nodes()} waypoints)")

    # 4. High-Traffic Corridors
    ax4 = fig.add_subplot(gs[1, 1])
    corridors = extract_corridors(life_segments, resolution=2.0, min_corridor_density=5.0)
    plot_corridors(ax4, corridors, map_data,
                  title=f"4. High-Traffic Corridors ({len(corridors)} corridors)")

    # 5. Density + Skeleton Overlay
    ax5 = fig.add_subplot(gs[2, 0])
    plot_density_heatmap(ax5, heatmap, bounds, title="5. Density + Skeleton Overlay")
    if skeleton_points:
        skeleton_array = np.array(skeleton_points)
        ax5.scatter(skeleton_array[:, 0], skeleton_array[:, 1],
                   c='cyan', s=1, alpha=0.9, zorder=3, label='Network Skeleton')
    ax5.legend()

    # 6. Graph Network with Traffic Visualization
    ax6 = fig.add_subplot(gs[2, 1])
    plot_graph_network(ax6, graph, map_data,
                      title=f"6. Network Graph - Traffic Weighted",
                      min_edge_weight=1)

    # Overall title
    fig.suptitle('CTW Path Network Analysis - Multiple Extraction Methods',
                 fontsize=16, fontweight='bold')

    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"Path network visualization saved to: {output_path}")
    else:
        plt.show()

    plt.close(fig)


def plot_team_networks(
    life_segments,
    map_data=None,
    output_dir: str = '.',
    resolution: float = 1.0
):
    """
    Create separate network visualizations for each team.

    Args:
        life_segments: List of LifeSegment objects
        map_data: Optional map bedrock data for background
        output_dir: Directory to save figures
        resolution: Grid resolution
    """
    from match_analysis_DEPRECATED.path_network import (
        create_density_heatmap,
        extract_skeleton_network,
        extract_graph_network
    )
    import os

    teams = ['red', 'blue']

    for team in teams:
        # Filter segments by team
        team_segments = [seg for seg in life_segments if seg.team == team]

        if not team_segments:
            continue

        fig, axes = plt.subplots(1, 3, figsize=(18, 6))
        fig.suptitle(f'{team.capitalize()} Team Path Network',
                     fontsize=14, fontweight='bold')

        # Density heatmap
        heatmap, bounds = create_density_heatmap(team_segments, resolution=resolution)
        plot_density_heatmap(axes[0], heatmap, bounds,
                           title=f"{team.capitalize()} - Density")

        # Skeleton
        skeleton, skeleton_points = extract_skeleton_network(
            heatmap, bounds, resolution=resolution, sigma=2.0
        )
        plot_skeleton_network(axes[1], skeleton_points, map_data,
                            title=f"{team.capitalize()} - Skeleton")

        # Graph
        graph = extract_graph_network(team_segments, cluster_radius=5.0)
        plot_graph_network(axes[2], graph, map_data,
                          title=f"{team.capitalize()} - Graph ({graph.number_of_nodes()} nodes)")

        output_path = os.path.join(output_dir, f'path_network_{team}_team.png')
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"Saved {team} team network to: {output_path}")
        plt.close(fig)
