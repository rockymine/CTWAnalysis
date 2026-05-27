import unittest

from map_viewer.services.wool_editor import (
    InvalidWoolPayload,
    WoolConflict,
    WoolNotFound,
    add_wool,
    delete_wool,
    update_wool,
)


def _wool(team: str, color: str, x: float = 0, z: float = 0) -> dict:
    loc = {"x": x, "y": 64.0, "z": z}
    return {"team": team, "color": color, "location": loc, "monument": {"x": 0, "y": 64.0, "z": 0}}


class TestAddWool(unittest.TestCase):
    def test_basic(self):
        data = {}
        result = add_wool(data, {"team": "red", "color": "orange"})
        self.assertEqual(result["wool"]["team"], "red")
        self.assertEqual(data["wools"][0]["color"], "orange")

    def test_location_parsed(self):
        data = {}
        result = add_wool(data, {"team": "red", "color": "blue", "location": {"x": 10, "y": 65, "z": 20}})
        self.assertEqual(result["wool"]["location"]["x"], 10.0)
        self.assertEqual(result["wool"]["location"]["y"], 65.0)

    def test_missing_team_raises(self):
        with self.assertRaises(InvalidWoolPayload):
            add_wool({}, {"color": "orange"})

    def test_missing_color_raises(self):
        with self.assertRaises(InvalidWoolPayload):
            add_wool({}, {"team": "red"})

    def test_duplicate_raises(self):
        data = {"wools": [_wool("red", "orange")]}
        with self.assertRaises(WoolConflict):
            add_wool(data, {"team": "red", "color": "orange"})


class TestUpdateWool(unittest.TestCase):
    def _shared_room_data(self) -> dict:
        loc = {"x": 10, "y": 64.0, "z": 10}
        return {
            "wools": [
                {"team": "red",  "color": "orange", "location": dict(loc), "monument": {}},
                {"team": "blue", "color": "orange", "location": dict(loc), "monument": {}},
            ]
        }

    def test_location_propagates_to_same_room(self):
        data = self._shared_room_data()
        update_wool(data, "red", "orange", {"location": {"x": 20, "y": 64, "z": 20}})
        # Both share the same room (same color + old location), so both update
        for entry in data["wools"]:
            self.assertEqual(entry["location"]["x"], 20.0)

    def test_location_does_not_propagate_to_different_color(self):
        data = {
            "wools": [
                _wool("red", "orange", 10, 10),
                _wool("blue", "lime", 10, 10),  # same x/z but different color
            ]
        }
        update_wool(data, "red", "orange", {"location": {"x": 99, "y": 64, "z": 99}})
        self.assertEqual(data["wools"][0]["location"]["x"], 99.0)
        self.assertEqual(data["wools"][1]["location"]["x"], 10.0)  # unchanged

    def test_team_rename(self):
        data = {"wools": [_wool("red", "orange")]}
        update_wool(data, "red", "orange", {"team": "crimson"})
        self.assertEqual(data["wools"][0]["team"], "crimson")

    def test_color_rename(self):
        data = {"wools": [_wool("red", "orange")]}
        update_wool(data, "red", "orange", {"color": "yellow"})
        self.assertEqual(data["wools"][0]["color"], "yellow")

    def test_wool_room_region_propagates(self):
        loc = {"x": 5, "y": 64.0, "z": 5}
        data = {
            "wools": [
                {"team": "red",  "color": "orange", "location": dict(loc), "monument": {}},
                {"team": "blue", "color": "lime",   "location": dict(loc), "monument": {}},
            ]
        }
        update_wool(data, "red", "orange", {"wool_room_region": "wool_room_red"})
        self.assertEqual(data["wools"][0].get("wool_room_region"), "wool_room_red")
        self.assertEqual(data["wools"][1].get("wool_room_region"), "wool_room_red")

    def test_wool_room_region_clear(self):
        data = {"wools": [{"team": "red", "color": "orange", "location": {"x": 0, "y": 64, "z": 0}, "monument": {}, "wool_room_region": "old_room"}]}
        update_wool(data, "red", "orange", {"wool_room_region": None})
        self.assertIsNone(data["wools"][0]["wool_room_region"])

    def test_not_found_raises(self):
        with self.assertRaises(WoolNotFound):
            update_wool({"wools": []}, "red", "orange", {"team": "crimson"})

    def test_team_rename_conflict_raises(self):
        data = {"wools": [_wool("red", "orange"), _wool("blue", "orange")]}
        with self.assertRaises(WoolConflict):
            update_wool(data, "red", "orange", {"team": "blue"})

    def test_color_rename_conflict_raises(self):
        data = {"wools": [_wool("red", "orange"), _wool("red", "lime")]}
        with self.assertRaises(WoolConflict):
            update_wool(data, "red", "orange", {"color": "lime"})


class TestDeleteWool(unittest.TestCase):
    def test_removes_entry(self):
        data = {"wools": [_wool("red", "orange"), _wool("red", "lime")]}
        delete_wool(data, "red", "orange")
        self.assertEqual(len(data["wools"]), 1)
        self.assertEqual(data["wools"][0]["color"], "lime")

    def test_not_found_raises(self):
        with self.assertRaises(WoolNotFound):
            delete_wool({"wools": []}, "red", "orange")


if __name__ == "__main__":
    unittest.main()
