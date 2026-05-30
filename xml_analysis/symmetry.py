"""Utilities for detecting mirror and translate relationships between region bounds.

Bounds are expressed as ((min_x, min_z), (max_x, max_z)) — the same format
returned by Region.get_bounds_2d().
"""
from __future__ import annotations


def mirror_bounds_2d(
    bounds: tuple,
    origin_x: float,
    origin_z: float,
    normal_x: float,
    normal_z: float,
) -> tuple:
    """Return the mirror of *bounds* across the plane at (origin_x, origin_z).

    normal_x / normal_z act as axis selectors: a non-zero value means that
    axis is reflected (x' = 2*origin_x - x or z' = 2*origin_z - z).
    Both axes can be active simultaneously for a 180° point-reflection.
    """
    (min_x, min_z), (max_x, max_z) = bounds
    if normal_x != 0:
        min_x, max_x = 2 * origin_x - max_x, 2 * origin_x - min_x
    if normal_z != 0:
        min_z, max_z = 2 * origin_z - max_z, 2 * origin_z - min_z
    return (min(min_x, max_x), min(min_z, max_z)), (max(min_x, max_x), max(min_z, max_z))


def is_mirror_of(
    bounds_a: tuple,
    bounds_b: tuple,
    origin_x: float,
    origin_z: float,
    normal_x: float,
    normal_z: float,
    tol: float = 0.01,
) -> bool:
    """Return True if bounds_b is the mirror of bounds_a across the given plane."""
    (m_min_x, m_min_z), (m_max_x, m_max_z) = mirror_bounds_2d(
        bounds_a, origin_x, origin_z, normal_x, normal_z
    )
    (b_min_x, b_min_z), (b_max_x, b_max_z) = bounds_b
    return (
        abs(m_min_x - b_min_x) <= tol
        and abs(m_min_z - b_min_z) <= tol
        and abs(m_max_x - b_max_x) <= tol
        and abs(m_max_z - b_max_z) <= tol
    )


def translate_offset_2d(
    bounds_a: tuple,
    bounds_b: tuple,
    tol: float = 0.01,
) -> tuple[float, float] | None:
    """If bounds_b is a translate of bounds_a return (offset_x, offset_z), else None.

    A valid translate means every corner of bounds_a shifts by the same (dx, dz)
    to reach bounds_b.  If the two rectangles have different sizes this returns None.
    """
    (a_min_x, a_min_z), (a_max_x, a_max_z) = bounds_a
    (b_min_x, b_min_z), (b_max_x, b_max_z) = bounds_b
    dx = b_min_x - a_min_x
    dz = b_min_z - a_min_z
    if abs((b_max_x - a_max_x) - dx) <= tol and abs((b_max_z - a_max_z) - dz) <= tol:
        return dx, dz
    return None
