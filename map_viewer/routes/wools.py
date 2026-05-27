from __future__ import annotations

from flask import Blueprint, jsonify, request

from map_viewer.services import wool_editor
from map_viewer.services.config import get_output_root
from map_viewer.services.map_data import load_map_data, save_map_data
from map_viewer.services.wool_editor import InvalidWoolPayload, WoolConflict, WoolNotFound

bp = Blueprint("wools", __name__, url_prefix="/api/map")


@bp.route("/<name>/wools", methods=["POST"])
def add_wool(name: str):
    body = request.get_json(silent=True) or {}
    data, data_path = load_map_data(name)
    try:
        result = wool_editor.add_wool(data, body)
    except InvalidWoolPayload as exc:
        return jsonify({"error": str(exc)}), 400
    except WoolConflict as exc:
        return jsonify({"error": str(exc)}), 409
    save_map_data(data, data_path)
    return jsonify({"ok": True, **result}), 201


@bp.route("/<name>/wool/<team_id>/<color>", methods=["PATCH"])
def update_wool(name: str, team_id: str, color: str):
    body = request.get_json(silent=True) or {}
    data, data_path = load_map_data(name)
    try:
        result = wool_editor.update_wool(data, team_id, color, body)
    except WoolNotFound as exc:
        return jsonify({"error": str(exc)}), 404
    except WoolConflict as exc:
        return jsonify({"error": str(exc)}), 409
    save_map_data(data, data_path)
    return jsonify({"ok": True, **result})


@bp.route("/<name>/wool/<team_id>/<color>", methods=["DELETE"])
def delete_wool(name: str, team_id: str, color: str):
    data, data_path = load_map_data(name)
    try:
        wool_editor.delete_wool(data, team_id, color)
    except WoolNotFound as exc:
        return jsonify({"error": str(exc)}), 404
    save_map_data(data, data_path)
    return jsonify({"ok": True})


@bp.route("/<name>/wool/<team_id>/<color>/room-status")
def wool_room_status(name: str, team_id: str, color: str):
    data, _ = load_map_data(name)
    out_dir = get_output_root() / name
    try:
        result = wool_editor.get_room_status(data, out_dir, team_id, color)
    except WoolNotFound as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify(result)
