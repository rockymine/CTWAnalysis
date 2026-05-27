from __future__ import annotations

import json
import urllib.error
import urllib.request


class MojangNotFound(Exception):
    pass


class MojangUpstreamError(Exception):
    pass


def _format_uuid(raw_id: str) -> str:
    if len(raw_id) == 32:
        return (f"{raw_id[:8]}-{raw_id[8:12]}-{raw_id[12:16]}-"
                f"{raw_id[16:20]}-{raw_id[20:]}")
    return raw_id


def _fetch_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise MojangNotFound from exc
        raise MojangUpstreamError from exc
    except Exception as exc:
        raise MojangUpstreamError from exc


def resolve_username(username: str) -> dict:
    """Look up a Minecraft username and return {"uuid": ..., "name": ...}.

    Raises MojangNotFound or MojangUpstreamError.
    """
    data = _fetch_json(f"https://api.mojang.com/users/profiles/minecraft/{username}")
    return {
        "uuid": _format_uuid(data.get("id", "")),
        "name": data.get("name", username),
    }


def resolve_uuid(uuid: str) -> dict:
    """Look up a Minecraft UUID and return {"uuid": ..., "name": ...}.

    Raises MojangNotFound or MojangUpstreamError.
    """
    uuid_nodashes = uuid.replace("-", "")
    data = _fetch_json(
        f"https://sessionserver.mojang.com/session/minecraft/profile/{uuid_nodashes}"
    )
    return {
        "uuid": uuid,
        "name": data.get("name", ""),
    }
