"""
Region class definitions for Minecraft map regions.

Supports various region types: rectangle, cuboid, cylinder, circle, sphere, block, point,
and composite regions: union, negative, complement.
"""

import re
from typing import List, Tuple, Optional
from dataclasses import dataclass, field


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
        """
        Get 2D bounding box (x_min, z_min), (x_max, z_max).

        Returns None if region cannot be represented in 2D.
        """
        return None


@dataclass
class RectangleRegion(Region):
    """2D rectangular region defined by min and max corners."""
    min_x: float = 0.0
    min_z: float = 0.0
    max_x: float = 0.0
    max_z: float = 0.0
    region_type: str = "rectangle"

    def get_bounds_2d(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        # Normalize coordinates to ensure min <= max
        actual_min_x = min(self.min_x, self.max_x)
        actual_max_x = max(self.min_x, self.max_x)
        actual_min_z = min(self.min_z, self.max_z)
        actual_max_z = max(self.min_z, self.max_z)
        return (actual_min_x, actual_min_z), (actual_max_x, actual_max_z)


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
        # Normalize coordinates to ensure min <= max
        actual_min_x = min(self.min_x, self.max_x)
        actual_max_x = max(self.min_x, self.max_x)
        actual_min_z = min(self.min_z, self.max_z)
        actual_max_z = max(self.min_z, self.max_z)
        return (actual_min_x, actual_min_z), (actual_max_x, actual_max_z)


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
        # Approximate cylinder as bounding square
        return (
            (self.base_x - self.radius, self.base_z - self.radius),
            (self.base_x + self.radius, self.base_z + self.radius)
        )


@dataclass
class CircleRegion(Region):
    """2D circular region defined by center and radius."""
    center_x: float = 0.0
    center_z: float = 0.0
    radius: float = 0.0
    region_type: str = "circle"

    def get_bounds_2d(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        # Approximate circle as bounding square
        return (
            (self.center_x - self.radius, self.center_z - self.radius),
            (self.center_x + self.radius, self.center_z + self.radius)
        )


@dataclass
class SphereRegion(Region):
    """Spherical region defined by origin and radius."""
    origin_x: float = 0.0
    origin_y: float = 0.0
    origin_z: float = 0.0
    radius: float = 0.0
    region_type: str = "sphere"

    def get_bounds_2d(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        # Approximate sphere as bounding square
        return (
            (self.origin_x - self.radius, self.origin_z - self.radius),
            (self.origin_x + self.radius, self.origin_z + self.radius)
        )


@dataclass
class BlockRegion(Region):
    """Single block region."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    region_type: str = "block"

    def get_bounds_2d(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        return (self.x, self.z), (self.x, self.z)


@dataclass
class PointRegion(Region):
    """Single point region."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    region_type: str = "point"

    def get_bounds_2d(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        return (self.x, self.z), (self.x, self.z)


@dataclass
class UnionRegion(Region):
    """Union of multiple regions."""
    children: List[Region] = field(default_factory=list)
    region_type: str = "union"

    def get_bounds_2d(self) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
        """Get combined bounding box of all children."""
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


@dataclass
class NegativeRegion(Region):
    """Negative/inverted region."""
    children: List[Region] = field(default_factory=list)
    region_type: str = "negative"

    def get_bounds_2d(self) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
        # Negative regions are tricky - for visualization, show the child bounds
        if self.children:
            return self.children[0].get_bounds_2d()
        return None


@dataclass
class ComplementRegion(Region):
    """Complement region (everything except the children)."""
    children: List[Region] = field(default_factory=list)
    region_type: str = "complement"

    def get_bounds_2d(self) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
        # Complement regions are infinite - for visualization, show the child bounds
        if self.children:
            return self.children[0].get_bounds_2d()
        return None
