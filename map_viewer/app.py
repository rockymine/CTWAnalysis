"""Flask app for the CTW map viewer.

Routes
------
GET /                              Single-page HTML app (templates/index.html)
GET /api/maps                      List maps that have map_context.json
GET /api/map/<name>/context        map_context.json payload
GET /api/map/<name>/regions        Region hierarchy grouped by thematic category
"""

from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, jsonify, abort, render_template, request

from map_viewer.region_encoder import encode_region_tree_categorized, regions_to_xml

OUTPUT_ROOT = Path(__file__).parent.parent / "output"


def _patch_embedded_region(container: list, region_id: str, new_bounds_2d: dict) -> None:
    """Update bounds_2d on any embedded region copy whose id matches region_id.

    spawns and wools in map_data.json store a full region dict rather than a
    reference, so they must be kept in sync when the region is patched.
    Recurses into children to handle nested composites.
    """
    for item in container:
        embedded = item.get("region") or item.get("monument")
        if embedded:
            _patch_region_recursive(embedded, region_id, new_bounds_2d)


def _patch_region_recursive(region: dict, region_id: str, new_bounds_2d: dict) -> None:
    if region.get("id") == region_id:
        region["bounds_2d"] = new_bounds_2d
    for child in region.get("children", []):
        _patch_region_recursive(child, region_id, new_bounds_2d)


def create_app() -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/maps")
    def list_maps():
        maps = [
            {"name": path.name, "display_name": path.name.replace("_", " ").title()}
            for path in sorted(OUTPUT_ROOT.iterdir())
            if (path / "map_context.json").exists()
        ]
        return jsonify(maps)

    @app.route("/api/map/<name>/context")
    def map_context(name: str):
        ctx_path = OUTPUT_ROOT / name / "map_context.json"
        if not ctx_path.exists():
            abort(404)
        return jsonify(json.loads(ctx_path.read_text(encoding="utf-8")))

    @app.route("/api/map/<name>/regions")
    def map_regions(name: str):
        data_path = OUTPUT_ROOT / name / "map_data.json"
        if not data_path.exists():
            abort(404)
        data = json.loads(data_path.read_text(encoding="utf-8"))
        groups = encode_region_tree_categorized(
            data.get("regions", {}),
            data.get("region_categories", {}),
        )
        return jsonify(groups)

    @app.route("/api/map/<name>/export/xml")
    def export_xml(name: str):
        data_path = OUTPUT_ROOT / name / "map_data.json"
        if not data_path.exists():
            abort(404)
        data = json.loads(data_path.read_text(encoding="utf-8"))
        xml = regions_to_xml(data.get("regions", {}))
        filename = f"{name}_regions.xml"
        return xml, 200, {
            "Content-Type": "application/xml; charset=utf-8",
            "Content-Disposition": f'attachment; filename="{filename}"',
        }

    @app.route("/api/map/<name>/region/<region_id>", methods=["PATCH"])
    def patch_region(name: str, region_id: str) -> tuple:
        body   = request.get_json(silent=True) or {}
        bounds = body.get("bounds")
        if not isinstance(bounds, dict):
            return jsonify({"error": "bounds dict required"}), 400

        data_path = OUTPUT_ROOT / name / "map_data.json"
        if not data_path.exists():
            abort(404)

        data   = json.loads(data_path.read_text(encoding="utf-8"))
        region = data.get("regions", {}).get(region_id)
        if region is None:
            return jsonify({"error": f"region {region_id!r} not found"}), 404

        new_bounds_2d = {
            "min": {"x": bounds["min_x"], "z": bounds["min_z"]},
            "max": {"x": bounds["max_x"], "z": bounds["max_z"]},
        }
        region["bounds_2d"] = new_bounds_2d

        # spawns and observer_spawn embed a full copy of each region rather than
        # a reference, so update any embedded region whose id matches.
        _patch_embedded_region(data.get("spawns", []), region_id, new_bounds_2d)
        _patch_embedded_region(data.get("wools", []), region_id, new_bounds_2d)
        obs = data.get("observer_spawn")
        if obs:
            _patch_embedded_region([obs], region_id, new_bounds_2d)

        data_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return jsonify({"ok": True})

    return app
