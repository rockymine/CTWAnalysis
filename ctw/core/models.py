"""
Shared model classes for CTW Analysis.

Contains all core dataclasses used across subprojects:
Island, skeleton types, and MapContext.

Coordinate conventions:
- Mask/skeleton space: (r, c) where r = row (z-axis), c = column (x-axis)
- World space: (x, z) as used in Minecraft coordinates
- Canonical space: world coords transformed via D4 symmetry, with minX=minZ=0
"""

import json
import os
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

from ctw.core.geometry import rotate_points, json_default


# ---------------------------------------------------------------------------
# Island
# ---------------------------------------------------------------------------

@dataclass
class Island:
    """Represents a detected island in the map."""
    id: int
    blocks: np.ndarray  # Nx2 array of (x, z) coordinates
    center: Tuple[float, float]  # Centroid
    area: int  # Number of blocks
    bounding_box: Tuple[int, int, int, int]  # (min_x, max_x, min_z, max_z)
    hull_vertices: np.ndarray = None  # Convex hull vertices
    simplified_polygon: Optional[dict] = None  # {exterior: [[x,z],...], holes: [...]}
    triangles: List[np.ndarray] = field(default_factory=list)  # Triangle vertices
    holes: List[np.ndarray] = field(default_factory=list)  # Internal air pockets
    skeleton_result: Optional[object] = None  # IslandResult from skeleton pipeline
    has_spawn: bool = False
    has_wool: bool = False
    has_center: bool = False
    distance_to_center: float = 0.0
    team: Optional[str] = None  # Team id if spawn island


# ---------------------------------------------------------------------------
# Skeleton types
# ---------------------------------------------------------------------------

@dataclass
class CanonicalTransform:
    """Encodes the D4 transformation between world and canonical space.

    The forward transform (to_canonical) applies:
      1. If mirror: flip X axis
      2. Apply rotation (0/90/180/270)
      3. Add translation (so minX=minZ=0)

    The reverse transform (to_original) undoes these steps.

    world_center is unused (kept at zeros) since the integer-based
    canonicalization doesn't use float centering.
    """
    rotation: int                    # 0, 90, 180, 270 degrees
    mirror: bool                     # Whether X is flipped before rotation
    translation: np.ndarray          # 2-vector added after rotation (= -min_vals)
    world_center: np.ndarray         # unused, kept for compatibility (zeros)

    def to_canonical(self, points: np.ndarray) -> np.ndarray:
        """Transform world (x, z) points to canonical space."""
        pts = np.round(points).astype(int)
        if self.mirror:
            pts = pts.copy()
            pts[:, 0] = -pts[:, 0]
        pts = rotate_points(pts.astype(float), self.rotation)
        pts = pts + self.translation
        return np.round(pts).astype(int)

    def to_original(self, points: np.ndarray) -> np.ndarray:
        """Transform canonical (x, z) points back to world space."""
        pts = points.astype(float) - self.translation
        pts = rotate_points(pts, -self.rotation % 360)
        if self.mirror:
            pts[:, 0] = -pts[:, 0]
        return pts


@dataclass
class CanonicalIsland:
    """An island in its canonical (symmetry-normalized) orientation."""
    island_id: int
    canonical_points: np.ndarray     # Nx2 int coords, min=0
    canonical_key: str               # Hash of sorted canonical_points
    transform: CanonicalTransform    # Maps world <-> canonical
    world_blocks: np.ndarray         # Original Nx2 world coords (reference)


@dataclass
class RasterMask:
    """Boolean mask for a rasterized island.

    Convention: mask[r, c] where r corresponds to z-axis, c to x-axis.
    """
    mask: np.ndarray                 # (H, W) bool
    padding: int                     # Padding applied around tight bbox
    origin: np.ndarray               # (x, z) of mask[0, 0] in canonical coords

    def rc_to_canonical(self, r: int, c: int) -> Tuple[int, int]:
        """Convert mask (r, c) to canonical (x, z)."""
        x = c + int(self.origin[0])
        z = r + int(self.origin[1])
        return (x, z)

    def canonical_to_rc(self, x: int, z: int) -> Tuple[int, int]:
        """Convert canonical (x, z) to mask (r, c)."""
        r = z - int(self.origin[1])
        c = x - int(self.origin[0])
        return (r, c)


@dataclass
class SkeletonPixels:
    """Raw skeleton pixel data with no processing."""
    mask: np.ndarray                 # (H, W) bool skeleton mask
    pixel_coords: np.ndarray         # Px2 array of (r, c) skeleton pixel coordinates


@dataclass
class GraphNode:
    """A node in the skeleton graph."""
    node_id: int
    rc: Tuple[int, int]              # (r, c) position in mask space
    degree: int                      # Pixel degree in skeleton
    node_type: str                   # 'endpoint' or 'junction'
    poi_type: Optional[str] = None   # 'spawn', 'wool', or None
    poi_color: Optional[str] = None  # team color (spawn) or wool color


@dataclass
class GraphEdge:
    """An edge in the skeleton graph."""
    edge_id: int
    src: int                         # Source node_id
    dst: int                         # Destination node_id
    pixel_path: np.ndarray           # Ordered Px2 array of (r, c) along skeleton


@dataclass
class SkeletonGraph:
    """Complete skeleton graph for one island."""
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    skeleton_pixels: SkeletonPixels  # Reference to underlying skeleton


@dataclass
class IslandResult:
    """Complete result for one island through the skeleton pipeline."""
    island_id: int
    canonical: CanonicalIsland
    raster: RasterMask
    skeleton: SkeletonPixels
    graph: SkeletonGraph


# ---------------------------------------------------------------------------
# MapContext
# ---------------------------------------------------------------------------

@dataclass
class MapContext:
    """Comprehensive map information aggregating all analysis results."""

    # Map metadata (from XML)
    map_name: str = ""
    map_version: str = ""
    objective: str = ""
    teams: List[Dict] = field(default_factory=list)

    # Layout info
    bounding_box: Optional[Tuple[float, float, float, float]] = None
    map_center: Optional[Tuple[float, float]] = None
    total_blocks: int = 0

    # Islands summary
    island_count: int = 0
    islands: List[Dict] = field(default_factory=list)

    # Skeleton summary
    total_nodes: int = 0
    total_edges: int = 0
    total_endpoints: int = 0
    total_junctions: int = 0
    unique_canonical_shapes: int = 0

    # POI summary
    poi_assignments: Dict = field(default_factory=dict)

    # Build region
    build_region: Optional[Dict] = None

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return {
            'map_name': self.map_name,
            'map_version': self.map_version,
            'objective': self.objective,
            'teams': self.teams,
            'bounding_box': list(self.bounding_box) if self.bounding_box else None,
            'map_center': list(self.map_center) if self.map_center else None,
            'total_blocks': self.total_blocks,
            'island_count': self.island_count,
            'islands': self.islands,
            'skeleton': {
                'total_nodes': self.total_nodes,
                'total_edges': self.total_edges,
                'total_endpoints': self.total_endpoints,
                'total_junctions': self.total_junctions,
                'unique_canonical_shapes': self.unique_canonical_shapes,
            },
            'poi_assignments': self.poi_assignments,
            'build_region': self.build_region,
        }

    def save_json(self, output_path: str) -> None:
        """Save to JSON file."""
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, default=json_default)
        print(f"Map context saved to: {output_path}")


# ---------------------------------------------------------------------------
# MapContext builders
# ---------------------------------------------------------------------------

def build_map_context(
    islands: List[Island],
    skeleton_results: List[IslandResult],
    canonical_groups: Dict[str, List[int]],
    layout_df,
    map_data=None,
    map_center: Optional[Tuple[float, float]] = None,
    poi_assignments: Optional[Dict] = None,
) -> MapContext:
    """Build a MapContext from all analysis results.

    Args:
        islands: List of Island objects.
        skeleton_results: List of IslandResult objects.
        canonical_groups: canonical_key -> island_ids mapping.
        layout_df: Layout DataFrame with world_x/world_z columns.
        map_data: Parsed MapData from XML (optional).
        map_center: Pre-computed map center (optional).
        poi_assignments: POI assignment results (optional).

    Returns:
        Populated MapContext.
    """
    ctx = MapContext()

    # XML metadata
    if map_data is not None:
        ctx.map_name = map_data.name
        ctx.map_version = map_data.version
        ctx.objective = map_data.objective
        ctx.teams = [
            {'id': t.id, 'color': t.color, 'name': t.name, 'max_players': t.max_players}
            for t in map_data.teams
        ]

    # Layout info
    x_col = 'world_x' if 'world_x' in layout_df.columns else 'x'
    z_col = 'world_z' if 'world_z' in layout_df.columns else 'z'
    ctx.bounding_box = (
        float(layout_df[x_col].min()),
        float(layout_df[x_col].max()) + 1,
        float(layout_df[z_col].min()),
        float(layout_df[z_col].max()) + 1,
    )
    ctx.total_blocks = len(layout_df)
    ctx.map_center = map_center

    # Islands
    ctx.island_count = len(islands)
    for island in islands:
        island_info = {
            'id': island.id,
            'area': island.area,
            'center': list(island.center),
            'bounding_box': list(island.bounding_box),
            'has_spawn': island.has_spawn,
            'has_wool': island.has_wool,
            'has_center': island.has_center,
            'distance_to_center': round(island.distance_to_center, 2),
            'team': island.team,
            'triangle_count': len(island.triangles),
            'hole_count': len(island.holes),
            'simplified_polygon': island.simplified_polygon,
        }
        ctx.islands.append(island_info)

    # Skeleton
    ctx.total_nodes = sum(len(r.graph.nodes) for r in skeleton_results)
    ctx.total_edges = sum(len(r.graph.edges) for r in skeleton_results)
    ctx.total_endpoints = sum(
        sum(1 for n in r.graph.nodes if n.node_type == 'endpoint')
        for r in skeleton_results
    )
    ctx.total_junctions = sum(
        sum(1 for n in r.graph.nodes if n.node_type == 'junction')
        for r in skeleton_results
    )
    ctx.unique_canonical_shapes = len(canonical_groups)

    # POI
    if poi_assignments is not None:
        ctx.poi_assignments = poi_assignments

    return ctx


def build_skeleton_dicts(
    islands: List[Island],
    skeleton_results: List[IslandResult],
) -> List[dict]:
    """Build per-island skeleton dicts for map_graph.json.

    Returns:
        List of dicts: [{"island_id": int, "team": str, "skeleton": {...}, ...}]
    """
    result_by_id = {r.island_id: r for r in skeleton_results}
    island_skeletons = []
    for island in islands:
        skel_result = result_by_id.get(island.id)
        island_skeletons.append({
            'island_id': island.id,
            'team': island.team,
            'skeleton': _build_skeleton_dict(skel_result) if skel_result else None,
            'pathfinding': None,
        })
    return island_skeletons


def _build_skeleton_dict(result: IslandResult) -> dict:
    """Convert IslandResult skeleton data to a JSON-serializable dict in world coords."""
    transform = result.canonical.transform
    raster = result.raster

    nodes = []
    for node in result.graph.nodes:
        cx, cz = raster.rc_to_canonical(node.rc[0], node.rc[1])
        canonical_pt = np.array([[cx, cz]], dtype=float)
        world_pt = transform.to_original(canonical_pt)[0]
        nodes.append({
            'node_id': node.node_id,
            'x': round(float(world_pt[0]), 1),
            'z': round(float(world_pt[1]), 1),
            'type': node.node_type,
            'degree': node.degree,
        })

    edges = []
    for edge in result.graph.edges:
        edges.append({
            'edge_id': edge.edge_id,
            'src': edge.src,
            'dst': edge.dst,
        })

    edge_pixels = {}
    for edge in result.graph.edges:
        path_canonical = np.array([
            raster.rc_to_canonical(r, c) for r, c in edge.pixel_path
        ], dtype=float)
        path_world = transform.to_original(path_canonical)
        edge_pixels[str(edge.edge_id)] = {
            'src': edge.src,
            'dst': edge.dst,
            'pixels': [[round(float(pt[0]), 1), round(float(pt[1]), 1)]
                        for pt in path_world],
        }

    return {
        'nodes': nodes,
        'edges': edges,
        'edge_pixels': edge_pixels,
    }
