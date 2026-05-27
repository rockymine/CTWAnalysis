from __future__ import annotations

from flask import Blueprint, jsonify, request

from map_viewer.services.config import load_config, save_config as _save_config

bp = Blueprint("config", __name__, url_prefix="/api")


@bp.route("/config")
def get_config():
    return jsonify(load_config())


@bp.route("/config", methods=["POST"])
def save_config():
    body = request.get_json(silent=True) or {}
    _save_config(body)
    return jsonify({"ok": True})
