from __future__ import annotations

from flask import Blueprint, abort, jsonify, request

from map_viewer.services import mojang
from map_viewer.services.mojang import MojangNotFound, MojangUpstreamError

bp = Blueprint("minecraft", __name__, url_prefix="/api/minecraft")


@bp.route("/player")
def minecraft_player():
    username = request.args.get("name", "").strip()
    uuid_arg = request.args.get("uuid", "").strip()
    try:
        if username:
            result = mojang.resolve_username(username)
        elif uuid_arg:
            result = mojang.resolve_uuid(uuid_arg)
        else:
            abort(400)
    except MojangNotFound:
        return jsonify({"error": "not_found"}), 404
    except MojangUpstreamError:
        return jsonify({"error": "upstream_error"}), 502
    return jsonify(result)
