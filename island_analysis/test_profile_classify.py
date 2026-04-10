"""Synthetic classification tests for island_analysis.profile.classify_island().

Tests that each shape category is detected correctly by constructing IslandFeatures
objects that represent idealised versions of each shape, using feature values derived
from verified real-world examples.

Run with:
    python -m unittest island_analysis.test_profile_classify
"""

import unittest

from island_analysis.profile import IslandFeatures, classify_island


def _make_features(**overrides) -> IslandFeatures:
    """Build an IslandFeatures with safe defaults and apply keyword overrides."""
    defaults = dict(
        canonical_key='test',
        aspect_ratio=1.0,
        compactness=0.7,
        convexity=0.75,
        pca_elongation=1.0,
        pca_angle_deg=0.0,
        hole_count=0,
        hole_ratio=0.0,
        bbox_width=20.0,
        bbox_height=20.0,
        area=400,
        perimeter=80.0,
        bbox_fill_ratio=1.0,
        rugosity=1.0,
        circle_fit_residual=0.30,   # high by default → not round; override for circles
        ellipse_residual=0.25,      # high by default → not round; override for ellipses
        skeleton_endpoint_count=2,
        skeleton_junction_count=0,
        skeleton_total_length=20.0,
        skeleton_topology='line',
        skeleton_path_bends=0,
    )
    defaults.update(overrides)
    return IslandFeatures(**defaults)


class TestSquareAndRectangle(unittest.TestCase):
    """Rules 1 & 2 — box-filling shapes."""

    def test_square(self):
        feat = _make_features(
            bbox_fill_ratio=0.95,
            aspect_ratio=1.05,
            convexity=0.96,
            skeleton_topology='none',
        )
        self.assertEqual(classify_island(feat), 'square')

    def test_rectangle(self):
        feat = _make_features(
            bbox_fill_ratio=0.92,
            aspect_ratio=2.0,
            convexity=0.95,
            skeleton_topology='none',
        )
        self.assertEqual(classify_island(feat), 'rectangle')

    def test_square_below_fill_threshold_not_square(self):
        """Low fill ratio must not classify as square even if otherwise round."""
        feat = _make_features(
            bbox_fill_ratio=0.70,
            aspect_ratio=1.0,
            convexity=0.95,
            skeleton_topology='none',
        )
        self.assertNotIn(classify_island(feat), ('square', 'rectangle'))


class TestDonut(unittest.TestCase):
    """Rule 3 — ring/annular shape.

    Verified reference examples (canonical_key prefix → map):
      8b48d700 → kingdom      convexity=0.988, rugosity=0.993, holes=1
      26761f15 → ouroboros    convexity=0.944, rugosity=1.058, holes=1
      00ad665f → pineium_ctw  convexity=0.952, rugosity=1.000, holes=1
    """

    def test_donut_kingdom_like(self):
        """High-convexity ring, single hole."""
        feat = _make_features(
            hole_count=1,
            convexity=0.988,
            rugosity=0.993,
            bbox_fill_ratio=0.715,
            skeleton_topology='none',
        )
        self.assertEqual(classify_island(feat), 'donut')

    def test_donut_ouroboros_like(self):
        """Moderate-convexity ring."""
        feat = _make_features(
            hole_count=1,
            convexity=0.944,
            rugosity=1.058,
            bbox_fill_ratio=0.34,
            skeleton_topology='none',
        )
        self.assertEqual(classify_island(feat), 'donut')

    def test_donut_pineium_like(self):
        """Small ring with single hole."""
        feat = _make_features(
            hole_count=1,
            convexity=0.952,
            rugosity=1.000,
            bbox_fill_ratio=0.82,
            skeleton_topology='none',
        )
        self.assertEqual(classify_island(feat), 'donut')

    def test_rugged_with_hole_not_donut(self):
        """Rugged island that encloses an air gap should NOT be classified as donut.

        This was the root cause of 97 false positives: hole_count >= 1 alone
        fires on any island whose block boundary encloses internal air, even
        complex rugged or fork shapes.
        """
        feat = _make_features(
            hole_count=2,
            convexity=0.66,   # jagged outer boundary
            rugosity=1.64,    # well above 1.1 — perimeter is very irregular
            skeleton_topology='none',
        )
        self.assertNotEqual(classify_island(feat), 'donut')

    def test_fork_with_hole_not_donut(self):
        """Complex branching island with enclosed pocket must not become donut."""
        feat = _make_features(
            hole_count=1,
            convexity=0.55,
            rugosity=1.51,
            skeleton_junction_count=2,
            skeleton_endpoint_count=4,
            skeleton_topology='tree',
        )
        self.assertNotEqual(classify_island(feat), 'donut')

    def test_boundary_convexity_below_threshold(self):
        """hole_count=1 with convexity just below 0.92 is not donut."""
        feat = _make_features(
            hole_count=1,
            convexity=0.91,
            rugosity=1.00,
            skeleton_topology='none',
        )
        self.assertNotEqual(classify_island(feat), 'donut')

    def test_boundary_rugosity_above_threshold(self):
        """hole_count=1 with rugosity just above 1.1 is not donut."""
        feat = _make_features(
            hole_count=1,
            convexity=0.95,
            rugosity=1.11,
            skeleton_topology='none',
        )
        self.assertNotEqual(classify_island(feat), 'donut')


class TestCircleEllipse(unittest.TestCase):
    """Rule 4 — circle or ellipse: fits a circle/ellipse curve well.

    Verified reference examples:
      a6d59506 → summertime_at_browns_farms  asp=1.00 circle_fit_residual=0.032
      e23c5e30 → sweetopia / thunderbolt     asp=1.00 circle_fit_residual=0.046
      696bce97 → exitium                     asp=2.27 ellipse_residual=0.072
      5e5e0548 → chestnut                    asp=1.55 ellipse_residual=0.072
      422ead87 → xion                        asp=2.27 ellipse_residual=0.086
      68672a4c → xion                        asp=1.44 ellipse_residual=0.079

    Previously misclassified as shard (a6d59506, e23c5e30) or blob (696bce97 etc.)
    because the old rule used topo='line' as a shard discriminator.  Minecraft
    pixelated circles frequently have line topology.
    """

    def test_circle_near_square_low_residual(self):
        """Near-circular island with low circle_fit_residual → circle.

        Mirrors a6d59506 (asp=1.00, circ_res=0.032) and e23c5e30 (circ_res=0.046).
        """
        feat = _make_features(
            convexity=0.95,
            aspect_ratio=1.0,
            circle_fit_residual=0.040,
            ellipse_residual=0.042,
            skeleton_topology='line',   # line topology must NOT block circle detection
            skeleton_path_bends=0,
            bbox_fill_ratio=0.78,
        )
        self.assertEqual(classify_island(feat), 'circle')

    def test_circle_with_line_topology_not_shard(self):
        """A Minecraft circle with line skeleton must not be classified as shard.

        This was the root cause: topo='line' was incorrectly used as a shard proxy.
        The residual is the correct discriminator.
        """
        feat = _make_features(
            convexity=0.934,
            aspect_ratio=1.0,
            circle_fit_residual=0.046,   # e23c5e30 actual value
            ellipse_residual=0.046,
            skeleton_topology='line',
            skeleton_path_bends=0,
            bbox_fill_ratio=0.778,
        )
        self.assertEqual(classify_island(feat), 'circle')

    def test_ellipse_elongated_low_residual(self):
        """Elongated oval (aspect > 1.2) with low ellipse_residual → circle.

        Mirrors 696bce97 (asp=2.27, ell_res=0.072).
        """
        feat = _make_features(
            convexity=0.942,
            aspect_ratio=2.27,
            circle_fit_residual=0.262,   # high — fitting a circle to an ellipse
            ellipse_residual=0.072,      # low — good ellipse fit
            skeleton_topology='line',
            skeleton_path_bends=0,
            bbox_fill_ratio=0.826,
        )
        self.assertEqual(classify_island(feat), 'circle')

    def test_ellipse_moderate_aspect_low_residual(self):
        """Aspect ~1.5 ellipse → circle.  Mirrors 5e5e0548 (asp=1.55, ell_res=0.072)."""
        feat = _make_features(
            convexity=0.924,
            aspect_ratio=1.55,
            circle_fit_residual=0.175,
            ellipse_residual=0.072,
            skeleton_topology='line',
            skeleton_path_bends=0,
            bbox_fill_ratio=0.786,
        )
        self.assertEqual(classify_island(feat), 'circle')

    def test_circle_boundary_residual_at_threshold(self):
        """Residual just below 0.08 passes; just above fails."""
        below = _make_features(convexity=0.90, aspect_ratio=1.0,
                               circle_fit_residual=0.079, ellipse_residual=0.079,
                               skeleton_topology='none', bbox_fill_ratio=0.75)
        above = _make_features(convexity=0.90, aspect_ratio=1.0,
                               circle_fit_residual=0.081, ellipse_residual=0.081,
                               skeleton_topology='none', bbox_fill_ratio=0.75)
        self.assertEqual(classify_island(below), 'circle')
        self.assertNotEqual(classify_island(above), 'circle')


class TestShard(unittest.TestCase):
    """Rule 5 — smooth two-pointed shape (diamond, rhombus, lens).

    Verified reference examples:
      fd4f5230 → station_x           convexity=0.962, circle_fit_residual=0.161
      b8c73a35 → ruedigers_octawool  convexity=0.950, circle_fit_residual=0.147
      c3bb195c → keipha_ctw          convexity=0.943, circle_fit_residual=0.179
      59523759 → nether_war_ctw      convexity=0.938, circle_fit_residual=0.297
    """

    def test_shard_station_x_like(self):
        feat = _make_features(
            convexity=0.962,
            circle_fit_residual=0.161,
            ellipse_residual=0.068,   # moderate but aspect=1.0 so circ_res governs
            skeleton_topology='line',
            skeleton_junction_count=0,
            skeleton_endpoint_count=2,
            skeleton_path_bends=0,
            bbox_fill_ratio=0.72,
        )
        self.assertEqual(classify_island(feat), 'shard')

    def test_shard_diamond_like(self):
        """Strong diamond shape (59523759): fill ≈ 0.5, high circle_fit_residual."""
        feat = _make_features(
            convexity=0.938,
            circle_fit_residual=0.297,
            ellipse_residual=0.145,
            skeleton_topology='line',
            skeleton_junction_count=0,
            skeleton_endpoint_count=2,
            skeleton_path_bends=0,
            bbox_fill_ratio=0.51,
        )
        self.assertEqual(classify_island(feat), 'shard')

    def test_line_topology_below_convexity_threshold_not_shard(self):
        """Line topology with convexity 0.88–0.93 is irregular — should not be shard."""
        feat = _make_features(
            convexity=0.89,
            circle_fit_residual=0.20,
            ellipse_residual=0.18,
            skeleton_topology='line',
            skeleton_junction_count=0,
            skeleton_endpoint_count=2,
            skeleton_path_bends=0,
            bbox_fill_ratio=0.60,
        )
        self.assertNotEqual(classify_island(feat), 'shard')

    def test_shard_requires_poor_ellipse_fit(self):
        """High convexity + line topology but LOW residual → circle, not shard.

        Prevents a Minecraft circle with line skeleton being classified as shard.
        """
        feat = _make_features(
            convexity=0.96,
            circle_fit_residual=0.040,  # good circle fit — it IS a circle
            ellipse_residual=0.040,
            bbox_fill_ratio=0.78,
            skeleton_topology='line',
            skeleton_path_bends=0,
        )
        self.assertEqual(classify_island(feat), 'circle')

    def test_shard_requires_line_topology(self):
        """High convexity alone is not enough — shard needs line topology."""
        feat = _make_features(
            convexity=0.96,
            circle_fit_residual=0.20,
            ellipse_residual=0.18,
            bbox_fill_ratio=0.70,
            skeleton_topology='none',
            skeleton_junction_count=0,
            skeleton_endpoint_count=0,
        )
        self.assertNotEqual(classify_island(feat), 'shard')


class TestPlus(unittest.TestCase):
    """Rule 6 — T / Y / + / star shape.

    Verified reference examples:
      bec526f8 → ruedigers_octawool  junct=1, endpt=4
      9f0308d2 → philosophers_stone  junct=1, endpt=4
      e181ac30 → emergency_meeting   junct=1, endpt=4
    """

    def test_plus_four_arm(self):
        feat = _make_features(
            convexity=0.66,
            skeleton_topology='tree',
            skeleton_junction_count=1,
            skeleton_endpoint_count=4,
            skeleton_path_bends=None,
        )
        self.assertEqual(classify_island(feat), 'plus')

    def test_plus_three_arm(self):
        """T / Y shapes also count — ≥ 3 endpoints."""
        feat = _make_features(
            convexity=0.72,
            skeleton_topology='tree',
            skeleton_junction_count=1,
            skeleton_endpoint_count=3,
            skeleton_path_bends=None,
        )
        self.assertEqual(classify_island(feat), 'plus')

    def test_two_junctions_not_plus(self):
        """Two junctions → fork territory, not plus."""
        feat = _make_features(
            convexity=0.60,
            skeleton_topology='tree',
            skeleton_junction_count=2,
            skeleton_endpoint_count=4,
            skeleton_path_bends=None,
        )
        self.assertNotEqual(classify_island(feat), 'plus')


class TestLShape(unittest.TestCase):
    """Rule 8 — single 90° bend in a line-topology path.

    Verified reference examples:
      5a56b3ce → garf    bends=1, topo=line
      8129bfc8 → vertex  bends=1, topo=line
      26cfa209 → vesuvius bends=1, topo=line
    """

    def test_l_shape_garf_like(self):
        feat = _make_features(
            convexity=0.714,
            skeleton_topology='line',
            skeleton_junction_count=0,
            skeleton_endpoint_count=2,
            skeleton_path_bends=1,
            bbox_fill_ratio=0.56,
        )
        self.assertEqual(classify_island(feat), 'L_shape')

    def test_l_shape_vesuvius_like(self):
        feat = _make_features(
            convexity=0.662,
            skeleton_topology='line',
            skeleton_junction_count=0,
            skeleton_endpoint_count=2,
            skeleton_path_bends=1,
            bbox_fill_ratio=0.49,
        )
        self.assertEqual(classify_island(feat), 'L_shape')

    def test_zero_bends_not_l(self):
        """Straight line path must not be L_shape."""
        feat = _make_features(
            convexity=0.71,
            skeleton_topology='line',
            skeleton_junction_count=0,
            skeleton_endpoint_count=2,
            skeleton_path_bends=0,
            bbox_fill_ratio=0.55,
        )
        self.assertNotEqual(classify_island(feat), 'L_shape')


class TestZShape(unittest.TestCase):
    """Rule 9 — two or more direction changes in a line-topology path."""

    def test_z_shape_two_bends(self):
        feat = _make_features(
            convexity=0.775,
            skeleton_topology='line',
            skeleton_junction_count=0,
            skeleton_endpoint_count=2,
            skeleton_path_bends=2,
            bbox_fill_ratio=0.49,
        )
        self.assertEqual(classify_island(feat), 'Z_shape')

    def test_z_shape_three_bends(self):
        feat = _make_features(
            convexity=0.737,
            skeleton_topology='line',
            skeleton_junction_count=0,
            skeleton_endpoint_count=2,
            skeleton_path_bends=3,
        )
        self.assertEqual(classify_island(feat), 'Z_shape')

    def test_one_bend_not_z(self):
        """One bend is L_shape, not Z_shape."""
        feat = _make_features(
            convexity=0.72,
            skeleton_topology='line',
            skeleton_junction_count=0,
            skeleton_endpoint_count=2,
            skeleton_path_bends=1,
        )
        self.assertEqual(classify_island(feat), 'L_shape')


class TestFallthrough(unittest.TestCase):
    """Remaining categories — rugged, linear, blob."""

    def test_rugged(self):
        feat = _make_features(
            rugosity=1.5,
            convexity=0.65,
            aspect_ratio=1.2,
            skeleton_topology='none',
        )
        self.assertEqual(classify_island(feat), 'rugged')

    def test_linear(self):
        feat = _make_features(
            aspect_ratio=3.0,
            rugosity=1.05,
            convexity=0.72,
            skeleton_topology='line',
            skeleton_path_bends=0,
            # bends=0 so L/Z don't fire; low convexity so shard doesn't fire
        )
        self.assertEqual(classify_island(feat), 'linear')

    def test_blob(self):
        feat = _make_features(
            aspect_ratio=1.2,
            rugosity=1.05,
            convexity=0.72,
            skeleton_topology='none',
        )
        self.assertEqual(classify_island(feat), 'blob')


if __name__ == '__main__':
    unittest.main()
