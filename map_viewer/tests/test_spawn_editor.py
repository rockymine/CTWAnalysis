import unittest

from map_viewer.services.spawn_editor import (
    InvalidSpawnPayload,
    SpawnConflict,
    SpawnNotFound,
    add_spawn_link,
    delete_spawn_link,
    update_spawn_link,
)


def _spawn(region_id: str, team: str = "red") -> dict:
    return {"team": team, "kit": "", "yaw": 0.0, "region": {"id": region_id}}


class TestAddSpawnLink(unittest.TestCase):
    def _data(self) -> dict:
        return {
            "regions": {
                "r1": {"id": "r1", "type": "point", "position": {"x": 0, "y": 64, "z": 0}},
            }
        }

    def test_basic(self):
        data = self._data()
        add_spawn_link(data, {"region_id": "r1", "team": "red", "yaw": 90.0})
        self.assertEqual(len(data["spawns"]), 1)
        self.assertEqual(data["spawns"][0]["team"], "red")
        self.assertEqual(data["spawns"][0]["yaw"], 90.0)

    def test_missing_region_id_raises(self):
        with self.assertRaises(InvalidSpawnPayload):
            add_spawn_link(self._data(), {})

    def test_region_not_found_raises(self):
        with self.assertRaises(SpawnNotFound):
            add_spawn_link(self._data(), {"region_id": "ghost"})

    def test_duplicate_spawn_raises(self):
        data = self._data()
        data["spawns"] = [_spawn("r1")]
        with self.assertRaises(SpawnConflict):
            add_spawn_link(data, {"region_id": "r1", "team": "blue"})


class TestUpdateSpawnLink(unittest.TestCase):
    def _data(self) -> dict:
        return {"spawns": [_spawn("r1", "red")]}

    def test_update_fields(self):
        data = self._data()
        update_spawn_link(data, "r1", {"team": "blue", "yaw": 45.0, "kit": "default"})
        spawn = data["spawns"][0]
        self.assertEqual(spawn["team"], "blue")
        self.assertEqual(spawn["yaw"], 45.0)
        self.assertEqual(spawn["kit"], "default")

    def test_partial_update(self):
        data = self._data()
        update_spawn_link(data, "r1", {"yaw": 180.0})
        self.assertEqual(data["spawns"][0]["yaw"], 180.0)
        self.assertEqual(data["spawns"][0]["team"], "red")

    def test_not_found_raises(self):
        with self.assertRaises(SpawnNotFound):
            update_spawn_link({"spawns": []}, "ghost", {"team": "red"})


class TestDeleteSpawnLink(unittest.TestCase):
    def test_removes_spawn(self):
        data = {"spawns": [_spawn("r1"), _spawn("r2")]}
        delete_spawn_link(data, "r1")
        self.assertEqual(len(data["spawns"]), 1)
        self.assertEqual(data["spawns"][0]["region"]["id"], "r2")

    def test_not_found_raises(self):
        with self.assertRaises(SpawnNotFound):
            delete_spawn_link({"spawns": []}, "ghost")


if __name__ == "__main__":
    unittest.main()
