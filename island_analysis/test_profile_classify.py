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
        bbox_fill_ratio=0.78,    # neutral default; override to 1.0 for rectangle tests
        rugosity=1.0,
        circle_fit_residual=0.30,   # high by default → not round; override for circles
        ellipse_residual=0.25,      # high by default → not round; override for ellipses
        skeleton_endpoint_count=2,
        skeleton_junction_count=0,
        skeleton_total_length=20.0,
        skeleton_topology='line',
        skeleton_path_bends=0,
        has_point_symmetry=False,
    )
    defaults.update(overrides)
    return IslandFeatures(**defaults)


class TestSquareAndRectangle(unittest.TestCase):
    """Rules 1 & 2 — box-filling shapes."""

    def test_square_folds_into_rectangle(self):
        """Near-square shape (equal bbox sides) -> 'rectangle', is_square=True."""
        feat = _make_features(
            bbox_fill_ratio=0.95,
            aspect_ratio=1.05,
            convexity=0.96,
            skeleton_topology='none',
            bbox_width=20.0,
            bbox_height=20.0,  # equal sides → is_square=True
        )
        # classify_island returns 'rectangle' for squares; is_square flag via _classify_full
        self.assertEqual(classify_island(feat), 'rectangle')
        from island_analysis.profile import _classify_full
        arch, bnd, is_sq, _ = _classify_full(feat)
        self.assertEqual(arch, 'rectangle')
        self.assertTrue(is_sq)

    def test_rectangle(self):
        feat = _make_features(
            bbox_fill_ratio=1.0,
            aspect_ratio=2.0,
            convexity=0.95,
            skeleton_topology='none',
            bbox_width=10.0,
            bbox_height=20.0,   # different sides -> not square
        )
        self.assertEqual(classify_island(feat), 'rectangle')

    def test_square_below_fill_threshold_not_rectangle(self):
        """Low fill ratio must not classify as rectangle."""
        feat = _make_features(
            bbox_fill_ratio=0.70,
            aspect_ratio=1.0,
            convexity=0.95,
            skeleton_topology='none',
        )
        self.assertNotIn(classify_island(feat), ('square', 'rectangle'))


class TestRing(unittest.TestCase):
    """Rules 3/3.5 — ring/annular shape (formerly 'donut').

    Verified reference examples (canonical_key prefix → map):
      8b48d700 → kingdom      convexity=0.988, rugosity=0.993, holes=1
      26761f15 → ouroboros    convexity=0.944, rugosity=1.058, holes=1
      00ad665f → pineium_ctw  convexity=0.952, rugosity=1.000, holes=1
    """

    def test_ring_kingdom_like(self):
        """High-convexity ring, single hole."""
        feat = _make_features(
            hole_count=1,
            convexity=0.988,
            rugosity=0.993,
            bbox_fill_ratio=0.715,
            skeleton_topology='none',
        )
        self.assertEqual(classify_island(feat), 'ring')

    def test_ring_ouroboros_like(self):
        """Moderate-convexity ring."""
        feat = _make_features(
            hole_count=1,
            convexity=0.944,
            rugosity=1.058,
            bbox_fill_ratio=0.34,
            skeleton_topology='none',
        )
        self.assertEqual(classify_island(feat), 'ring')

    def test_ring_pineium_like(self):
        """Small ring with single hole."""
        feat = _make_features(
            hole_count=1,
            convexity=0.952,
            rugosity=1.000,
            bbox_fill_ratio=0.82,
            skeleton_topology='none',
        )
        self.assertEqual(classify_island(feat), 'ring')

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
        self.assertNotEqual(classify_island(feat), 'ring')

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
        self.assertNotEqual(classify_island(feat), 'ring')

    def test_boundary_convexity_below_threshold(self):
        """hole_count=1 with convexity just below 0.92 is not donut."""
        feat = _make_features(
            hole_count=1,
            convexity=0.91,
            rugosity=1.00,
            skeleton_topology='none',
        )
        self.assertNotEqual(classify_island(feat), 'ring')

    def test_boundary_rugosity_above_threshold(self):
        """hole_count=1 with rugosity just above 1.1 is not donut."""
        feat = _make_features(
            hole_count=1,
            convexity=0.95,
            rugosity=1.11,
            skeleton_topology='none',
        )
        self.assertNotEqual(classify_island(feat), 'ring')

    def test_multiple_holes_not_donut(self):
        """hole_count > 1 is NOT a donut — a genuine ring has exactly one void.

        e22d8e28 (emergency_meeting): circle-shaped ring whose blocks don't fully
        close at the top, creating two separate air pockets (hole_count=2).
        15ef7fba (goo_lagoon): complex island with 4 enclosed pockets.
        Both had smooth outer boundaries that passed the old hole_count >= 1 rule.
        """
        for holes in (2, 3, 4):
            feat = _make_features(
                hole_count=holes,
                convexity=0.93,
                rugosity=1.00,
                skeleton_topology='none',
            )
            self.assertNotEqual(
                classify_island(feat), 'ring',
                msg=f'hole_count={holes} should not classify as ring',
            )


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
            has_point_symmetry=True,
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
            has_point_symmetry=True,
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
            has_point_symmetry=True,
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
            has_point_symmetry=True,
        )
        self.assertEqual(classify_island(feat), 'circle')

    def test_circle_boundary_residual_at_threshold(self):
        """circ_res just below 0.12 passes; just above fails (near-square shapes)."""
        below = _make_features(convexity=0.90, aspect_ratio=1.0,
                               circle_fit_residual=0.119, ellipse_residual=0.119,
                               skeleton_topology='none', bbox_fill_ratio=0.75,
                               has_point_symmetry=True)
        above = _make_features(convexity=0.90, aspect_ratio=1.0,
                               circle_fit_residual=0.121, ellipse_residual=0.121,
                               skeleton_topology='none', bbox_fill_ratio=0.75,
                               has_point_symmetry=True)
        self.assertEqual(classify_island(below), 'circle')
        self.assertNotEqual(classify_island(above), 'circle')

    def test_small_circle_radius2_worldedit(self):
        """WorldEdit radius-2 cylinder (area=21) has circ_res ~0.11 — must be circle.

        6eb91fd7: conv=0.913, circ_res=0.110 — previously landed in blob because
        the old threshold (0.08) was too tight for small Minecraft circles.
        """
        feat = _make_features(
            convexity=0.913, aspect_ratio=1.0,
            circle_fit_residual=0.1097, ellipse_residual=0.1172,
            bbox_fill_ratio=0.84, area=21,
            skeleton_topology='none',
            has_point_symmetry=True,
        )
        self.assertEqual(classify_island(feat), 'circle')

    def test_ellipse_fill_gate_separates_from_shard(self):
        """Elongated ellipse (fill≥0.72) is circle; elongated shard (fill<0.72) is not.

        5e666a93 (ellipse): ell_res=0.094, fill=0.771 → circle
        296006fc (shard):   ell_res=0.092, fill=0.697 → NOT circle (low fill)
        """
        ellipse = _make_features(
            convexity=0.900, aspect_ratio=1.43,
            ellipse_residual=0.0942, circle_fit_residual=0.15,
            bbox_fill_ratio=0.7714, has_point_symmetry=True,
            skeleton_topology='line',
        )
        shard_shape = _make_features(
            convexity=0.895, aspect_ratio=1.36,
            ellipse_residual=0.0916, circle_fit_residual=0.17,
            bbox_fill_ratio=0.6970,
            skeleton_topology='line',
        )
        self.assertEqual(classify_island(ellipse), 'circle')
        self.assertNotEqual(classify_island(shard_shape), 'circle')

    def test_circle_with_holes_not_circle(self):
        """A round shape with interior holes must not classify as circle.

        e22d8e28 (emergency_meeting): ring shape with unclosed top → hole_count=2,
        circle_fit_residual=0.077.  Smooth and round but has holes — not a solid circle.
        """
        feat = _make_features(
            convexity=0.92,
            aspect_ratio=1.0,
            circle_fit_residual=0.077,
            ellipse_residual=0.077,
            hole_count=2,
            skeleton_topology='none',
            bbox_fill_ratio=0.70,
        )
        self.assertNotEqual(classify_island(feat), 'circle')


class TestShard(unittest.TestCase):
    """Rule 5 — smooth two-pointed shape (diamond, rhombus, lens, tear).

    Original verified examples (high convexity):
      fd4f5230 → station_x           convexity=0.962, circle_fit_residual=0.161
      b8c73a35 → ruedigers_octawool  convexity=0.950, circle_fit_residual=0.147
      c3bb195c → keipha_ctw          convexity=0.943, circle_fit_residual=0.179
      59523759 → nether_war_ctw      convexity=0.938, circle_fit_residual=0.297

    Additional verified examples (lower convexity, previously mis-classified as blob):
      cb5874e2 → station_x           convexity=0.923, circle_fit_residual=0.146
      3855d0e3 → istana_ctw          convexity=0.919, circle_fit_residual=0.253
      de43e1a0 → istana_ctw          convexity=0.890, aspect=1.45, fill=0.619
      296006fc → thunderbolt         convexity=0.895, aspect=1.36, fill=0.697
      ad1f82ab → bloom               convexity=0.882, aspect=2.0,  fill=0.600
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

    def test_shard_lower_convexity_near_square(self):
        """Diamond/shard with convexity 0.88–0.93 and high circ_res → shard.

        cb5874e2: conv=0.923, circ_res=0.146 — previously blob due to old threshold 0.93.
        3855d0e3: conv=0.919, circ_res=0.253 — same issue.
        """
        for conv, circ in [(0.923, 0.146), (0.919, 0.253)]:
            feat = _make_features(
                convexity=conv,
                circle_fit_residual=circ,
                ellipse_residual=0.14,
                aspect_ratio=1.0,
                skeleton_topology='line',
                skeleton_junction_count=0,
                skeleton_endpoint_count=2,
                skeleton_path_bends=0,
                bbox_fill_ratio=0.68,
            )
            self.assertEqual(classify_island(feat), 'shard', msg=f'conv={conv}')

    def test_shard_elongated_low_fill(self):
        """Elongated tear/shard with low fill → shard even when ell_res is low.

        de43e1a0: conv=0.890, asp=1.45, ell_res=0.100, fill=0.619 → shard
        296006fc: conv=0.895, asp=1.36, ell_res=0.092, fill=0.697 → shard
        Both have ell_res near the 0.10 threshold, but fill < 0.72 forces shard.
        """
        for conv, asp, ell, fill in [(0.890, 1.45, 0.0998, 0.619),
                                     (0.895, 1.36, 0.0916, 0.697)]:
            feat = _make_features(
                convexity=conv, aspect_ratio=asp,
                ellipse_residual=ell, circle_fit_residual=0.26,
                bbox_fill_ratio=fill,
                skeleton_topology='line',
                skeleton_junction_count=0,
                skeleton_endpoint_count=2,
                skeleton_path_bends=0,
            )
            self.assertEqual(classify_island(feat), 'shard', msg=f'conv={conv} fill={fill}')

    def test_shard_diamond_low_convexity(self):
        """Diamond (ad1f82ab): conv=0.882 just below circle gate (0.88) → shard via Rule 5.

        Conv 0.882 < 0.88 so Rule 4 (circle) never fires.  Rule 5 catches it.
        """
        feat = _make_features(
            convexity=0.882, aspect_ratio=2.0,
            ellipse_residual=0.1121, circle_fit_residual=0.2528,
            bbox_fill_ratio=0.600,
            skeleton_topology='line',
            skeleton_junction_count=0,
            skeleton_endpoint_count=2,
            skeleton_path_bends=0,
        )
        self.assertEqual(classify_island(feat), 'shard')

    def test_shard_requires_convexity_above_floor(self):
        """Convexity below 0.87 is too irregular for shard."""
        feat = _make_features(
            convexity=0.86,
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
            has_point_symmetry=True,
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
            skeleton_min_arm_angle=90.0,  # well above 60° threshold
            skeleton_path_bends=None,
        )
        self.assertEqual(classify_island(feat), 'plus')

    def test_plus_three_arm_not_plus(self):
        """3-endpoint shapes do NOT match plus (requires exactly 4 endpoints)."""
        feat = _make_features(
            convexity=0.72,
            skeleton_topology='tree',
            skeleton_junction_count=1,
            skeleton_endpoint_count=3,
            skeleton_path_bends=None,
        )
        self.assertNotEqual(classify_island(feat), 'plus')

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
    """Rules 4.5/4.8 — L-shape via bbox corner cutout."""

    def test_l_clean(self):
        """One clean corner cut (coverage >= 0.90) -> 'L'."""
        feat = _make_features(
            convexity=0.714,
            skeleton_topology='line',
            bbox_fill_ratio=0.75,
            bbox_cutout_count=1,
            bbox_cutout_coverage=0.93,
            bbox_cutout_min_fill=0.97,
            bbox_cutout_corners=frozenset({'TL'}),
        )
        self.assertEqual(classify_island(feat), 'L')

    def test_l_noisy(self):
        """One corner cut with weaker coverage (0.70-0.90) -> 'L_noisy'."""
        feat = _make_features(
            convexity=0.68,
            skeleton_topology='none',
            bbox_fill_ratio=0.75,
            bbox_cutout_count=1,
            bbox_cutout_coverage=0.75,
            bbox_cutout_min_fill=0.95,
            bbox_cutout_corners=frozenset({'BR'}),
        )
        self.assertEqual(classify_island(feat), 'L_noisy')

    def test_no_cutout_not_l(self):
        """No corner cut must not be L."""
        feat = _make_features(
            convexity=0.71,
            skeleton_topology='line',
            bbox_fill_ratio=0.55,
        )
        self.assertNotIn(classify_island(feat), ('L', 'L_noisy'))


class TestZShape(unittest.TestCase):
    """Rules 4.6/4.9 — Z-shape via diagonal bbox corner cutouts."""

    def test_z_clean_diagonal(self):
        """Two diagonal corner cuts (TL+BR) -> 'Z'."""
        feat = _make_features(
            convexity=0.775,
            skeleton_topology='none',
            bbox_fill_ratio=0.65,
            bbox_cutout_count=2,
            bbox_cutout_coverage=0.92,
            bbox_cutout_min_fill=0.96,
            bbox_cutout_corners=frozenset({'TL', 'BR'}),
        )
        self.assertEqual(classify_island(feat), 'Z')

    def test_z_noisy_diagonal(self):
        """Weaker diagonal cuts -> 'Z_noisy'."""
        feat = _make_features(
            convexity=0.75,
            skeleton_topology='none',
            bbox_fill_ratio=0.65,
            bbox_cutout_count=2,
            bbox_cutout_coverage=0.78,
            bbox_cutout_min_fill=0.95,
            bbox_cutout_corners=frozenset({'TR', 'BL'}),
        )
        self.assertEqual(classify_island(feat), 'Z_noisy')

    def test_adjacent_cuts_not_z(self):
        """Two adjacent corner cuts are T not Z."""
        feat = _make_features(
            convexity=0.75,
            skeleton_topology='none',
            bbox_fill_ratio=0.65,
            bbox_cutout_count=2,
            bbox_cutout_coverage=0.92,
            bbox_cutout_min_fill=0.96,
            bbox_cutout_corners=frozenset({'TL', 'TR'}),
        )
        self.assertNotEqual(classify_island(feat), 'Z')


class TestFallthrough(unittest.TestCase):
    """Remaining categories — amoeba_rugged, linear, amoeba."""

    def test_amoeba_rugged(self):
        """Rugosity >= 1.2 and no deep concavity -> 'amoeba_rugged'."""
        feat = _make_features(
            rugosity=1.5,
            convexity=0.65,
            aspect_ratio=1.2,
            skeleton_topology='none',
        )
        self.assertEqual(classify_island(feat), 'amoeba_rugged')

    def test_linear(self):
        feat = _make_features(
            aspect_ratio=3.0,
            rugosity=1.05,
            convexity=0.72,
            skeleton_topology='line',
            skeleton_path_bends=0,
        )
        self.assertEqual(classify_island(feat), 'linear')

    def test_amoeba(self):
        """Default fallthrough -> 'amoeba' (formerly 'blob')."""
        feat = _make_features(
            aspect_ratio=1.2,
            rugosity=1.05,
            convexity=0.72,
            skeleton_topology='none',
        )
        self.assertEqual(classify_island(feat), 'amoeba')


if __name__ == '__main__':
    unittest.main()
