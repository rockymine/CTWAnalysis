"""
CTW Map Renderer

Functions for rendering map tiles on matplotlib axes.
"""

import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.collections import PatchCollection
from matplotlib.axes import Axes

from .constants import (
    MAP_TILE_SIZE,
    MAP_TILE_COLOR,
    MAP_TILE_ALPHA,
    MAP_TILE_EDGE_COLOR,
    MAP_TILE_EDGE_WIDTH
)


def render_map_tiles(
    ax: Axes,
    map_data: pd.DataFrame,
    tile_size: float = MAP_TILE_SIZE,
    color: str = MAP_TILE_COLOR,
    alpha: float = MAP_TILE_ALPHA,
    edge_color: str = MAP_TILE_EDGE_COLOR,
    edge_width: float = MAP_TILE_EDGE_WIDTH
) -> None:
    """
    Render map bedrock blocks as tiles on matplotlib axes.

    Args:
        ax: Matplotlib axes object
        map_data: DataFrame with X, Z columns (bedrock positions)
        tile_size: Size of each tile in blocks
        color: Tile fill color
        alpha: Transparency (0-1)
        edge_color: Tile edge color
        edge_width: Tile edge width

    """
    patches = []

    for _, block in map_data.iterrows():
        rect = Rectangle(
            (block['X'], block['Z']),
            tile_size,
            tile_size
        )
        patches.append(rect)

    # Use PatchCollection for better performance
    collection = PatchCollection(
        patches,
        facecolor=color,
        edgecolor=edge_color,
        linewidth=edge_width,
        alpha=alpha
    )

    ax.add_collection(collection)


def setup_map_axes(
    ax: Axes,
    map_data: pd.DataFrame,
    padding: float = 5,
    title: str = None
) -> None:
    """
    Configure axes for map visualization.

    Args:
        ax: Matplotlib axes object
        map_data: DataFrame with X, Z columns (for determining bounds)
        padding: Extra space around map bounds
        title: Optional plot title
    """
    # Get map bounds
    x_min, x_max = map_data['X'].min(), map_data['X'].max()
    z_min, z_max = map_data['Z'].min(), map_data['Z'].max()

    # Set axis properties
    ax.set_xlabel('X Coordinate', fontsize=12)
    ax.set_ylabel('Z Coordinate', fontsize=12)
    ax.set_aspect('equal')
    ax.grid(True, alpha=0.3)

    # Set limits with padding
    ax.set_xlim(x_min - padding, x_max + padding)
    ax.set_ylim(z_min - padding, z_max + padding)

    if title:
        ax.set_title(title, fontsize=14, fontweight='bold')
