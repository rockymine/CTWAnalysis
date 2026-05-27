from __future__ import annotations


class WoolEditorError(Exception):
    pass


class WoolNotFound(WoolEditorError):
    pass


class WoolConflict(WoolEditorError):
    pass


class InvalidWoolPayload(WoolEditorError):
    pass


def _parse_xyz(raw: dict) -> dict:
    return {
        "x": float(raw.get("x", 0)),
        "y": float(raw.get("y", 0)),
        "z": float(raw.get("z", 0)),
    }


def add_wool(data: dict, payload: dict) -> dict:
    """Create a new wool entry identified by (team, color).

    Returns {"wool": wool_dict}.
    Raises InvalidWoolPayload on missing fields, WoolConflict on duplicate.
    """
    team_id = (payload.get("team") or "").strip()
    color   = (payload.get("color") or "").strip()
    if not team_id:
        raise InvalidWoolPayload("team is required")
    if not color:
        raise InvalidWoolPayload("color is required")

    wools: list = data.setdefault("wools", [])

    if any(w.get("team") == team_id and w.get("color") == color for w in wools):
        raise WoolConflict(f"wool ({team_id!r}, {color!r}) already exists")

    new_wool: dict = {
        "team":     team_id,
        "color":    color,
        "location": _parse_xyz(payload.get("location") or {}),
        "monument": _parse_xyz(payload.get("monument") or {}),
    }
    wools.append(new_wool)
    return {"wool": new_wool}


def update_wool(data: dict, team_id: str, color: str, payload: dict) -> dict:
    """Update a wool entry by its (team, color) composite key.

    Location updates apply to all entries sharing the same (color, old_location)
    since those represent the same physical room.  Team/color renames apply only
    to the matched entry.  wool_room_region propagates to all entries at the
    same location; an explicit None clears the assignment.

    Returns {"wool": updated_wool_dict}.
    Raises WoolNotFound, WoolConflict.
    """
    wools: list = data.get("wools", [])

    wool = next(
        (w for w in wools if w.get("team") == team_id and w.get("color") == color),
        None,
    )
    if wool is None:
        raise WoolNotFound(f"wool ({team_id!r}, {color!r}) not found")

    if "location" in payload:
        new_loc = _parse_xyz(payload["location"])
        old_loc = wool["location"]
        for entry in wools:
            if entry.get("color") == color and entry.get("location") == old_loc:
                entry["location"] = new_loc

    new_team = (payload.get("team") or "").strip()
    if new_team and new_team != team_id:
        if any(w.get("team") == new_team and w.get("color") == wool.get("color")
               for w in wools if w is not wool):
            raise WoolConflict(f"wool ({new_team!r}, {wool['color']!r}) already exists")
        wool["team"] = new_team

    new_color = (payload.get("color") or "").strip()
    if new_color and new_color != wool.get("color"):
        if any(w.get("team") == wool.get("team") and w.get("color") == new_color
               for w in wools if w is not wool):
            raise WoolConflict(f"wool ({wool['team']!r}, {new_color!r}) already exists")
        wool["color"] = new_color

    if "wool_room_region" in payload:
        new_region_id = payload["wool_room_region"]  # str | None
        current_loc = wool["location"]
        for entry in wools:
            if entry.get("location") == current_loc:
                entry["wool_room_region"] = new_region_id

    return {"wool": wool}


def delete_wool(data: dict, team_id: str, color: str) -> dict:
    """Delete the single wool entry identified by (team, color).

    Returns {}.
    Raises WoolNotFound.
    """
    wools: list = data.get("wools", [])

    if not any(w.get("team") == team_id and w.get("color") == color for w in wools):
        raise WoolNotFound(f"wool ({team_id!r}, {color!r}) not found")

    data["wools"] = [
        w for w in wools
        if not (w.get("team") == team_id and w.get("color") == color)
    ]
    return {}
