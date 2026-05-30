"""
Build region extraction from CTW map XML and block data.

Determines where players can build over the void between islands using:
1. XML <apply> elements with deny(void) filters and region references
2. Block 36 at y=0 in layout_y0.parquet (fallback for maps without XML regions)

Core math:
  The void-area region (negative/complement) carves out "allowed" zones from
  the universe.  We decompose it into children, discard spawn/wool/monument
  children (they have their own deny-build rules), and keep only structurally
  meaningful ones (bridges, lanes, the central rectangle).

  buildable_void = union(kept_children) - island_blocks
"""

from typing import Any, Optional

import pandas as pd
from shapely.geometry import box, Polygon, MultiPolygon
from shapely.ops import unary_union
from shapely.validation import make_valid

from common.geometry import BoundingBox, world_blocks_to_shapely
from .datatypes import MapData, ApplyRule
from .regions import Region


# Patterns in region IDs that should be excluded from buildable void.
# These regions typically have their own deny-build rules or don't extend
# to void level, so including them would inflate the buildable area.
_EXCLUDED_VOID_CHILD_PATTERNS = frozenset(['spawn', 'wool', 'monument'])


def extract_build_region(
    map_data: MapData,
    map_bounds: BoundingBox,
    island_polygons: list[Any],
    y0_df: Optional[pd.DataFrame] = None,
) -> Optional[dict]:
    """
    Extract the buildable void region for a map.

    Args:
        map_data: Parsed MapData from XML (has .regions, .apply_rules)
        map_bounds: (min_x, max_x, min_z, max_z) bounding box
        island_polygons: List of Shapely polygons for each island
        y0_df: Pre-loaded Y=0 layout DataFrame for block-36 fallback.
            Pass None when layout_y0.parquet was not extracted.

    Returns:
        Dict with build region info, or None if no build region found.
    """
    # Convert bounding box: map_bounds is (min_x, max_x, min_z, max_z)
    # Shapely bounds format: (min_x, min_z, max_x, max_z)
    PAD = 10
    shapely_bounds = (
        map_bounds[0] - PAD,
        map_bounds[2] - PAD,
        map_bounds[1] + PAD,
        map_bounds[3] + PAD,
    )

    # Try XML-based extraction first
    build_allowed = _extract_from_xml(map_data, shapely_bounds)

    source = "xml"
    if build_allowed is None or build_allowed.is_empty:
        # Fallback to y=0 build-platform blocks (block 36, water)
        build_allowed = _extract_y0_platform_region(y0_df)
        source = "y0_blocks"

    if build_allowed is None or build_allowed.is_empty:
        return None

    # Subtract island blocks to get buildable void
    island_union = _safe_union(island_polygons)
    buildable_void = build_allowed.difference(island_union)
    buildable_void = _ensure_valid(buildable_void)

    if buildable_void.is_empty:
        return None

    # Simplify for storage
    buildable_void = buildable_void.simplify(0.5, preserve_topology=True)

    return {
        'source': source,
        'polygons': _geometry_to_coords(build_allowed),
        'buildable_void': _geometry_to_coords(buildable_void),
        'buildable_void_area': round(float(buildable_void.area), 1),
    }


# ---------------------------------------------------------------------------
# XML-based extraction
# ---------------------------------------------------------------------------

def _extract_from_xml(map_data: MapData, shapely_bounds: tuple[float, float, float, float]) -> Optional[Polygon]:
    """
    Find build-allowed geometry from apply rules using two strategies:

    1. Void-complement (primary): rules with 'void' in a filter value whose
       region is a negative/complement — children of the void region are the
       allowed areas.
    2. Allow-always (fallback): rules with ``block="always"`` or
       ``block-place="always"`` pointing to a named region — that region IS
       the build-allowed area directly (no decomposition needed).  Used by
       maps like gethsemane that define a positive build-area instead of a
       void-complement.
    """
    if not hasattr(map_data, 'apply_rules') or not map_data.apply_rules:
        return None

    # ── Strategy 1: void-complement ───────────────────────────────────────
    allowed_parts = []
    for rule in _find_deny_void_rules(map_data.apply_rules):
        region = _resolve_rule_to_region(rule, map_data.regions)
        if region is None:
            continue
        allowed = _extract_allowed_from_void_region(
            region, map_data.regions, shapely_bounds
        )
        if allowed and not allowed.is_empty:
            allowed_parts.append(allowed)

    if allowed_parts:
        return _ensure_valid(_safe_union(allowed_parts))

    # ── Strategy 2: allow-always (positive build region) ──────────────────
    for rule in _find_allow_always_rules(map_data.apply_rules):
        region = _resolve_rule_to_region(rule, map_data.regions)
        if region is None:
            continue
        geom = region.to_shapely_2d(shapely_bounds, map_data.regions)
        if geom and not geom.is_empty:
            allowed_parts.append(_ensure_valid(geom))

    if not allowed_parts:
        return None

    return _ensure_valid(_safe_union(allowed_parts))


def _find_deny_void_rules(apply_rules: list[ApplyRule]) -> list[ApplyRule]:
    """Return apply rules whose filters reference 'void'."""
    void_rules = []
    for rule in apply_rules:
        for attr_val in [rule.block_filter, rule.block_place_filter,
                         rule.block_break_filter, rule.use_filter]:
            if attr_val and 'void' in attr_val.lower():
                void_rules.append(rule)
                break
    return void_rules


def _find_allow_always_rules(apply_rules: list[ApplyRule]) -> list[ApplyRule]:
    """Return apply rules that positively allow building in a named region.

    These use ``block="always"`` or ``block-place="always"`` and reference a
    specific region (as opposed to global rules with no region).  The region
    directly defines the build-allowed area — no void decomposition needed.
    """
    return [
        r for r in apply_rules
        if (r.block_filter == 'always' or r.block_place_filter == 'always')
        and (r.region_id or r.inline_region is not None)
    ]


def _resolve_rule_to_region(rule: ApplyRule, regions_dict: dict[str, Region]) -> Optional[Region]:
    """Resolve an apply rule to its Region object (not geometry)."""
    if rule.inline_region is not None:
        return rule.inline_region
    if rule.region_id and rule.region_id in regions_dict:
        return regions_dict[rule.region_id]
    return None


def _extract_allowed_from_void_region(
    region: Region,
    regions_dict: dict[str, Region],
    shapely_bounds: tuple[float, float, float, float],
) -> Optional[Any]:
    """
    Extract the build-allowed geometry from a void-deny region.

    For negative/complement regions (the common case), the "carved out"
    children represent areas excluded from the void-deny rule — i.e. areas
    where building IS allowed.  We filter out spawn/wool/monument children
    and keep only structurally meaningful ones (bridges, lanes, etc.).

    For other region types, falls back to universe - region geometry.
    """
    from .regions import NegativeRegion, ComplementRegion

    if isinstance(region, (NegativeRegion, ComplementRegion)):
        # Negative: universe - union(children)  → children are the allowed areas
        # Complement: base - union(rest)        → rest children are the allowed areas
        if isinstance(region, NegativeRegion):
            subtracted = region.children
        else:
            subtracted = region.children[1:] if len(region.children) > 1 else []

        kept = [c for c in subtracted if not _should_exclude_void_child(c)]

        if not kept:
            return None

        child_geoms = [
            c.to_shapely_2d(shapely_bounds, regions_dict) for c in kept
        ]
        return _safe_union(child_geoms)

    # Fallback for other region types: universe minus the region
    universe = box(*shapely_bounds)
    region_geom = region.to_shapely_2d(shapely_bounds, regions_dict)
    if region_geom is None or region_geom.is_empty:
        return None
    return _ensure_valid(universe.difference(region_geom))


# ---------------------------------------------------------------------------
# Void-child filtering
# ---------------------------------------------------------------------------

def _child_region_ids(child: Region) -> list[str]:
    """Collect all IDs associated with a region child for pattern matching."""
    ids = []
    if child.id:
        ids.append(child.id)
    if getattr(child, 'ref_id', ''):
        ids.append(child.ref_id)
    if getattr(child, 'ref_region_id', ''):
        ids.append(child.ref_region_id)
    return ids


def _should_exclude_void_child(child: Region) -> bool:
    """
    Check if a child of a void-area region should be excluded.

    Children whose IDs match spawn/wool/monument patterns are excluded
    because they have their own deny-build rules or don't extend to
    void level.
    """
    for rid in _child_region_ids(child):
        lower = rid.lower()
        if any(p in lower for p in _EXCLUDED_VOID_CHILD_PATTERNS):
            return True
    return False


# ---------------------------------------------------------------------------
# y=0 build-platform block fallback
# ---------------------------------------------------------------------------

# Block IDs that indicate a build platform at y=0.
# The PGM plugin treats any non-air block at y=0 under a player as
# non-void, so these blocks silently define build-allowed areas:
#   36 — invisible piston head (used when islands are raised above y=0)
#    8 — flowing water  }  used on flat maps where the void between
#    9 — stationary water}  islands is filled with water at y=0
_Y0_PLATFORM_BLOCK_IDS: frozenset[int] = frozenset([36, 8, 9])


def _extract_y0_platform_region(y0_df: Optional[pd.DataFrame]) -> Optional[Any]:
    """Build a region from build-platform blocks at y=0.

    Recognises block 36 (invisible piston head), flowing water (8), and
    stationary water (9).  All three indicate areas where the PGM plugin
    implicitly allows building because a non-air block exists at y=0.

    Args:
        y0_df: Pre-loaded Y=0 layout DataFrame, or None if unavailable.
    """
    if y0_df is None or 'block_id' not in y0_df.columns:
        return None

    platform = y0_df[y0_df['block_id'].isin(_Y0_PLATFORM_BLOCK_IDS)]
    if platform.empty:
        return None

    x_col = 'world_x' if 'world_x' in platform.columns else 'x'
    z_col = 'world_z' if 'world_z' in platform.columns else 'z'

    coords = list(zip(platform[x_col].astype(float), platform[z_col].astype(float)))
    if not coords:
        return None

    return _ensure_valid(world_blocks_to_shapely(coords))


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _safe_union(geoms: list[Any]) -> Polygon:
    """Union a list of geometries, skipping empty/invalid ones."""
    valid = [g for g in geoms if g is not None and not g.is_empty]
    if not valid:
        return Polygon()
    result = unary_union(valid)
    return _ensure_valid(result)


def _ensure_valid(geom: Any) -> Any:
    """Ensure geometry is valid."""
    if geom is None:
        return Polygon()
    if not geom.is_valid:
        geom = make_valid(geom)
    return geom


def _geometry_to_coords(geom: Any) -> list[dict]:
    """Convert Shapely geometry to list of polygon coord dicts."""
    from shapely.geometry import GeometryCollection

    if geom is None or geom.is_empty:
        return []

    polygons = []
    if isinstance(geom, Polygon):
        polygons = [geom]
    elif isinstance(geom, MultiPolygon):
        polygons = list(geom.geoms)
    elif isinstance(geom, GeometryCollection):
        polygons = [g for g in geom.geoms if isinstance(g, Polygon)]
    else:
        return []

    result = []
    for poly in polygons:
        if poly.is_empty:
            continue
        exterior = [
            [round(float(x), 1), round(float(z), 1)]
            for x, z in poly.exterior.coords
        ]
        holes = [
            [[round(float(x), 1), round(float(z), 1)] for x, z in ring.coords]
            for ring in poly.interiors
        ]
        result.append({'exterior': exterior, 'holes': holes})

    return result
