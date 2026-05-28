from __future__ import annotations

from flask import Blueprint, jsonify, request

from layout_analysis.map_layout_config import get_map_layout, save_map_layout

bp = Blueprint("layout_config", __name__, url_prefix="/api")


@bp.route("/layout-config/<name>")
def get_layout_config(name: str):
    cfg = get_map_layout(name)
    if cfg is None:
        return jsonify(None)
    return jsonify({
        "layer":           cfg.layer,
        "exclude":         cfg.exclude,
        "skip":            cfg.skip,
        "exclude_islands": cfg.exclude_islands,
        "playable_bbox":   list(cfg.playable_bbox) if cfg.playable_bbox else None,
    })


@bp.route("/layout-config/<name>", methods=["PATCH"])
def patch_layout_config(name: str):
    body = request.get_json(force=True) or {}
    save_map_layout(name, body)
    return jsonify({"ok": True})
