"""
Island detection using connected component analysis, and hole detection.
"""

import numpy as np
import pandas as pd
from typing import List
from scipy import ndimage
from scipy.spatial import ConvexHull
from collections import deque

from .datatypes import Island


def detect_islands(
    block_data: pd.DataFrame,
    x_col: str = 'world_x',
    z_col: str = 'world_z',
    ignore_y: bool = True,
    connectivity: int = 8,
    min_island_size: int = 10
) -> List[Island]:
    """
    Detect connected islands of blocks using connected component analysis.

    Args:
        block_data: DataFrame with block coordinates
        x_col: Column name for X coordinates
        z_col: Column name for Z coordinates
        ignore_y: If True, project all blocks to 2D (ignore Y)
        connectivity: 4 or 8 for neighbor connectivity
        min_island_size: Minimum blocks to count as an island

    Returns:
        List of Island objects sorted by size (largest first)
    """
    # Extract unique 2D positions
    if ignore_y:
        positions = block_data[[x_col, z_col]].drop_duplicates().values
    else:
        positions = block_data[[x_col, z_col]].values

    if len(positions) == 0:
        return []

    # Determine grid bounds
    min_x, min_z = positions.min(axis=0)
    max_x, max_z = positions.max(axis=0)

    # Create 2D grid (offset to 0-indexed)
    width = int(max_x - min_x + 1)
    height = int(max_z - min_z + 1)
    grid = np.zeros((height, width), dtype=np.uint8)

    # Populate grid
    for x, z in positions:
        grid_x = int(x - min_x)
        grid_z = int(z - min_z)
        grid[grid_z, grid_x] = 1

    # Define connectivity structure
    if connectivity == 8:
        structure = np.ones((3, 3), dtype=np.uint8)
    else:  # 4-connectivity
        structure = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.uint8)

    # Label connected components
    labeled_grid, num_features = ndimage.label(grid, structure=structure)

    # Extract islands
    islands = []
    for label_id in range(1, num_features + 1):
        # Get all positions for this label
        island_mask = labeled_grid == label_id
        island_positions = np.argwhere(island_mask)  # (z, x) indices

        if len(island_positions) < min_island_size:
            continue

        # Convert back to world coordinates
        world_coords = np.zeros((len(island_positions), 2))
        world_coords[:, 0] = island_positions[:, 1] + min_x  # x
        world_coords[:, 1] = island_positions[:, 0] + min_z  # z

        # Calculate properties
        center = (world_coords[:, 0].mean() + 0.5, world_coords[:, 1].mean() + 0.5)
        bbox = (
            int(world_coords[:, 0].min()),
            int(world_coords[:, 0].max()) + 1,
            int(world_coords[:, 1].min()),
            int(world_coords[:, 1].max()) + 1,
        )

        island = Island(
            id=len(islands) + 1,
            blocks=world_coords,
            center=center,
            area=len(world_coords),
            bounding_box=bbox
        )

        # Compute convex hull
        if len(world_coords) >= 3:
            try:
                hull = ConvexHull(world_coords)
                island.hull_vertices = world_coords[hull.vertices]
            except:
                pass

        islands.append(island)

    # Sort by area (largest first)
    islands.sort(key=lambda i: i.area, reverse=True)

    # Reassign IDs after sorting
    for i, island in enumerate(islands):
        island.id = i + 1

    return islands


def find_island_holes(
    island: Island,
    grid_resolution: float = 1.0
) -> List[np.ndarray]:
    """
    Find internal holes (air pockets) within an island's bounding box.

    Args:
        island: Island object
        grid_resolution: Resolution for hole detection grid

    Returns:
        List of hole polygons (each as Nx2 array of vertices)
    """
    min_x, max_x, min_z, max_z = island.bounding_box

    # Create a grid of the bounding box
    width = int((max_x - min_x) / grid_resolution) + 1
    height = int((max_z - min_z) / grid_resolution) + 1

    # Create binary grid (1 = block, 0 = air)
    grid = np.zeros((height, width), dtype=np.uint8)

    for x, z in island.blocks:
        grid_x = int((x - min_x) / grid_resolution)
        grid_z = int((z - min_z) / grid_resolution)
        if 0 <= grid_x < width and 0 <= grid_z < height:
            grid[grid_z, grid_x] = 1

    # Invert to find air
    air_grid = 1 - grid

    # Fill from edges to mark external air
    # Use flood fill from border
    external_air = np.zeros_like(air_grid)
    height, width = air_grid.shape

    # Flood fill from all border cells
    queue = deque()
    for x in range(width):
        if air_grid[0, x] == 1:
            queue.append((0, x))
            external_air[0, x] = 1
        if air_grid[height-1, x] == 1:
            queue.append((height-1, x))
            external_air[height-1, x] = 1

    for z in range(height):
        if air_grid[z, 0] == 1:
            queue.append((z, 0))
            external_air[z, 0] = 1
        if air_grid[z, width-1] == 1:
            queue.append((z, width-1))
            external_air[z, width-1] = 1

    # BFS to mark all external air
    while queue:
        z, x = queue.popleft()
        for dz, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nz, nx = z + dz, x + dx
            if 0 <= nz < height and 0 <= nx < width:
                if air_grid[nz, nx] == 1 and external_air[nz, nx] == 0:
                    external_air[nz, nx] = 1
                    queue.append((nz, nx))

    # Internal holes = air that's not external
    internal_holes = air_grid - external_air

    # Label connected hole regions
    labeled_holes, num_holes = ndimage.label(internal_holes)

    holes = []
    for hole_id in range(1, num_holes + 1):
        hole_mask = labeled_holes == hole_id
        hole_positions = np.argwhere(hole_mask)

        if len(hole_positions) < 3:
            continue

        # Convert to world coordinates
        world_coords = np.zeros((len(hole_positions), 2))
        world_coords[:, 0] = hole_positions[:, 1] * grid_resolution + min_x
        world_coords[:, 1] = hole_positions[:, 0] * grid_resolution + min_z

        # Get convex hull of hole
        try:
            hull = ConvexHull(world_coords)
            holes.append(world_coords[hull.vertices])
        except:
            pass

    return holes
