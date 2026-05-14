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

from flask import Flask, jsonify, abort, render_template

from map_viewer.region_encoder import encode_region_tree_categorized

OUTPUT_ROOT = Path(__file__).parent.parent / "output"


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

    return app
