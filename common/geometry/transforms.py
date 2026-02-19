"""CanonicalTransform, RasterMask, and raster-to-world helpers. See COORDINATE_SYSTEMS.md."""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import Tuple


# ---------------------------------------------------------------------------
# Internal rotation helper
# ---------------------------------------------------------------------------

def _rotate_points(points: np.ndarray, degrees: int) -> np.ndarray:
    """Rotate 2-D (x, z) points by an exact multiple of 90 degrees.

    Args:
        points: Nx2 float or int array of (x, z) coordinates.
        degrees: Rotation angle; must be 0, 90, 180, or 270 (mod 360).

    Returns:
        Nx2 array of rotated coordinates (same dtype promotion as input).

    Raises:
        ValueError: If *degrees* is not a multiple of 90.
    """
    d = degrees % 360
    if d == 0:
        return points.copy()
    elif d == 90:
        # (x, z) -> (-z, x)
        return np.column_stack([-points[:, 1], points[:, 0]])
    elif d == 180:
        # (x, z) -> (-x, -z)
        return -points.copy()
    elif d == 270:
        # (x, z) -> (z, -x)
        return np.column_stack([points[:, 1], -points[:, 0]])
    else:
        raise ValueError(f"Rotation must be a multiple of 90, got {degrees}")


# ---------------------------------------------------------------------------
# CanonicalTransform
# ---------------------------------------------------------------------------

@dataclass
class CanonicalTransform:
    """Encodes the D4 transformation between world and canonical space.

    The **forward** transform (:meth:`to_canonical`) applies:

    1. If ``mirror`` is True: flip the X axis (``x -> -x``).
    2. Rotate by ``rotation`` degrees (0/90/180/270).
    3. Add ``translation`` so that the minimum coordinate equals 0.

    The **reverse** transform (:meth:`to_original`) undoes these steps in
    reverse order: subtract translation, counter-rotate, un-mirror.

    ``world_center`` is unused and kept at zeros for API compatibility.

    Attributes:
        rotation: Rotation angle in degrees (0, 90, 180, or 270).
        mirror:   Whether the X axis is flipped before rotation.
        translation: 2-vector added after rotation (equals ``-min_vals``).
        world_center: Unused; kept at zeros for compatibility.
    """
    rotation: int                    # 0, 90, 180, 270 degrees
    mirror: bool                     # Whether X is flipped before rotation
    translation: np.ndarray          # 2-vector added after rotation (= -min_vals)
    world_center: np.ndarray         # unused, kept for compatibility (zeros)

    def to_canonical(self, points: np.ndarray) -> np.ndarray:
        """Transform world (x, z) block indices to canonical space.

        Args:
            points: Nx2 array of world (x, z) integer block indices.

        Returns:
            Nx2 integer array of canonical (x, z) indices.
        """
        pts = np.round(points).astype(int)
        if self.mirror:
            pts = pts.copy()
            pts[:, 0] = -pts[:, 0]
        pts = _rotate_points(pts.astype(float), self.rotation)
        pts = pts + self.translation
        return np.round(pts).astype(int)

    def to_original(self, points: np.ndarray) -> np.ndarray:
        """Transform canonical (x, z) block indices back to world space.

        Args:
            points: Nx2 array of canonical (x, z) integer block indices.

        Returns:
            Nx2 float array of world (x, z) coordinates.
        """
        pts = points.astype(float) - self.translation
        pts = _rotate_points(pts, -self.rotation % 360)
        if self.mirror:
            pts[:, 0] = -pts[:, 0]
        return pts


# ---------------------------------------------------------------------------
# RasterMask
# ---------------------------------------------------------------------------

@dataclass
class RasterMask:
    """Boolean mask for a rasterised island.

    The mask is indexed as ``mask[r, c]`` where ``r`` corresponds to the
    z-axis and ``c`` to the x-axis in canonical space.

    Coordinate mapping::

        canonical (x, z)  <-->  raster (r, c)
        r = z - origin[1]       z = r + origin[1]
        c = x - origin[0]       x = c + origin[0]

    For a mask built with *padding* p the origin is ``(-p, -p)``.

    Attributes:
        mask:    (H, W) boolean array.
        padding: Number of empty pixels added around the tight bbox.
        origin:  (x, z) of ``mask[0, 0]`` in canonical coordinates.
    """
    mask: np.ndarray                 # (H, W) bool
    padding: int                     # Padding applied around tight bbox
    origin: np.ndarray               # (x, z) of mask[0, 0] in canonical coords

    def rc_to_canonical(self, r: int, c: int) -> Tuple[int, int]:
        """Convert raster (r, c) indices to canonical (x, z).

        Args:
            r: Row index in the mask array (z-axis direction).
            c: Column index in the mask array (x-axis direction).

        Returns:
            ``(x, z)`` canonical integer coordinates.
        """
        x = c + int(self.origin[0])
        z = r + int(self.origin[1])
        return (x, z)

    def canonical_to_rc(self, x: int, z: int) -> Tuple[int, int]:
        """Convert canonical (x, z) to raster (r, c) indices.

        Args:
            x: Canonical x index.
            z: Canonical z index.

        Returns:
            ``(r, c)`` raster array indices.
        """
        r = z - int(self.origin[1])
        c = x - int(self.origin[0])
        return (r, c)


# ---------------------------------------------------------------------------
# Raster → World convenience helpers
# ---------------------------------------------------------------------------

def raster_to_world_path(
    pixel_path: np.ndarray,
    raster: RasterMask,
    transform: CanonicalTransform,
) -> np.ndarray:
    """Convert a raster pixel path to world-space coordinates.

    Combines the two-step raster → canonical → world conversion::

        (r, c) --[rc_to_canonical]--> (x_c, z_c) --[to_original]--> (x_w, z_w)

    Args:
        pixel_path: Px2 integer array of (r, c) raster coordinates.
        raster:     :class:`RasterMask` providing the canonical origin.
        transform:  :class:`CanonicalTransform` for canonical → world mapping.

    Returns:
        Px2 float array of world (x, z) coordinates.
    """
    canonical_pts = np.array(
        [raster.rc_to_canonical(r, c) for r, c in pixel_path],
        dtype=float,
    )
    return transform.to_original(canonical_pts)


def raster_to_world_point(
    rc: Tuple[int, int],
    raster: RasterMask,
    transform: CanonicalTransform,
) -> np.ndarray:
    """Convert a single raster (r, c) position to world-space coordinates.

    Args:
        rc:        ``(r, c)`` raster position.
        raster:    :class:`RasterMask` providing the canonical origin.
        transform: :class:`CanonicalTransform` for canonical → world mapping.

    Returns:
        1-D float array ``[x_w, z_w]`` in world space.
    """
    cx, cz = raster.rc_to_canonical(rc[0], rc[1])
    return transform.to_original(np.array([[cx, cz]], dtype=float))[0]
