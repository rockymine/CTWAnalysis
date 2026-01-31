"""
Island Visualization

Visualization functions for displaying detected islands and their triangulations.
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Polygon
from matplotlib.collections import PatchCollection, PolyCollection
from typing import List, Dict, Tuple, Optional
import colorsys


def generate_distinct_colors(n: int) -> List[Tuple[float, float, float]]:
    """Generate n visually distinct colors."""
    colors = []
    for i in range(n):
        hue = i / n
        saturation = 0.7 + (i % 3) * 0.1
        lightness = 0.5
        rgb = colorsys.hls_to_rgb(hue, lightness, saturation)
        colors.append(rgb)
    return colors


def plot_islands(
    islands: List,
    ax=None,
    title: str = "Detected Islands",
    show_blocks: bool = False,
    show_hulls: bool = True,
    show_triangles: bool = False,
    show_labels: bool = True,
    show_centers: bool = True,
    alpha: float = 0.5,
    figsize: Tuple[int, int] = (14, 10)
):
    """
    Plot detected islands with various visualization options.

    Args:
        islands: List of Island objects
        ax: Optional matplotlib axes
        title: Plot title
        show_blocks: Show individual block positions
        show_hulls: Show convex hulls
        show_triangles: Show triangulation
        show_labels: Show island IDs
        show_centers: Show island centers
        alpha: Transparency level
        figsize: Figure size if creating new figure
    """
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.figure

    colors = generate_distinct_colors(len(islands))

    for i, island in enumerate(islands):
        color = colors[i]

        # Plot blocks as scatter
        if show_blocks:
            ax.scatter(
                island.blocks[:, 0],
                island.blocks[:, 1],
                c=[color],
                s=3,
                alpha=alpha * 0.5,
                label=f'Island {island.id}' if i < 10 else None
            )

        # Plot convex hull
        if show_hulls and island.hull_vertices is not None:
            hull = np.vstack([island.hull_vertices, island.hull_vertices[0]])
            ax.fill(hull[:, 0], hull[:, 1], color=color, alpha=alpha, edgecolor='black', linewidth=1)

        # Plot triangles
        if show_triangles and island.triangles:
            for tri in island.triangles:
                triangle = Polygon(tri, closed=True, fill=True,
                                  facecolor=color, edgecolor='darkgray',
                                  alpha=alpha * 0.8, linewidth=0.5)
                ax.add_patch(triangle)

        # Plot center
        if show_centers:
            ax.scatter(*island.center, c='black', s=50, marker='x', zorder=5)

        # Add label
        if show_labels:
            ax.annotate(
                f'{island.id}',
                island.center,
                fontsize=12,
                fontweight='bold',
                ha='center',
                va='center',
                color='white',
                bbox=dict(boxstyle='circle', facecolor=color, edgecolor='black')
            )

    ax.set_xlabel('X Coordinate (blocks)')
    ax.set_ylabel('Z Coordinate (blocks)')
    ax.set_title(title)
    ax.axis('equal')
    ax.grid(True, alpha=0.3)

    return fig, ax


def plot_island_triangulation(
    islands: List,
    ax=None,
    title: str = "Island Triangulation",
    show_blocks: bool = True,
    show_holes: bool = True,
    alpha: float = 0.6,
    figsize: Tuple[int, int] = (14, 10)
):
    """
    Plot island triangulation with optional hole visualization.

    Args:
        islands: List of Island objects with triangles
        ax: Optional matplotlib axes
        title: Plot title
        show_blocks: Show original block positions
        show_holes: Show detected internal holes
        alpha: Transparency level
        figsize: Figure size
    """
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.figure

    colors = generate_distinct_colors(len(islands))

    for i, island in enumerate(islands):
        color = colors[i]

        # Plot blocks as light background
        if show_blocks:
            ax.scatter(
                island.blocks[:, 0],
                island.blocks[:, 1],
                c=[(*color, 0.2)],
                s=1,
                alpha=0.3
            )

        # Plot triangles
        if island.triangles:
            for tri in island.triangles:
                triangle = Polygon(
                    tri, closed=True, fill=True,
                    facecolor=color, edgecolor='black',
                    alpha=alpha, linewidth=0.3
                )
                ax.add_patch(triangle)

        # Plot holes
        if show_holes and island.holes:
            for hole in island.holes:
                hole_closed = np.vstack([hole, hole[0]])
                ax.fill(hole_closed[:, 0], hole_closed[:, 1],
                       color='white', edgecolor='red',
                       linewidth=2, alpha=0.8)

        # Label
        ax.annotate(
            f'{island.id}\n({len(island.triangles)} tri)',
            island.center,
            fontsize=9,
            ha='center',
            va='center',
            color='white',
            fontweight='bold',
            bbox=dict(boxstyle='round', facecolor=color, edgecolor='black', alpha=0.8)
        )

    ax.set_xlabel('X Coordinate (blocks)')
    ax.set_ylabel('Z Coordinate (blocks)')
    ax.set_title(title)
    ax.axis('equal')
    ax.grid(True, alpha=0.3)

    return fig, ax


def plot_island_comparison(
    islands: List,
    output_path: str = None,
    figsize: Tuple[int, int] = (20, 15)
):
    """
    Create a comprehensive comparison plot showing different island visualizations.

    Args:
        islands: List of Island objects
        output_path: Optional path to save figure
        figsize: Figure size
    """
    fig = plt.figure(figsize=figsize)
    gs = fig.add_gridspec(2, 2, hspace=0.3, wspace=0.25)

    # 1. Raw blocks
    ax1 = fig.add_subplot(gs[0, 0])
    plot_islands(islands, ax=ax1, title="1. Detected Islands (Blocks)",
                show_blocks=True, show_hulls=False, show_triangles=False,
                show_labels=True, alpha=0.7)

    # 2. Convex hulls
    ax2 = fig.add_subplot(gs[0, 1])
    plot_islands(islands, ax=ax2, title="2. Convex Hulls",
                show_blocks=False, show_hulls=True, show_triangles=False,
                show_labels=True, alpha=0.5)

    # 3. Triangulation
    ax3 = fig.add_subplot(gs[1, 0])
    plot_island_triangulation(islands, ax=ax3,
                             title="3. Triangle Mesh Reconstruction",
                             show_blocks=False, show_holes=True, alpha=0.6)

    # 4. Combined view
    ax4 = fig.add_subplot(gs[1, 1])
    colors = generate_distinct_colors(len(islands))

    for i, island in enumerate(islands):
        color = colors[i]

        # Light hull background
        if island.hull_vertices is not None:
            hull = np.vstack([island.hull_vertices, island.hull_vertices[0]])
            ax4.fill(hull[:, 0], hull[:, 1], color=color, alpha=0.2)
            ax4.plot(hull[:, 0], hull[:, 1], color='black', linewidth=1, alpha=0.5)

        # Triangle edges
        if island.triangles:
            for tri in island.triangles:
                tri_closed = np.vstack([tri, tri[0]])
                ax4.plot(tri_closed[:, 0], tri_closed[:, 1],
                        color=color, linewidth=0.5, alpha=0.8)

        # Center and label
        ax4.scatter(*island.center, c='red', s=80, marker='*', zorder=5, edgecolors='black')
        ax4.annotate(f'{island.id}', island.center, fontsize=10, fontweight='bold',
                    ha='center', va='bottom', xytext=(0, 5), textcoords='offset points')

    ax4.set_xlabel('X Coordinate (blocks)')
    ax4.set_ylabel('Z Coordinate (blocks)')
    ax4.set_title("4. Combined View (Hulls + Triangle Edges + Centers)")
    ax4.axis('equal')
    ax4.grid(True, alpha=0.3)

    fig.suptitle('Island Detection and Triangulation Analysis', fontsize=16, fontweight='bold')

    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"Island comparison saved to: {output_path}")
    else:
        plt.show()

    plt.close(fig)
    return fig


def plot_island_statistics(
    islands: List,
    stats: Dict,
    output_path: str = None,
    figsize: Tuple[int, int] = (16, 10)
):
    """
    Create statistical overview of detected islands.

    Args:
        islands: List of Island objects
        stats: Statistics dictionary from compute_island_statistics
        output_path: Optional path to save figure
        figsize: Figure size
    """
    fig = plt.figure(figsize=figsize)
    gs = fig.add_gridspec(2, 3, hspace=0.3, wspace=0.3)

    colors = generate_distinct_colors(len(islands))

    # 1. Island sizes (bar chart)
    ax1 = fig.add_subplot(gs[0, 0])
    sizes = [i.area for i in islands]
    bars = ax1.bar(range(1, len(islands) + 1), sizes, color=colors)
    ax1.set_xlabel('Island ID')
    ax1.set_ylabel('Area (blocks)')
    ax1.set_title('Island Sizes')
    ax1.set_xticks(range(1, len(islands) + 1))

    # 2. Distance from center (bar chart)
    ax2 = fig.add_subplot(gs[0, 1])
    if hasattr(islands[0], '_distance_from_center'):
        distances = [i._distance_from_center for i in islands]
    else:
        map_center = stats['map_center']
        distances = [np.sqrt((i.center[0] - map_center[0])**2 +
                            (i.center[1] - map_center[1])**2) for i in islands]
    ax2.bar(range(1, len(islands) + 1), distances, color=colors)
    ax2.set_xlabel('Island ID')
    ax2.set_ylabel('Distance (blocks)')
    ax2.set_title('Distance from Map Center')
    ax2.set_xticks(range(1, len(islands) + 1))

    # 3. Size distribution (pie chart)
    ax3 = fig.add_subplot(gs[0, 2])
    labels = [f'Island {i.id}' for i in islands[:6]]  # Top 6
    if len(islands) > 6:
        labels.append('Others')
        sizes_pie = [i.area for i in islands[:6]] + [sum(i.area for i in islands[6:])]
        colors_pie = colors[:6] + [(0.7, 0.7, 0.7)]
    else:
        sizes_pie = sizes
        colors_pie = colors
    ax3.pie(sizes_pie, labels=labels, colors=colors_pie, autopct='%1.1f%%')
    ax3.set_title('Area Distribution')

    # 4. Spatial distribution
    ax4 = fig.add_subplot(gs[1, :2])
    map_center = stats['map_center']

    for i, island in enumerate(islands):
        ax4.scatter(island.center[0], island.center[1],
                   s=island.area / 10,  # Size proportional to area
                   c=[colors[i]], alpha=0.7, edgecolors='black', linewidth=1)
        ax4.annotate(f'{island.id}', island.center, fontsize=9,
                    ha='center', va='center', fontweight='bold')

    ax4.scatter(*map_center, c='red', s=200, marker='X', zorder=5, edgecolors='black', linewidth=2)
    ax4.annotate('CENTER', map_center, fontsize=10, fontweight='bold',
                ha='center', va='bottom', xytext=(0, 10), textcoords='offset points', color='red')

    ax4.set_xlabel('X Coordinate')
    ax4.set_ylabel('Z Coordinate')
    ax4.set_title('Spatial Distribution of Islands (size = area)')
    ax4.axis('equal')
    ax4.grid(True, alpha=0.3)

    # 5. Statistics text
    ax5 = fig.add_subplot(gs[1, 2])
    ax5.axis('off')

    stats_text = f"""
ISLAND STATISTICS
═════════════════════════

Number of islands: {stats['num_islands']}
Total blocks: {stats['total_blocks']:,}

Largest island: {stats['largest_island']:,} blocks
Smallest island: {stats['smallest_island']:,} blocks
Average size: {stats['avg_island_size']:.1f} blocks
Median size: {stats['median_island_size']:.1f} blocks

Map center: ({stats['map_center'][0]:.1f}, {stats['map_center'][1]:.1f})
Avg distance from center: {stats['avg_distance_from_center']:.1f} blocks

═════════════════════════
"""
    ax5.text(0.1, 0.9, stats_text, transform=ax5.transAxes,
            fontsize=11, verticalalignment='top', fontfamily='monospace',
            bbox=dict(boxstyle='round', facecolor='lightgray', alpha=0.8))

    fig.suptitle('Island Detection Statistics', fontsize=16, fontweight='bold')

    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"Island statistics saved to: {output_path}")
    else:
        plt.show()

    plt.close(fig)
    return fig


def plot_triangulation_detail(
    islands: List,
    output_path: str = None,
    figsize: Tuple[int, int] = (20, 16),
    cols: int = 3
):
    """
    Create detailed view of each island's triangulation.

    Args:
        islands: List of Island objects
        output_path: Path to save figure
        figsize: Figure size
        cols: Number of columns in grid
    """
    n_islands = len(islands)
    rows = (n_islands + cols - 1) // cols

    fig, axes = plt.subplots(rows, cols, figsize=figsize)
    axes = np.array(axes).flatten()

    colors = generate_distinct_colors(len(islands))

    for i, island in enumerate(islands):
        ax = axes[i]
        color = colors[i]

        # Plot the actual blocks as background
        ax.scatter(
            island.blocks[:, 0],
            island.blocks[:, 1],
            c='lightgray',
            s=2,
            alpha=0.5,
            label='Blocks'
        )

        # Plot triangles with distinct colors
        if island.triangles:
            tri_colors = plt.cm.Set3(np.linspace(0, 1, len(island.triangles)))
            for j, tri in enumerate(island.triangles):
                triangle = Polygon(
                    tri, closed=True, fill=True,
                    facecolor=tri_colors[j], edgecolor='black',
                    alpha=0.6, linewidth=1.5
                )
                ax.add_patch(triangle)

        # Plot convex hull outline
        if island.hull_vertices is not None:
            hull = np.vstack([island.hull_vertices, island.hull_vertices[0]])
            ax.plot(hull[:, 0], hull[:, 1], 'r--', linewidth=1, alpha=0.5, label='Convex Hull')

        ax.set_title(f'Island {island.id}\n{island.area:,} blocks, {len(island.triangles)} triangles')
        ax.axis('equal')
        ax.grid(True, alpha=0.3)

    # Hide unused subplots
    for i in range(n_islands, len(axes)):
        axes[i].set_visible(False)

    fig.suptitle('Island Triangulation Detail View', fontsize=16, fontweight='bold')
    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"Triangulation detail saved to: {output_path}")
    else:
        plt.show()

    plt.close(fig)
    return fig


def create_island_report(
    islands: List,
    stats: Dict,
    output_dir: str,
    map_name: str = "Unknown"
):
    """
    Generate complete island analysis report with multiple visualizations.

    Args:
        islands: List of Island objects
        stats: Statistics dictionary
        output_dir: Output directory
        map_name: Name of the map
    """
    import os
    os.makedirs(output_dir, exist_ok=True)

    # Generate all visualizations
    plot_island_comparison(
        islands,
        output_path=os.path.join(output_dir, 'island_comparison.png')
    )

    plot_island_statistics(
        islands, stats,
        output_path=os.path.join(output_dir, 'island_statistics.png')
    )

    # Generate triangulation detail view
    plot_triangulation_detail(
        islands,
        output_path=os.path.join(output_dir, 'island_triangulation_detail.png')
    )

    # Text report
    report_path = os.path.join(output_dir, 'island_report.txt')
    with open(report_path, 'w') as f:
        f.write("=" * 70 + "\n")
        f.write(f"ISLAND DETECTION REPORT - {map_name}\n")
        f.write("=" * 70 + "\n\n")

        f.write(f"Total islands detected: {stats['num_islands']}\n")
        f.write(f"Total blocks analyzed: {stats['total_blocks']:,}\n")
        f.write(f"Map center: ({stats['map_center'][0]:.1f}, {stats['map_center'][1]:.1f})\n\n")

        f.write("-" * 70 + "\n")
        f.write("ISLAND DETAILS\n")
        f.write("-" * 70 + "\n\n")

        for island in islands:
            f.write(f"Island {island.id}:\n")
            f.write(f"  Area: {island.area:,} blocks\n")
            f.write(f"  Center: ({island.center[0]:.1f}, {island.center[1]:.1f})\n")
            f.write(f"  Bounding box: X[{island.bounding_box[0]}, {island.bounding_box[1]}] ")
            f.write(f"Z[{island.bounding_box[2]}, {island.bounding_box[3]}]\n")
            if island.triangles:
                f.write(f"  Triangles: {len(island.triangles)}\n")
            if island.holes:
                f.write(f"  Internal holes: {len(island.holes)}\n")
            f.write("\n")

        f.write("=" * 70 + "\n")

    print(f"Island report saved to: {report_path}")
