import unittest

from map_viewer.services.team_editor import (
    InvalidTeamPayload,
    TeamConflict,
    TeamNotFound,
    add_team,
    delete_team,
    update_team,
)


def _team(team_id: str, **kwargs) -> dict:
    return {"id": team_id, "name": team_id, "color": "red", "max_players": 20, "min_players": 0, **kwargs}


class TestAddTeam(unittest.TestCase):
    def test_basic(self):
        data = {}
        result = add_team(data, {"id": "red", "name": "Red Team", "color": "red"})
        self.assertEqual(result["team"]["id"], "red")
        self.assertEqual(data["teams"][0]["id"], "red")

    def test_missing_id_raises(self):
        with self.assertRaises(InvalidTeamPayload):
            add_team({}, {"name": "Red Team"})

    def test_duplicate_id_raises(self):
        data = {"teams": [_team("red")]}
        with self.assertRaises(TeamConflict):
            add_team(data, {"id": "red"})

    def test_dye_color_optional(self):
        data = {}
        result = add_team(data, {"id": "red", "dye_color": "RED"})
        self.assertEqual(result["team"]["dye_color"], "RED")

    def test_defaults(self):
        data = {}
        result = add_team(data, {"id": "blue"})
        self.assertEqual(result["team"]["color"], "red")
        self.assertEqual(result["team"]["max_players"], 20)


class TestUpdateTeam(unittest.TestCase):
    def _data(self) -> dict:
        return {
            "teams": [_team("red")],
            "spawns": [{"team": "red", "region": {"id": "spawn1"}}],
        }

    def test_rename_propagates_to_spawns(self):
        data = self._data()
        update_team(data, "red", {"id": "crimson"})
        self.assertEqual(data["teams"][0]["id"], "crimson")
        self.assertEqual(data["spawns"][0]["team"], "crimson")

    def test_rename_propagates_to_observer_spawn(self):
        data = self._data()
        data["observer_spawn"] = {"team": "red", "region": {"id": "obs"}}
        update_team(data, "red", {"id": "crimson"})
        self.assertEqual(data["observer_spawn"]["team"], "crimson")

    def test_field_update(self):
        data = self._data()
        result = update_team(data, "red", {"name": "The Reds", "max_players": 10})
        self.assertEqual(result["team"]["name"], "The Reds")
        self.assertEqual(result["team"]["max_players"], 10)

    def test_not_found_raises(self):
        with self.assertRaises(TeamNotFound):
            update_team({"teams": []}, "ghost", {"name": "X"})

    def test_rename_conflict_raises(self):
        data = {"teams": [_team("red"), _team("blue")], "spawns": []}
        with self.assertRaises(TeamConflict):
            update_team(data, "red", {"id": "blue"})


class TestDeleteTeam(unittest.TestCase):
    def test_removes_team_and_spawns(self):
        data = {
            "teams": [_team("red"), _team("blue")],
            "spawns": [
                {"team": "red", "region": {"id": "r1"}},
                {"team": "blue", "region": {"id": "r2"}},
            ],
        }
        delete_team(data, "red")
        self.assertEqual(len(data["teams"]), 1)
        self.assertEqual(data["teams"][0]["id"], "blue")
        self.assertEqual(len(data["spawns"]), 1)
        self.assertEqual(data["spawns"][0]["team"], "blue")

    def test_not_found_raises(self):
        with self.assertRaises(TeamNotFound):
            delete_team({"teams": []}, "ghost")


if __name__ == "__main__":
    unittest.main()
