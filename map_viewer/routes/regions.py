from __future__ import annotations

from flask import Blueprint, jsonify, request

from map_viewer.services import region_editor
from map_viewer.services.map_data import load_map_data, save_map_data
from map_viewer.services.region_editor import InvalidRegionPayload, RegionConflict, RegionNotFound

bp = Blueprint("regions", __name__, url_prefix="/api/map")


@bp.route("/<name>/regions", methods=["POST"])
def create_region(name: str):
    body = request.get_json(silent=True) or {}
    data, data_path = load_map_data(name)
    try:
        result = region_editor.create_region(data, body)
    except InvalidRegionPayload as exc:
        return jsonify({"error": str(exc)}), 400
    except RegionConflict as exc:
        return jsonify({"error": str(exc)}), 409
    save_map_data(data, data_path)
    return jsonify({"ok": True, **result}), 201


@bp.route("/<name>/regions/group", methods=["POST"])
def group_regions(name: str):
    body = request.get_json(silent=True) or {}
    data, data_path = load_map_data(name)
    try:
        result = region_editor.group_regions(data, body)
    except InvalidRegionPayload as exc:
        return jsonify({"error": str(exc)}), 400
    except RegionNotFound as exc:
        return jsonify({"error": str(exc)}), 404
    except RegionConflict as exc:
        return jsonify({"error": str(exc)}), 409
    save_map_data(data, data_path)
    return jsonify({"ok": True, **result}), 201


@bp.route("/<name>/regions/ungroup", methods=["POST"])
def ungroup_region(name: str):
    body = request.get_json(silent=True) or {}
    data, data_path = load_map_data(name)
    try:
        result = region_editor.ungroup_region(data, body)
    except InvalidRegionPayload as exc:
        return jsonify({"error": str(exc)}), 400
    except RegionNotFound as exc:
        return jsonify({"error": str(exc)}), 404
    save_map_data(data, data_path)
    return jsonify({"ok": True, **result})


@bp.route("/<name>/regions/restore", methods=["POST"])
def restore_region(name: str):
    body     = request.get_json(silent=True) or {}
    snapshot = body.get("snapshot")
    if not snapshot:
        return jsonify({"error": "snapshot required"}), 400
    data, data_path = load_map_data(name)
    try:
        result = region_editor.restore_region(data, snapshot)
    except InvalidRegionPayload as exc:
        return jsonify({"error": str(exc)}), 400
    except RegionNotFound as exc:
        return jsonify({"error": str(exc)}), 404
    except RegionConflict as exc:
        return jsonify({"error": str(exc)}), 409
    save_map_data(data, data_path)
    return jsonify({"ok": True, **result})


@bp.route("/<name>/region/<region_id>", methods=["DELETE"])
def delete_region(name: str, region_id: str):
    data, data_path = load_map_data(name)
    try:
        result = region_editor.delete_region(data, region_id)
    except RegionNotFound as exc:
        return jsonify({"error": str(exc)}), 404
    save_map_data(data, data_path)
    return jsonify({"ok": True, **result})


@bp.route("/<name>/region/<region_id>", methods=["PATCH"])
def patch_region(name: str, region_id: str):
    body = request.get_json(silent=True) or {}
    data, data_path = load_map_data(name)
    try:
        result = region_editor.patch_region(data, region_id, body)
    except InvalidRegionPayload as exc:
        return jsonify({"error": str(exc)}), 400
    except RegionNotFound as exc:
        return jsonify({"error": str(exc)}), 404
    except RegionConflict as exc:
        return jsonify({"error": str(exc)}), 409
    save_map_data(data, data_path)
    return jsonify({"ok": True, **result})
