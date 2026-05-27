from __future__ import annotations


class TeamEditorError(Exception):
    pass


class TeamNotFound(TeamEditorError):
    pass


class TeamConflict(TeamEditorError):
    pass


class InvalidTeamPayload(TeamEditorError):
    pass


def add_team(data: dict, payload: dict) -> dict:
    """Create a new team entry in data.

    Returns {"team": team_dict}.
    Raises InvalidTeamPayload on missing id, TeamConflict on id clash.
    """
    team_id = (payload.get("id") or "").strip()
    if not team_id:
        raise InvalidTeamPayload("id is required")

    teams: list = data.setdefault("teams", [])

    if any(t.get("id") == team_id for t in teams):
        raise TeamConflict(f"team id {team_id!r} already in use")

    new_team: dict = {
        "id":          team_id,
        "name":        payload.get("name", team_id),
        "color":       payload.get("color", "red"),
        "max_players": int(payload.get("max_players", 20)),
        "min_players": int(payload.get("min_players", 0)),
    }
    if payload.get("dye_color"):
        new_team["dye_color"] = str(payload["dye_color"])

    teams.append(new_team)
    return {"team": new_team}


def update_team(data: dict, team_id: str, payload: dict) -> dict:
    """Update fields on an existing team, optionally renaming its id.

    An id rename propagates to all spawns and observer_spawn that reference it.
    Returns {"team": updated_team_dict}.
    Raises TeamNotFound, TeamConflict.
    """
    teams: list = data.get("teams", [])

    team = next((t for t in teams if t.get("id") == team_id), None)
    if team is None:
        raise TeamNotFound(f"team {team_id!r} not found")

    new_id = (payload.get("id") or "").strip()
    if new_id and new_id != team_id:
        if any(t.get("id") == new_id for t in teams if t is not team):
            raise TeamConflict(f"team id {new_id!r} already in use")
        for spawn in data.get("spawns", []):
            if spawn.get("team") == team_id:
                spawn["team"] = new_id
        obs = data.get("observer_spawn")
        if obs and obs.get("team") == team_id:
            obs["team"] = new_id
        team["id"] = new_id

    for field in ("name", "color", "dye_color"):
        if field in payload:
            team[field] = str(payload[field])
    for field in ("max_players", "min_players"):
        if field in payload:
            team[field] = int(payload[field])

    return {"team": team}


def delete_team(data: dict, team_id: str) -> dict:
    """Remove a team and all spawns that reference it.

    Returns {}.
    Raises TeamNotFound.
    """
    teams: list = data.get("teams", [])

    if not any(t.get("id") == team_id for t in teams):
        raise TeamNotFound(f"team {team_id!r} not found")

    data["teams"] = [t for t in teams if t.get("id") != team_id]
    data["spawns"] = [s for s in data.get("spawns", []) if s.get("team") != team_id]
    return {}
