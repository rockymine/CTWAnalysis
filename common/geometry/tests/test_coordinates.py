"""Tests for common.geometry.coordinates.

Verifies correctness of get_grid_extent, get_center_from_extent,
get_block_centroid, block_unit_square, and blocks_to_unit_squares,
including exact agreement with the legacy inline formulas that are being
replaced in skeleton_analysis, island_analysis, layout_analysis,
ctw/commands/debug.py, and visualization/map_primitives.py.
"""

import unittest
import numpy as np

from common.geometry.coordinates import (
    get_grid_extent,
    get_center_from_extent,
    get_block_centroid,
    block_unit_square,
    blocks_to_unit_squares,
)


# ===========================================================================
# get_grid_extent
# ===========================================================================

class TestGetGridExtent(unittest.TestCase):
    """Tests for get_grid_extent (the canonical +1 bounding box)."""

    def test_single_block(self):
        """A single block at (5, 3) occupies [5,6] x [3,4]."""
        extent = get_grid_extent([5], [3])
        self.assertEqual(extent, (5.0, 6.0, 3.0, 4.0))

    def test_single_block_at_origin(self):
        """Block at (0, 0) occupies [0,1] x [0,1]."""
        self.assertEqual(get_grid_extent([0], [0]), (0.0, 1.0, 0.0, 1.0))

    def test_width_is_one_not_zero(self):
        """The +1 rule: a single block must have width 1, not 0."""
        extent = get_grid_extent([10], [10])
        self.assertAlmostEqual(extent[1] - extent[0], 1.0)
        self.assertAlmostEqual(extent[3] - extent[2], 1.0)

    def test_contiguous_row(self):
        """Three blocks at x=0,1,2 span [0,3]."""
        extent = get_grid_extent([0, 1, 2], [0, 0, 0])
        self.assertEqual(extent, (0.0, 3.0, 0.0, 1.0))

    def test_3x3_grid(self):
        """3x3 block grid spans [0,3] x [0,3]."""
        xs = [0, 1, 2] * 3
        zs = [0, 0, 0, 1, 1, 1, 2, 2, 2]
        self.assertEqual(get_grid_extent(xs, zs), (0.0, 3.0, 0.0, 3.0))

    def test_negative_coordinates(self):
        """Negative block indices handled correctly."""
        extent = get_grid_extent([-5, -3, -1], [-10, -8, -6])
        self.assertEqual(extent, (-5.0, 0.0, -10.0, -5.0))

    def test_mixed_sign_coordinates(self):
        """Blocks spanning negative to positive indices."""
        extent = get_grid_extent([-2, 0, 2], [-1, 0, 1])
        self.assertEqual(extent, (-2.0, 3.0, -1.0, 2.0))

    def test_numpy_array_input(self):
        """Accepts numpy arrays as input."""
        xs = np.array([0, 10, 5])
        zs = np.array([0, 0, 8])
        extent = get_grid_extent(xs, zs)
        self.assertEqual(extent, (0.0, 11.0, 0.0, 9.0))

    def test_returns_python_floats(self):
        """All four values in the returned tuple are Python floats."""
        extent = get_grid_extent([0], [0])
        for v in extent:
            self.assertIsInstance(v, float)

    def test_large_map(self):
        """Reproduces a realistic Minecraft map extent."""
        # Blocks spanning x in [-115, 114], z in [-115, 114]
        extent = get_grid_extent([-115, 114], [-115, 114])
        self.assertEqual(extent, (-115.0, 115.0, -115.0, 115.0))

    def test_agrees_with_legacy_layout_builder_formula(self):
        """get_grid_extent produces the same result as layout_analysis/builder.py.

        Legacy code (layout_analysis/builder.py):
            ctx.bounding_box = (
                float(df[x].min()),
                float(df[x].max()) + 1,
                float(df[z].min()),
                float(df[z].max()) + 1,
            )
        """
        xs = np.array([10, 20, 15, 10, 20])
        zs = np.array([5, 5, 10, 15, 15])

        # Legacy formula
        legacy = (
            float(xs.min()),
            float(xs.max()) + 1,
            float(zs.min()),
            float(zs.max()) + 1,
        )

        self.assertEqual(get_grid_extent(xs, zs), legacy)

    def test_agrees_with_legacy_detection_formula(self):
        """get_grid_extent produces the same result as island_analysis/detection.py.

        Legacy code:
            bbox = (
                int(world_coords[:, 0].min()),
                int(world_coords[:, 0].max()) + 1,
                int(world_coords[:, 1].min()),
                int(world_coords[:, 1].max()) + 1,
            )
        """
        world_xs = np.array([10.0, 11.0, 12.0, 10.0, 12.0])
        world_zs = np.array([20.0, 20.0, 20.0, 22.0, 22.0])

        # Legacy formula (yields ints; we compare as floats)
        legacy = (
            float(int(world_xs.min())),
            float(int(world_xs.max()) + 1),
            float(int(world_zs.min())),
            float(int(world_zs.max()) + 1),
        )
        new = get_grid_extent(world_xs, world_zs)
        self.assertEqual(new, legacy)


# ===========================================================================
# get_center_from_extent
# ===========================================================================

class TestGetCenterFromExtent(unittest.TestCase):
    """Tests for get_center_from_extent."""

    def test_unit_extent(self):
        """Single-block extent [5,6] x [3,4] has centre (5.5, 3.5)."""
        cx, cz = get_center_from_extent(5.0, 6.0, 3.0, 4.0)
        self.assertAlmostEqual(cx, 5.5)
        self.assertAlmostEqual(cz, 3.5)

    def test_symmetric_extent(self):
        """Symmetric extent [0,10] x [0,10] has centre (5, 5)."""
        cx, cz = get_center_from_extent(0.0, 10.0, 0.0, 10.0)
        self.assertAlmostEqual(cx, 5.0)
        self.assertAlmostEqual(cz, 5.0)

    def test_negative_extent(self):
        """Extent with negative lower bounds."""
        cx, cz = get_center_from_extent(-10.0, 0.0, -5.0, 5.0)
        self.assertAlmostEqual(cx, -5.0)
        self.assertAlmostEqual(cz, 0.0)

    def test_non_zero_lower_bound(self):
        """Extent not starting at zero."""
        cx, cz = get_center_from_extent(3.0, 9.0, 1.0, 7.0)
        self.assertAlmostEqual(cx, 6.0)
        self.assertAlmostEqual(cz, 4.0)

    def test_odd_block_count_gives_half_offset(self):
        """Odd block count -> centre falls at x.5, z.5 (within a block)."""
        # 5 blocks wide: extent [0, 5], centre = 2.5
        cx, cz = get_center_from_extent(0.0, 5.0, 0.0, 7.0)
        self.assertAlmostEqual(cx, 2.5)
        self.assertAlmostEqual(cz, 3.5)

    def test_even_block_count_gives_integer_centre(self):
        """Even block count -> centre falls exactly on a block boundary."""
        # 6 blocks wide: extent [0, 6], centre = 3.0
        cx, cz = get_center_from_extent(0.0, 6.0, 0.0, 8.0)
        self.assertAlmostEqual(cx, 3.0)
        self.assertAlmostEqual(cz, 4.0)

    def test_composed_with_get_grid_extent(self):
        """Composed call matches legacy compute_map_center formula.

        Legacy (skeleton_analysis/poi_annotation.py):
            (min_x + max_x + 1) / 2.0   (where max_x is raw block index)
        """
        # Simulate 11 blocks: indices 0..10
        xs = list(range(0, 11))
        zs = list(range(0, 21))

        min_x, max_x_raw = xs[0], xs[-1]
        min_z, max_z_raw = zs[0], zs[-1]

        # Legacy formula using raw block indices
        old_cx = (min_x + max_x_raw + 1) / 2.0
        old_cz = (min_z + max_z_raw + 1) / 2.0

        # New approach
        extent = get_grid_extent(xs, zs)
        new_cx, new_cz = get_center_from_extent(*extent)

        self.assertAlmostEqual(new_cx, old_cx)
        self.assertAlmostEqual(new_cz, old_cz)

    def test_agrees_with_classify_center_input(self):
        """Centre from extent matches how symmetry_analysis.builder uses bbox.

        symmetry_analysis/builder.py (classify_center):
            center_x = (min_x + max_x) / 2.0
        where bbox already has max_x = raw_max + 1.
        """
        bbox = (-115.0, 115.0, -115.0, 115.0)   # even x even, 230 blocks wide
        cx, cz = get_center_from_extent(*bbox)
        self.assertAlmostEqual(cx, 0.0)
        self.assertAlmostEqual(cz, 0.0)


# ===========================================================================
# get_block_centroid
# ===========================================================================

class TestGetBlockCentroid(unittest.TestCase):
    """Tests for get_block_centroid."""

    def test_single_block(self):
        """Single block at (5, 3) has centroid (5.5, 3.5)."""
        cx, cz = get_block_centroid([5], [3])
        self.assertAlmostEqual(cx, 5.5)
        self.assertAlmostEqual(cz, 3.5)

    def test_two_horizontal_blocks(self):
        """Blocks at (0,0) and (1,0): mean_x=0.5, centroid_x=1.0."""
        cx, cz = get_block_centroid([0, 1], [0, 0])
        self.assertAlmostEqual(cx, 1.0)   # mean(0,1) + 0.5
        self.assertAlmostEqual(cz, 0.5)   # mean(0,0) + 0.5

    def test_symmetric_3x3_grid(self):
        """Symmetric 3x3 grid: centroid at (1.5, 1.5)."""
        xs = [0, 1, 2, 0, 1, 2, 0, 1, 2]
        zs = [0, 0, 0, 1, 1, 1, 2, 2, 2]
        cx, cz = get_block_centroid(xs, zs)
        self.assertAlmostEqual(cx, 1.5)   # mean=1.0, +0.5
        self.assertAlmostEqual(cz, 1.5)

    def test_numpy_array_input(self):
        """Accepts numpy arrays as input."""
        xs = np.array([0, 2, 4])
        zs = np.array([1, 3, 5])
        cx, cz = get_block_centroid(xs, zs)
        self.assertAlmostEqual(cx, 2.5)   # mean(0,2,4)=2.0, +0.5
        self.assertAlmostEqual(cz, 3.5)   # mean(1,3,5)=3.0, +0.5

    def test_negative_block_indices(self):
        """Centroid with negative block indices."""
        cx, cz = get_block_centroid([-1, 0], [-1, 0])
        self.assertAlmostEqual(cx, 0.0)   # mean(-1,0)=-0.5, +0.5=0.0
        self.assertAlmostEqual(cz, 0.0)

    def test_agrees_with_legacy_detection_formula(self):
        """Result matches island_analysis/detection.py legacy formula.

        Legacy:
            center = (world_coords[:, 0].mean() + 0.5,
                      world_coords[:, 1].mean() + 0.5)
        """
        world_xs = np.array([10.0, 11.0, 12.0, 10.0, 11.0, 12.0])
        world_zs = np.array([20.0, 20.0, 20.0, 21.0, 21.0, 21.0])

        old_center = (world_xs.mean() + 0.5, world_zs.mean() + 0.5)
        new_center = get_block_centroid(world_xs, world_zs)

        self.assertAlmostEqual(new_center[0], old_center[0])
        self.assertAlmostEqual(new_center[1], old_center[1])

    def test_centroid_differs_from_extent_center_for_sparse_layout(self):
        """For non-uniform layouts, centroid != extent centre.

        This verifies the two functions serve distinct purposes.
        """
        # Two blocks very far apart in x, with most on one side
        xs = [0, 0, 0, 0, 100]
        zs = [0, 1, 2, 3, 0]

        centroid = get_block_centroid(xs, zs)
        extent_center = get_center_from_extent(*get_grid_extent(xs, zs))

        # centroid_x = mean(0,0,0,0,100) + 0.5 = 20.5
        self.assertAlmostEqual(centroid[0], 20.5)
        # extent centre_x = (0 + 101) / 2 = 50.5
        self.assertAlmostEqual(extent_center[0], 50.5)
        self.assertNotAlmostEqual(centroid[0], extent_center[0])

    def test_returns_python_floats(self):
        """Return values are Python floats."""
        cx, cz = get_block_centroid([5], [5])
        self.assertIsInstance(cx, float)
        self.assertIsInstance(cz, float)


# ===========================================================================
# Cross-function consistency
# ===========================================================================

class TestCrossFunction(unittest.TestCase):
    """Tests that verify the three functions work consistently together."""

    def test_uniform_rectangle_centroid_equals_extent_center(self):
        """For a fully filled rectangle, centroid == extent centre."""
        xs = [x for x in range(10) for _ in range(10)]
        zs = [z for _ in range(10) for z in range(10)]

        centroid = get_block_centroid(xs, zs)
        extent_center = get_center_from_extent(*get_grid_extent(xs, zs))

        self.assertAlmostEqual(centroid[0], extent_center[0])
        self.assertAlmostEqual(centroid[1], extent_center[1])

    def test_extent_width_equals_block_count_for_row(self):
        """For a contiguous row of N blocks, extent width == N."""
        n = 7
        xs = list(range(n))
        zs = [0] * n
        extent = get_grid_extent(xs, zs)
        self.assertAlmostEqual(extent[1] - extent[0], float(n))

    def test_extent_and_center_roundtrip_map_center(self):
        """Reproduce realistic map-centre computation end-to-end.

        Simulates what compute_map_center does after refactoring:
            extent = get_grid_extent(df[x_col], df[z_col])
            center = get_center_from_extent(*extent)
        """
        # Simulate a small layout
        xs = list(range(-50, 51))   # 101 blocks -> odd -> centre at x.5
        zs = list(range(-50, 51))

        extent = get_grid_extent(xs, zs)
        cx, cz = get_center_from_extent(*extent)

        # 101 blocks: indices -50..50 -> extent (-50, 51) -> centre = (-50+51)/2 = 0.5
        # Odd block count -> centre falls at a half-integer (inside a block)
        self.assertAlmostEqual(cx, 0.5)
        self.assertAlmostEqual(cz, 0.5)


# ===========================================================================
# block_unit_square
# ===========================================================================

class TestBlockUnitSquare(unittest.TestCase):
    """Tests for block_unit_square — single-block vertex list."""

    def test_origin_block(self):
        """Block at (0, 0) has corners (0,0), (1,0), (1,1), (0,1)."""
        verts = block_unit_square(0, 0)
        self.assertEqual(len(verts), 4)
        self.assertEqual(verts[0], (0.0, 0.0))
        self.assertEqual(verts[1], (1.0, 0.0))
        self.assertEqual(verts[2], (1.0, 1.0))
        self.assertEqual(verts[3], (0.0, 1.0))

    def test_offset_block(self):
        """Block at (3, 5) has corners at (3,5), (4,5), (4,6), (3,6)."""
        verts = block_unit_square(3, 5)
        self.assertEqual(verts[0], (3.0, 5.0))
        self.assertEqual(verts[1], (4.0, 5.0))
        self.assertEqual(verts[2], (4.0, 6.0))
        self.assertEqual(verts[3], (3.0, 6.0))

    def test_negative_coordinates(self):
        """Block at (-2, -3) has corners at (-2,-3), (-1,-3), (-1,-2), (-2,-2)."""
        verts = block_unit_square(-2, -3)
        self.assertEqual(verts[0], (-2.0, -3.0))
        self.assertEqual(verts[1], (-1.0, -3.0))
        self.assertEqual(verts[2], (-1.0, -2.0))
        self.assertEqual(verts[3], (-2.0, -2.0))

    def test_returns_python_floats(self):
        """All coordinates are Python floats."""
        verts = block_unit_square(5, 7)
        for x, z in verts:
            self.assertIsInstance(x, float)
            self.assertIsInstance(z, float)

    def test_unit_width_and_height(self):
        """Each edge of the square has length 1."""
        verts = block_unit_square(10, 20)
        xs = [v[0] for v in verts]
        zs = [v[1] for v in verts]
        self.assertAlmostEqual(max(xs) - min(xs), 1.0)
        self.assertAlmostEqual(max(zs) - min(zs), 1.0)

    def test_agrees_with_legacy_debug_formula(self):
        """Matches the legacy debug.py inline formula.

        Legacy (ctw/commands/debug.py):
            verts.append([(x, z), (x+1, z), (x+1, z+1), (x, z+1)])
        """
        x, z = 7, 12
        legacy = [(x, z), (x + 1, z), (x + 1, z + 1), (x, z + 1)]
        result = block_unit_square(x, z)
        self.assertEqual(len(result), len(legacy))
        for new_pt, old_pt in zip(result, legacy):
            self.assertAlmostEqual(new_pt[0], old_pt[0])
            self.assertAlmostEqual(new_pt[1], old_pt[1])


# ===========================================================================
# blocks_to_unit_squares
# ===========================================================================

class TestBlocksToUnitSquares(unittest.TestCase):
    """Tests for blocks_to_unit_squares — vectorised vertex array."""

    def test_shape_single_block(self):
        """Single block produces shape (1, 4, 2)."""
        result = blocks_to_unit_squares([5], [3])
        self.assertEqual(result.shape, (1, 4, 2))

    def test_shape_multiple_blocks(self):
        """N blocks produce shape (N, 4, 2)."""
        result = blocks_to_unit_squares([0, 1, 2], [0, 0, 0])
        self.assertEqual(result.shape, (3, 4, 2))

    def test_single_block_vertices(self):
        """Single block at (3, 5): corners match block_unit_square."""
        result = blocks_to_unit_squares([3], [5])
        expected = block_unit_square(3, 5)
        for i, (ex, ez) in enumerate(expected):
            self.assertAlmostEqual(result[0, i, 0], ex)
            self.assertAlmostEqual(result[0, i, 1], ez)

    def test_vertex_layout(self):
        """Verify vertex layout: BL, BR, TR, TL for each block."""
        xs = np.array([10.0, 20.0])
        zs = np.array([5.0, 5.0])
        result = blocks_to_unit_squares(xs, zs)

        for i, (x, z) in enumerate(zip(xs, zs)):
            bl = result[i, 0]  # bottom-left
            br = result[i, 1]  # bottom-right
            tr = result[i, 2]  # top-right
            tl = result[i, 3]  # top-left

            self.assertAlmostEqual(bl[0], x)
            self.assertAlmostEqual(bl[1], z)
            self.assertAlmostEqual(br[0], x + 1)
            self.assertAlmostEqual(br[1], z)
            self.assertAlmostEqual(tr[0], x + 1)
            self.assertAlmostEqual(tr[1], z + 1)
            self.assertAlmostEqual(tl[0], x)
            self.assertAlmostEqual(tl[1], z + 1)

    def test_numpy_input(self):
        """Accepts numpy array inputs."""
        xs = np.array([0, 5, 10])
        zs = np.array([0, 5, 10])
        result = blocks_to_unit_squares(xs, zs)
        self.assertEqual(result.shape, (3, 4, 2))

    def test_negative_coordinates(self):
        """Negative block indices produce correct unit squares."""
        result = blocks_to_unit_squares([-3], [-7])
        self.assertAlmostEqual(result[0, 0, 0], -3.0)  # BL x
        self.assertAlmostEqual(result[0, 1, 0], -2.0)  # BR x
        self.assertAlmostEqual(result[0, 2, 1], -6.0)  # TR z
        self.assertAlmostEqual(result[0, 3, 1], -6.0)  # TL z

    def test_consistent_with_block_unit_square(self):
        """blocks_to_unit_squares row i matches block_unit_square for same block."""
        test_blocks = [(0, 0), (5, 3), (-2, 7), (100, -50)]
        xs = [b[0] for b in test_blocks]
        zs = [b[1] for b in test_blocks]
        batch = blocks_to_unit_squares(xs, zs)

        for i, (x, z) in enumerate(test_blocks):
            single = block_unit_square(x, z)
            for j, (ex, ez) in enumerate(single):
                self.assertAlmostEqual(batch[i, j, 0], ex,
                                       msg=f"block {i} vertex {j} x mismatch")
                self.assertAlmostEqual(batch[i, j, 1], ez,
                                       msg=f"block {i} vertex {j} z mismatch")

    def test_agrees_with_legacy_map_primitives_formula(self):
        """Matches the legacy map_primitives.py inline formula.

        Legacy (visualization/map_primitives.py):
            squares = np.stack([
                np.column_stack([xs,       zs]),
                np.column_stack([xs + 1,   zs]),
                np.column_stack([xs + 1,   zs + 1]),
                np.column_stack([xs,       zs + 1]),
            ], axis=1)
        """
        xs = np.array([0.0, 3.0, -1.0])
        zs = np.array([0.0, 4.0, 2.0])

        legacy = np.stack([
            np.column_stack([xs,     zs]),
            np.column_stack([xs + 1, zs]),
            np.column_stack([xs + 1, zs + 1]),
            np.column_stack([xs,     zs + 1]),
        ], axis=1)

        result = blocks_to_unit_squares(xs, zs)
        np.testing.assert_array_almost_equal(result, legacy)

    def test_returns_float64_array(self):
        """Output dtype is float64."""
        result = blocks_to_unit_squares([1, 2], [3, 4])
        self.assertEqual(result.dtype, np.float64)


if __name__ == "__main__":
    unittest.main()
