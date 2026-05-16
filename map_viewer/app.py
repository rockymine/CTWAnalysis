"""Flask app for the CTW map viewer.

Routes
------
GET /                              Dashboard (templates/index.html)
GET /editor                        Map editor (templates/editor.html)
GET /api/config                    Load configuration
POST /api/config                   Save configuration
GET /api/maps                      List maps that have map_context.json (editor API)
GET /api/source-maps               List all map folders from configured maps_folder
GET /api/source-map/<n>/validate   Validate map folder structure
GET /api/source-map/<n>/pipeline-status   Check which pipeline steps are complete
GET /api/source-map/<n>/pipeline/run      SSE stream: run the analysis pipeline
GET /api/map/<name>/context        map_context.json payload
GET /api/map/<name>/regions        Region hierarchy grouped by thematic category
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from pathlib import Path
from typing import Optional

import pandas as pd
from flask import Flask, Response, jsonify, abort, render_template, request, stream_with_context

from map_viewer.region_encoder import encode_region_tree_categorized, regions_to_xml
from common.visualization.block_colors import block_color

_DEFAULT_OUTPUT_ROOT = Path(__file__).parent.parent / "output"
CONFIG_PATH = Path(__file__).parent / "config.json"

logger = logging.getLogger("ctw")


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "maps_folder": "",
        "output_folder": str(_DEFAULT_OUTPUT_ROOT),
    }


def _get_output_root() -> Path:
    cfg = _load_config()
    folder = cfg.get("output_folder", "").strip()
    return Path(folder) if folder else _DEFAULT_OUTPUT_ROOT


# ── Helpers shared across region endpoints ─────────────────────────────────

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


def _collect_region_subtree_ids(regions: dict, region_id: str) -> list[str]:
    """Return region_id and all descendant ids found in regions (depth-first)."""
    result = [region_id]
    for child in regions.get(region_id, {}).get("children", []):
        child_id = child.get("id")
        if child_id and child_id in regions:
            result.extend(_collect_region_subtree_ids(regions, child_id))
    return result


def _rename_in_children(region: dict, old_id: str, new_id: str) -> None:
    """Recursively update id in a composite region's children array."""
    for child in region.get("children", []):
        if child.get("id") == old_id:
            child["id"] = new_id
        _rename_in_children(child, old_id, new_id)


def _find_child_region(regions_dict: dict, target_sid: str) -> dict | None:
    """Find a region by synthetic id, searching recursively through children.

    Synthetic ids mirror region_encoder._encode_node logic:
      named region   → its own xml id
      anonymous child at index i of parent with sid P → f"{P}__{i}"
    Returns the mutable child dict so the caller can update it in-place.
    """
    def _walk(region: dict, region_sid: str) -> dict | None:
        for i, child in enumerate(region.get("children", [])):
            child_xml_id = child.get("id", "")
            child_sid = child_xml_id if child_xml_id else f"{region_sid}__{i}"
            if child_sid == target_sid:
                return child
            result = _walk(child, child_sid)
            if result is not None:
                return result
        return None

    for rid, region in regions_dict.items():
        region_sid = region.get("id", "") or rid
        result = _walk(region, region_sid)
        if result is not None:
            return result
    return None


# ── Pipeline status helpers ────────────────────────────────────────────────

_PIPELINE_STEPS = [
    {"id": "layout",   "label": "Layout",   "file": "layout_bedrock.parquet"},
    {"id": "islands",  "label": "Islands",  "file": "islands.json"},
    {"id": "symmetry", "label": "Symmetry", "file": "symmetry.json"},
    {"id": "xml",      "label": "XML",      "file": "map_data.json"},
    {"id": "assembly", "label": "Assembly", "file": "map_context.json"},
]


def _check_pipeline_status(output_dir: Path) -> list[dict]:
    return [
        {
            "id": step["id"],
            "label": step["label"],
            "file": step["file"],
            "done": (output_dir / step["file"]).exists(),
        }
        for step in _PIPELINE_STEPS
    ]


def create_app() -> Flask:
    app = Flask(__name__)

    # ── Page routes ─────────────────────────────────────────────────────────

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/editor")
    def editor():
        return render_template("editor.html")

    # ── Configuration API ────────────────────────────────────────────────────

    @app.route("/api/config")
    def get_config():
        return jsonify(_load_config())

    @app.route("/api/config", methods=["POST"])
    def save_config():
        body = request.get_json(silent=True) or {}
        config = _load_config()
        for key in ("maps_folder", "output_folder"):
            if key in body:
                config[key] = str(body[key]).strip()
        CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
        return jsonify({"ok": True})

    # ── Source-map discovery API ─────────────────────────────────────────────

    @app.route("/api/source-maps")
    def list_source_maps():
        config = _load_config()
        maps_folder = Path(config.get("maps_folder", "").strip())
        if not maps_folder or not maps_folder.exists():
            return jsonify({"error": "maps_folder not configured or does not exist"}), 400

        output_root = _get_output_root()

        maps = []
        for path in sorted(maps_folder.iterdir()):
            if not path.is_dir():
                continue
            out_dir = output_root / path.name
            steps = _check_pipeline_status(out_dir)
            all_done = all(s["done"] for s in steps)
            maps.append({
                "name": path.name,
                "display_name": path.name.replace("_", " ").title(),
                "preprocessed": all_done,
            })
        return jsonify(maps)

    @app.route("/api/source-map/<name>/validate")
    def validate_source_map(name: str):
        config = _load_config()
        maps_folder = Path(config.get("maps_folder", "").strip())
        map_path = maps_folder / name

        if not map_path.exists():
            return jsonify({"valid": False, "issues": ["Map folder does not exist"]})

        issues = []
        if not (map_path / "map.xml").exists():
            issues.append("Missing map.xml")
        if not (map_path / "region").exists():
            issues.append("Missing 'region' folder (Anvil world data required for layout extraction)")

        return jsonify({"valid": len(issues) == 0, "issues": issues})

    @app.route("/api/source-map/<name>/thumbnail")
    def source_map_thumbnail(name: str):
        from flask import send_file
        config = _load_config()
        maps_folder = Path(config.get("maps_folder", "").strip())
        candidates = [
            maps_folder / name / "map.png",
            _get_output_root() / name / "map.png",
        ]
        for path in candidates:
            if path.exists():
                return send_file(path, mimetype="image/png")
        abort(404)

    @app.route("/api/source-map/<name>/pipeline-status")
    def pipeline_status(name: str):
        import time
        output_root = _get_output_root()
        out_dir = output_root / name
        steps = _check_pipeline_status(out_dir)
        all_done = all(s["done"] for s in steps)
        last_updated: Optional[float] = None
        if all_done:
            mtimes = [
                (out_dir / s["file"]).stat().st_mtime
                for s in steps
                if (out_dir / s["file"]).exists()
            ]
            if mtimes:
                last_updated = max(mtimes)
        return jsonify({"steps": steps, "all_done": all_done, "last_updated": last_updated})

    @app.route("/api/source-map/<name>/pipeline/run")
    def run_pipeline(name: str):
        force = request.args.get("force", "0") == "1"

        config = _load_config()
        maps_folder_str = config.get("maps_folder", "").strip()
        if not maps_folder_str:
            return jsonify({"error": "maps_folder not configured"}), 400

        map_folder = Path(maps_folder_str) / name
        if not map_folder.exists():
            return jsonify({"error": f"Map folder not found: {name}"}), 404

        output_root = _get_output_root()
        map_output_dir = output_root / name

        def generate():
            event_queue: queue.Queue[Optional[str]] = queue.Queue()

            def send(event_type: str, data: dict) -> None:
                msg = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                event_queue.put(msg)

            def pipeline_thread() -> None:
                try:
                    import traceback
                    from ctw.log import setup_map_file_logging
                    from map_analysis.pipeline import run_island_geometry, run_symmetry, assemble_map
                    from ctw.commands.layout import analyze_layout
                    from ctw.commands.xml import analyze_xml
                    from layout_analysis.map_layout_config import get_map_layout

                    map_output_dir.mkdir(parents=True, exist_ok=True)
                    setup_map_file_logging(map_output_dir)

                    map_layout_cfg = get_map_layout(name)

                    if map_layout_cfg is not None and map_layout_cfg.skip:
                        send("skipped", {"reason": "Map is excluded in map_layouts.yaml"})
                        return

                    # Determine island layout type (mirrors run.py logic)
                    if map_layout_cfg is not None:
                        if map_layout_cfg.layer == "y0" and not map_layout_cfg.exclude:
                            island_layout_type = "y0"
                        else:
                            island_layout_type = "decided"
                    else:
                        island_layout_type = "bedrock"

                    # Step 1 — Layout
                    send("step", {"step": "layout", "status": "running", "label": "Layout"})
                    try:
                        parquet_files = analyze_layout(
                            map_folder,
                            force_rerun=force,
                            output_dir=map_output_dir,
                            map_layout_config=map_layout_cfg,
                        )
                        n = len(parquet_files) if parquet_files else 0
                        send("step", {"step": "layout", "status": "done", "label": "Layout",
                                      "detail": f"{n} file(s) written"})
                    except Exception as exc:
                        send("step", {"step": "layout", "status": "error", "label": "Layout",
                                      "detail": str(exc)})
                        send("error", {"message": f"Layout failed: {exc}"})
                        return

                    # Step 2 — Islands
                    send("step", {"step": "islands", "status": "running", "label": "Islands"})
                    try:
                        geometry = run_island_geometry(
                            map_folder,
                            force_rerun=force,
                            layout_type=island_layout_type,
                            map_output_dir=map_output_dir,
                        )
                        if not geometry:
                            send("step", {"step": "islands", "status": "error", "label": "Islands",
                                          "detail": "No islands detected — check layout"})
                            send("error", {"message": "Island detection produced no results"})
                            return
                        send("step", {"step": "islands", "status": "done", "label": "Islands",
                                      "detail": f"{len(geometry.islands)} island(s)"})
                    except Exception as exc:
                        send("step", {"step": "islands", "status": "error", "label": "Islands",
                                      "detail": str(exc)})
                        send("error", {"message": f"Islands failed: {exc}"})
                        return

                    # Step 3 — Symmetry
                    send("step", {"step": "symmetry", "status": "running", "label": "Symmetry"})
                    symmetry = None
                    try:
                        symmetry = run_symmetry(map_output_dir, geometry=geometry)
                        desc = (symmetry.primary["description"] if symmetry and symmetry.primary
                                else "none detected")
                        send("step", {"step": "symmetry", "status": "done", "label": "Symmetry",
                                      "detail": desc})
                    except Exception as exc:
                        send("step", {"step": "symmetry", "status": "error", "label": "Symmetry",
                                      "detail": str(exc)})
                        # Non-fatal: continue without symmetry

                    # Step 4 — XML
                    send("step", {"step": "xml", "status": "running", "label": "XML"})
                    xml_context = None
                    try:
                        xml_context = analyze_xml(map_folder, force_rerun=force,
                                                  output_dir=map_output_dir)
                        if xml_context:
                            md = xml_context.map_data
                            detail_txt = f"{len(md.teams)} team(s), {len(md.wools)} wool(s)"
                        else:
                            detail_txt = "no map.xml found"
                        send("step", {"step": "xml", "status": "done", "label": "XML",
                                      "detail": detail_txt})
                    except Exception as exc:
                        send("step", {"step": "xml", "status": "error", "label": "XML",
                                      "detail": str(exc)})
                        # Non-fatal: assemble without XML

                    # Step 5 — Assembly
                    send("step", {"step": "assembly", "status": "running", "label": "Assembly"})
                    try:
                        exclude_obs = (map_layout_cfg.exclude_observer_island
                                       if map_layout_cfg is not None else False)
                        exclude_isl = (map_layout_cfg.exclude_islands
                                       if map_layout_cfg is not None else [])
                        bbox = (map_layout_cfg.playable_bbox
                                if map_layout_cfg is not None else None)

                        assemble_map(
                            map_folder, geometry, map_output_dir,
                            symmetry=symmetry, xml_context=xml_context,
                            exclude_observer_island=exclude_obs,
                            exclude_islands=exclude_isl,
                            playable_bbox=bbox,
                        )
                        send("step", {"step": "assembly", "status": "done", "label": "Assembly"})
                    except Exception as exc:
                        send("step", {"step": "assembly", "status": "error", "label": "Assembly",
                                      "detail": str(exc)})
                        send("error", {"message": f"Assembly failed: {exc}"})
                        return

                    send("done", {"message": "Pipeline complete"})

                except Exception as exc:
                    import traceback as _tb
                    send("error", {"message": f"Unexpected error: {exc}",
                                   "detail": _tb.format_exc()})
                finally:
                    event_queue.put(None)  # sentinel

            thread = threading.Thread(target=pipeline_thread, daemon=True)
            thread.start()

            while True:
                item = event_queue.get()
                if item is None:
                    break
                yield item

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── Editor map list (maps with map_context.json) ─────────────────────────

    @app.route("/api/maps")
    def list_maps():
        output_root = _get_output_root()
        if not output_root.exists():
            return jsonify([])
        maps = [
            {"name": path.name, "display_name": path.name.replace("_", " ").title()}
            for path in sorted(output_root.iterdir())
            if (path / "map_context.json").exists()
        ]
        return jsonify(maps)

    # ── Map data endpoints (used by editor) ──────────────────────────────────

    @app.route("/api/map/<name>/context")
    def map_context(name: str):
        ctx_path = _get_output_root() / name / "map_context.json"
        if not ctx_path.exists():
            abort(404)
        return jsonify(json.loads(ctx_path.read_text(encoding="utf-8")))

    @app.route("/api/map/<name>/regions")
    def map_regions(name: str):
        data_path = _get_output_root() / name / "map_data.json"
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
        data_path = _get_output_root() / name / "map_data.json"
        if not data_path.exists():
            abort(404)
        data = json.loads(data_path.read_text(encoding="utf-8"))
        xml = regions_to_xml(data.get("regions", {}))
        filename = f"{name}_regions.xml"
        return xml, 200, {
            "Content-Type": "application/xml; charset=utf-8",
            "Content-Disposition": f'attachment; filename="{filename}"',
        }

    @app.route("/api/map/<name>/layers/top-surface")
    def layer_top_surface(name: str):
        parquet_path = _get_output_root() / name / "layout_top_surface.parquet"
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
            "xs":    df["world_x"].tolist(),
            "zs":    df["world_z"].tolist(),
            "colors": colors,
            "min_x": int(df["world_x"].min()), "min_z": int(df["world_z"].min()),
            "max_x": int(df["world_x"].max()), "max_z": int(df["world_z"].max()),
        })

    @app.route("/api/map/<name>/regions", methods=["POST"])
    def create_region(name: str) -> tuple:
        body = request.get_json(silent=True) or {}
        if body.get("type", "rectangle") != "rectangle":
            return jsonify({"error": "only 'rectangle' type is supported"}), 400
        try:
            min_x = int(round(float(body["min_x"])))
            min_z = int(round(float(body["min_z"])))
            max_x = int(round(float(body["max_x"])))
            max_z = int(round(float(body["max_z"])))
        except (KeyError, TypeError, ValueError):
            return jsonify({"error": "min_x, min_z, max_x, max_z are required numbers"}), 400

        data_path = _get_output_root() / name / "map_data.json"
        if not data_path.exists():
            abort(404)

        data    = json.loads(data_path.read_text(encoding="utf-8"))
        regions = data.setdefault("regions", {})

        region_id = (body.get("id") or "").strip()
        if not region_id:
            i = 1
            while f"region_{i}" in regions:
                i += 1
            region_id = f"region_{i}"
        elif region_id in regions:
            return jsonify({"error": f"id {region_id!r} already in use"}), 409

        regions[region_id] = {
            "id": region_id,
            "type": "rectangle",
            "min_x": min_x, "min_z": min_z,
            "max_x": max_x, "max_z": max_z,
            "bounds_2d": {
                "min": {"x": min_x, "z": min_z},
                "max": {"x": max_x, "z": max_z},
            },
        }
        data.setdefault("region_categories", {}).setdefault("other", []).append(region_id)

        data_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return jsonify({"ok": True, "id": region_id}), 201

    @app.route("/api/map/<name>/regions/group", methods=["POST"])
    def group_regions(name: str) -> tuple:
        body      = request.get_json(silent=True) or {}
        child_ids = [str(cid) for cid in body.get("child_ids", [])]
        if len(child_ids) < 2:
            return jsonify({"error": "at least 2 regions required"}), 400

        data_path = _get_output_root() / name / "map_data.json"
        if not data_path.exists():
            abort(404)

        data    = json.loads(data_path.read_text(encoding="utf-8"))
        regions = data.setdefault("regions", {})

        missing = [cid for cid in child_ids if cid not in regions]
        if missing:
            return jsonify({"error": f"unknown region(s): {missing}"}), 404

        union_id = (body.get("id") or "").strip()
        if not union_id:
            i = 1
            while f"union_{i}" in regions:
                i += 1
            union_id = f"union_{i}"
        elif union_id in regions:
            return jsonify({"error": f"id {union_id!r} already in use"}), 409

        children = [regions[cid] for cid in child_ids]
        bounded  = [c for c in children if c.get("bounds_2d")]
        if bounded:
            min_x = min(c["bounds_2d"]["min"]["x"] for c in bounded)
            min_z = min(c["bounds_2d"]["min"]["z"] for c in bounded)
            max_x = max(c["bounds_2d"]["max"]["x"] for c in bounded)
            max_z = max(c["bounds_2d"]["max"]["z"] for c in bounded)
            bounds_2d = {"min": {"x": min_x, "z": min_z}, "max": {"x": max_x, "z": max_z}}
        else:
            bounds_2d = None
            min_x = min_z = max_x = max_z = 0

        regions[union_id] = {
            "id": union_id,
            "type": "union",
            "children": children,
            **({"bounds_2d": bounds_2d} if bounds_2d else {}),
        }
        data.setdefault("region_categories", {}).setdefault("other", []).append(union_id)

        data_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return jsonify({
            "ok": True, "id": union_id,
            "bounds": {"min_x": min_x, "min_z": min_z, "max_x": max_x, "max_z": max_z},
        }), 201

    @app.route("/api/map/<name>/region/<region_id>", methods=["DELETE"])
    def delete_region(name: str, region_id: str) -> tuple:
        data_path = _get_output_root() / name / "map_data.json"
        if not data_path.exists():
            abort(404)
        data    = json.loads(data_path.read_text(encoding="utf-8"))
        regions = data.get("regions", {})
        if region_id not in regions:
            return jsonify({"error": f"region {region_id!r} not found"}), 404
        for rid in _collect_region_subtree_ids(regions, region_id):
            regions.pop(rid, None)
            for cat_list in data.get("region_categories", {}).values():
                if rid in cat_list:
                    cat_list.remove(rid)
        data_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return jsonify({"ok": True})

    @app.route("/api/map/<name>/region/<region_id>", methods=["PATCH"])
    def patch_region(name: str, region_id: str) -> tuple:
        body   = request.get_json(silent=True) or {}
        bounds = body.get("bounds") if isinstance(body.get("bounds"), dict) else None
        if not body.get("id") and bounds is None:
            return jsonify({"error": "provide 'id' or 'bounds'"}), 400

        data_path = _get_output_root() / name / "map_data.json"
        if not data_path.exists():
            abort(404)

        data    = json.loads(data_path.read_text(encoding="utf-8"))
        regions = data.get("regions", {})

        # Top-level lookup first; fall back to recursive child search for synthetic ids.
        region = regions.get(region_id)
        is_top_level = region is not None
        if not is_top_level:
            region = _find_child_region(regions, region_id)
            if region is None:
                return jsonify({"error": f"region {region_id!r} not found"}), 404

        # ── optional id rename (top-level named regions only) ─────────────────
        if is_top_level:
            new_id = (body.get("id") or "").strip()
            if new_id and new_id != region_id:
                if new_id in regions:
                    return jsonify({"error": f"id {new_id!r} already in use"}), 409
                regions[new_id] = regions.pop(region_id)
                regions[new_id]["id"] = new_id
                for cat_list in data.get("region_categories", {}).values():
                    for i, rid in enumerate(cat_list):
                        if rid == region_id:
                            cat_list[i] = new_id
                for r in regions.values():
                    _rename_in_children(r, region_id, new_id)
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
            if is_top_level:
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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CTW map viewer server")
    parser.add_argument("--port", type=int, default=7891)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    wz_log = logging.getLogger("werkzeug")
    wz_log.setLevel(logging.INFO)

    app = create_app()
    url = f"http://localhost:{args.port}"
    print(f"Map viewer running at {url}", flush=True)

    if not args.no_browser:
        import webbrowser
        webbrowser.open(url)

    app.run(host="127.0.0.1", port=args.port, debug=False)
