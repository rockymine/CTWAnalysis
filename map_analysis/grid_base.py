"""Grid-based rasterization of map_context.json polygon geometry.

Converts island and build-region polygons from a completed map_context.json
into a set of axis-aligned grid cells.  Each cell is grid_size × grid_size
blocks.  Containment is tested at the cell centre, and island polygons take
priority over build-region polygons (matching PositionClassifier precedence).

No player data or DB connection is required — only map_context.json.

Typical usage:
    grid_base = load_grid_base(output_dir, map_slug, grid_size)
    # or, if map_context is already loaded:
    grid_base = rasterize_map_polygons(map_context, map_slug, grid_size)
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from shapely import STRtree
from shapely import points as shp_points
from shapely.geometry import Polygon

logger = logging.getLogger("ctw")


# ---------------------------------------------------------------------------
# Grid alignment helpers
# ---------------------------------------------------------------------------


def _cell_origin(coord: float, center: int, grid_size: int) -> int:
    """Return the grid-aligned cell origin for *coord* when the grid is anchored at *center*.

    Cell boundaries exist at center, center ± grid_size, center ± 2*grid_size, …
    so a symmetric map always has its centre on a cell boundary rather than
    inside a cell, giving each team identical cell placements.

    Examples (grid_size=4, center=102):
        _cell_origin(98,  102, 4)  →  98    (cell [98, 102))
        _cell_origin(101, 102, 4)  →  98    (cell [98, 102))
        _cell_origin(102, 102, 4)  →  102   (cell [102, 106))
        _cell_origin(105, 102, 4)  →  102   (cell [102, 106))
    """
    return center + int(math.floor((coord - center) / grid_size)) * grid_size


# ---------------------------------------------------------------------------
# Adaptive grid size (shared with traffic graph)
# ---------------------------------------------------------------------------


def _adaptive_grid_size(total_blocks: int) -> int:
    """Compute map-adaptive grid cell size from total playable block count.

    Returns a grid_size such that the map is divided into roughly 300 cells.
    Minimum grid_size is 2 to avoid degenerate single-block grids.
    """
    return max(2, round(math.sqrt(max(total_blocks, 1) / 300)))


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class GridCell:
    """One rasterized grid cell with geometry attributes."""

    cx: int                      # grid-aligned x origin (block index, lower-left corner)
    cz: int                      # grid-aligned z origin (block index, lower-left corner)
    location_type: str           # 'island' | 'build_region'
    island_id: Optional[int]     # set for island cells; None for build-region cells


@dataclass
class GridBase:
    """All geometry-derived grid cells for one map at one grid_size.

    Produced by rasterize_map_polygons().  Serves as the shared geometry
    substrate for both build_geometry_graph() and build_traffic_graph().

    Attributes
    ----------
    map_slug:
        Map identifier.
    grid_size:
        Cell side length in blocks.
    center_x, center_z:
        Map centre (rounded to nearest integer) used to anchor grid cell
        boundaries.  The grid is aligned so that cell boundaries exist at
        center_x ± n*grid_size and center_z ± n*grid_size, giving each
        team identical cell placements on symmetric maps.
        Use _cell_origin(coord, center_x, grid_size) to discretize a
        world coordinate to its cell origin consistently.
    cells:
        All rasterized cells (island + build-region).
    valid_cell_set:
        Fast-lookup set of (cx, cz) pairs for all cells.
    cell_island_id:
        Maps (cx, cz) → island_id (None for build-region cells).
    wool_pois:
        Wool anchor positions sourced from map_context poi_assignments.
        Each dict has keys: poi_type, coords, team, poi_color, island_id.
        May be replaced by DB-confirmed positions when calling
        build_geometry_graph(wool_pois=<db_list>).
    spawn_pois:
        Spawn anchor positions sourced from map_context poi_assignments.
        Same dict schema as wool_pois.
    """

    map_slug: str
    grid_size: int
    center_x: int = 0
    center_z: int = 0
    cells: list[GridCell] = field(default_factory=list)
    valid_cell_set: set[tuple[int, int]] = field(default_factory=set)
    cell_island_id: dict[tuple[int, int], Optional[int]] = field(default_factory=dict)
    wool_pois: list[dict] = field(default_factory=list)
    spawn_pois: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Rasterization
# ---------------------------------------------------------------------------


def rasterize_map_polygons(
    map_context: dict,
    map_slug: str,
    grid_size: int,
) -> GridBase:
    """Rasterize map_context island and build-region polygons into grid cells.

    For each grid cell whose centre falls within an island or build-region
    polygon a GridCell is created.  Island polygons take priority: if a cell
    centre falls inside both an island polygon and a build-region polygon,
    it is classified as 'island'.

    The cell centre is at (cx + grid_size/2, cz + grid_size/2).  Island
    polygon edges run along integer grid lines; the centre point is firmly
    inside any polygon that contains the full cell, matching the +0.5 block-
    centre convention used by PositionClassifier.

    Uses Shapely STRtree for bulk containment (O(N log M) rather than O(N·M)).

    Parameters
    ----------
    map_context:
        Parsed map_context.json dict.
    map_slug:
        Map identifier stored on the returned GridBase.
    grid_size:
        Cell side length in blocks.  All cx, cz values are multiples of
        grid_size.  Use _adaptive_grid_size(total_blocks) to match the
        traffic graph's default.

    Returns
    -------
    GridBase with cells, valid_cell_set, cell_island_id, wool_pois, and
    spawn_pois populated.
    """
    # ── Build Shapely polygons ─────────────────────────────────────────────
    island_polygons: list[tuple[int, Polygon]] = []  # (island_id, polygon)
    for island in map_context.get("islands", []):
        poly_data = island.get("simplified_polygon")
        if poly_data is None:
            continue
        exterior = poly_data.get("exterior", [])
        if len(exterior) < 3:
            continue
        holes = [h for h in poly_data.get("holes", []) if len(h) >= 3]
        try:
            polygon = Polygon(exterior, holes)
            if polygon.is_valid:
                island_polygons.append((island["id"], polygon))
        except Exception:
            pass

    build_polygons: list[Polygon] = []
    build_region = map_context.get("build_region")
    if build_region:
        for poly_data in build_region.get("buildable_void", []):
            exterior = poly_data.get("exterior", [])
            if len(exterior) < 3:
                continue
            holes = [h for h in poly_data.get("holes", []) if len(h) >= 3]
            try:
                polygon = Polygon(exterior, holes)
                if polygon.is_valid:
                    build_polygons.append(polygon)
            except Exception:
                pass

    island_tree: Optional[STRtree] = None
    island_ids_arr: list[int] = []
    build_tree: Optional[STRtree] = None

    if island_polygons:
        island_tree = STRtree([poly for _, poly in island_polygons])
        island_ids_arr = [iid for iid, _ in island_polygons]
    if build_polygons:
        build_tree = STRtree(build_polygons)

    if island_tree is None and build_tree is None:
        logger.warning(
            "rasterize_map_polygons('%s'): no island or build-region polygons found",
            map_slug,
        )
        return GridBase(map_slug=map_slug, grid_size=grid_size)

    # ── Enumerate candidate grid cells (center-aligned) ───────────────────
    bbox = map_context.get("bounding_box")
    if bbox is None:
        logger.warning(
            "rasterize_map_polygons('%s'): bounding_box absent in map_context", map_slug
        )
        return GridBase(map_slug=map_slug, grid_size=grid_size)

    min_x, max_x, min_z, max_z = bbox

    # ── Odd-grid-size heuristic ────────────────────────────────────────────
    # When the bounding box has odd width or height the map's symmetry axis
    # falls at a half-integer world coordinate.  For a symmetric cell layout
    # that axis must be at a cell boundary, which requires:
    #   center_x = axis - k * (grid_size / 2)  for some integer k.
    # With even grid_size this expression is never an integer, so no exact
    # solution exists.  Bumping to the next odd grid_size makes grid_size/2 a
    # half-integer, so the expression becomes integer for k=1.
    raw_center = map_context.get("map_center", [0, 0])
    raw_cx = float(raw_center[0])
    raw_cz = float(raw_center[1])

    axis_half_x = (raw_cx % 1.0) == 0.5
    axis_half_z = (raw_cz % 1.0) == 0.5

    if (axis_half_x or axis_half_z) and grid_size % 2 == 0:
        grid_size += 1
        logger.debug(
            "rasterize_map_polygons('%s'): half-integer map axis → bumped grid_size "
            "to %d for symmetric cell placement",
            map_slug, grid_size,
        )

    # For a half-integer axis with odd grid_size, shift center_x left by
    # grid_size/2 so the cell [center_x, center_x+grid_size) straddles the
    # axis and the grid is exactly symmetric.
    if axis_half_x and grid_size % 2 == 1:
        center_x = int(raw_cx - grid_size / 2)
    else:
        center_x = round(raw_cx)

    if axis_half_z and grid_size % 2 == 1:
        center_z = int(raw_cz - grid_size / 2)
    else:
        center_z = round(raw_cz)

    # Align start to the first cell boundary at or below min_x/min_z.
    cx_start = _cell_origin(min_x, center_x, grid_size)
    cz_start = _cell_origin(min_z, center_z, grid_size)
    cx_values = list(range(int(cx_start), int(max_x), grid_size))
    cz_values = list(range(int(cz_start), int(max_z), grid_size))

    all_cells_cx: list[int] = []
    all_cells_cz: list[int] = []
    for cx in cx_values:
        for cz in cz_values:
            all_cells_cx.append(cx)
            all_cells_cz.append(cz)

    if not all_cells_cx:
        return GridBase(map_slug=map_slug, grid_size=grid_size)

    half = grid_size / 2.0
    cell_centers_x = np.array(all_cells_cx, dtype=float) + half
    cell_centers_z = np.array(all_cells_cz, dtype=float) + half

    # ── Bulk containment via STRtree ──────────────────────────────────────
    n = len(cell_centers_x)
    location_type_arr = np.full(n, "void", dtype=object)
    island_id_arr = np.full(n, None, dtype=object)

    pts = shp_points(cell_centers_x, cell_centers_z)

    if island_tree is not None:
        result = island_tree.query(pts, predicate="within")
        # result shape: (2, k) — result[0]=point indices, result[1]=poly indices
        if result.shape[1] > 0:
            for pi, gi in zip(result[0], result[1]):
                if location_type_arr[pi] == "void":
                    location_type_arr[pi] = "island"
                    island_id_arr[pi] = island_ids_arr[gi]

    if build_tree is not None:
        void_mask = location_type_arr == "void"
        if void_mask.any():
            void_idx = np.where(void_mask)[0]
            void_pts = shp_points(cell_centers_x[void_idx], cell_centers_z[void_idx])
            result2 = build_tree.query(void_pts, predicate="within")
            if result2.shape[1] > 0:
                for pi in set(result2[0]):
                    location_type_arr[void_idx[pi]] = "build_region"

    # ── Build GridBase ─────────────────────────────────────────────────────
    cells: list[GridCell] = []
    valid_cell_set: set[tuple[int, int]] = set()
    cell_island_id: dict[tuple[int, int], Optional[int]] = {}

    for i in range(n):
        loc = location_type_arr[i]
        if loc == "void":
            continue
        cx = int(all_cells_cx[i])
        cz = int(all_cells_cz[i])
        iid = island_id_arr[i]
        cells.append(GridCell(
            cx=cx,
            cz=cz,
            location_type=loc,
            island_id=int(iid) if iid is not None else None,
        ))
        valid_cell_set.add((cx, cz))
        cell_island_id[(cx, cz)] = int(iid) if iid is not None else None

    # ── Collect POI anchors from map_context ───────────────────────────────
    poi = map_context.get("poi_assignments", {})

    wool_pois: list[dict] = []
    for w in poi.get("wools", []):
        color = w.get("wool_color") or w.get("color")
        wool_pois.append({
            "poi_type":  "wool",
            "coords":    [float(w["x"]), float(w["z"])],
            "team":      w.get("team"),
            "poi_color": color,
            "island_id": w.get("island_id"),
        })

    spawn_pois: list[dict] = []
    for sp in poi.get("spawns", []):
        spawn_pois.append({
            "poi_type":  "spawn",
            "coords":    [float(sp["x"]), float(sp["z"])],
            "team":      sp.get("team"),
            "poi_color": sp.get("team_color"),
            "island_id": sp.get("island_id"),
        })

    logger.debug(
        "rasterize_map_polygons('%s'): %d cells (%d island, %d build_region), "
        "grid_size=%d, %d wool POIs, %d spawn POIs",
        map_slug,
        len(cells),
        sum(1 for c in cells if c.location_type == "island"),
        sum(1 for c in cells if c.location_type == "build_region"),
        grid_size,
        len(wool_pois),
        len(spawn_pois),
    )

    return GridBase(
        map_slug=map_slug,
        grid_size=grid_size,
        center_x=center_x,
        center_z=center_z,
        cells=cells,
        valid_cell_set=valid_cell_set,
        cell_island_id=cell_island_id,
        wool_pois=wool_pois,
        spawn_pois=spawn_pois,
    )


# ---------------------------------------------------------------------------
# Convenience loader
# ---------------------------------------------------------------------------


def load_grid_base(output_dir: Path, map_slug: str, grid_size: int) -> GridBase:
    """Load map_context.json from output_dir and rasterize into a GridBase.

    Parameters
    ----------
    output_dir:
        Map output directory (e.g. output/tumbleweed).
    map_slug:
        Map identifier.
    grid_size:
        Cell side length in blocks.

    Raises
    ------
    FileNotFoundError
        If map_context.json is absent from output_dir.
    """
    context_path = output_dir / "map_context.json"
    if not context_path.exists():
        raise FileNotFoundError(
            f"map_context.json not found at {context_path}. "
            "Run 'ctw run --map <slug>' first."
        )
    with open(context_path, encoding="utf-8") as fh:
        map_context = json.load(fh)
    return rasterize_map_polygons(map_context, map_slug, grid_size)
