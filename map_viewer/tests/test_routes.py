"""Integration tests for Flask Blueprint routes using the test client.

These tests verify the HTTP layer: URL routing, JSON parsing, exception-to-status
mapping, and response shape. Service-layer logic is covered separately in the
unit tests; here we mock load_map_data/save_map_data to avoid filesystem access.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from map_viewer.app import create_app


def _mock_path() -> MagicMock:
    return MagicMock(spec=Path)


def _patch(module: str, data: dict):
    """Return a pair of patchers for load_map_data and save_map_data in *module*."""
    load = patch(f"{module}.load_map_data", return_value=(data, _mock_path()))
    save = patch(f"{module}.save_map_data")
    return load, save


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()


# ---------------------------------------------------------------------------
# Regions
# ---------------------------------------------------------------------------

class TestRegionRoutes(_Base):
    MODULE = "map_viewer.routes.regions"

    def _data(self) -> dict:
        return {
            "regions": {
                "r1": {
                    "id": "r1", "type": "rectangle",
                    "min_x": 0, "min_z": 0, "max_x": 10, "max_z": 10,
                    "bounds_2d": {"min": {"x": 0, "z": 0}, "max": {"x": 10, "z": 10}},
                },
                "r2": {
                    "id": "r2", "type": "rectangle",
                    "min_x": 20, "min_z": 20, "max_x": 30, "max_z": 30,
                    "bounds_2d": {"min": {"x": 20, "z": 20}, "max": {"x": 30, "z": 30}},
                },
            },
            "region_categories": {"other": ["r1", "r2"]},
        }

    def test_create_region_returns_201(self):
        load, save = _patch(self.MODULE, {})
        with load, save:
            resp = self.client.post("/api/map/test/regions", json={
                "type": "rectangle", "min_x": 0, "min_z": 0, "max_x": 10, "max_z": 10,
            })
        self.assertEqual(resp.status_code, 201)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertIn("id", body)

    def test_create_region_conflict_returns_409(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.post("/api/map/test/regions", json={
                "type": "rectangle", "id": "r1",
                "min_x": 0, "min_z": 0, "max_x": 10, "max_z": 10,
            })
        self.assertEqual(resp.status_code, 409)

    def test_create_region_missing_fields_returns_400(self):
        load, save = _patch(self.MODULE, {})
        with load, save:
            resp = self.client.post("/api/map/test/regions", json={"type": "rectangle"})
        self.assertEqual(resp.status_code, 400)

    def test_delete_region_returns_200_with_snapshot(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.delete("/api/map/test/region/r1")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertIn("snapshot", body)

    def test_delete_region_not_found_returns_404(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.delete("/api/map/test/region/ghost")
        self.assertEqual(resp.status_code, 404)

    def test_patch_region_rename_returns_200(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.patch("/api/map/test/region/r1", json={"id": "r1-new"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_patch_region_empty_payload_returns_400(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.patch("/api/map/test/region/r1", json={})
        self.assertEqual(resp.status_code, 400)

    def test_patch_region_not_found_returns_404(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.patch("/api/map/test/region/ghost", json={"id": "x"})
        self.assertEqual(resp.status_code, 404)

    def test_group_regions_returns_201(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.post("/api/map/test/regions/group",
                                    json={"child_ids": ["r1", "r2"]})
        self.assertEqual(resp.status_code, 201)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertIn("id", body)
        self.assertIn("bounds", body)

    def test_group_regions_missing_child_returns_404(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.post("/api/map/test/regions/group",
                                    json={"child_ids": ["r1", "ghost"]})
        self.assertEqual(resp.status_code, 404)

    def test_restore_region_missing_snapshot_returns_400(self):
        load, save = _patch(self.MODULE, {})
        with load, save:
            resp = self.client.post("/api/map/test/regions/restore", json={})
        self.assertEqual(resp.status_code, 400)

    def test_restore_region_returns_200(self):
        snapshot = {
            "root_id": "r1",
            "category": "other",
            "region_entries": {
                "r1": {
                    "id": "r1", "type": "rectangle",
                    "min_x": 0, "min_z": 0, "max_x": 10, "max_z": 10,
                },
            },
        }
        load, save = _patch(self.MODULE, {})
        with load, save:
            resp = self.client.post("/api/map/test/regions/restore",
                                    json={"snapshot": snapshot})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------

class TestTeamRoutes(_Base):
    MODULE = "map_viewer.routes.teams"

    def _data(self) -> dict:
        return {
            "teams": [{"id": "red", "name": "Red", "color": "red",
                       "max_players": 20, "min_players": 0}],
            "spawns": [],
        }

    def test_add_team_returns_201(self):
        load, save = _patch(self.MODULE, {"teams": [], "spawns": []})
        with load, save:
            resp = self.client.post("/api/map/test/teams",
                                    json={"id": "blue", "name": "Blue", "color": "blue"})
        self.assertEqual(resp.status_code, 201)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertIn("team", body)

    def test_add_team_missing_id_returns_400(self):
        load, save = _patch(self.MODULE, {"teams": []})
        with load, save:
            resp = self.client.post("/api/map/test/teams", json={"name": "Blue"})
        self.assertEqual(resp.status_code, 400)

    def test_add_team_conflict_returns_409(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.post("/api/map/test/teams",
                                    json={"id": "red", "color": "red"})
        self.assertEqual(resp.status_code, 409)

    def test_update_team_returns_200(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.patch("/api/map/test/teams/red",
                                     json={"name": "Scarlet"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_update_team_not_found_returns_404(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.patch("/api/map/test/teams/ghost",
                                     json={"name": "X"})
        self.assertEqual(resp.status_code, 404)

    def test_update_team_rename_conflict_returns_409(self):
        data = {
            "teams": [
                {"id": "red", "name": "Red", "color": "red", "max_players": 20, "min_players": 0},
                {"id": "blue", "name": "Blue", "color": "blue", "max_players": 20, "min_players": 0},
            ],
            "spawns": [],
        }
        load, save = _patch(self.MODULE, data)
        with load, save:
            resp = self.client.patch("/api/map/test/teams/red", json={"id": "blue"})
        self.assertEqual(resp.status_code, 409)

    def test_delete_team_returns_200(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.delete("/api/map/test/teams/red")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_delete_team_not_found_returns_404(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.delete("/api/map/test/teams/ghost")
        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------------------
# Spawns
# ---------------------------------------------------------------------------

class TestSpawnRoutes(_Base):
    MODULE = "map_viewer.routes.spawns"

    def _data(self) -> dict:
        return {
            "teams": [{"id": "red"}],
            "spawns": [
                {"team": "red", "region": {"id": "spawn-1", "type": "point",
                                           "position": {"x": 0, "y": 64, "z": 0}}},
            ],
            "regions": {
                "spawn-1": {"id": "spawn-1", "type": "point",
                            "position": {"x": 0, "y": 64, "z": 0}},
                "spawn-2": {"id": "spawn-2", "type": "point",
                            "position": {"x": 10, "y": 64, "z": 10}},
            },
        }

    def test_add_spawn_link_returns_201(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.post("/api/map/test/spawns",
                                    json={"region_id": "spawn-2", "team": "red"})
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.get_json()["ok"])

    def test_add_spawn_link_missing_region_id_returns_400(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.post("/api/map/test/spawns", json={"team": "red"})
        self.assertEqual(resp.status_code, 400)

    def test_add_spawn_link_unknown_region_returns_404(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.post("/api/map/test/spawns",
                                    json={"region_id": "ghost"})
        self.assertEqual(resp.status_code, 404)

    def test_add_spawn_link_duplicate_returns_409(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.post("/api/map/test/spawns",
                                    json={"region_id": "spawn-1", "team": "red"})
        self.assertEqual(resp.status_code, 409)

    def test_update_spawn_link_returns_200(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.patch("/api/map/test/spawn/spawn-1",
                                     json={"team": "red"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_update_spawn_link_not_found_returns_404(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.patch("/api/map/test/spawn/ghost",
                                     json={"team": "red"})
        self.assertEqual(resp.status_code, 404)

    def test_delete_spawn_link_returns_200(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.delete("/api/map/test/spawn/spawn-1")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_delete_spawn_link_not_found_returns_404(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.delete("/api/map/test/spawn/ghost")
        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------------------
# Wools
# ---------------------------------------------------------------------------

class TestWoolRoutes(_Base):
    MODULE = "map_viewer.routes.wools"

    def _data(self) -> dict:
        return {
            "teams": [{"id": "red"}, {"id": "blue"}],
            "wools": [
                {
                    "team": "red", "color": "orange",
                    "location": {"x": 0, "y": 64, "z": 0},
                    "monument": {"id": "red-orange-wool"},
                },
            ],
        }

    def test_add_wool_returns_201(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.post("/api/map/test/wools",
                                    json={"team": "blue", "color": "yellow",
                                          "x": 10, "y": 64, "z": 10})
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.get_json()["ok"])

    def test_add_wool_conflict_returns_409(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.post("/api/map/test/wools",
                                    json={"team": "red", "color": "orange",
                                          "x": 0, "y": 64, "z": 0})
        self.assertEqual(resp.status_code, 409)

    def test_update_wool_returns_200(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.patch("/api/map/test/wool/red/orange",
                                     json={"x": 5, "y": 64, "z": 5})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_update_wool_not_found_returns_404(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.patch("/api/map/test/wool/red/purple",
                                     json={"x": 5, "y": 64, "z": 5})
        self.assertEqual(resp.status_code, 404)

    def test_delete_wool_returns_200(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.delete("/api/map/test/wool/red/orange")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_delete_wool_not_found_returns_404(self):
        load, save = _patch(self.MODULE, self._data())
        with load, save:
            resp = self.client.delete("/api/map/test/wool/red/purple")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
