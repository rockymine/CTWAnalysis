"""Tests for symmetry_analysis.builder.

Uses synthetic island layouts with known symmetry properties to verify
center classification, pair transform detection, global symmetry scoring,
group-aware pair counting, and intra-team symmetry (mirror split and
canonical coverage).
"""

import json
import os
import tempfile
import unittest

from symmetry_analysis.builder import (
    classify_center,
    _build_canonical_pairs,
    _detect_pair_transform,
    _aggregate_pair_transforms,
    _detect_global_symmetry,
    _verify_polygon_symmetry,
    _assign_islands_to_teams,
    _check_canonical_coverage,
    _detect_intra_team_symmetry,
    detect_symmetry,
)


# ---------------------------------------------------------------------------
# Helpers — synthetic island builders
# ---------------------------------------------------------------------------

def _make_island(island_id, center, area, team=None, has_spawn=False,
                 has_wool=False, has_center=False, polygon_offset=None):
    """Create a minimal island dict matching map_context.json format.

    If polygon_offset is None, generates a square polygon centered on `center`
    whose side length approximates the given area.
    """
    cx, cz = center
    half = area ** 0.5 / 2.0
    if polygon_offset is not None:
        ox, oz = polygon_offset
    else:
        ox, oz = cx, cz

    exterior = [
        [ox - half, oz - half],
        [ox + half, oz - half],
        [ox + half, oz + half],
        [ox - half, oz + half],
        [ox - half, oz - half],
    ]

    isl = {
        "id": island_id,
        "center": list(center),
        "area": area,
        "simplified_polygon": {"exterior": exterior, "holes": []},
        "has_center": has_center,
        "has_spawn": has_spawn,
        "has_wool": has_wool,
    }
    if team:
        isl["team"] = team
    return isl


def _make_rect_island(island_id, x_min, x_max, z_min, z_max, team=None,
                      has_spawn=False, has_wool=False, has_center=False):
    """Create an island dict with an explicit rectangular polygon."""
    cx = (x_min + x_max) / 2.0
    cz = (z_min + z_max) / 2.0
    area = (x_max - x_min) * (z_max - z_min)
    exterior = [
        [x_min, z_min], [x_max, z_min], [x_max, z_max],
        [x_min, z_max], [x_min, z_min],
    ]
    isl = {
        "id": island_id,
        "center": [cx, cz],
        "area": area,
        "simplified_polygon": {"exterior": exterior, "holes": []},
        "has_center": has_center,
        "has_spawn": has_spawn,
        "has_wool": has_wool,
    }
    if team:
        isl["team"] = team
    return isl


# ===================================================================
# Center classification
# ===================================================================

class TestClassifyCenter(unittest.TestCase):
    """Tests for classify_center with all four center types."""

    def test_single_block_center(self):
        """Odd x Odd dimensions -> single block center."""
        # 5 wide x 7 tall -> center at (2.5, 3.5) -> block (2, 3)
        result = classify_center((0, 5, 0, 7))
        self.assertEqual(result["type"], "single_block")
        self.assertAlmostEqual(result["center_x"], 2.5)
        self.assertAlmostEqual(result["center_z"], 3.5)
        self.assertEqual(result["blocks"], [(2, 3)])
        self.assertEqual(result["map_width_x"], 5)
        self.assertEqual(result["map_width_z"], 7)

    def test_2x2_area_center(self):
        """Even x Even dimensions -> 2x2 center area."""
        # 6 wide x 8 tall -> center at (3.0, 4.0) -> blocks (2,3)x(3,4)
        result = classify_center((0, 6, 0, 8))
        self.assertEqual(result["type"], "2x2_area")
        self.assertAlmostEqual(result["center_x"], 3.0)
        self.assertAlmostEqual(result["center_z"], 4.0)
        self.assertEqual(len(result["blocks"]), 4)
        self.assertIn((2, 3), result["blocks"])
        self.assertIn((3, 3), result["blocks"])
        self.assertIn((2, 4), result["blocks"])
        self.assertIn((3, 4), result["blocks"])

    def test_2x1_line_center(self):
        """Even x Odd dimensions -> 2x1 center line."""
        # 6 wide x 7 tall -> center at (3.0, 3.5) -> blocks (2,3) and (3,3)
        result = classify_center((0, 6, 0, 7))
        self.assertEqual(result["type"], "2x1_line")
        self.assertAlmostEqual(result["center_x"], 3.0)
        self.assertAlmostEqual(result["center_z"], 3.5)
        self.assertEqual(len(result["blocks"]), 2)
        self.assertIn((2, 3), result["blocks"])
        self.assertIn((3, 3), result["blocks"])

    def test_1x2_line_center(self):
        """Odd x Even dimensions -> 1x2 center line."""
        # 5 wide x 8 tall -> center at (2.5, 4.0) -> blocks (2,3) and (2,4)
        result = classify_center((0, 5, 0, 8))
        self.assertEqual(result["type"], "1x2_line")
        self.assertAlmostEqual(result["center_x"], 2.5)
        self.assertAlmostEqual(result["center_z"], 4.0)
        self.assertEqual(len(result["blocks"]), 2)
        self.assertIn((2, 3), result["blocks"])
        self.assertIn((2, 4), result["blocks"])

    def test_negative_coords(self):
        """Center classification with negative bounding box coordinates."""
        # bbox: (-115, 115, -115, 115) -> 230x230 -> even x even -> 2x2
        result = classify_center((-115, 115, -115, 115))
        self.assertEqual(result["type"], "2x2_area")
        self.assertAlmostEqual(result["center_x"], 0.0)
        self.assertAlmostEqual(result["center_z"], 0.0)
        self.assertEqual(result["map_width_x"], 230)

    def test_asymmetric_negative_coords(self):
        """Center with asymmetric negative bbox -> single block."""
        # bbox: (-165, -16, -195, 110) -> 149 x 305 -> odd x odd
        result = classify_center((-165, -16, -195, 110))
        self.assertEqual(result["type"], "single_block")
        self.assertAlmostEqual(result["center_x"], -90.5)
        self.assertAlmostEqual(result["center_z"], -42.5)


# ===================================================================
# Pair transform detection
# ===================================================================

class TestPairTransformDetection(unittest.TestCase):
    """Tests for _detect_pair_transform centroid transform matching."""

    def setUp(self):
        self.cx = 0.0
        self.cz = 0.0

    def test_mirror_x(self):
        """Pair reflected across X=0."""
        a = {"center": [5.0, 3.0]}
        b = {"center": [-5.0, 3.0]}
        transforms = _detect_pair_transform(a, b, self.cx, self.cz)
        self.assertIn("mirror_x", transforms)
        self.assertNotIn("mirror_z", transforms)

    def test_mirror_z(self):
        """Pair reflected across Z=0."""
        a = {"center": [3.0, 5.0]}
        b = {"center": [3.0, -5.0]}
        transforms = _detect_pair_transform(a, b, self.cx, self.cz)
        self.assertIn("mirror_z", transforms)
        self.assertNotIn("mirror_x", transforms)

    def test_rot_180(self):
        """Pair related by 180-degree rotation."""
        a = {"center": [5.0, 3.0]}
        b = {"center": [-5.0, -3.0]}
        transforms = _detect_pair_transform(a, b, self.cx, self.cz)
        self.assertIn("rot_180", transforms)

    def test_rot_90(self):
        """Pair related by 90-degree CCW rotation."""
        # (5, 3) -> rot_90 -> (0 + 3, 0 - 5) = (3, -5)
        a = {"center": [5.0, 3.0]}
        b = {"center": [3.0, -5.0]}
        transforms = _detect_pair_transform(a, b, self.cx, self.cz)
        self.assertIn("rot_90", transforms)

    def test_rot_270(self):
        """Pair related by 270-degree CCW rotation (= 90 CW)."""
        # (5, 3) -> rot_270 -> (0 - 3, 0 + 5) = (-3, 5)
        a = {"center": [5.0, 3.0]}
        b = {"center": [-3.0, 5.0]}
        transforms = _detect_pair_transform(a, b, self.cx, self.cz)
        self.assertIn("rot_270", transforms)

    def test_diametrically_opposite_matches_mirror_and_rot(self):
        """Islands on opposite sides of center match both mirror_z and rot_180."""
        a = {"center": [0.0, 10.0]}
        b = {"center": [0.0, -10.0]}
        transforms = _detect_pair_transform(a, b, self.cx, self.cz)
        self.assertIn("mirror_z", transforms)
        self.assertIn("rot_180", transforms)

    def test_no_transform(self):
        """Islands in random positions match no transform."""
        a = {"center": [5.0, 3.0]}
        b = {"center": [7.0, 1.0]}
        transforms = _detect_pair_transform(a, b, self.cx, self.cz, tolerance=1.0)
        self.assertEqual(transforms, [])

    def test_non_zero_center(self):
        """Transforms work with non-zero map center."""
        cx, cz = 10.0, 20.0
        # mirror_x across x=10: (15, 25) -> (5, 25)
        a = {"center": [15.0, 25.0]}
        b = {"center": [5.0, 25.0]}
        transforms = _detect_pair_transform(a, b, cx, cz)
        self.assertIn("mirror_x", transforms)


# ===================================================================
# Global symmetry — synthetic map layouts
# ===================================================================

def _build_rot180_map():
    """Two-team rot_180 map with NO mirror symmetry.

    Layout (center at 0,0):
        Spawns offset from axis: (-5, -40) and (5, 40).
        Neutral pairs at (20, -10)/(-20, 10) and (15, -30)/(-15, 30).
        Only rot_180 holds — mirrors do not.

    bbox: even x even -> 2x2 center.
    """
    islands = [
        _make_rect_island(1, -10, 0, -55, -25, team="red",
                          has_spawn=True, has_wool=True),
        _make_rect_island(2, 0, 10, 25, 55, team="blue",
                          has_spawn=True, has_wool=True),
        _make_rect_island(3, 15, 25, -15, -5),
        _make_rect_island(4, -25, -15, 5, 15),
        _make_rect_island(5, 10, 20, -35, -25),
        _make_rect_island(6, -20, -10, 25, 35),
    ]
    teams = [{"id": "red"}, {"id": "blue"}]
    bbox = (-25, 25, -55, 55)  # 50 x 110 -> even x even
    return islands, teams, bbox


def _build_mirror_x_map():
    """Two-team mirror_x map: teams separated along X axis.

    Layout (center at 0,0):
        Team A spawn at (-30, 0), Team B spawn at (30, 0)
        Neutral pair at (-10, 20) / (10, 20) — mirror_x
        Neutral pair at (-10, -20) / (10, -20) — mirror_x
    """
    islands = [
        _make_rect_island(1, -45, -15, -10, 10, team="red",
                          has_spawn=True, has_wool=True),
        _make_rect_island(2, 15, 45, -10, 10, team="blue",
                          has_spawn=True, has_wool=True),
        _make_rect_island(3, -20, -5, 10, 30),
        _make_rect_island(4, 5, 20, 10, 30),
        _make_rect_island(5, -20, -5, -30, -10),
        _make_rect_island(6, 5, 20, -30, -10),
    ]
    teams = [{"id": "red"}, {"id": "blue"}]
    bbox = (-45, 45, -30, 30)  # 90 x 60
    return islands, teams, bbox


def _build_rot90_map():
    """Four-team rot_90 map: 4 spawn islands + 4 neutral islands.

    Layout (center at 0,0, bbox 100x100 -> even x even):
        Spawns at cardinal directions, rotated 90 degrees.
        Neutral islands near each spawn, positioned so each is
        unambiguously closest to exactly one team.

    rot_90 transform: (x, z) -> (z, -x).
    Neutral chain: (10,-30) -> (-30,-10) -> (-10,30) -> (30,10).
    """
    islands = [
        _make_rect_island(1, -10, 10, -50, -30, team="blue",
                          has_spawn=True, has_wool=True),    # south
        _make_rect_island(2, 30, 50, -10, 10, team="yellow",
                          has_spawn=True, has_wool=True),    # east
        _make_rect_island(3, -50, -30, -10, 10, team="green",
                          has_spawn=True, has_wool=True),    # west
        _make_rect_island(4, -10, 10, 30, 50, team="red",
                          has_spawn=True, has_wool=True),    # north
    ]
    # Neutral islands — each clearly closest to one team's spawn.
    # (10,-30) near blue(0,-40), (-30,-10) near green(-40,0),
    # (-10,30) near red(0,40), (30,10) near yellow(40,0).
    islands += [
        _make_rect_island(5, 5, 15, -35, -25),    # near blue
        _make_rect_island(6, -35, -25, -15, -5),   # near green
        _make_rect_island(7, -15, -5, 25, 35),     # near red
        _make_rect_island(8, 25, 35, 5, 15),       # near yellow
    ]
    teams = [
        {"id": "blue"}, {"id": "yellow"},
        {"id": "green"}, {"id": "red"},
    ]
    bbox = (-50, 50, -50, 50)  # 100 x 100
    return islands, teams, bbox


def _build_d2_map():
    """Two-team D2 map: has both mirrors AND rot_180.

    Layout (center at 0,0):
        Spawns along Z axis, neutral 4-island group at diagonals.
        All 3 transforms (mirror_x, mirror_z, rot_180) hold.
    """
    islands = [
        _make_rect_island(1, -15, 15, -55, -25, team="red",
                          has_spawn=True, has_wool=True),
        _make_rect_island(2, -15, 15, 25, 55, team="blue",
                          has_spawn=True, has_wool=True),
        # Diagonal neutral islands — same area, all 4 quadrants
        _make_rect_island(3, 10, 25, -20, -5),    # (+, -)
        _make_rect_island(4, -25, -10, 5, 20),    # (-, +)
        _make_rect_island(5, -25, -10, -20, -5),  # (-, -)
        _make_rect_island(6, 10, 25, 5, 20),      # (+, +)
    ]
    teams = [{"id": "red"}, {"id": "blue"}]
    bbox = (-25, 25, -55, 55)  # 50 x 110
    return islands, teams, bbox


class TestGlobalSymmetryRot180(unittest.TestCase):
    """Tests for 180-degree rotational symmetry detection."""

    def setUp(self):
        self.islands, self.teams, self.bbox = _build_rot180_map()
        self.center = classify_center(self.bbox)
        self.cx = self.center["center_x"]
        self.cz = self.center["center_z"]

    def test_pair_analysis_finds_rot180(self):
        """Pair analysis should find rot_180 transforms."""
        pair_analysis = _aggregate_pair_transforms(
            self.islands, self.cx, self.cz,
        )
        counts = pair_analysis["transform_counts"]
        self.assertGreater(counts.get("rot_180", 0), 0)

    def test_rot180_detected(self):
        """rot_180 should be detected (confidence >= 60%)."""
        pair_analysis = _aggregate_pair_transforms(
            self.islands, self.cx, self.cz,
        )
        results = _detect_global_symmetry(
            self.islands, self.cx, self.cz, pair_analysis,
        )
        rot180 = next(r for r in results if r["type"] == "rot_180")
        self.assertTrue(rot180["detected"])
        self.assertGreaterEqual(rot180["confidence"], 0.60)

    def test_rot90_not_detected(self):
        """rot_90 should not be detected on a rot_180-only map."""
        pair_analysis = _aggregate_pair_transforms(
            self.islands, self.cx, self.cz,
        )
        results = _detect_global_symmetry(
            self.islands, self.cx, self.cz, pair_analysis,
        )
        rot90 = next(r for r in results if r["type"] == "rot_90")
        self.assertFalse(rot90["detected"])


class TestGlobalSymmetryMirrorX(unittest.TestCase):
    """Tests for mirror_x symmetry detection."""

    def setUp(self):
        self.islands, self.teams, self.bbox = _build_mirror_x_map()
        self.center = classify_center(self.bbox)
        self.cx = self.center["center_x"]
        self.cz = self.center["center_z"]

    def test_mirror_x_detected(self):
        """mirror_x should be detected."""
        pair_analysis = _aggregate_pair_transforms(
            self.islands, self.cx, self.cz,
        )
        results = _detect_global_symmetry(
            self.islands, self.cx, self.cz, pair_analysis,
        )
        mirror_x = next(r for r in results if r["type"] == "mirror_x")
        self.assertTrue(mirror_x["detected"])


class TestGlobalSymmetryRot90(unittest.TestCase):
    """Tests for 90-degree rotational symmetry detection."""

    def setUp(self):
        self.islands, self.teams, self.bbox = _build_rot90_map()
        self.center = classify_center(self.bbox)
        self.cx = self.center["center_x"]
        self.cz = self.center["center_z"]

    def test_rot90_detected(self):
        """rot_90 should be detected on a 4-team rotational map."""
        pair_analysis = _aggregate_pair_transforms(
            self.islands, self.cx, self.cz,
        )
        results = _detect_global_symmetry(
            self.islands, self.cx, self.cz, pair_analysis,
        )
        rot90 = next(r for r in results if r["type"] == "rot_90")
        self.assertTrue(rot90["detected"])
        self.assertGreaterEqual(rot90["confidence"], 0.80)

    def test_rot180_also_detected(self):
        """rot_180 should also be detected (consequence of rot_90)."""
        pair_analysis = _aggregate_pair_transforms(
            self.islands, self.cx, self.cz,
        )
        results = _detect_global_symmetry(
            self.islands, self.cx, self.cz, pair_analysis,
        )
        rot180 = next(r for r in results if r["type"] == "rot_180")
        self.assertTrue(rot180["detected"])


# ===================================================================
# Group-aware pair support
# ===================================================================

class TestGroupAwarePairSupport(unittest.TestCase):
    """Tests that pair support correctly counts group-compatible transforms."""

    def test_d2_rot180_gets_full_support(self):
        """On a D2 map (rot_180 + both mirrors), rot_180 pair support = 100%.

        A naive count would give < 100% because some pairs are labelled
        mirror_x or mirror_z, but group-aware counting includes them.
        """
        islands, teams, bbox = _build_d2_map()
        center = classify_center(bbox)
        cx, cz = center["center_x"], center["center_z"]

        pair_analysis = _aggregate_pair_transforms(islands, cx, cz)
        results = _detect_global_symmetry(islands, cx, cz, pair_analysis)

        rot180 = next(r for r in results if r["type"] == "rot_180")
        # Should be 100% because mirror pairs also count for rot_180
        # when both mirrors have high IoU
        self.assertTrue(rot180["detected"])
        self.assertGreaterEqual(rot180["pair_support"], 0.90)

    def test_rot90_map_full_support(self):
        """On a rot_90 map, rot_180 pairs also count toward rot_90 support."""
        islands, teams, bbox = _build_rot90_map()
        center = classify_center(bbox)
        cx, cz = center["center_x"], center["center_z"]

        pair_analysis = _aggregate_pair_transforms(islands, cx, cz)
        results = _detect_global_symmetry(islands, cx, cz, pair_analysis)

        rot90 = next(r for r in results if r["type"] == "rot_90")
        self.assertGreaterEqual(rot90["pair_support"], 0.90)

    def test_mirrors_not_inflated_on_rot180_only_map(self):
        """On a rot_180-only map (no mirrors), mirror pair support stays low."""
        islands, teams, bbox = _build_rot180_map()
        center = classify_center(bbox)
        cx, cz = center["center_x"], center["center_z"]

        pair_analysis = _aggregate_pair_transforms(islands, cx, cz)
        results = _detect_global_symmetry(islands, cx, cz, pair_analysis)

        mirror_x = next(r for r in results if r["type"] == "mirror_x")
        mirror_z = next(r for r in results if r["type"] == "mirror_z")
        # Mirrors should not be detected on a pure rot_180 map
        self.assertFalse(mirror_x["detected"])
        self.assertFalse(mirror_z["detected"])


# ===================================================================
# Intra-team symmetry
# ===================================================================

class TestIntraTeamMirrorSplit(unittest.TestCase):
    """Tests for 2-team intra-team mirror split symmetry."""

    def test_symmetric_territories(self):
        """Teams with mirror-symmetric territories should be detected."""
        islands, teams, bbox = _build_d2_map()
        center = classify_center(bbox)
        cx, cz = center["center_x"], center["center_z"]

        pair_analysis = _aggregate_pair_transforms(islands, cx, cz)
        global_sym = _detect_global_symmetry(islands, cx, cz, pair_analysis)

        intra = _detect_intra_team_symmetry(
            islands, cx, cz, center, global_sym, teams,
        )
        self.assertEqual(len(intra), 2)
        for team_result in intra:
            self.assertEqual(team_result.get("check_type"), "mirror_split")
            self.assertTrue(
                team_result["symmetry_detected"],
                f"Team {team_result['team']} should have intra-team symmetry",
            )

    def test_asymmetric_territories(self):
        """Teams with non-symmetric territories should not be detected."""
        # Make a rot_180 map where each team's islands are NOT mirror-symmetric
        islands = [
            _make_rect_island(1, -15, 15, -55, -25, team="red",
                              has_spawn=True, has_wool=True),
            _make_rect_island(2, -15, 15, 25, 55, team="blue",
                              has_spawn=True, has_wool=True),
            # Only one neutral island per side, not centered on axis
            _make_rect_island(3, 10, 30, -25, -5),
            _make_rect_island(4, -30, -10, 5, 25),
        ]
        teams = [{"id": "red"}, {"id": "blue"}]
        bbox = (-30, 30, -55, 55)

        center = classify_center(bbox)
        cx, cz = center["center_x"], center["center_z"]

        pair_analysis = _aggregate_pair_transforms(islands, cx, cz)
        global_sym = _detect_global_symmetry(islands, cx, cz, pair_analysis)

        intra = _detect_intra_team_symmetry(
            islands, cx, cz, center, global_sym, teams,
        )
        for team_result in intra:
            self.assertFalse(
                team_result.get("symmetry_detected", False),
                f"Team {team_result['team']} should NOT have intra-team symmetry",
            )


class TestIntraTeamCanonicalCoverage(unittest.TestCase):
    """Tests for 4-team canonical coverage intra-team symmetry."""

    def test_perfect_coverage(self):
        """Each team gets exactly 1 island from each canonical group."""
        islands, teams, bbox = _build_rot90_map()
        center = classify_center(bbox)
        cx, cz = center["center_x"], center["center_z"]

        pair_analysis = _aggregate_pair_transforms(islands, cx, cz)
        global_sym = _detect_global_symmetry(islands, cx, cz, pair_analysis)

        intra = _detect_intra_team_symmetry(
            islands, cx, cz, center, global_sym, teams,
        )
        self.assertEqual(len(intra), 4)
        for team_result in intra:
            self.assertEqual(team_result.get("check_type"), "canonical_coverage")
            self.assertTrue(
                team_result["symmetry_detected"],
                f"Team {team_result['team']} should have canonical coverage",
            )
            # 2 canonical groups: spawn (area 400) and neutral (area 100)
            self.assertEqual(team_result["groups_covered"],
                             team_result["canonical_groups"])

    def test_no_global_symmetry_no_intra(self):
        """If no global symmetry detected, intra-team returns empty."""
        islands = [
            _make_island(1, (0, 0), 100, team="red", has_spawn=True),
            _make_island(2, (50, 50), 200, team="blue", has_spawn=True),
        ]
        teams = [{"id": "red"}, {"id": "blue"}]
        bbox = (0, 60, 0, 60)
        center = classify_center(bbox)
        cx, cz = center["center_x"], center["center_z"]

        pair_analysis = _aggregate_pair_transforms(islands, cx, cz)
        global_sym = _detect_global_symmetry(islands, cx, cz, pair_analysis)

        intra = _detect_intra_team_symmetry(
            islands, cx, cz, center, global_sym, teams,
        )
        self.assertEqual(intra, [])


# ===================================================================
# Polygon IoU verification
# ===================================================================

class TestPolygonIoU(unittest.TestCase):
    """Tests for _verify_polygon_symmetry polygon-level checks."""

    def test_perfect_rot180_iou(self):
        """Symmetric layout should give IoU close to 1.0."""
        islands, _, bbox = _build_rot180_map()
        center = classify_center(bbox)
        iou, _ = _verify_polygon_symmetry(
            islands, center["center_x"], center["center_z"], "rot_180",
        )
        self.assertGreaterEqual(iou, 0.99)

    def test_perfect_rot90_iou(self):
        """4-team rotational layout should give IoU close to 1.0."""
        islands, _, bbox = _build_rot90_map()
        center = classify_center(bbox)
        iou, _ = _verify_polygon_symmetry(
            islands, center["center_x"], center["center_z"], "rot_90",
        )
        self.assertGreaterEqual(iou, 0.99)

    def test_no_symmetry_low_iou(self):
        """Random layout should give low IoU for all transforms."""
        islands = [
            _make_rect_island(1, 0, 10, 0, 10),
            _make_rect_island(2, 30, 50, 40, 60),
            _make_rect_island(3, -20, -5, 30, 40),
        ]
        center = classify_center((-20, 50, 0, 60))
        for transform in ["mirror_x", "mirror_z", "rot_180", "rot_90"]:
            iou, _ = _verify_polygon_symmetry(
                islands, center["center_x"], center["center_z"], transform,
            )
            self.assertLess(iou, 0.50, f"{transform} IoU should be low")


# ===================================================================
# End-to-end detect_symmetry via temp file
# ===================================================================

class TestDetectSymmetryEndToEnd(unittest.TestCase):
    """End-to-end test using detect_symmetry with a temporary JSON file."""

    def _write_map_context(self, islands, teams, bbox, map_name="test_map"):
        """Write a minimal map_context.json to a temp file and return path."""
        ctx = {
            "map_name": map_name,
            "bounding_box": list(bbox),
            "islands": islands,
            "teams": teams,
        }
        f = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False,
        )
        json.dump(ctx, f)
        f.close()
        return f.name

    def test_rot180_end_to_end(self):
        """End-to-end: rot_180 map detected correctly."""
        islands, teams, bbox = _build_rot180_map()
        path = self._write_map_context(islands, teams, bbox)
        try:
            result = detect_symmetry(path)
            self.assertEqual(result["map_name"], "test_map")

            detected = [s for s in result["global_symmetry"] if s["detected"]]
            types = {s["type"] for s in detected}
            self.assertIn("rot_180", types)
            self.assertNotIn("rot_90", types)
        finally:
            os.unlink(path)

    def test_rot90_end_to_end(self):
        """End-to-end: rot_90 map detected with canonical coverage."""
        islands, teams, bbox = _build_rot90_map()
        path = self._write_map_context(islands, teams, bbox)
        try:
            result = detect_symmetry(path)

            detected = [s for s in result["global_symmetry"] if s["detected"]]
            types = {s["type"] for s in detected}
            self.assertIn("rot_90", types)

            # Intra-team should use canonical coverage
            for t in result["intra_team_symmetry"]:
                self.assertEqual(t.get("check_type"), "canonical_coverage")
                self.assertTrue(t["symmetry_detected"])
        finally:
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()
