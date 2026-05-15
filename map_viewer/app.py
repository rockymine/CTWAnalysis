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


def _walk_embedded_regions(container: list):
    """Yield each embedded region dict found in spawns/wools/observer_spawn items."""
    for item in container:
        embedded = item.get("region") or item.get("monument")
        if embedded:
            yield from _walk_region_recursive(embedded)


def _walk_region_recursive(region: dict):
    yield region
    for child in region.get("children", []):
        yield from _walk_region_recursive(child)


def _patch_embedded_region(container: list, region_id: str, new_bounds_2d: dict) -> None:
    """Update bounds_2d on any embedded region copy whose id matches region_id."""
    for r in _walk_embedded_regions(container):
        if r.get("id") == region_id:
            r["bounds_2d"] = new_bounds_2d


def _rename_embedded_region(container: list, old_id: str, new_id: str) -> None:
    """Rename id field on any embedded region copy whose id matches old_id."""
    for r in _walk_embedded_regions(container):
        if r.get("id") == old_id:
            r["id"] = new_id


def _rename_in_children(region: dict, old_id: str, new_id: str) -> None:
    """Recursively update id in a composite region's children array."""
    for child in region.get("children", []):
        if child.get("id") == old_id:
            child["id"] = new_id
        _rename_in_children(child, old_id, new_id)


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
        bounds = body.get("bounds") if isinstance(body.get("bounds"), dict) else None
        if not body.get("id") and bounds is None:
            return jsonify({"error": "provide 'id' or 'bounds'"}), 400

        data_path = OUTPUT_ROOT / name / "map_data.json"
        if not data_path.exists():
            abort(404)

        data    = json.loads(data_path.read_text(encoding="utf-8"))
        regions = data.get("regions", {})
        region  = regions.get(region_id)
        if region is None:
            return jsonify({"error": f"region {region_id!r} not found"}), 404

        # ── optional id rename ────────────────────────────────────────────────
        new_id = (body.get("id") or "").strip()
        if new_id and new_id != region_id:
            if new_id in regions:
                return jsonify({"error": f"id {new_id!r} already in use"}), 409
            # Re-key in regions dict and update the id field inside the dict
            regions[new_id] = regions.pop(region_id)
            regions[new_id]["id"] = new_id
            # Keep region_categories consistent
            for cat_list in data.get("region_categories", {}).values():
                for i, rid in enumerate(cat_list):
                    if rid == region_id:
                        cat_list[i] = new_id
            # Update id in any composite parent's children array
            for r in regions.values():
                _rename_in_children(r, region_id, new_id)
            # Update embedded copies in spawns / wools / observer_spawn
            for container_key in ("spawns", "wools"):
                _rename_embedded_region(data.get(container_key, []), region_id, new_id)
            obs = data.get("observer_spawn")
            if obs:
                _rename_embedded_region([obs], region_id, new_id)
            region_id = new_id
            region = regions[region_id]

        # ── optional bounds update ────────────────────────────────────────────
        if bounds:
            new_bounds_2d = {
                "min": {"x": bounds["min_x"], "z": bounds["min_z"]},
                "max": {"x": bounds["max_x"], "z": bounds["max_z"]},
            }
            region["bounds_2d"] = new_bounds_2d
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
