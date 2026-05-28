from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from typing import Optional

from flask import Blueprint, Response, abort, jsonify, request, send_file, stream_with_context

import pandas as pd
from layout_analysis.wool_query import query_resources_in_region, query_wool_in_region
from common.visualization.block_colors import block_color
from layout_analysis.map_layout_config import load_map_layouts
from map_viewer.services.config import get_output_root, load_config
from map_viewer.services.pipeline import check_pipeline_status, run_layout_only_steps, run_pipeline_steps

bp = Blueprint("source_maps", __name__, url_prefix="/api")


def _load_materials() -> dict[int, str]:
    path = Path(__file__).parent.parent.parent / "materials.txt"
    result: dict[int, str] = {}
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if ":" not in line:
                    continue
                bid_str, name = line.split(":", 1)
                result[int(bid_str)] = name
    except FileNotFoundError:
        pass
    return result


_MATERIALS: dict[int, str] = _load_materials()


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
    all_layouts = load_map_layouts()
    maps = []
    for path in sorted(maps_folder.iterdir()):
        if not path.is_dir():
            continue
        out_dir = output_root / path.name
        steps = check_pipeline_status(out_dir)
        all_done = all(s["done"] for s in steps)
        layout_cfg = all_layouts.get(path.name)
        configured = layout_cfg is not None and not layout_cfg.skip and bool(layout_cfg.layer)
        maps.append({
            "name": path.name,
            "display_name": path.name.replace("_", " ").title(),
            "preprocessed": all_done,
            "configured": configured,
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
    steps_param = request.args.get("steps", "")

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
                if steps_param == "layout_all":
                    run_layout_only_steps(map_folder, map_output_dir, force, send)
                else:
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


@bp.route("/source-map/<name>/layout-layers")
def layout_layers(name: str):
    out_dir = get_output_root() / name
    # (filename, fixed_block_id_or_None)
    # bedrock parquet omits block_id since it's always 7 (bedrock)
    layer_files = {
        "y0":           ("layout_y0.parquet",           None),
        "bedrock":      ("layout_bedrock.parquet",      7),
        "lowest_solid": ("layout_lowest_solid.parquet", None),
        "top_surface":  ("layout_top_surface.parquet",  None),
    }
    result = {}
    for key, (filename, fixed_block_id) in layer_files.items():
        parquet_path = out_dir / filename
        if not parquet_path.exists():
            result[key] = None
            continue
        if fixed_block_id is not None:
            df = pd.read_parquet(parquet_path, columns=["world_x", "world_z", "block_data"])
            bdata_vals = df["block_data"].astype(int)
            color_cache: dict[int, str] = {
                bdat: "#{:02x}{:02x}{:02x}".format(*block_color(fixed_block_id, bdat))
                for bdat in bdata_vals.unique()
            }
            colors = [color_cache[bdat] for bdat in bdata_vals]
            unique_bids = [fixed_block_id]
        else:
            df = pd.read_parquet(parquet_path, columns=["world_x", "world_z", "block_id", "block_data"])
            bid_vals  = df["block_id"].astype(int)
            bdat_vals = df["block_data"].astype(int)
            unique_pairs = set(zip(bid_vals, bdat_vals))
            color_cache = {
                (bid, bdat): "#{:02x}{:02x}{:02x}".format(*block_color(bid, bdat))
                for bid, bdat in unique_pairs
            }
            colors = [color_cache[(bid, bdat)] for bid, bdat in zip(bid_vals, bdat_vals)]
            unique_bids = sorted(int(x) for x in bid_vals.unique())
        unique_blocks = [
            {
                "id":    bid,
                "name":  _MATERIALS.get(bid, f"Block {bid}"),
                "color": "#{:02x}{:02x}{:02x}".format(*block_color(bid, 0)),
            }
            for bid in unique_bids
        ]
        result[key] = {
            "xs":     df["world_x"].tolist(),
            "zs":     df["world_z"].tolist(),
            "colors": colors,
            "min_x": int(df["world_x"].min()), "max_x": int(df["world_x"].max()),
            "min_z": int(df["world_z"].min()), "max_z": int(df["world_z"].max()),
            "unique_blocks": unique_blocks,
        }
    return jsonify(result)


@bp.route("/source-map/<name>/observer-island-hint")
def observer_island_hint(name: str):
    """Return the island_id most likely containing the observer spawn, or null.

    Uses the observer_spawn bounds from map_data.json and finds the nearest
    island centroid in map_context.json.  Returns null if either file is absent
    or no observer spawn is defined.
    """
    out_dir = get_output_root() / name
    map_data_path = out_dir / "map_data.json"
    context_path  = out_dir / "map_context.json"

    if not map_data_path.exists() or not context_path.exists():
        return jsonify({"island_id": None})

    try:
        map_data_raw = json.loads(map_data_path.read_text(encoding="utf-8"))
        context_raw  = json.loads(context_path.read_text(encoding="utf-8"))
    except Exception:
        return jsonify({"island_id": None})

    observer_spawn = map_data_raw.get("observer_spawn")
    if not observer_spawn:
        return jsonify({"island_id": None})

    region = observer_spawn.get("region") or {}
    bounds = region.get("bounds_2d")
    if not bounds:
        return jsonify({"island_id": None})

    try:
        mn = bounds["min"]
        mx = bounds["max"]
        cx = (mn["x"] + mx["x"]) / 2.0
        cz = (mn["z"] + mx["z"]) / 2.0
    except Exception:
        return jsonify({"island_id": None})

    islands = context_raw.get("islands", [])
    if not islands:
        return jsonify({"island_id": None})

    best_id: Optional[int] = None
    best_dist = float("inf")
    for island in islands:
        center = island.get("center")
        if not center or len(center) < 2:
            continue
        dx = center[0] - cx
        dz = center[1] - cz
        dist = dx * dx + dz * dz
        if dist < best_dist:
            best_dist = dist
            best_id = island.get("id")

    return jsonify({"island_id": best_id})


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
