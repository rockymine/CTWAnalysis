"""
Island statistics and classification.
"""

import numpy as np
from typing import List, Dict, Tuple

from .datatypes import Island


def compute_island_statistics(islands: List[Island]) -> Dict:
    """
    Compute statistics about detected islands.

    Args:
        islands: List of Island objects

    Returns:
        Dictionary with statistics
    """
    if not islands:
        return {'num_islands': 0}

    total_blocks = sum(i.area for i in islands)
    areas = [i.area for i in islands]

    # Find center of all islands
    all_centers = np.array([i.center for i in islands])
    map_center = all_centers.mean(axis=0)

    # Calculate distances from map center
    distances = np.sqrt(np.sum((all_centers - map_center) ** 2, axis=1))

    return {
        'num_islands': len(islands),
        'total_blocks': total_blocks,
        'largest_island': max(areas),
        'smallest_island': min(areas),
        'avg_island_size': np.mean(areas),
        'median_island_size': np.median(areas),
        'map_center': tuple(map_center),
        'avg_distance_from_center': np.mean(distances),
        'island_sizes': areas
    }


def classify_islands(
    islands: List[Island],
    map_center: Tuple[float, float] = None
) -> Dict[str, List[Island]]:
    """
    Classify islands by their likely role in the map.

    Args:
        islands: List of Island objects
        map_center: Optional map center (auto-calculated if None)

    Returns:
        Dictionary mapping classification to list of islands
    """
    if not islands:
        return {}

    # Calculate map center if not provided
    if map_center is None:
        all_centers = np.array([i.center for i in islands])
        map_center = tuple(all_centers.mean(axis=0))

    classifications = {
        'spawn_islands': [],  # Large islands at edges (team spawns)
        'center_island': [],  # Island closest to center
        'peripheral_islands': [],  # Medium islands around center
        'small_islands': []  # Small decoration/obstacle islands
    }

    # Sort by distance from center
    for island in islands:
        dist = np.sqrt((island.center[0] - map_center[0])**2 +
                      (island.center[1] - map_center[1])**2)
        island._distance_from_center = dist

    # Classify based on size and position
    sorted_by_size = sorted(islands, key=lambda i: i.area, reverse=True)
    sorted_by_dist = sorted(islands, key=lambda i: i._distance_from_center)

    # The two largest are likely spawn islands
    if len(sorted_by_size) >= 2:
        classifications['spawn_islands'] = sorted_by_size[:2]

    # Island closest to center
    if sorted_by_dist:
        classifications['center_island'] = [sorted_by_dist[0]]

    # Classify remaining
    for island in islands:
        if island in classifications['spawn_islands']:
            continue
        if island in classifications['center_island']:
            continue

        if island.area < 50:
            classifications['small_islands'].append(island)
        else:
            classifications['peripheral_islands'].append(island)

    return classifications
