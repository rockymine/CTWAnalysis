from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from typing import Optional

from flask import Blueprint, Response, abort, jsonify, request, send_file, stream_with_context

from layout_analysis.wool_query import query_resources_in_region, query_wool_in_region
from map_viewer.services.config import get_output_root, load_config
from map_viewer.services.pipeline import check_pipeline_status, run_pipeline_steps

bp = Blueprint("source_maps", __name__, url_prefix="/api")


def _parse_bounds_args() -> tuple[float, float, float, float]:
    """Parse min_x, min_z, max_x, max_z from query string.

    Raises ValueError/KeyError (caught by the caller for a 400 response).
    """
    return (
        float(request.args["min_x"]),
        float(request.args["min_z"]),
        float(request.args["max_x"]),
        float(request.args["max_z"]),
    )


@bp.route("/source-maps")
def list_source_maps():
    config = load_config()
    maps_folder = Path(config.get("maps_folder", "").strip())
    if not maps_folder or not maps_folder.exists():
        return jsonify({"error": "maps_folder not configured or does not exist"}), 400

    output_root = get_output_root()
    maps = []
    for path in sorted(maps_folder.iterdir()):
        if not path.is_dir():
            continue
        out_dir = output_root / path.name
        steps = check_pipeline_status(out_dir)
        all_done = all(s["done"] for s in steps)
        maps.append({
            "name": path.name,
            "display_name": path.name.replace("_", " ").title(),
            "preprocessed": all_done,
        })
    return jsonify(maps)


@bp.route("/source-map/<name>/validate")
def validate_source_map(name: str):
    config = load_config()
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


@bp.route("/source-map/<name>/thumbnail")
def source_map_thumbnail(name: str):
    config = load_config()
    maps_folder = Path(config.get("maps_folder", "").strip())
    candidates = [
        maps_folder / name / "map.png",
        get_output_root() / name / "map.png",
    ]
    for path in candidates:
        if path.exists():
            return send_file(path, mimetype="image/png")
    abort(404)


@bp.route("/source-map/<name>/pipeline-status")
def pipeline_status(name: str):
    out_dir = get_output_root() / name
    steps = check_pipeline_status(out_dir)
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


@bp.route("/source-map/<name>/pipeline/run")
def run_pipeline(name: str):
    force = request.args.get("force", "0") == "1"

    config = load_config()
    maps_folder_str = config.get("maps_folder", "").strip()
    if not maps_folder_str:
        return jsonify({"error": "maps_folder not configured"}), 400

    map_folder = Path(maps_folder_str) / name
    if not map_folder.exists():
        return jsonify({"error": f"Map folder not found: {name}"}), 404

    map_output_dir = get_output_root() / name

    def generate():
        event_queue: queue.Queue[Optional[str]] = queue.Queue()

        def send(event_type: str, data: dict) -> None:
            event_queue.put(f"event: {event_type}\ndata: {json.dumps(data)}\n\n")

        def pipeline_thread() -> None:
            try:
                run_pipeline_steps(map_folder, map_output_dir, name, force, send)
            finally:
                event_queue.put(None)

        threading.Thread(target=pipeline_thread, daemon=True).start()

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


@bp.route("/source-map/<name>/query/wool-in-region")
def api_query_wool_in_region(name: str):
    try:
        min_x, min_z, max_x, max_z = _parse_bounds_args()
    except (KeyError, ValueError) as exc:
        return jsonify({"error": f"Invalid or missing parameter: {exc}"}), 400

    out_dir = get_output_root() / name
    if not out_dir.exists():
        return jsonify({"error": "Map not found or not preprocessed"}), 404

    return jsonify(query_wool_in_region(out_dir, min_x, min_z, max_x, max_z))


@bp.route("/source-map/<name>/query/resources-in-region")
def api_query_resources_in_region(name: str):
    try:
        min_x, min_z, max_x, max_z = _parse_bounds_args()
    except (KeyError, ValueError) as exc:
        return jsonify({"error": f"Invalid or missing parameter: {exc}"}), 400

    out_dir = get_output_root() / name
    if not out_dir.exists():
        return jsonify({"error": "Map not found or not preprocessed"}), 404

    return jsonify(query_resources_in_region(out_dir, min_x, min_z, max_x, max_z))
