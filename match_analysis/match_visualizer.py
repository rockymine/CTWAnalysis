"""
CTW Match Visualizer

Configurable visualization of match data with team colors and event toggles.
"""

from typing import List, Optional
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.widgets import CheckButtons, RadioButtons
from matplotlib.patches import Patch

from .preprocessing import LifeSegment
from .map_renderer import render_map_tiles, setup_map_axes
from .constants import (
    EVENT_IDS,
    TEAM_COLORS,
    EVENT_MARKERS,
    DEFAULT_LINE_WIDTH,
    DEFAULT_LINE_ALPHA
)


class MatchVisualizer:
    """
    Configurable match visualization with team colors and event toggles.

    Features:
    - Team-based color coding (red/blue/unknown)
    - Toggleable event displays (kills/deaths/wool events)
    - Interactive controls via matplotlib widgets
    - Team filtering (show red/blue/all)
    """

    def __init__(
        self,
        map_data: pd.DataFrame,
        life_segments: List[LifeSegment],
        show_kills: bool = False,
        show_deaths: bool = True,
        show_wool_events: bool = True,
        color_by_team: bool = True
    ):
        """
        Initialize match visualizer.

        Args:
            map_data: DataFrame with map bedrock coordinates (X, Z)
            life_segments: List of LifeSegment objects
            show_kills: Display kill events
            show_deaths: Display death events
            show_wool_events: Display wool touch/capture events
            color_by_team: Use team colors for position traces
        """
        self.map_data = map_data
        self.life_segments = life_segments
        self.show_kills = show_kills
        self.show_deaths = show_deaths
        self.show_wool_events = show_wool_events
        self.color_by_team = color_by_team

    def _get_segment_color(self, segment: LifeSegment) -> str:
        """Get color for a life segment based on team."""
        if self.color_by_team:
            return TEAM_COLORS.get(segment.team, TEAM_COLORS['unknown'])
        else:
            return '#7F8C8D'  # Gray for non-team coloring

    def plot_life_segment(
        self,
        ax: Axes,
        segment: LifeSegment,
        show_positions: bool = True
    ) -> None:
        """
        Plot a single life segment with team color.

        Args:
            ax: Matplotlib axes object
            segment: LifeSegment to visualize
            show_positions: Whether to draw position trace lines
        """
        events = segment.events

        if events.empty:
            return

        # Get segment color
        color = self._get_segment_color(segment)

        # Plot position trace
        if show_positions:
            position_events = events[events['event_type'] == EVENT_IDS['POSITION']]
            if not position_events.empty:
                ax.plot(
                    position_events['x'],
                    position_events['z'],
                    color=color,
                    alpha=DEFAULT_LINE_ALPHA,
                    linewidth=DEFAULT_LINE_WIDTH,
                    zorder=1
                )

        # Plot spawn
        spawn_x, spawn_y, spawn_z = segment.spawn_coords
        spawn_marker = EVENT_MARKERS['spawn']
        ax.scatter(
            [spawn_x], [spawn_z],
            marker=spawn_marker['marker'],
            s=spawn_marker['size'],
            c=spawn_marker['color'],
            edgecolors=spawn_marker['edgecolor'],
            linewidths=spawn_marker['linewidth'],
            zorder=3,
            label='Spawn' if not hasattr(ax, '_spawn_labeled') else ''
        )
        if not hasattr(ax, '_spawn_labeled'):
            ax._spawn_labeled = True

        # Plot deaths
        if self.show_deaths:
            death_events = events[events['event_type'] == EVENT_IDS['DEATH']]
            if not death_events.empty:
                death_marker = EVENT_MARKERS['death']
                ax.scatter(
                    death_events['x'],
                    death_events['z'],
                    marker=death_marker['marker'],
                    s=death_marker['size'],
                    c=death_marker['color'],
                    linewidths=death_marker['linewidth'],
                    zorder=3,
                    label='Death' if not hasattr(ax, '_death_labeled') else ''
                )
                if not hasattr(ax, '_death_labeled'):
                    ax._death_labeled = True

        # Plot kills
        if self.show_kills:
            kill_events = events[events['event_type'] == EVENT_IDS['KILL']]
            if not kill_events.empty:
                kill_marker = EVENT_MARKERS['kill']
                ax.scatter(
                    kill_events['x'],
                    kill_events['z'],
                    marker=kill_marker['marker'],
                    s=kill_marker['size'],
                    c=kill_marker['color'],
                    linewidths=kill_marker['linewidth'],
                    zorder=3,
                    label='Kill' if not hasattr(ax, '_kill_labeled') else ''
                )
                if not hasattr(ax, '_kill_labeled'):
                    ax._kill_labeled = True

        # Plot wool events
        if self.show_wool_events:
            wool_touch_events = events[events['event_type'] == EVENT_IDS['WOOL_TOUCH']]
            if not wool_touch_events.empty:
                touch_marker = EVENT_MARKERS['wool_touch']
                ax.scatter(
                    wool_touch_events['x'],
                    wool_touch_events['z'],
                    marker=touch_marker['marker'],
                    s=touch_marker['size'],
                    c=touch_marker['color'],
                    edgecolors=touch_marker['edgecolor'],
                    linewidths=touch_marker['linewidth'],
                    zorder=3,
                    label='Wool Touch' if not hasattr(ax, '_touch_labeled') else ''
                )
                if not hasattr(ax, '_touch_labeled'):
                    ax._touch_labeled = True

            wool_capture_events = events[events['event_type'] == EVENT_IDS['WOOL_CAPTURE']]
            if not wool_capture_events.empty:
                capture_marker = EVENT_MARKERS['wool_capture']
                ax.scatter(
                    wool_capture_events['x'],
                    wool_capture_events['z'],
                    marker=capture_marker['marker'],
                    s=capture_marker['size'],
                    c=capture_marker['color'],
                    edgecolors=capture_marker['edgecolor'],
                    linewidths=capture_marker['linewidth'],
                    zorder=4,
                    label='Wool Capture' if not hasattr(ax, '_capture_labeled') else ''
                )
                if not hasattr(ax, '_capture_labeled'):
                    ax._capture_labeled = True

    def plot_all_teams(
        self,
        ax: Axes,
        team_filter: Optional[str] = None
    ) -> None:
        """
        Plot all life segments, optionally filtered by team.

        Args:
            ax: Matplotlib axes object
            team_filter: 'red', 'blue', or None (all teams)
        """
        # Clear previous labels tracking
        for attr in ['_spawn_labeled', '_death_labeled', '_kill_labeled',
                     '_touch_labeled', '_capture_labeled']:
            if hasattr(ax, attr):
                delattr(ax, attr)

        # Filter segments by team if requested
        segments_to_plot = self.life_segments
        if team_filter:
            segments_to_plot = [seg for seg in self.life_segments if seg.team == team_filter]

        # Plot each segment
        for segment in segments_to_plot:
            self.plot_life_segment(ax, segment)

        # Add team color legend if coloring by team
        if self.color_by_team:
            team_patches = []
            if team_filter is None or team_filter == 'red':
                team_patches.append(Patch(color=TEAM_COLORS['red'], label='Red Team'))
            if team_filter is None or team_filter == 'blue':
                team_patches.append(Patch(color=TEAM_COLORS['blue'], label='Blue Team'))
            if team_filter is None:
                team_patches.append(Patch(color=TEAM_COLORS['unknown'], label='Unknown Team'))

            # Add team patches to existing legend
            handles, labels = ax.get_legend_handles_labels()
            handles.extend(team_patches)
            labels.extend([p.get_label() for p in team_patches])

            ax.legend(handles, labels, loc='upper right', fontsize=9)
        else:
            ax.legend(loc='upper right', fontsize=9)

    def create_static_view(
        self,
        team_filter: Optional[str] = None,
        title: str = "CTW Match Visualization"
    ) -> plt.Figure:
        """
        Create a static visualization plot.

        Args:
            team_filter: Optional team filter ('red', 'blue', or None)
            title: Plot title

        Returns:
            Matplotlib figure object
        """
        fig, ax = plt.subplots(figsize=(14, 10))

        # Render map
        render_map_tiles(ax, self.map_data)
        setup_map_axes(ax, self.map_data, title=title)

        # Plot segments
        self.plot_all_teams(ax, team_filter)

        plt.tight_layout()
        return fig

    def create_interactive_view(self, title: str = "CTW Match Visualization") -> None:
        """
        Create interactive matplotlib window with toggle controls.

        Features:
        - Checkboxes to toggle kills/deaths/wool events
        - Radio buttons to filter by team

        Args:
            title: Plot title
        """
        # Create figure with space for controls
        fig = plt.figure(figsize=(16, 10))

        # Main plot axes (left side)
        ax_main = fig.add_axes([0.15, 0.1, 0.7, 0.85])

        # Control panel axes
        ax_check = fig.add_axes([0.02, 0.5, 0.1, 0.2])
        ax_radio = fig.add_axes([0.02, 0.2, 0.1, 0.25])

        # Initial render
        def render():
            ax_main.clear()
            render_map_tiles(ax_main, self.map_data)
            setup_map_axes(ax_main, self.map_data, title=title)

            # Get current team filter
            team_filter = None
            if hasattr(render, 'current_team') and render.current_team != 'All':
                team_filter = render.current_team.lower()

            self.plot_all_teams(ax_main, team_filter)
            fig.canvas.draw_idle()

        render.current_team = 'All'

        # Checkbox for event toggles
        check_labels = ['Kills', 'Deaths', 'Wool Events']
        check_states = [self.show_kills, self.show_deaths, self.show_wool_events]
        check = CheckButtons(ax_check, check_labels, check_states)

        def on_check(label):
            if label == 'Kills':
                self.show_kills = not self.show_kills
            elif label == 'Deaths':
                self.show_deaths = not self.show_deaths
            elif label == 'Wool Events':
                self.show_wool_events = not self.show_wool_events
            render()

        check.on_clicked(on_check)

        # Radio buttons for team filter
        radio_labels = ['All', 'Red', 'Blue']
        radio = RadioButtons(ax_radio, radio_labels, active=0)

        def on_radio(label):
            render.current_team = label
            render()

        radio.on_clicked(on_radio)

        # Add labels to control panels
        ax_check.set_title('Event Toggles', fontsize=10, fontweight='bold')
        ax_radio.set_title('Team Filter', fontsize=10, fontweight='bold')

        # Initial render
        render()

        plt.show()

    def export_team_views(self, output_dir: str = 'output') -> None:
        """
        Export separate PNG files for each team view.

        Args:
            output_dir: Directory to save output files
        """
        import os
        os.makedirs(output_dir, exist_ok=True)

        # All teams view
        fig = self.create_static_view(title="All Teams - CTW Match")
        fig.savefig(f"{output_dir}/all_teams.png", dpi=150, bbox_inches='tight')
        plt.close(fig)
        print(f"Saved: {output_dir}/all_teams.png")

        # Red team view
        fig = self.create_static_view(team_filter='red', title="Red Team - CTW Match")
        fig.savefig(f"{output_dir}/red_team.png", dpi=150, bbox_inches='tight')
        plt.close(fig)
        print(f"Saved: {output_dir}/red_team.png")

        # Blue team view
        fig = self.create_static_view(team_filter='blue', title="Blue Team - CTW Match")
        fig.savefig(f"{output_dir}/blue_team.png", dpi=150, bbox_inches='tight')
        plt.close(fig)
        print(f"Saved: {output_dir}/blue_team.png")
