from __future__ import annotations

from map_viewer.services.spawns import spawn_region_id


class SpawnEditorError(Exception):
    pass


class SpawnNotFound(SpawnEditorError):
    pass


class SpawnConflict(SpawnEditorError):
    pass


class InvalidSpawnPayload(SpawnEditorError):
    pass


def add_spawn_link(data: dict, payload: dict) -> dict:
    """Create a spawn link connecting a region to a team + metadata.

    Returns {}.
    Raises InvalidSpawnPayload on missing region_id, SpawnNotFound if the
    region does not exist, SpawnConflict if a spawn for it already exists.
    """
    region_id = (payload.get("region_id") or "").strip()
    if not region_id:
        raise InvalidSpawnPayload("region_id is required")

    regions: dict = data.get("regions", {})
    if region_id not in regions:
        raise SpawnNotFound(f"region {region_id!r} not found")

    spawns: list = data.setdefault("spawns", [])
    if any(spawn_region_id(s) == region_id for s in spawns):
        raise SpawnConflict(f"spawn for region {region_id!r} already exists")

    spawns.append({
        "team":   str(payload.get("team", "")),
        "kit":    str(payload.get("kit", "")),
        "yaw":    float(payload.get("yaw", 0.0)),
        "region": regions[region_id],
    })
    return {}


def update_spawn_link(data: dict, region_id: str, payload: dict) -> dict:
    """Update team, yaw, and kit for the spawn linked to region_id.

    Returns {}.
    Raises SpawnNotFound.
    """
    spawns: list = data.get("spawns", [])
    spawn = next((s for s in spawns if spawn_region_id(s) == region_id), None)
    if spawn is None:
        raise SpawnNotFound(f"no spawn for region {region_id!r}")

    if "team" in payload:
        spawn["team"] = str(payload["team"])
    if "yaw" in payload:
        spawn["yaw"] = float(payload["yaw"])
    if "kit" in payload:
        spawn["kit"] = str(payload["kit"])
    return {}


def delete_spawn_link(data: dict, region_id: str) -> dict:
    """Remove the spawn link for region_id.

    Returns {}.
    Raises SpawnNotFound.
    """
    spawns: list = data.get("spawns", [])
    if not any(spawn_region_id(s) == region_id for s in spawns):
        raise SpawnNotFound(f"no spawn for region {region_id!r}")

    data["spawns"] = [s for s in spawns if spawn_region_id(s) != region_id]
    return {}
