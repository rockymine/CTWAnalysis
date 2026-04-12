"""Tests for _bbox_corner_cutout_count and the L/Z/T shape classification rules.

Each test documents the expected geometry and which corners should be identified.
"""

import unittest

from island_analysis.profile import (
    _bbox_corner_cutout_count,
    _DIAGONAL_CORNER_PAIRS,
    _ADJACENT_CORNER_PAIRS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _solid_rect_exterior(x0: float, z0: float, x1: float, z1: float) -> list[list[float]]:
    """Return exterior ring for a solid filled rectangle [x0,x1) × [z0,z1)."""
    return [[x0, z0], [x1, z0], [x1, z1], [x0, z1], [x0, z0]]


def _l_shape_exterior(
    x0: float, z0: float, x1: float, z1: float,
    cut_x0: float, cut_z0: float, cut_x1: float, cut_z1: float,
) -> list[list[float]]:
    """Return exterior ring for a rectangle with one rectangular corner removed.

    The cutout must be at an actual corner of the [x0,x1]×[z0,z1] bbox.
    This helper only supports axis-aligned cuts that remove a top-right corner:
        full rect minus cut_rect at (cut_x0..x1) × (z0..cut_z1).
    For other corners, pass coordinates accordingly — caller is responsible for
    constructing the correct polygon.
    """
    raise NotImplementedError("Use specific per-test polygons below for clarity.")


# ---------------------------------------------------------------------------
# No cutouts
# ---------------------------------------------------------------------------

class TestNoCutouts(unittest.TestCase):
    """Shapes with no corner cutouts return (0, 1.0, 0.0, frozenset())."""

    def test_perfect_rectangle(self):
        ext = _solid_rect_exterior(0, 0, 6, 4)
        count, min_fill, coverage, corners = _bbox_corner_cutout_count(ext, [], 24.0)
        self.assertEqual(count, 0)
        self.assertEqual(corners, frozenset())

    def test_mid_top_notch_no_corner_cutouts(self):
        # 6×4 rectangle with a 2×2 notch cut from the MIDDLE of the top edge.
        # Negative space: (2..4)×(0..2) — touches only the top edge (edge_count=1),
        # so it does not qualify as a corner cutout.
        exterior = [
            [0, 0], [2, 0], [2, 2], [4, 2], [4, 0], [6, 0],
            [6, 4], [0, 4], [0, 0],
        ]
        count, _mf, _cov, corners = _bbox_corner_cutout_count(exterior, [], 20.0)
        self.assertEqual(count, 0)
        self.assertEqual(corners, frozenset())



# ---------------------------------------------------------------------------
# One cutout — L_shape (any single corner)
# ---------------------------------------------------------------------------

class TestOneCutout(unittest.TestCase):
    """Shapes with one qualifying rectangular corner cutout."""

    def _assert_one_cutout(self, exterior: list, area: float, expected_corner: str) -> None:
        count, _mf, coverage, corners = _bbox_corner_cutout_count(exterior, [], area)
        self.assertEqual(count, 1, f"Expected 1 cutout, got {count}")
        self.assertGreater(coverage, 0.70, f"Coverage {coverage:.2f} < 0.70")
        self.assertIn(expected_corner, corners)
        self.assertEqual(len(corners), 1)

    def test_top_left_cutout(self):
        # 6×4 rectangle with a 2×2 block removed from the top-left corner.
        # Blocks: full 6×4 grid minus (0..2)×(0..2)
        # TL corner = min_x + min_z
        exterior = [
            [2, 0], [6, 0], [6, 4], [0, 4], [0, 2], [2, 2], [2, 0],
        ]
        self._assert_one_cutout(exterior, 20.0, 'TL')

    def test_top_right_cutout(self):
        # 6×4 rectangle with a 2×2 block removed from the top-right corner.
        # TR corner = max_x + min_z
        exterior = [
            [0, 0], [4, 0], [4, 2], [6, 2], [6, 4], [0, 4], [0, 0],
        ]
        self._assert_one_cutout(exterior, 20.0, 'TR')

    def test_bottom_left_cutout(self):
        # 6×4 rectangle with a 2×2 block removed from the bottom-left corner.
        # BL corner = min_x + max_z
        exterior = [
            [0, 0], [6, 0], [6, 4], [2, 4], [2, 2], [0, 2], [0, 0],
        ]
        self._assert_one_cutout(exterior, 20.0, 'BL')

    def test_bottom_right_cutout(self):
        # 6×4 rectangle with a 2×2 block removed from the bottom-right corner.
        # BR corner = max_x + max_z
        exterior = [
            [0, 0], [6, 0], [6, 2], [4, 2], [4, 4], [0, 4], [0, 0],
        ]
        self._assert_one_cutout(exterior, 20.0, 'BR')

    def test_non_square_cut_tl(self):
        # 8×4 rectangle with a 3×2 block cut from the top-left (non-square cutout).
        exterior = [
            [3, 0], [8, 0], [8, 4], [0, 4], [0, 2], [3, 2], [3, 0],
        ]
        self._assert_one_cutout(exterior, 26.0, 'TL')


# ---------------------------------------------------------------------------
# Two diagonal cutouts — Z_shape
# ---------------------------------------------------------------------------

class TestDiagonalCutouts(unittest.TestCase):
    """Two corner cutouts at diagonally opposite corners → Z_shape."""

    def _assert_diagonal(self, exterior: list, area: float, pair: frozenset) -> None:
        count, _mf, coverage, corners = _bbox_corner_cutout_count(exterior, [], area)
        self.assertEqual(count, 2, f"Expected 2 cutouts, got {count}")
        self.assertGreater(coverage, 0.70)
        self.assertEqual(corners, pair)
        self.assertIn(corners, _DIAGONAL_CORNER_PAIRS)

    def test_tl_br_diagonal(self):
        # 6×4 rectangle, 2×2 cuts at TL (0..2)×(0..2) and BR (4..6)×(2..4).
        exterior = [
            [2, 0], [6, 0], [6, 2], [4, 2], [4, 4], [0, 4], [0, 2], [2, 2], [2, 0],
        ]
        self._assert_diagonal(exterior, 16.0, frozenset({'TL', 'BR'}))

    def test_tr_bl_diagonal(self):
        # 6×4 rectangle, 2×2 cuts at TR (4..6)×(0..2) and BL (0..2)×(2..4).
        exterior = [
            [0, 0], [4, 0], [4, 2], [6, 2], [6, 4], [2, 4], [2, 2], [0, 2], [0, 0],
        ]
        self._assert_diagonal(exterior, 16.0, frozenset({'TR', 'BL'}))


# ---------------------------------------------------------------------------
# Two adjacent cutouts — T_shape
# ---------------------------------------------------------------------------

class TestAdjacentCutouts(unittest.TestCase):
    """Two corner cutouts at adjacent corners sharing one side → T_shape."""

    def _assert_adjacent(self, exterior: list, area: float, pair: frozenset) -> None:
        count, _mf, coverage, corners = _bbox_corner_cutout_count(exterior, [], area)
        self.assertEqual(count, 2, f"Expected 2 cutouts, got {count}")
        self.assertGreater(coverage, 0.70)
        self.assertEqual(corners, pair)
        self.assertIn(corners, _ADJACENT_CORNER_PAIRS)

    def test_tl_tr_top_edge(self):
        # 6×4 rectangle, 2×2 cuts at TL (0..2)×(0..2) and TR (4..6)×(0..2).
        # Leaves a T shape (stem pointing up).
        exterior = [
            [2, 0], [4, 0], [4, 2], [6, 2], [6, 4], [0, 4], [0, 2], [2, 2], [2, 0],
        ]
        self._assert_adjacent(exterior, 16.0, frozenset({'TL', 'TR'}))

    def test_bl_br_bottom_edge(self):
        # 6×4 rectangle, 2×2 cuts at BL (0..2)×(2..4) and BR (4..6)×(2..4).
        # Leaves a T shape (stem pointing down).
        exterior = [
            [0, 0], [6, 0], [6, 2], [4, 2], [4, 4], [2, 4], [2, 2], [0, 2], [0, 0],
        ]
        self._assert_adjacent(exterior, 16.0, frozenset({'BL', 'BR'}))

    def test_tl_bl_left_edge(self):
        # 6×4 rectangle, 2×2 cuts at TL (0..2)×(0..2) and BL (0..2)×(2..4).
        # Leaves a T shape (stem pointing left).
        exterior = [
            [2, 0], [6, 0], [6, 4], [2, 4], [2, 2], [0, 2], [0, 0],
        ]
        # Wait — this polygon has the left strip removed entirely (2 blocks wide × 4 tall).
        # That touches both left+top AND left+bottom — but it is ONE component spanning
        # the full height, so edge_count=3 (left+top+bottom) → is_opposite (top+bottom) → NOT a corner.
        # Instead, build two separate cuts: small cuts at corners only.
        # TL cut: (0..2)×(0..1.5) — does not reach z=4 so only touches top+left
        # BL cut: (0..2)×(2.5..4) — only touches bottom+left
        exterior = [
            [2, 0], [6, 0], [6, 4], [2, 4], [2, 2.5], [0, 2.5], [0, 1.5], [2, 1.5], [2, 0],
        ]
        self._assert_adjacent(exterior, 18.0, frozenset({'TL', 'BL'}))

    def test_tr_br_right_edge(self):
        # 6×4 rectangle, cuts at TR (4..6)×(0..1.5) and BR (4..6)×(2.5..4).
        # Leaves a T shape (stem pointing right).
        exterior = [
            [0, 0], [4, 0], [4, 1.5], [6, 1.5], [6, 2.5], [4, 2.5], [4, 4], [0, 4], [0, 0],
        ]
        # This shape has a horizontal bar on the right (the part that remains between cuts)
        # not a cutout — let's rethink.
        # The negative space (bbox − island) consists of:
        #   region A: (4..6)×(0..1.5) → touches right(max_x) + top(min_z) → TR
        #   region B: (4..6)×(2.5..4) → touches right(max_x) + bottom(max_z) → BR
        self._assert_adjacent(exterior, 20.0, frozenset({'TR', 'BR'}))


# ---------------------------------------------------------------------------
# Four cutouts — e.g. Minecraft diamond / circle approximation
# ---------------------------------------------------------------------------

class TestFourCutouts(unittest.TestCase):
    """Shapes where all four corners of the bbox are rectangular cutouts."""

    def test_minecraft_diamond_4x4(self):
        # 4×4 Minecraft circle approximation (staircase diamond).
        # The 4 bbox corners are each 1×1 solid squares (fill=1.0), each touching
        # exactly two adjacent bbox edges → 4 qualifying corner cutouts.
        exterior = [
            [1, 0], [3, 0], [3, 1], [4, 1], [4, 3],
            [3, 3], [3, 4], [1, 4], [1, 3], [0, 3],
            [0, 1], [1, 1], [1, 0],
        ]
        count, _mf, _cov, corners = _bbox_corner_cutout_count(exterior, [], 12.0)
        self.assertEqual(count, 4)
        self.assertEqual(corners, frozenset({'TL', 'TR', 'BL', 'BR'}))

    def test_plus_shape_5x5(self):
        # Plus / cross in a 5×5 bbox.  Each corner quadrant (2×2) is solid negative
        # space touching exactly two adjacent bbox edges → 4 qualifying corner cutouts.
        exterior = [
            [2, 0], [3, 0], [3, 2], [5, 2], [5, 3],
            [3, 3], [3, 5], [2, 5], [2, 3], [0, 3],
            [0, 2], [2, 2], [2, 0],
        ]
        count, _mf, _cov, corners = _bbox_corner_cutout_count(exterior, [], 9.0)
        self.assertEqual(count, 4)
        self.assertEqual(corners, frozenset({'TL', 'TR', 'BL', 'BR'}))


# ---------------------------------------------------------------------------
# Corner pair constant tests
# ---------------------------------------------------------------------------

class TestCornerPairConstants(unittest.TestCase):
    """Verify the diagonal / adjacent pair constants cover all expected combos."""

    def test_diagonal_pairs_count(self):
        self.assertEqual(len(_DIAGONAL_CORNER_PAIRS), 2)

    def test_adjacent_pairs_count(self):
        self.assertEqual(len(_ADJACENT_CORNER_PAIRS), 4)

    def test_diagonal_and_adjacent_are_disjoint(self):
        diag_set = set(_DIAGONAL_CORNER_PAIRS)
        adj_set = set(_ADJACENT_CORNER_PAIRS)
        self.assertEqual(diag_set & adj_set, set())

    def test_all_two_corner_combos_covered(self):
        # There are C(4,2) = 6 possible pairs of corners; 2 diagonal + 4 adjacent = 6.
        all_corners = {'TL', 'TR', 'BL', 'BR'}
        all_pairs = {
            frozenset({a, b})
            for i, a in enumerate(sorted(all_corners))
            for b in sorted(all_corners)
            if a < b
        }
        classified = set(_DIAGONAL_CORNER_PAIRS) | set(_ADJACENT_CORNER_PAIRS)
        self.assertEqual(classified, all_pairs)


if __name__ == '__main__':
    unittest.main()
