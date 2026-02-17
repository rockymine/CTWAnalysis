"""
Visualizer for Minecraft map regions and objectives.

Creates 2D plots showing spawns, wool rooms, and other important regions.
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Rectangle, Circle
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional

from .datatypes import MapData, Spawn, Wool
from .regions import Region, RectangleRegion, CuboidRegion, CircleRegion, CylinderRegion


class MapVisualizer:
    """Visualize map regions and objectives."""

    # Color scheme
    COLORS = {
        'red_spawn': '#FF4444',
        'blue_spawn': '#4444FF',
        'red_wool': '#FFAA44',
        'blue_wool': '#44AAFF',
        'spawn': '#888888',
        'wool': '#FFFF44',
        'build': '#44FF44',
        'other': '#CCCCCC',
        'wool_location': '#FF00FF',
        'monument': '#00FFFF',
    }

    def __init__(self, map_data: MapData):
        """
        Initialize visualizer with map data.

        Args:
            map_data: Parsed map data
        """
        self.data = map_data

    def plot_all(self, output_path: str, show_legend: bool = True):
        """
        Create a comprehensive plot showing all regions and objectives.

        Args:
            output_path: Path to save the plot
            show_legend: Whether to show the legend
        """
        fig, ax = plt.subplots(figsize=(14, 14))

        # Plot spawn regions
        self._plot_spawns(ax)

        # Plot wool locations and monuments
        self._plot_wools(ax)

        # Plot named regions
        self._plot_named_regions(ax)

        # Set labels and title
        ax.set_xlabel('World X', fontsize=12)
        ax.set_ylabel('World Z', fontsize=12)
        ax.set_title(f'{self.data.name} - Map Layout\n{self.data.objective}',
                     fontsize=14, fontweight='bold')
        ax.set_aspect('equal')
        ax.grid(True, alpha=0.3, linestyle='--')

        if show_legend:
            ax.legend(loc='upper right', fontsize=10)

        # Save
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()

        print(f"  Saved map visualization: {output_path}")

    def plot_by_category(self, output_dir: str, categories: Dict[str, List[str]]):
        """
        Create separate plots for each region category.

        Args:
            output_dir: Directory to save plots
            categories: Dictionary mapping category names to region IDs
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        for category, region_ids in categories.items():
            if not region_ids:
                continue

            fig, ax = plt.subplots(figsize=(12, 12))

            # Plot regions in this category (recursively for unions)
            for region_id in region_ids:
                if region_id in self.data.regions:
                    region = self.data.regions[region_id]
                    self._plot_region_recursive(ax, region, category, alpha=0.3)

            # Always show spawns and wools for context
            self._plot_spawns(ax, alpha=0.2)
            self._plot_wools(ax, alpha=0.2)

            ax.set_xlabel('World X', fontsize=12)
            ax.set_ylabel('World Z', fontsize=12)
            ax.set_title(f'{self.data.name} - {category.title()} Regions',
                         fontsize=14, fontweight='bold')
            ax.set_aspect('equal')
            ax.grid(True, alpha=0.3, linestyle='--')
            ax.legend(loc='upper right', fontsize=10)

            plot_path = output_path / f'{category}_regions.png'
            plt.savefig(plot_path, dpi=150, bbox_inches='tight')
            plt.close()

            print(f"  Saved {category} plot: {plot_path}")

    def _plot_spawns(self, ax, alpha: float = 0.3):
        """Plot spawn regions."""
        for spawn in self.data.spawns:
            if spawn.region is None:
                continue

            # Determine color based on team
            if spawn.team == 'red':
                color = self.COLORS['red_spawn']
                label = 'Red Spawn'
            elif spawn.team == 'blue':
                color = self.COLORS['blue_spawn']
                label = 'Blue Spawn'
            else:
                color = self.COLORS['spawn']
                label = 'Spawn'

            bounds = spawn.region.get_bounds_2d()
            if bounds:
                self._draw_rectangle(ax, bounds, color, label, alpha=alpha)

    def _plot_wools(self, ax, alpha: float = 1.0):
        """Plot wool locations and monuments."""
        for wool in self.data.wools:
            # Determine team color
            if wool.team == 'red':
                base_color = 'red'
            elif wool.team == 'blue':
                base_color = 'blue'
            else:
                base_color = 'gray'

            # Plot wool location
            ax.plot(wool.location[0], wool.location[2],
                   marker='*', markersize=15,
                   color=self.COLORS['wool_location'],
                   markeredgecolor='black', markeredgewidth=1.5,
                   label=f'{wool.color.title()} Wool ({wool.team})',
                   alpha=alpha)

            # Plot monument
            ax.plot(wool.monument[0], wool.monument[2],
                   marker='o', markersize=10,
                   color=self.COLORS['monument'],
                   markeredgecolor='black', markeredgewidth=1.5,
                   label=f'{wool.color.title()} Monument',
                   alpha=alpha)

    def _plot_named_regions(self, ax):
        """Plot all named regions from the regions section."""
        for region_id, region in self.data.regions.items():
            # Determine category and color
            category = self._categorize_region(region_id)
            self._plot_region_recursive(ax, region, category, alpha=0.2)

    def _categorize_region(self, region_id: str) -> str:
        """Categorize a region based on its ID."""
        region_id_lower = region_id.lower()

        if 'spawn' in region_id_lower:
            if 'red' in region_id_lower:
                return 'red_spawn'
            elif 'blue' in region_id_lower:
                return 'blue_spawn'
            return 'spawn'
        elif 'wool' in region_id_lower:
            if 'red' in region_id_lower:
                return 'red_wool'
            elif 'blue' in region_id_lower:
                return 'blue_wool'
            return 'wool'
        elif 'build' in region_id_lower:
            return 'build'
        else:
            return 'other'

    def _plot_region_recursive(self, ax, region: Region, category: str, alpha: float = 0.3):
        """
        Plot a region, recursively handling union/negative/complement regions.

        For composite regions (union, negative, complement), we plot their children
        instead of creating a combined bounding box.
        """
        from .regions import UnionRegion, NegativeRegion, ComplementRegion

        # If this is a composite region, recursively plot children
        if isinstance(region, (UnionRegion, NegativeRegion, ComplementRegion)):
            for child in region.children:
                # Recursively plot each child
                self._plot_region_recursive(ax, child, category, alpha=alpha)
        else:
            # This is a leaf region (rectangle, circle, etc.) - plot it directly
            self._plot_region(ax, region, category, alpha=alpha)

    def _plot_region(self, ax, region: Region, category: str, alpha: float = 0.3):
        """Plot a single leaf region (non-composite)."""
        from .regions import BlockRegion, PointRegion

        bounds = region.get_bounds_2d()
        if bounds is None:
            return

        color = self.COLORS.get(category, self.COLORS['other'])
        label = f'{region.id}' if region.id else category

        # Handle different region types for better visualization
        if isinstance(region, (CircleRegion, CylinderRegion)):
            self._draw_circle(ax, region, color, label, alpha=alpha)
        elif isinstance(region, (BlockRegion, PointRegion)):
            self._draw_point(ax, region, color, label, alpha=alpha)
        else:
            self._draw_rectangle(ax, bounds, color, label, alpha=alpha)

    def _draw_rectangle(self, ax, bounds, color: str, label: str, alpha: float = 0.3):
        """Draw a rectangle on the plot."""
        (min_x, min_z), (max_x, max_z) = bounds

        # Handle infinite bounds
        if np.isinf(min_x) or np.isinf(max_x) or np.isinf(min_z) or np.isinf(max_z):
            return

        width = max_x - min_x
        height = max_z - min_z

        rect = Rectangle((min_x, min_z), width, height,
                         linewidth=2, edgecolor=color, facecolor=color,
                         alpha=alpha, label=label)
        ax.add_patch(rect)

    def _draw_circle(self, ax, region, color: str, label: str, alpha: float = 0.3):
        """Draw a circle on the plot."""
        if isinstance(region, CircleRegion):
            center_x = region.center_x
            center_z = region.center_z
            radius = region.radius
        elif isinstance(region, CylinderRegion):
            center_x = region.base_x
            center_z = region.base_z
            radius = region.radius
        else:
            return

        circle = Circle((center_x, center_z), radius,
                       linewidth=2, edgecolor=color, facecolor=color,
                       alpha=alpha, label=label)
        ax.add_patch(circle)

    def _draw_point(self, ax, region, color: str, label: str, alpha: float = 0.3):
        """Draw a point or block as a marker on the plot."""
        from .regions import BlockRegion, PointRegion

        if isinstance(region, (BlockRegion, PointRegion)):
            x = region.x
            z = region.z
        else:
            return

        ax.plot(x, z,
               marker='x', markersize=8,
               color=color,
               markeredgewidth=2,
               label=label,
               alpha=min(1.0, alpha * 2))  # Make points more visible

    def print_summary(self):
        """Print a text summary of the map."""
        print("\n" + "=" * 70)
        print(f"MAP: {self.data.name} (v{self.data.version})")
        print("=" * 70)
        print(f"Objective: {self.data.objective}")

        if self.data.max_build_height:
            print(f"Max Build Height: {self.data.max_build_height}")

        print(f"\nTeams ({len(self.data.teams)}):")
        for team in self.data.teams:
            print(f"  - {team.name} ({team.id}): {team.color}, max {team.max_players} players")

        print(f"\nSpawns ({len(self.data.spawns)}):")
        for spawn in self.data.spawns:
            print(f"  - Team {spawn.team}: kit={spawn.kit}, yaw={spawn.yaw}")

        print(f"\nWools ({len(self.data.wools)}):")
        for wool in self.data.wools:
            print(f"  - {wool.color.title()} (Team {wool.team})")
            print(f"    Location: {wool.location}")
            print(f"    Monument: {wool.monument}")

        print(f"\nNamed Regions ({len(self.data.regions)}):")
        for region_id, region in self.data.regions.items():
            bounds = region.get_bounds_2d()
            bounds_str = f"{bounds}" if bounds else "N/A"
            print(f"  - {region_id} ({region.region_type}): {bounds_str}")

        print("=" * 70)
