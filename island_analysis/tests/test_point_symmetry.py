"""Tests for _check_point_symmetry in island_analysis.profile.

Each test case documents the expected centre type (1x1 / 1x2 / 2x1 / 2x2)
and the reason for the expected outcome.
"""

import unittest

from island_analysis.profile import _check_point_symmetry


def _rect(x0: int, z0: int, x1: int, z1: int) -> tuple[list, list]:
    """Return (exterior, bbox) for a solid filled rectangle [x0,x1) x [z0,z1)."""
    exterior = [
        [x0, z0], [x1, z0], [x1, z1], [x0, z1], [x0, z0],
    ]
    bbox = [x0, x1, z0, z1]
    return exterior, bbox


# ---------------------------------------------------------------------------
# Solid rectangles — all must be symmetric (fill == 1.0)
# ---------------------------------------------------------------------------

class TestSolidRectangles(unittest.TestCase):
    """Solid rectangles have perfect point symmetry regardless of size/parity."""

    def test_1x1_block(self):
        # Single block: centre type 1x1 (cx=0.5, cz=0.5)
        ext, bbox = _rect(0, 0, 1, 1)
        self.assertTrue(_check_point_symmetry(ext, bbox))

    def test_2x2_block(self):
        # 2x2: centre type 2x2 (cx=1, cz=1)
        ext, bbox = _rect(0, 0, 2, 2)
        self.assertTrue(_check_point_symmetry(ext, bbox))

    def test_3x3_block(self):
        # 3x3: centre type 1x1 (cx=1.5, cz=1.5)
        ext, bbox = _rect(0, 0, 3, 3)
        self.assertTrue(_check_point_symmetry(ext, bbox))

    def test_4x4_block(self):
        # 4x4: centre type 2x2 (cx=2, cz=2)
        ext, bbox = _rect(0, 0, 4, 4)
        self.assertTrue(_check_point_symmetry(ext, bbox))

    def test_5x3_rectangle_2x1_center(self):
        # Width=5 (odd), height=3 (odd) → centre type 1x1 (cx=2.5, cz=1.5)
        ext, bbox = _rect(0, 0, 5, 3)
        self.assertTrue(_check_point_symmetry(ext, bbox))

    def test_4x3_rectangle_2x1_center(self):
        # Width=4 (even), height=3 (odd) → centre type 2x1 (cx=2, cz=1.5)
        ext, bbox = _rect(0, 0, 4, 3)
        self.assertTrue(_check_point_symmetry(ext, bbox))

    def test_3x4_rectangle_1x2_center(self):
        # Width=3 (odd), height=4 (even) → centre type 1x2 (cx=1.5, cz=2)
        ext, bbox = _rect(0, 0, 3, 4)
        self.assertTrue(_check_point_symmetry(ext, bbox))

    def test_6x4_rectangle_2x2_center(self):
        # Width=6 (even), height=4 (even) → centre type 2x2 (cx=3, cz=2)
        ext, bbox = _rect(0, 0, 6, 4)
        self.assertTrue(_check_point_symmetry(ext, bbox))

    def test_offset_origin(self):
        # Same shape but at a non-zero world position — centre arithmetic must
        # use the actual bbox, not an assumed origin.
        ext, bbox = _rect(10, 20, 14, 24)   # 4x4 at (10,20)
        self.assertTrue(_check_point_symmetry(ext, bbox))


# ---------------------------------------------------------------------------
# Point-symmetric non-rectangular shapes
# ---------------------------------------------------------------------------

class TestSymmetricNonRectangular(unittest.TestCase):
    """Shapes that are point-symmetric but do not fill their bounding box."""

    def test_plus_shape(self):
        # Plus / cross: the arm blocks are symmetric under 180° rotation.
        # Blocks (relative to a 5x5 bbox at origin):
        #   col 2: rows 0-4  (vertical arm)
        #   row 2: cols 0-4  (horizontal arm)
        # Centre: cx=2.5, cz=2.5 (1x1 centre of a 5x5 bbox)
        exterior = [
            [2, 0], [3, 0], [3, 2], [5, 2], [5, 3],
            [3, 3], [3, 5], [2, 5], [2, 3], [0, 3],
            [0, 2], [2, 2], [2, 0],
        ]
        bbox = [0, 5, 0, 5]
        self.assertTrue(_check_point_symmetry(exterior, bbox))

    def test_z_shape(self):
        # Z-shape: two offset rectangles joined diagonally.
        # Blocks: top row (0-2, 0), middle (0-2, 1), bottom row (0-2, 2) ... wrong
        # Use a clean Z: top-left 2x1 and bottom-right 2x1 joined by a middle row.
        # Blocks: row z=0: x in {0,1}, row z=1: x in {0,1,2}, row z=2: x in {1,2}
        # Centre: cx=1 (even width 3? no: bbox x=[0,3], cx=1.5), cz=1 (odd height 3, cz=1.5)
        # → 1x1 centre; this Z is point-symmetric.
        exterior = [
            [0, 0], [2, 0], [2, 1], [3, 1], [3, 3],
            [1, 3], [1, 2], [0, 2], [0, 0],
        ]
        bbox = [0, 3, 0, 3]
        self.assertTrue(_check_point_symmetry(exterior, bbox))

    def test_diamond_4x4(self):
        # Diamond inscribed in a 4x4 bbox (Minecraft circle approximation).
        # Blocks:       z=0: x in {1,2}
        #               z=1: x in {0,1,2,3}
        #               z=2: x in {0,1,2,3}
        #               z=3: x in {1,2}
        # Centre: 2x2 (cx=2, cz=2). Point-symmetric.
        exterior = [
            [1, 0], [3, 0], [3, 1], [4, 1], [4, 3],
            [3, 3], [3, 4], [1, 4], [1, 3], [0, 3],
            [0, 1], [1, 1], [1, 0],
        ]
        bbox = [0, 4, 0, 4]
        self.assertTrue(_check_point_symmetry(exterior, bbox))


# ---------------------------------------------------------------------------
# Asymmetric shapes
# ---------------------------------------------------------------------------

class TestAsymmetricShapes(unittest.TestCase):
    """Shapes that do NOT have 180° point symmetry."""

    def test_l_shape(self):
        # L-shape: top-left 2x2 plus a single block extending right.
        # Blocks: (0,0),(1,0),(0,1),(1,1),(2,0) — no 180° symmetry.
        exterior = [
            [0, 0], [3, 0], [3, 1], [2, 1], [2, 2],
            [0, 2], [0, 0],
        ]
        bbox = [0, 3, 0, 2]
        self.assertFalse(_check_point_symmetry(exterior, bbox))

    def test_rectangle_with_one_corner_missing(self):
        # 3x3 square with the top-right block removed — L-like, not symmetric.
        exterior = [
            [0, 0], [3, 0], [3, 2], [2, 2], [2, 3],
            [0, 3], [0, 0],
        ]
        bbox = [0, 3, 0, 3]
        self.assertFalse(_check_point_symmetry(exterior, bbox))

    def test_rectangle_with_two_adjacent_corners_missing(self):
        # 4x4 with the top-right 2x2 quarter removed — one side is bitten off.
        exterior = [
            [0, 0], [4, 0], [4, 2], [2, 2], [2, 4],
            [0, 4], [0, 0],
        ]
        bbox = [0, 4, 0, 4]
        self.assertFalse(_check_point_symmetry(exterior, bbox))

    def test_t_shape(self):
        # T-shape: wide top bar plus a downward stem — no 180° symmetry.
        # Blocks: z=0: x in {0,1,2}, z=1: x in {1}, z=2: x in {1}
        exterior = [
            [0, 0], [3, 0], [3, 1], [2, 1], [2, 3],
            [1, 3], [1, 1], [0, 1], [0, 0],
        ]
        bbox = [0, 3, 0, 3]
        self.assertFalse(_check_point_symmetry(exterior, bbox))


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_too_few_vertices(self):
        # Degenerate polygon — should return False without crashing.
        self.assertFalse(_check_point_symmetry([[0, 0], [1, 0]], [0, 1, 0, 1]))

    def test_empty_exterior(self):
        self.assertFalse(_check_point_symmetry([], [0, 3, 0, 3]))

    def test_single_block_is_symmetric(self):
        # A single block is trivially point-symmetric about its own centre.
        ext, bbox = _rect(5, 7, 6, 8)
        self.assertTrue(_check_point_symmetry(ext, bbox))


if __name__ == '__main__':
    unittest.main()
