"""
Region class definitions for Minecraft map regions.

Supports various region types: rectangle, cuboid, cylinder, circle, sphere, block, point,
and composite regions: union, negative, complement, intersect.
Each region can be converted to a Shapely 2D geometry via to_shapely_2d().
"""

import math
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Shapely helpers (lazy import to avoid hard dependency at module level)
# ---------------------------------------------------------------------------

def _shapely_box(min_x, min_z, max_x, max_z):
    from shapely.geometry import box
    return box(min(min_x, max_x), min(min_z, max_z),
               max(min_x, max_x), max(min_z, max_z))


def _expand_block_bounds(min_x, min_z, max_x, max_z):
    """Expand inclusive block bounds to unit-square extents.

    Coordinate convention:
      - Block (x, z) occupies [x, x+1] × [z, z+1]
      - XML rectangular regions specify *included* blocks via min/max
      - Convert to polygon extents by keeping min as-is and adding +1 to max

    Returns ``(min_x, min_z, max_x+1, max_z+1)`` in Shapely box argument
    order ``(minx, miny, maxx, maxy)``.  The equivalent pipeline utility for
    bounding-box work is :func:`common.geometry.get_grid_extent`, which
    returns ``(min_x, max_x+1, min_z, max_z+1)`` in ``BBox`` order.
    """
    return (min_x, min_z, max_x + 1, max_z + 1)


def _shapely_empty():
    from shapely.geometry import Polygon
    return Polygon()


def _shapely_circle(cx, cz, radius, resolution=32):
    from shapely.geometry import Point
    return Point(cx, cz).buffer(radius, resolution=resolution)


def _shapely_union(geoms):
    from shapely.ops import unary_union
    valid = [g for g in geoms if g and not g.is_empty]
    if not valid:
        return _shapely_empty()
    return unary_union(valid)


def _make_valid(geom):
    if geom.is_valid:
        return geom
    from shapely.validation import make_valid
    return make_valid(geom)


# ---------------------------------------------------------------------------
# Base Region
# ---------------------------------------------------------------------------

@dataclass
class Region:
    """Base class for all region types."""
    id: str = ""
    region_type: str = "unknown"

    @staticmethod
    def parse_value(value: str) -> float:
        """Parse a coordinate value, handling 'oo' as infinity."""
        value = value.strip()
        if value.lower() == "oo":
            return float('inf')
        if value.lower() == "-oo":
            return float('-inf')
        if '$' in value:
            return 0.0
        return float(value)

    def get_bounds_2d(self) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
        """Get 2D bounding box (x_min, z_min), (x_max, z_max)."""
        return None

    def to_shapely_2d(self, bounds: Tuple[float, float, float, float],
                      registry: Dict[str, 'Region'] = None):
        """
        Convert to a Shapely 2D geometry.

        Args:
            bounds: (min_x, min_z, max_x, max_z) map extent for infinite regions.
            registry: Dict of region_id -> Region for resolving references.

        Returns:
            A shapely geometry (Polygon, MultiPolygon, or empty).
        """
        return _shapely_empty()


# ---------------------------------------------------------------------------
# Primitive regions
# ---------------------------------------------------------------------------

@dataclass
class RectangleRegion(Region):
    """2D rectangular region defined by min and max corners."""
    min_x: float = 0.0
    min_z: float = 0.0
    max_x: float = 0.0
    max_z: float = 0.0
    region_type: str = "rectangle"

    def get_bounds_2d(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        return (
            (min(self.min_x, self.max_x), min(self.min_z, self.max_z)),
            (max(self.min_x, self.max_x), max(self.min_z, self.max_z)),
        )

    def to_shapely_2d(self, bounds, registry=None):
        return _shapely_box(self.min_x, self.min_z, self.max_x, self.max_z)


@dataclass
class CuboidRegion(Region):
    """3D cuboid region defined by min and max corners."""
    min_x: float = 0.0
    min_y: float = 0.0
    min_z: float = 0.0
    max_x: float = 0.0
    max_y: float = 0.0
    max_z: float = 0.0
    region_type: str = "cuboid"

    def get_bounds_2d(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        return (
            (min(self.min_x, self.max_x), min(self.min_z, self.max_z)),
            (max(self.min_x, self.max_x), max(self.min_z, self.max_z)),
        )

    def to_shapely_2d(self, bounds, registry=None):
        return _shapely_box(self.min_x, self.min_z, self.max_x, self.max_z)


@dataclass
class CylinderRegion(Region):
    """Cylindrical region defined by base center, radius, and height."""
    base_x: float = 0.0
    base_y: float = 0.0
    base_z: float = 0.0
    radius: float = 0.0
    height: float = 0.0
    region_type: str = "cylinder"

    def get_bounds_2d(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        return (
            (self.base_x - self.radius, self.base_z - self.radius),
            (self.base_x + self.radius, self.base_z + self.radius)
        )

    def to_shapely_2d(self, bounds, registry=None):
        if self.radius <= 0:
            return _shapely_empty()
        return _shapely_circle(self.base_x, self.base_z, self.radius)


@dataclass
class CircleRegion(Region):
    """2D circular region defined by center and radius."""
    center_x: float = 0.0
    center_z: float = 0.0
    radius: float = 0.0
    region_type: str = "circle"

    def get_bounds_2d(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        return (
            (self.center_x - self.radius, self.center_z - self.radius),
            (self.center_x + self.radius, self.center_z + self.radius)
        )

    def to_shapely_2d(self, bounds, registry=None):
        if self.radius <= 0:
            return _shapely_empty()
        return _shapely_circle(self.center_x, self.center_z, self.radius)


@dataclass
class SphereRegion(Region):
    """Spherical region defined by origin and radius."""
    origin_x: float = 0.0
    origin_y: float = 0.0
    origin_z: float = 0.0
    radius: float = 0.0
    region_type: str = "sphere"

    def get_bounds_2d(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        return (
            (self.origin_x - self.radius, self.origin_z - self.radius),
            (self.origin_x + self.radius, self.origin_z + self.radius)
        )

    def to_shapely_2d(self, bounds, registry=None):
        if self.radius <= 0:
            return _shapely_empty()
        return _shapely_circle(self.origin_x, self.origin_z, self.radius)


@dataclass
class BlockRegion(Region):
    """Single block region."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    region_type: str = "block"

    def get_bounds_2d(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        return (self.x, self.z), (self.x, self.z)

    def to_shapely_2d(self, bounds, registry=None):
        min_x, min_z, max_x, max_z = _expand_block_bounds(
            self.x, self.z, self.x, self.z
        )
        return _shapely_box(min_x, min_z, max_x, max_z)


@dataclass
class PointRegion(Region):
    """Single point region."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    region_type: str = "point"

    def get_bounds_2d(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        return (self.x, self.z), (self.x, self.z)

    def to_shapely_2d(self, bounds, registry=None):
        return _shapely_box(self.x - 0.5, self.z - 0.5, self.x + 0.5, self.z + 0.5)


# ---------------------------------------------------------------------------
# Composite regions
# ---------------------------------------------------------------------------

@dataclass
class UnionRegion(Region):
    """Union of multiple regions."""
    children: List[Region] = field(default_factory=list)
    region_type: str = "union"

    def get_bounds_2d(self) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
        if not self.children:
            return None
        bounds_list = [child.get_bounds_2d() for child in self.children if child.get_bounds_2d()]
        if not bounds_list:
            return None
        min_x = min(b[0][0] for b in bounds_list)
        min_z = min(b[0][1] for b in bounds_list)
        max_x = max(b[1][0] for b in bounds_list)
        max_z = max(b[1][1] for b in bounds_list)
        return (min_x, min_z), (max_x, max_z)

    def to_shapely_2d(self, bounds, registry=None):
        child_geoms = [c.to_shapely_2d(bounds, registry) for c in self.children]
        return _shapely_union(child_geoms)


@dataclass
class NegativeRegion(Region):
    """Negative/inverted region: universe minus union of all children."""
    children: List[Region] = field(default_factory=list)
    region_type: str = "negative"

    def get_bounds_2d(self) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
        if self.children:
            return self.children[0].get_bounds_2d()
        return None

    def to_shapely_2d(self, bounds, registry=None):
        universe = _shapely_box(bounds[0], bounds[1], bounds[2], bounds[3])
        child_union = _shapely_union(
            [c.to_shapely_2d(bounds, registry) for c in self.children]
        )
        result = universe.difference(child_union)
        return _make_valid(result)


@dataclass
class ComplementRegion(Region):
    """Complement region: first child minus all subsequent children."""
    children: List[Region] = field(default_factory=list)
    region_type: str = "complement"

    def get_bounds_2d(self) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
        if self.children:
            return self.children[0].get_bounds_2d()
        return None

    def to_shapely_2d(self, bounds, registry=None):
        if not self.children:
            return _shapely_empty()
        base = self.children[0].to_shapely_2d(bounds, registry)
        if len(self.children) > 1:
            subtract = _shapely_union(
                [c.to_shapely_2d(bounds, registry) for c in self.children[1:]]
            )
            base = base.difference(subtract)
        return _make_valid(base)


@dataclass
class IntersectRegion(Region):
    """Intersection of multiple regions."""
    children: List[Region] = field(default_factory=list)
    region_type: str = "intersect"

    def get_bounds_2d(self) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
        if self.children:
            return self.children[0].get_bounds_2d()
        return None

    def to_shapely_2d(self, bounds, registry=None):
        if not self.children:
            return _shapely_empty()
        result = self.children[0].to_shapely_2d(bounds, registry)
        for child in self.children[1:]:
            result = result.intersection(child.to_shapely_2d(bounds, registry))
        return _make_valid(result)


# ---------------------------------------------------------------------------
# Transformation regions
# ---------------------------------------------------------------------------

@dataclass
class MirrorRegion(Region):
    """Mirror of a region across a plane defined by origin and normal vector.

    The source region can be provided as an inline child (source) or as an
    ID reference (ref_region_id) resolved via the registry.
    """
    source: Optional[Region] = None
    ref_region_id: str = ""
    origin_x: float = 0.0
    origin_y: float = 0.0
    origin_z: float = 0.0
    normal_x: float = 0.0
    normal_y: float = 0.0
    normal_z: float = 0.0
    region_type: str = "mirror"

    def _resolve_source(self, bounds, registry):
        if self.source:
            return self.source.to_shapely_2d(bounds, registry)
        if registry and self.ref_region_id in registry:
            return registry[self.ref_region_id].to_shapely_2d(bounds, registry)
        return _shapely_empty()

    def get_bounds_2d(self):
        source = self.source
        if source is None:
            return None
        source_bounds = source.get_bounds_2d()
        if source_bounds is None:
            return None
        (min_x, min_z), (max_x, max_z) = source_bounds
        if self.normal_x != 0:
            min_x, max_x = 2 * self.origin_x - max_x, 2 * self.origin_x - min_x
        if self.normal_z != 0:
            min_z, max_z = 2 * self.origin_z - max_z, 2 * self.origin_z - min_z
        return (min(min_x, max_x), min(min_z, max_z)), (max(min_x, max_x), max(min_z, max_z))

    def to_shapely_2d(self, bounds, registry=None):
        source_geom = self._resolve_source(bounds, registry)
        if source_geom.is_empty:
            return source_geom
        from shapely.affinity import scale
        xfact = -1 if self.normal_x != 0 else 1
        zfact = -1 if self.normal_z != 0 else 1  # shapely y = minecraft z
        return scale(source_geom, xfact=xfact, yfact=zfact,
                     origin=(self.origin_x, self.origin_z))


@dataclass
class TranslateRegion(Region):
    """Translated copy of a region, offset by (x, y, z) blocks.

    The source region can be provided as an inline child (source) or as an
    ID reference (ref_region_id) resolved via the registry.
    """
    source: Optional[Region] = None
    ref_region_id: str = ""
    offset_x: float = 0.0
    offset_y: float = 0.0
    offset_z: float = 0.0
    region_type: str = "translate"

    def _resolve_source(self, bounds, registry):
        if self.source:
            return self.source.to_shapely_2d(bounds, registry)
        if registry and self.ref_region_id in registry:
            return registry[self.ref_region_id].to_shapely_2d(bounds, registry)
        return _shapely_empty()

    def get_bounds_2d(self):
        source = self.source
        if source is None:
            return None
        source_bounds = source.get_bounds_2d()
        if source_bounds is None:
            return None
        (min_x, min_z), (max_x, max_z) = source_bounds
        return (min_x + self.offset_x, min_z + self.offset_z), \
               (max_x + self.offset_x, max_z + self.offset_z)

    def to_shapely_2d(self, bounds, registry=None):
        source_geom = self._resolve_source(bounds, registry)
        if source_geom.is_empty:
            return source_geom
        from shapely.affinity import translate
        return translate(source_geom, xoff=self.offset_x, yoff=self.offset_z)


# ---------------------------------------------------------------------------
# Reference and special regions
# ---------------------------------------------------------------------------

@dataclass
class RegionReference(Region):
    """Reference to another named region: <region id="some-id"/>."""
    ref_id: str = ""
    region_type: str = "reference"

    def to_shapely_2d(self, bounds, registry=None):
        if registry and self.ref_id in registry:
            return registry[self.ref_id].to_shapely_2d(bounds, registry)
        return _shapely_empty()


@dataclass
class EverywhereRegion(Region):
    """Represents the entire world (<everywhere/>)."""
    region_type: str = "everywhere"

    def to_shapely_2d(self, bounds, registry=None):
        return _shapely_box(bounds[0], bounds[1], bounds[2], bounds[3])


@dataclass
class AboveRegion(Region):
    """Everything above a Y level. In 2D projection = everywhere."""
    y: float = 0.0
    region_type: str = "above"

    def to_shapely_2d(self, bounds, registry=None):
        return _shapely_box(bounds[0], bounds[1], bounds[2], bounds[3])
