# Path Network Analysis

Extracts and visualizes movement networks from player paths, similar to how ants create trail networks. This feature identifies the "highway system" of most frequented routes in CTW matches.

## Overview

The path network analysis treats player movements like ant colonies exploring territory. By analyzing thousands of player paths, the system identifies:

- **High-traffic corridors** - Main routes players use repeatedly
- **Waypoint networks** - Key locations players pass through
- **Network skeletons** - Centerlines of movement flows
- **Team-specific patterns** - How each team moves differently

## Visualization Methods

The analysis provides 6 different extraction and visualization techniques:

### 1. Movement Density Heatmap
- **Method**: 2D histogram of all player positions
- **Shows**: Overall traffic patterns across the map
- **Color**: Hot colors indicate high traffic areas
- **Use**: Quick overview of where players spend time

### 2. Path Network Skeleton (Centerlines)
- **Method**: Morphological skeletonization of density map
- **Shows**: Centerlines of high-traffic areas
- **Technique**: Gaussian smoothing + threshold + skeletonization
- **Use**: Identify main "highways" and corridors

### 3. Waypoint Network Graph
- **Method**: DBSCAN clustering + path tracing
- **Shows**: Key waypoints as nodes, connections as edges
- **Node size**: Proportional to number of visits
- **Edge thickness**: Proportional to traffic volume
- **Use**: Understand connection structure and chokepoints

### 4. High-Traffic Corridors
- **Method**: Connected component analysis on density map
- **Shows**: Continuous regions of high movement
- **Color intensity**: Based on average traffic density
- **Use**: Identify specific corridor areas

### 5. Density + Skeleton Overlay
- **Method**: Combines heatmap with skeleton
- **Shows**: How skeleton relates to density
- **Use**: Validate skeleton extraction quality

### 6. Network Graph - Traffic Weighted
- **Method**: Enhanced waypoint graph visualization
- **Shows**: Same as method 3 with better visibility
- **Use**: Detailed network structure analysis

## Output Files

For each match, three path network visualizations are generated:

- **path_network_combined.png** - All 6 methods in one figure (20x15 inches)
- **path_network_red_team.png** - Red team specific network (3 methods)
- **path_network_blue_team.png** - Blue team specific network (3 methods)

## Analysis Parameters

### Resolution
- **Default**: 1.0 blocks
- **Effect**: Grid cell size for density heatmap
- **Lower values**: More detail, larger files, slower processing
- **Higher values**: Coarser network, faster processing

### Cluster Radius
- **Default**: 5.0 blocks
- **Effect**: Waypoint detection sensitivity
- **Lower values**: More waypoints, finer detail
- **Higher values**: Fewer waypoints, broader strokes

### Sigma (Smoothing)
- **Default**: 2.0
- **Effect**: Gaussian smoothing for skeleton extraction
- **Lower values**: More detailed skeleton, noisier
- **Higher values**: Smoother skeleton, less detail

### Threshold Percentile
- **Default**: 70%
- **Effect**: How much of density map becomes skeleton
- **Lower values**: More skeleton coverage
- **Higher values**: Only highest-traffic areas

## Path Statistics

For each match, the following statistics are calculated:

- **Total paths**: Number of player life segments with movement
- **Total distance**: Sum of all path lengths (blocks)
- **Average path length**: Mean distance traveled per life
- **Median path length**: Typical distance traveled
- **Max path length**: Longest single path recorded

## Network Metrics

The extracted networks provide:

- **Skeleton points**: Number of centerline points
- **Waypoints**: Number of key locations identified
- **Connections**: Number of edges between waypoints
- **Corridors**: Number of high-traffic corridor regions

## Usage

### Integrated Workflow

Path networks are automatically generated during match analysis:

```bash
python run_analysis_workflow.py --map tumbleweed
```

### Standalone Script

Generate path networks independently:

```bash
# Basic usage with config.json
python generate_path_networks.py

# Specify match and map
python generate_path_networks.py --match <match-file> --map-bedrock <bedrock-parquet>

# Adjust parameters
python generate_path_networks.py --match <match-file> --resolution 0.5 --cluster-radius 3.0

# Skip team-specific networks
python generate_path_networks.py --match <match-file> --no-team-networks

# Custom output directory
python generate_path_networks.py --match <match-file> --output analysis_results
```

## Interpretation Guide

### Identifying Main Routes

1. **Check skeleton network**: Continuous lines show main paths
2. **Verify with corridors**: Corridors should align with skeleton
3. **Examine waypoint graph**: Nodes should appear at route intersections

### Team Comparison

1. **Compare team-specific networks**: Different strategies visible
2. **Look for asymmetry**: Attacking vs defending patterns
3. **Check corridor coverage**: Which team controls which areas

### Tactical Insights

- **Chokepoints**: High-traffic waypoints with many connections
- **Flanking routes**: Low-traffic paths around main corridors
- **Safe zones**: Areas with minimal enemy traffic
- **Rush routes**: Direct, high-speed paths to objectives

## Technical Details

### Dependencies

```
numpy
matplotlib
scipy
networkx
scikit-image
scikit-learn
pandas
```

### Algorithms

1. **Density Heatmap**: `numpy.histogram2d` with position events
2. **Skeleton Extraction**: `scipy.ndimage.gaussian_filter` + `skimage.morphology.skeletonize`
3. **Waypoint Clustering**: `sklearn.cluster.DBSCAN` on positions
4. **Graph Building**: Path tracing between clustered waypoints
5. **Corridor Extraction**: `scipy.ndimage.label` on thresholded density

### Performance

- **Typical runtime**: 5-10 seconds per match
- **Memory usage**: ~100-200 MB for large matches
- **Scales with**: Number of position events (not total players)

## Examples

### Dense Mid-Control Maps

Maps with intense mid-area fighting show:
- High density in center
- Multiple parallel corridors
- Well-connected waypoint graph

### Lane-Based Maps

Maps with distinct lanes show:
- Separate corridor clusters
- Disconnected waypoint subgraphs
- Clear team territory separation

### Open Arena Maps

Maps with open spaces show:
- Diffuse density patterns
- Skeletal networks in edges/walls
- Few well-defined corridors

## Future Enhancements

Potential improvements:

- **Temporal analysis**: How networks change over match duration
- **Speed-based coloring**: Show fast vs slow movement areas
- **Objective routing**: Paths specifically to wool rooms
- **Elevation layers**: Separate networks by Y-coordinate
- **Path clustering**: Group similar routes automatically
- **Metro-style diagrams**: Simplified schematic representations

## API Reference

### Core Functions

```python
from match_analysis.path_network import (
    create_density_heatmap,
    extract_skeleton_network,
    extract_graph_network,
    extract_corridors,
    calculate_path_statistics
)

from match_analysis.path_network_viz import (
    plot_density_heatmap,
    plot_skeleton_network,
    plot_graph_network,
    plot_corridors,
    plot_combined_network,
    plot_team_networks
)
```

### Example Code

```python
# Load data
match_data = load_match_data('match.parquet')
life_segments = detect_life_segments(match_data)
life_segments = assign_teams(life_segments)

# Create heatmap
heatmap, bounds = create_density_heatmap(life_segments, resolution=1.0)

# Extract skeleton
skeleton, points = extract_skeleton_network(heatmap, bounds)

# Build graph
graph = extract_graph_network(life_segments, cluster_radius=5.0)

# Visualize
plot_combined_network(life_segments, map_data, 'output.png')
```

## Troubleshooting

### No skeleton points found
- **Cause**: Not enough position events or too high threshold
- **Solution**: Lower `threshold_percentile` or increase `sigma`

### Too many waypoints
- **Cause**: Cluster radius too small
- **Solution**: Increase `cluster_radius` parameter

### Disconnected graph
- **Cause**: Players don't follow common routes
- **Solution**: Normal for very chaotic matches

### High memory usage
- **Cause**: Very fine resolution
- **Solution**: Increase `resolution` parameter

## Credits

Inspired by ant colony trail network formation and metro map design principles.
