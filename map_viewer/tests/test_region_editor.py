import unittest

from map_viewer.services.region_editor import (
    InvalidRegionPayload,
    RegionConflict,
    RegionNotFound,
    create_region,
    delete_region,
    group_regions,
    patch_region,
    restore_region,
)


def _rect(region_id: str) -> dict:
    return {
        "id": region_id, "type": "rectangle",
        "min_x": 0, "min_z": 0, "max_x": 10, "max_z": 10,
        "bounds_2d": {"min": {"x": 0, "z": 0}, "max": {"x": 10, "z": 10}},
    }


class TestCreateRegion(unittest.TestCase):
    def test_auto_id_rectangle(self):
        data = {}
        result = create_region(data, {"type": "rectangle", "min_x": 0, "min_z": 0, "max_x": 5, "max_z": 5})
        self.assertEqual(result["id"], "region_1")
        self.assertIn("region_1", data["regions"])

    def test_explicit_id(self):
        data = {}
        result = create_region(data, {"type": "point", "id": "my_point", "x": 10, "y": 64, "z": 10})
        self.assertEqual(result["id"], "my_point")
        self.assertIn("my_point", data["regions"])

    def test_auto_id_increments(self):
        data = {"regions": {"region_1": _rect("region_1")}}
        result = create_region(data, {"type": "rectangle", "min_x": 0, "min_z": 0, "max_x": 5, "max_z": 5})
        self.assertEqual(result["id"], "region_2")

    def test_category_recorded(self):
        data = {}
        create_region(data, {"type": "rectangle", "min_x": 0, "min_z": 0, "max_x": 5, "max_z": 5, "category": "spawn_area"})
        self.assertIn("region_1", data["region_categories"]["spawn_area"])

    def test_unsupported_type_raises(self):
        with self.assertRaises(InvalidRegionPayload):
            create_region({}, {"type": "polygon"})

    def test_duplicate_id_raises(self):
        data = {"regions": {"r1": _rect("r1")}}
        with self.assertRaises(RegionConflict):
            create_region(data, {"type": "rectangle", "id": "r1", "min_x": 0, "min_z": 0, "max_x": 5, "max_z": 5})

    def test_missing_field_raises(self):
        with self.assertRaises(InvalidRegionPayload):
            create_region({}, {"type": "rectangle"})  # missing min_x etc.


class TestGroupRegions(unittest.TestCase):
    def setUp(self):
        self.data = {
            "regions": {
                "r1": _rect("r1"),
                "r2": _rect("r2"),
            }
        }

    def test_creates_union(self):
        result = group_regions(self.data, {"child_ids": ["r1", "r2"]})
        self.assertEqual(result["id"], "union_1")
        self.assertIn("union_1", self.data["regions"])
        self.assertEqual(self.data["regions"]["union_1"]["type"], "union")

    def test_too_few_children_raises(self):
        with self.assertRaises(InvalidRegionPayload):
            group_regions(self.data, {"child_ids": ["r1"]})

    def test_missing_child_raises(self):
        with self.assertRaises(RegionNotFound):
            group_regions(self.data, {"child_ids": ["r1", "does_not_exist"]})

    def test_duplicate_union_id_raises(self):
        self.data["regions"]["union_1"] = _rect("union_1")
        with self.assertRaises(RegionConflict):
            group_regions(self.data, {"child_ids": ["r1", "r2"], "id": "union_1"})


class TestDeleteRegion(unittest.TestCase):
    def test_delete_top_level(self):
        data = {
            "regions": {"r1": _rect("r1")},
            "region_categories": {"other": ["r1"]},
        }
        result = delete_region(data, "r1")
        self.assertNotIn("r1", data["regions"])
        self.assertNotIn("r1", data["region_categories"]["other"])
        self.assertEqual(result["snapshot"]["root_id"], "r1")
        self.assertEqual(result["snapshot"]["category"], "other")

    def test_delete_named_inline_child(self):
        # Named children have an id but are only stored inline (not as a top-level
        # regions key). find_parent_of_child matches by the stored id field.
        child = {"id": "named_child", "type": "rectangle", "min_x": 0, "min_z": 0, "max_x": 5, "max_z": 5}
        parent = {
            "id": "parent", "type": "union",
            "children": [child],
            "bounds_2d": {"min": {"x": 0, "z": 0}, "max": {"x": 5, "z": 5}},
        }
        data = {"regions": {"parent": parent}}
        result = delete_region(data, "named_child")
        self.assertEqual(data["regions"]["parent"]["children"], [])
        self.assertIsNone(result["snapshot"]["category"])

    def test_not_found_raises(self):
        with self.assertRaises(RegionNotFound):
            delete_region({"regions": {}}, "nonexistent")


class TestRestoreRegion(unittest.TestCase):
    def test_restore_top_level(self):
        data = {"regions": {}}
        snapshot = {
            "root_id": "r1",
            "category": "spawn_area",
            "region_entries": {"r1": _rect("r1")},
        }
        result = restore_region(data, snapshot)
        self.assertEqual(result["id"], "r1")
        self.assertIn("r1", data["regions"])
        self.assertIn("r1", data["region_categories"]["spawn_area"])

    def test_restore_conflict_raises(self):
        data = {"regions": {"r1": _rect("r1")}}
        snapshot = {"root_id": "r1", "category": "other", "region_entries": {"r1": _rect("r1")}}
        with self.assertRaises(RegionConflict):
            restore_region(data, snapshot)

    def test_restore_inline_child(self):
        parent = {"id": "parent", "type": "union", "children": []}
        data = {"regions": {"parent": parent}}
        child = {"id": "", "type": "rectangle"}
        snapshot = {
            "root_id": "parent__0",
            "category": None,
            "parent_id": "parent",
            "child_index": 0,
            "region_entries": {"parent__0": child},
        }
        restore_region(data, snapshot)
        self.assertEqual(data["regions"]["parent"]["children"], [child])

    def test_restore_missing_parent_raises(self):
        snapshot = {
            "root_id": "parent__0",
            "category": None,
            "parent_id": "ghost",
            "child_index": 0,
            "region_entries": {"parent__0": {}},
        }
        with self.assertRaises(RegionNotFound):
            restore_region({"regions": {}}, snapshot)

    def test_invalid_snapshot_raises(self):
        with self.assertRaises(InvalidRegionPayload):
            restore_region({}, {"root_id": "", "region_entries": {}})


class TestPatchRegion(unittest.TestCase):
    def _data_with_rect(self) -> dict:
        return {
            "regions": {"r1": _rect("r1")},
            "region_categories": {"other": ["r1"]},
        }

    def test_rename(self):
        data = self._data_with_rect()
        patch_region(data, "r1", {"id": "r1_renamed"})
        self.assertIn("r1_renamed", data["regions"])
        self.assertNotIn("r1", data["regions"])
        self.assertIn("r1_renamed", data["region_categories"]["other"])

    def test_bounds_update(self):
        data = self._data_with_rect()
        result = patch_region(data, "r1", {"bounds": {"min_x": 1, "min_z": 1, "max_x": 9, "max_z": 9}})
        self.assertIn("bounds", result)
        self.assertEqual(data["regions"]["r1"]["bounds_2d"]["min"]["x"], 1)

    def test_coords_update_cylinder(self):
        # apply_coord_update handles cylinder coords (radius → new bounds_2d)
        data = {
            "regions": {"c1": {
                "id": "c1", "type": "cylinder",
                "base": {"x": 0, "y": 64, "z": 0}, "radius": 5.0, "height": 10.0,
                "bounds_2d": {"min": {"x": -5, "z": -5}, "max": {"x": 5, "z": 5}},
            }},
            "region_categories": {"other": ["c1"]},
        }
        result = patch_region(data, "c1", {"coords": {"radius": 10.0}})
        self.assertIn("bounds", result)
        self.assertEqual(result["bounds"]["min_x"], -10.0)

    def test_empty_payload_raises(self):
        data = self._data_with_rect()
        with self.assertRaises(InvalidRegionPayload):
            patch_region(data, "r1", {})

    def test_not_found_raises(self):
        with self.assertRaises(RegionNotFound):
            patch_region({"regions": {}}, "ghost", {"id": "new"})

    def test_rename_conflict_raises(self):
        data = {
            "regions": {"r1": _rect("r1"), "r2": _rect("r2")},
            "region_categories": {},
        }
        with self.assertRaises(RegionConflict):
            patch_region(data, "r1", {"id": "r2"})


if __name__ == "__main__":
    unittest.main()
