from __future__ import annotations

from flask import Blueprint, jsonify, request

from map_viewer.services import spawn_editor
from map_viewer.services.map_data import load_map_data, save_map_data
from map_viewer.services.spawn_editor import InvalidSpawnPayload, SpawnConflict, SpawnNotFound

bp = Blueprint("spawns", __name__, url_prefix="/api/map")


@bp.route("/<name>/spawns", methods=["POST"])
def add_spawn_link(name: str):
    body = request.get_json(silent=True) or {}
    data, data_path = load_map_data(name)
    try:
        spawn_editor.add_spawn_link(data, body)
    except InvalidSpawnPayload as exc:
        return jsonify({"error": str(exc)}), 400
    except SpawnNotFound as exc:
        return jsonify({"error": str(exc)}), 404
    except SpawnConflict as exc:
        return jsonify({"error": str(exc)}), 409
    save_map_data(data, data_path)
    return jsonify({"ok": True}), 201


@bp.route("/<name>/spawn/<region_id>", methods=["PATCH"])
def update_spawn_link(name: str, region_id: str):
    body = request.get_json(silent=True) or {}
    data, data_path = load_map_data(name)
    try:
        spawn_editor.update_spawn_link(data, region_id, body)
    except SpawnNotFound as exc:
        return jsonify({"error": str(exc)}), 404
    save_map_data(data, data_path)
    return jsonify({"ok": True})


@bp.route("/<name>/spawn/<region_id>", methods=["DELETE"])
def delete_spawn_link(name: str, region_id: str):
    data, data_path = load_map_data(name)
    try:
        spawn_editor.delete_spawn_link(data, region_id)
    except SpawnNotFound as exc:
        return jsonify({"error": str(exc)}), 404
    save_map_data(data, data_path)
    return jsonify({"ok": True})
