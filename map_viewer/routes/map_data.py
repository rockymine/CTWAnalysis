from __future__ import annotations

import json

import pandas as pd
from flask import Blueprint, abort, jsonify, request

from common.visualization.block_colors import block_color
from map_viewer.services.config import get_output_root
from map_viewer.services.map_data import load_map_data, save_map_data
from map_viewer.services.region_tree import encode_region_tree_categorized
from map_viewer.services.region_xml import regions_to_xml

bp = Blueprint("map_data", __name__, url_prefix="/api")

_METADATA_FIELDS = {
    "name", "version", "objective", "max_build_height", "gamemode",
    "phase", "authors", "symmetry_status",
}


@bp.route("/maps")
def list_maps():
    output_root = get_output_root()
    if not output_root.exists():
        return jsonify([])
    maps = [
        {"name": path.name, "display_name": path.name.replace("_", " ").title()}
        for path in sorted(output_root.iterdir())
        if (path / "map_context.json").exists()
    ]
    return jsonify(maps)


@bp.route("/map/<name>/map-data")
def map_data_raw(name: str):
    data, _ = load_map_data(name)
    return jsonify(data)


@bp.route("/map/<name>/metadata", methods=["PATCH"])
def patch_map_metadata(name: str):
    data, data_path = load_map_data(name)
    payload = request.get_json(force=True)
    for key, value in payload.items():
        if key in _METADATA_FIELDS:
            data[key] = value
    save_map_data(data, data_path)
    return jsonify({"ok": True})


@bp.route("/map/<name>/symmetry")
def map_symmetry(name: str):
    sym_path = get_output_root() / name / "symmetry.json"
    if not sym_path.exists():
        abort(404)
    return jsonify(json.loads(sym_path.read_text(encoding="utf-8")))


@bp.route("/map/<name>/context")
def map_context(name: str):
    ctx_path = get_output_root() / name / "map_context.json"
    if not ctx_path.exists():
        abort(404)
    return jsonify(json.loads(ctx_path.read_text(encoding="utf-8")))


@bp.route("/map/<name>/regions")
def map_regions(name: str):
    data, _ = load_map_data(name)
    groups = encode_region_tree_categorized(
        data.get("regions", {}),
        data.get("region_categories", {}),
    )
    return jsonify(groups)


@bp.route("/map/<name>/export/xml")
def export_xml(name: str):
    data, _ = load_map_data(name)
    xml = regions_to_xml(data.get("regions", {}))
    filename = f"{name}_regions.xml"
    return xml, 200, {
        "Content-Type": "application/xml; charset=utf-8",
        "Content-Disposition": f'attachment; filename="{filename}"',
    }


@bp.route("/map/<name>/layers/top-surface")
def layer_top_surface(name: str):
    parquet_path = get_output_root() / name / "layout_top_surface.parquet"
    if not parquet_path.exists():
        abort(404)
    df = pd.read_parquet(
        parquet_path, columns=["world_x", "world_z", "block_id", "block_data"]
    )
    colors = [
        "#{:02x}{:02x}{:02x}".format(*block_color(int(bid), int(bdat)))
        for bid, bdat in zip(df["block_id"], df["block_data"])
    ]
    return jsonify({
        "xs":     df["world_x"].tolist(),
        "zs":     df["world_z"].tolist(),
        "colors": colors,
        "min_x": int(df["world_x"].min()), "min_z": int(df["world_z"].min()),
        "max_x": int(df["world_x"].max()), "max_z": int(df["world_z"].max()),
    })
