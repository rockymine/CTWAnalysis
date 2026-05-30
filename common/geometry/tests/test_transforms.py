"""
Tests for common.geometry.transforms and world_blocks_to_shapely.

Covers:
  - _rotate_points: all four rotation angles
  - CanonicalTransform.to_canonical / to_original round-trips
  - RasterMask.rc_to_canonical / canonical_to_rc round-trips
  - raster_to_world_path / raster_to_world_point convenience helpers
  - world_blocks_to_shapely: bounds, area, empty input
"""

import unittest
import numpy as np

from common.geometry.transforms import (
    _rotate_points,
    CanonicalTransform,
    RasterMask,
    raster_to_world_path,
    raster_to_world_point,
)
from common.geometry.coordinates import world_blocks_to_shapely


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_transform(rotation=0, mirror=False, translation=(0, 0)):
    """Build a CanonicalTransform with given parameters."""
    return CanonicalTransform(
        rotation=rotation,
        mirror=mirror,
        translation=np.array(translation, dtype=float),

    )


def _make_raster(padding=1):
    """Build a minimal RasterMask with origin = (-padding, -padding)."""
    mask = np.zeros((5, 5), dtype=bool)
    origin = np.array([-padding, -padding], dtype=float)
    return RasterMask(mask=mask, padding=padding, origin=origin)


# ---------------------------------------------------------------------------
# _rotate_points
# ---------------------------------------------------------------------------

class TestRotatePoints(unittest.TestCase):
    """_rotate_points exact-integer rotation."""

    def _pts(self, data):
        return np.array(data, dtype=float)

    def test_rotate_0(self):
        pts = self._pts([[1, 2], [3, 4]])
        result = _rotate_points(pts, 0)
        np.testing.assert_array_equal(result, pts)

    def test_rotate_90(self):
        # (x, z) -> (-z, x)
        pts = self._pts([[1, 2]])
        result = _rotate_points(pts, 90)
        np.testing.assert_array_equal(result, [[-2, 1]])

    def test_rotate_180(self):
        pts = self._pts([[1, 2]])
        result = _rotate_points(pts, 180)
        np.testing.assert_array_equal(result, [[-1, -2]])

    def test_rotate_270(self):
        # (x, z) -> (z, -x)
        pts = self._pts([[1, 2]])
        result = _rotate_points(pts, 270)
        np.testing.assert_array_equal(result, [[2, -1]])

    def test_rotate_360_is_identity(self):
        pts = self._pts([[5, -3]])
        result = _rotate_points(pts, 360)
        np.testing.assert_array_equal(result, pts)

    def test_rotate_bad_angle_raises(self):
        pts = self._pts([[1, 1]])
        with self.assertRaises(ValueError):
            _rotate_points(pts, 45)

    def test_rotate_90_four_times_is_identity(self):
        pts = self._pts([[7, -2], [0, 5]])
        result = pts.copy()
        for _ in range(4):
            result = _rotate_points(result, 90)
        np.testing.assert_array_almost_equal(result, pts)


# ---------------------------------------------------------------------------
# CanonicalTransform
# ---------------------------------------------------------------------------

class TestCanonicalTransform(unittest.TestCase):
    """CanonicalTransform.to_canonical / to_original."""

    def _roundtrip(self, transform, pts):
        """Assert canonical -> world -> canonical gives original (after re-shifting)."""
        canonical = transform.to_canonical(pts)
        back = transform.to_original(canonical)
        # to_original undoes the shift, rotation, and mirror — result should
        # match the *integer* inputs
        np.testing.assert_array_almost_equal(back, pts, decimal=6)

    def test_identity_transform(self):
        t = _make_transform(rotation=0, mirror=False, translation=(0, 0))
        pts = np.array([[3, 5], [7, 2]], dtype=float)
        canonical = t.to_canonical(pts)
        np.testing.assert_array_equal(canonical, pts.astype(int))
        back = t.to_original(canonical)
        np.testing.assert_array_almost_equal(back, pts)

    def test_translation_only(self):
        t = _make_transform(rotation=0, mirror=False, translation=(10, 20))
        pts = np.array([[0, 0], [5, 5]], dtype=float)
        canonical = t.to_canonical(pts)
        # translation is added: (0+10, 0+20), (5+10, 5+20)
        np.testing.assert_array_equal(canonical, [[10, 20], [15, 25]])
        back = t.to_original(canonical)
        np.testing.assert_array_almost_equal(back, pts)

    def test_rotation_90(self):
        t = _make_transform(rotation=90, mirror=False, translation=(0, 0))
        pts = np.array([[1, 0]], dtype=float)
        # rotate 90: (x,z) -> (-z, x) = (0, 1)
        canonical = t.to_canonical(pts)
        np.testing.assert_array_equal(canonical, [[0, 1]])
        back = t.to_original(canonical)
        np.testing.assert_array_almost_equal(back, pts)

    def test_rotation_180(self):
        t = _make_transform(rotation=180, mirror=False, translation=(0, 0))
        pts = np.array([[3, 4]], dtype=float)
        canonical = t.to_canonical(pts)
        np.testing.assert_array_equal(canonical, [[-3, -4]])
        back = t.to_original(canonical)
        np.testing.assert_array_almost_equal(back, pts)

    def test_mirror_only(self):
        t = _make_transform(rotation=0, mirror=True, translation=(0, 0))
        pts = np.array([[5, 3]], dtype=float)
        canonical = t.to_canonical(pts)
        # mirror flips x: (-5, 3)
        np.testing.assert_array_equal(canonical, [[-5, 3]])
        back = t.to_original(canonical)
        np.testing.assert_array_almost_equal(back, pts)

    def test_mirror_and_rotation_90(self):
        t = _make_transform(rotation=90, mirror=True, translation=(0, 0))
        pts = np.array([[2, 3]], dtype=float)
        # mirror: (-2, 3)  then rotate 90: (x,z)->(-z,x): (-3, -2)
        canonical = t.to_canonical(pts)
        np.testing.assert_array_equal(canonical, [[-3, -2]])
        back = t.to_original(canonical)
        np.testing.assert_array_almost_equal(back, pts)

    def test_full_d4_roundtrip_all_elements(self):
        """All 8 D4 elements correctly round-trip a set of points."""
        pts = np.array([[10, 5], [3, 8], [0, 0]], dtype=float)
        for rotation in [0, 90, 180, 270]:
            for mirror in [False, True]:
                t = _make_transform(rotation=rotation, mirror=mirror,
                                    translation=(0, 0))
                canonical = t.to_canonical(pts)
                back = t.to_original(canonical)
                np.testing.assert_array_almost_equal(
                    back, pts, decimal=5,
                    err_msg=f"Round-trip failed for rot={rotation} mirror={mirror}"
                )

    def test_translation_shifts_canonical(self):
        """Translation is added to canonical coords, subtracted in reverse."""
        t = _make_transform(rotation=0, mirror=False, translation=(5, 7))
        pts = np.array([[0, 0]], dtype=float)
        canonical = t.to_canonical(pts)
        np.testing.assert_array_equal(canonical, [[5, 7]])


# ---------------------------------------------------------------------------
# RasterMask
# ---------------------------------------------------------------------------

class TestRasterMask(unittest.TestCase):
    """RasterMask coordinate conversions."""

    def test_rc_to_canonical_no_padding(self):
        raster = RasterMask(
            mask=np.zeros((3, 3), dtype=bool),
            padding=0,
            origin=np.array([0.0, 0.0]),
        )
        self.assertEqual(raster.rc_to_canonical(0, 0), (0, 0))
        self.assertEqual(raster.rc_to_canonical(2, 1), (1, 2))

    def test_rc_to_canonical_with_padding(self):
        raster = _make_raster(padding=1)
        # origin = (-1, -1)
        # rc_to_canonical(r, c): x = c + (-1), z = r + (-1)
        self.assertEqual(raster.rc_to_canonical(1, 1), (0, 0))   # r=1, c=1 -> x=0, z=0
        self.assertEqual(raster.rc_to_canonical(2, 3), (2, 1))   # r=2, c=3 -> x=2, z=1

    def test_canonical_to_rc_no_padding(self):
        raster = RasterMask(
            mask=np.zeros((3, 3), dtype=bool),
            padding=0,
            origin=np.array([0.0, 0.0]),
        )
        self.assertEqual(raster.canonical_to_rc(0, 0), (0, 0))
        self.assertEqual(raster.canonical_to_rc(1, 2), (2, 1))

    def test_canonical_to_rc_with_padding(self):
        raster = _make_raster(padding=2)
        # origin = (-2, -2)
        # canonical_to_rc(x, z): r = z - (-2) = z + 2, c = x + 2
        self.assertEqual(raster.canonical_to_rc(0, 0), (2, 2))
        self.assertEqual(raster.canonical_to_rc(3, 1), (3, 5))

    def test_rc_canonical_roundtrip(self):
        raster = _make_raster(padding=3)
        for r in range(7):
            for c in range(7):
                x, z = raster.rc_to_canonical(r, c)
                r2, c2 = raster.canonical_to_rc(x, z)
                self.assertEqual((r, c), (r2, c2), f"Round-trip failed for r={r}, c={c}")


# ---------------------------------------------------------------------------
# raster_to_world_path / raster_to_world_point
# ---------------------------------------------------------------------------

class TestRasterToWorld(unittest.TestCase):
    """raster_to_world_path and raster_to_world_point helpers."""

    def _setup(self):
        """Return (raster, transform) for a simple 1-padding, identity-transform case."""
        raster = _make_raster(padding=1)  # origin=(-1,-1)
        transform = _make_transform(rotation=0, mirror=False, translation=(0, 0))
        return raster, transform

    def test_path_identity_transform(self):
        """With identity transform, world = canonical = raster - padding."""
        raster, transform = self._setup()
        # pixel (r=1, c=1) -> canonical (0, 0) -> world (0, 0)
        pixel_path = np.array([[1, 1], [2, 3]], dtype=int)
        world = raster_to_world_path(pixel_path, raster, transform)
        expected = np.array([[0.0, 0.0], [2.0, 1.0]])
        np.testing.assert_array_almost_equal(world, expected)

    def test_point_identity_transform(self):
        raster, transform = self._setup()
        world_pt = raster_to_world_point((2, 3), raster, transform)
        # canonical (2, 1), world (2, 1)
        np.testing.assert_array_almost_equal(world_pt, [2.0, 1.0])

    def test_path_with_translation(self):
        """Translation in transform shifts world coordinates."""
        raster = _make_raster(padding=0)
        # canonical = world with offset (100, 200)
        transform = _make_transform(rotation=0, mirror=False, translation=(100, 200))
        pixel_path = np.array([[0, 0]], dtype=int)
        # rc_to_canonical(0,0)=(0,0); to_original(canonical-translation)=(0-100, 0-200)
        world = raster_to_world_path(pixel_path, raster, transform)
        np.testing.assert_array_almost_equal(world, [[-100.0, -200.0]])

    def test_path_with_rotation_90(self):
        """90-degree rotation round-trips correctly through raster_to_world_path."""
        raster = _make_raster(padding=0)
        # to_original reverses 90-degree rotation: (x,z)->canonical via rot90
        # then to_original(canonical) undoes it
        transform = _make_transform(rotation=90, mirror=False, translation=(0, 0))
        # A canonical point (0, 1) in canonical space came from world (1, 0)
        # verify to_original([0,1]) = [1,0]
        world_pt = raster_to_world_point((1, 0), raster, transform)
        # rc_to_canonical(1, 0) = (0, 1); to_original([0,1]) = ...
        # to_original undoes 90deg rot: apply -90 (=270): (x,z)->(z,-x)
        # (0,1) rotated 270: (1, 0)
        np.testing.assert_array_almost_equal(world_pt, [1.0, 0.0])

    def test_path_and_point_consistent(self):
        """raster_to_world_path and raster_to_world_point agree for single points."""
        raster = _make_raster(padding=2)
        transform = _make_transform(rotation=180, mirror=True, translation=(5, 10))
        for r, c in [(2, 2), (3, 4), (0, 1)]:
            path = np.array([[r, c]], dtype=int)
            path_result = raster_to_world_path(path, raster, transform)[0]
            point_result = raster_to_world_point((r, c), raster, transform)
            np.testing.assert_array_almost_equal(path_result, point_result,
                                                  err_msg=f"Mismatch at r={r}, c={c}")


# ---------------------------------------------------------------------------
# world_blocks_to_shapely
# ---------------------------------------------------------------------------

class TestWorldBlocksToShapely(unittest.TestCase):
    """world_blocks_to_shapely: bounds, area, topology."""

    def test_single_block(self):
        p = world_blocks_to_shapely([[3, 5]])
        self.assertAlmostEqual(p.area, 1.0)
        self.assertEqual(p.bounds, (3.0, 5.0, 4.0, 6.0))

    def test_two_adjacent_blocks(self):
        p = world_blocks_to_shapely([[0, 0], [1, 0]])
        self.assertAlmostEqual(p.area, 2.0)
        self.assertEqual(p.bounds, (0.0, 0.0, 2.0, 1.0))

    def test_three_blocks_L_shape(self):
        # L-shape: (0,0), (1,0), (0,1)
        p = world_blocks_to_shapely([[0, 0], [1, 0], [0, 1]])
        self.assertAlmostEqual(p.area, 3.0)

    def test_empty_input(self):
        p = world_blocks_to_shapely([])
        self.assertTrue(p.is_empty)

    def test_negative_coordinates(self):
        p = world_blocks_to_shapely([[-2, -3]])
        self.assertAlmostEqual(p.area, 1.0)
        self.assertEqual(p.bounds, (-2.0, -3.0, -1.0, -2.0))

    def test_numpy_input(self):
        blocks = np.array([[0, 0], [0, 1]], dtype=int)
        p = world_blocks_to_shapely(blocks)
        self.assertAlmostEqual(p.area, 2.0)

    def test_float_input_treated_as_block_indices(self):
        # float inputs are block indices, not sub-block coords
        p = world_blocks_to_shapely([[1.0, 2.0]])
        self.assertEqual(p.bounds, (1.0, 2.0, 2.0, 3.0))

    def test_extent_equals_get_grid_extent(self):
        """world_blocks_to_shapely bounds match get_grid_extent output."""
        from common.geometry import get_grid_extent
        xs = [10, 11, 12, 10]
        zs = [5, 5, 5, 6]
        p = world_blocks_to_shapely(list(zip(xs, zs)))
        min_x, max_x, min_z, max_z = get_grid_extent(xs, zs)
        # Shapely bounds = (minx, minz, maxx, maxz)
        self.assertAlmostEqual(p.bounds[0], min_x)
        self.assertAlmostEqual(p.bounds[1], min_z)
        self.assertAlmostEqual(p.bounds[2], max_x)
        self.assertAlmostEqual(p.bounds[3], max_z)

    def test_area_equals_block_count_for_solid_rectangle(self):
        """Solid N×M rectangle has area == N*M."""
        blocks = [[x, z] for x in range(5) for z in range(7)]
        p = world_blocks_to_shapely(blocks)
        self.assertAlmostEqual(p.area, 35.0)

    def test_consistent_with_old_inline_formula(self):
        """Result matches what the old inline box(x,z,x+1,z+1) loop produces."""
        from shapely.geometry import box
        from shapely.ops import unary_union
        blocks = [[0, 0], [1, 0], [2, 1]]
        old = unary_union([box(x, z, x + 1, z + 1) for x, z in blocks])
        new = world_blocks_to_shapely(blocks)
        self.assertAlmostEqual(new.area, old.area)
        self.assertEqual(new.bounds, old.bounds)


if __name__ == '__main__':
    unittest.main()
