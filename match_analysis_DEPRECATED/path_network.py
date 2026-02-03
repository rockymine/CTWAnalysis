"""
Path Network Analysis - Extract movement networks from player paths

Analyzes player movement patterns to extract common routes and pathways,
similar to how ants create trail networks. Implements multiple techniques
to visualize the "highway network" of player movement.
"""

import numpy as np
import pandas as pd
from typing import List, Tuple, Dict, Set
from collections import defaultdict, Counter
from scipy.ndimage import gaussian_filter
from scipy import ndimage
from skimage.morphology import skeletonize
from sklearn.cluster import DBSCAN
import networkx as nx


def create_density_heatmap(
    life_segments,
    resolution: float = 1.0,
    bounds: Tuple[float, float, float, float] = None
) -> Tuple[np.ndarray, Tuple[float, float, float, float]]:
    """
    Create a 2D density heatmap of all player positions.

    Args:
        life_segments: List of LifeSegment objects
        resolution: Grid cell size in blocks
        bounds: Optional (min_x, max_x, min_z, max_z) bounds

    Returns:
        Tuple of (heatmap array, bounds)
    """
    # Collect all positions
    all_positions = []
    for seg in life_segments:
        if not seg.events.empty:
            positions = seg.events[seg.events['event_type'] == 5][['x', 'z']]  # 5 = POSITION
            if not positions.empty:
                all_positions.append(positions.values)

    if not all_positions:
        return np.zeros((10, 10)), (0, 10, 0, 10)

    all_positions = np.vstack(all_positions)

    # Determine bounds
    if bounds is None:
        min_x, min_z = all_positions.min(axis=0)
        max_x, max_z = all_positions.max(axis=0)
        # Add padding
        padding = 10
        min_x -= padding
        max_x += padding
        min_z -= padding
        max_z += padding
    else:
        min_x, max_x, min_z, max_z = bounds

    # Create grid
    x_bins = int((max_x - min_x) / resolution)
    z_bins = int((max_z - min_z) / resolution)

    # Create 2D histogram
    heatmap, _, _ = np.histogram2d(
        all_positions[:, 0],
        all_positions[:, 1],
        bins=[x_bins, z_bins],
        range=[[min_x, max_x], [min_z, max_z]]
    )

    return heatmap.T, (min_x, max_x, min_z, max_z)


def extract_skeleton_network(
    heatmap: np.ndarray,
    bounds: Tuple[float, float, float, float],
    resolution: float = 1.0,
    sigma: float = 2.0,
    threshold_percentile: float = 75.0
) -> Tuple[np.ndarray, List[Tuple[float, float]]]:
    """
    Extract skeleton (centerlines) from density heatmap.

    Uses morphological skeletonization to find the "backbone" of movement.

    Args:
        heatmap: 2D density array
        bounds: (min_x, max_x, min_z, max_z)
        resolution: Grid cell size
        sigma: Gaussian smoothing parameter
        threshold_percentile: Percentile threshold for binary mask

    Returns:
        Tuple of (skeleton binary array, list of skeleton points in world coords)
    """
    # Smooth the heatmap
    smoothed = gaussian_filter(heatmap, sigma=sigma)

    # Create binary mask of high-density areas
    nonzero_values = smoothed[smoothed > 0]
    if len(nonzero_values) == 0:
        # No data, return empty skeleton
        return np.zeros_like(heatmap, dtype=bool), []

    threshold = np.percentile(nonzero_values, threshold_percentile)
    binary_mask = smoothed > threshold

    # Extract skeleton
    skeleton = skeletonize(binary_mask)

    # Convert skeleton pixels to world coordinates
    min_x, max_x, min_z, max_z = bounds
    skeleton_points = []

    for i in range(skeleton.shape[0]):
        for j in range(skeleton.shape[1]):
            if skeleton[i, j]:
                # Convert grid indices to world coordinates
                world_x = min_x + (j + 0.5) * resolution
                world_z = min_z + (i + 0.5) * resolution
                skeleton_points.append((world_x, world_z))

    return skeleton, skeleton_points


def extract_graph_network(
    life_segments,
    cluster_radius: float = 5.0,
    min_samples: int = 5
) -> nx.Graph:
    """
    Extract a graph network of common waypoints and connections.

    Uses spatial clustering to identify waypoints, then builds edges
    based on actual player paths.

    Args:
        life_segments: List of LifeSegment objects
        cluster_radius: DBSCAN epsilon parameter (blocks)
        min_samples: Minimum points for a waypoint cluster

    Returns:
        NetworkX graph with waypoints as nodes and paths as edges
    """
    # Collect all position events
    all_positions = []
    segment_paths = []

    for seg in life_segments:
        if not seg.events.empty:
            positions = seg.events[seg.events['event_type'] == 5][['x', 'z']].values
            if len(positions) > 0:
                all_positions.append(positions)
                segment_paths.append(positions)

    if not all_positions:
        return nx.Graph()

    all_positions = np.vstack(all_positions)

    # Cluster positions to find waypoints
    clustering = DBSCAN(eps=cluster_radius, min_samples=min_samples)
    labels = clustering.fit_predict(all_positions)

    # Calculate waypoint centers
    waypoints = {}
    for label in set(labels):
        if label == -1:  # Skip noise
            continue
        cluster_points = all_positions[labels == label]
        center = cluster_points.mean(axis=0)
        waypoints[label] = center

    # Build graph
    G = nx.Graph()

    # Add nodes
    for label, center in waypoints.items():
        G.add_node(label, pos=center, visits=np.sum(labels == label))

    # Add edges based on actual paths
    edge_counts = defaultdict(int)

    for path in segment_paths:
        if len(path) < 2:
            continue

        # Find which waypoint each position is closest to
        path_waypoints = []
        for pos in path:
            min_dist = float('inf')
            closest_wp = None
            for label, center in waypoints.items():
                dist = np.linalg.norm(pos - center)
                if dist < cluster_radius and dist < min_dist:
                    min_dist = dist
                    closest_wp = label
            if closest_wp is not None:
                path_waypoints.append(closest_wp)

        # Add edges between consecutive waypoints
        for i in range(len(path_waypoints) - 1):
            wp1, wp2 = path_waypoints[i], path_waypoints[i + 1]
            if wp1 != wp2:
                edge = tuple(sorted([wp1, wp2]))
                edge_counts[edge] += 1

    # Add edges with weights
    for (wp1, wp2), count in edge_counts.items():
        if G.has_node(wp1) and G.has_node(wp2):
            G.add_edge(wp1, wp2, weight=count, traffic=count)

    return G


def extract_corridors(
    life_segments,
    resolution: float = 2.0,
    sigma: float = 3.0,
    min_corridor_density: float = 10.0
) -> List[Dict]:
    """
    Extract high-traffic corridors from movement data.

    Identifies linear regions of high movement density.

    Args:
        life_segments: List of LifeSegment objects
        resolution: Grid cell size
        sigma: Smoothing parameter
        min_corridor_density: Minimum density to consider as corridor

    Returns:
        List of corridor dictionaries with positions and traffic levels
    """
    # Create density heatmap
    heatmap, bounds = create_density_heatmap(life_segments, resolution=resolution)

    # Smooth
    smoothed = gaussian_filter(heatmap, sigma=sigma)

    # Find corridor regions (connected high-density areas)
    corridor_mask = smoothed > min_corridor_density
    labeled, num_features = ndimage.label(corridor_mask)

    min_x, max_x, min_z, max_z = bounds

    corridors = []
    for label in range(1, num_features + 1):
        # Get all points in this corridor
        corridor_points = np.argwhere(labeled == label)

        if len(corridor_points) < 5:  # Skip tiny corridors
            continue

        # Convert to world coordinates
        world_points = []
        densities = []
        for i, j in corridor_points:
            world_x = min_x + (j + 0.5) * resolution
            world_z = min_z + (i + 0.5) * resolution
            world_points.append((world_x, world_z))
            densities.append(smoothed[i, j])

        corridors.append({
            'points': world_points,
            'avg_density': np.mean(densities),
            'max_density': np.max(densities),
            'size': len(world_points)
        })

    # Sort by average density
    corridors.sort(key=lambda c: c['avg_density'], reverse=True)

    return corridors


def find_major_routes(
    life_segments,
    start_region: Tuple[float, float, float, float],
    end_region: Tuple[float, float, float, float],
    num_routes: int = 3
) -> List[List[Tuple[float, float]]]:
    """
    Find the most common routes between two regions.

    Args:
        life_segments: List of LifeSegment objects
        start_region: (min_x, max_x, min_z, max_z) for start area
        end_region: (min_x, max_x, min_z, max_z) for end area
        num_routes: Number of distinct routes to extract

    Returns:
        List of routes, where each route is a list of (x, z) points
    """
    def point_in_region(x, z, region):
        min_x, max_x, min_z, max_z = region
        return min_x <= x <= max_x and min_z <= z <= max_z

    # Find paths that go from start to end
    qualifying_paths = []

    for seg in life_segments:
        if seg.events.empty:
            continue

        positions = seg.events[seg.events['event_type'] == 5][['x', 'z']].values
        if len(positions) < 2:
            continue

        # Check if path starts in start_region and ends in end_region (or vice versa)
        starts_in_start = any(point_in_region(x, z, start_region) for x, z in positions[:5])
        ends_in_end = any(point_in_region(x, z, end_region) for x, z in positions[-5:])
        starts_in_end = any(point_in_region(x, z, end_region) for x, z in positions[:5])
        ends_in_start = any(point_in_region(x, z, start_region) for x, z in positions[-5:])

        if (starts_in_start and ends_in_end) or (starts_in_end and ends_in_start):
            qualifying_paths.append(positions)

    if not qualifying_paths:
        return []

    # Cluster similar paths using DTW or simple spatial clustering
    # For now, use a simple approach: sample paths and cluster samples

    # Subsample paths to common length
    target_length = 20
    resampled_paths = []
    for path in qualifying_paths:
        if len(path) < 2:
            continue
        indices = np.linspace(0, len(path) - 1, target_length, dtype=int)
        resampled = path[indices]
        resampled_paths.append(resampled)

    if not resampled_paths:
        return []

    # Simple clustering: find paths that are spatially similar
    # For now, just return the most representative paths
    # TODO: Implement proper path clustering (e.g., k-medoids with DTW)

    # Return a sample of paths as "major routes"
    if len(resampled_paths) <= num_routes:
        return [path.tolist() for path in resampled_paths]

    # Sample evenly
    indices = np.linspace(0, len(resampled_paths) - 1, num_routes, dtype=int)
    return [resampled_paths[i].tolist() for i in indices]


def calculate_path_statistics(life_segments) -> Dict:
    """
    Calculate overall statistics about player paths.

    Args:
        life_segments: List of LifeSegment objects

    Returns:
        Dictionary with path statistics
    """
    total_distance = 0
    num_paths = 0
    path_lengths = []

    for seg in life_segments:
        if seg.events.empty:
            continue

        positions = seg.events[seg.events['event_type'] == 5][['x', 'z']].values
        if len(positions) < 2:
            continue

        # Calculate path length
        distances = np.sqrt(np.sum(np.diff(positions, axis=0)**2, axis=1))
        path_length = np.sum(distances)

        total_distance += path_length
        path_lengths.append(path_length)
        num_paths += 1

    return {
        'total_paths': num_paths,
        'total_distance': total_distance,
        'avg_path_length': np.mean(path_lengths) if path_lengths else 0,
        'median_path_length': np.median(path_lengths) if path_lengths else 0,
        'max_path_length': np.max(path_lengths) if path_lengths else 0,
    }
