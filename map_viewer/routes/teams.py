from __future__ import annotations

from flask import Blueprint, jsonify, request

from map_viewer.services import team_editor
from map_viewer.services.map_data import load_map_data, save_map_data
from map_viewer.services.team_editor import InvalidTeamPayload, TeamConflict, TeamNotFound

bp = Blueprint("teams", __name__, url_prefix="/api/map")


@bp.route("/<name>/teams", methods=["POST"])
def add_team(name: str):
    body = request.get_json(silent=True) or {}
    data, data_path = load_map_data(name)
    try:
        result = team_editor.add_team(data, body)
    except InvalidTeamPayload as exc:
        return jsonify({"error": str(exc)}), 400
    except TeamConflict as exc:
        return jsonify({"error": str(exc)}), 409
    save_map_data(data, data_path)
    return jsonify({"ok": True, **result}), 201


@bp.route("/<name>/teams/<team_id>", methods=["PATCH"])
def update_team(name: str, team_id: str):
    body = request.get_json(silent=True) or {}
    data, data_path = load_map_data(name)
    try:
        result = team_editor.update_team(data, team_id, body)
    except TeamNotFound as exc:
        return jsonify({"error": str(exc)}), 404
    except TeamConflict as exc:
        return jsonify({"error": str(exc)}), 409
    save_map_data(data, data_path)
    return jsonify({"ok": True, **result})


@bp.route("/<name>/teams/<team_id>", methods=["DELETE"])
def delete_team(name: str, team_id: str):
    data, data_path = load_map_data(name)
    try:
        team_editor.delete_team(data, team_id)
    except TeamNotFound as exc:
        return jsonify({"error": str(exc)}), 404
    save_map_data(data, data_path)
    return jsonify({"ok": True})
