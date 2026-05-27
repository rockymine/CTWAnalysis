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

from map_viewer.constants import CONFIG_PATH
from map_viewer.region_encoder import (
    encode_region_tree_categorized,
    regions_to_xml,
)
from common.visualization.block_colors import block_color

from map_viewer.services.config import get_output_root, load_config
from map_viewer.services.pipeline import check_pipeline_status
from map_viewer.services.region_tree import collect_region_subtree_ids, find_child_region, find_parent_of_child, patch_embedded_region, remove_inline_children, rename_embedded_region, rename_in_children
from map_viewer.services.spawns import spawn_region_id
from map_viewer.services.wools import wool_color_to_damage
from map_viewer.services.regions import apply_coord_update, resolve_region_bounds


class _QueueLogHandler(logging.Handler):
    """Forwards ctw logger records into the SSE event queue during a pipeline run."""

    def __init__(self, send_fn):
        super().__init__()
        self._send = send_fn

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._send("log", {"message": self.format(record), "level": record.levelname.lower()})
        except Exception:
            self.handleError(record)

logger = logging.getLogger("ctw")


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
        return jsonify(load_config())

    @app.route("/api/config", methods=["POST"])
    def save_config():
        body = request.get_json(silent=True) or {}
        config = load_config()
        for key in ("maps_folder", "output_folder"):
            if key in body:
                config[key] = str(body[key]).strip()
        CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
        return jsonify({"ok": True})

    # ── Source-map discovery API ─────────────────────────────────────────────

    @app.route("/api/source-maps")
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

    @app.route("/api/source-map/<name>/validate")
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

    @app.route("/api/source-map/<name>/thumbnail")
    def source_map_thumbnail(name: str):
        from flask import send_file
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

    @app.route("/api/source-map/<name>/pipeline-status")
    def pipeline_status(name: str):
        import time
        output_root = get_output_root()
        out_dir = output_root / name
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

    @app.route("/api/source-map/<name>/pipeline/run")
    def run_pipeline(name: str):
        force = request.args.get("force", "0") == "1"

        config = load_config()
        maps_folder_str = config.get("maps_folder", "").strip()
        if not maps_folder_str:
            return jsonify({"error": "maps_folder not configured"}), 400

        map_folder = Path(maps_folder_str) / name
        if not map_folder.exists():
            return jsonify({"error": f"Map folder not found: {name}"}), 404

        output_root = get_output_root()
        map_output_dir = output_root / name

        def generate():
            event_queue: queue.Queue[Optional[str]] = queue.Queue()

            def send(event_type: str, data: dict) -> None:
                msg = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                event_queue.put(msg)

            def pipeline_thread() -> None:
                _log_handler: Optional[_QueueLogHandler] = None
                try:
                    import traceback
                    from ctw.log import setup_map_file_logging
                    from map_analysis.pipeline import run_island_geometry, run_symmetry, assemble_map
                    from layout_analysis.pipeline import analyze_layout
                    from xml_analysis.pipeline import analyze_xml
                    from layout_analysis.map_layout_config import get_map_layout

                    map_output_dir.mkdir(parents=True, exist_ok=True)
                    setup_map_file_logging(map_output_dir)

                    _log_handler = _QueueLogHandler(send)
                    _log_handler.setLevel(logging.DEBUG)
                    _log_handler.setFormatter(logging.Formatter('%(message)s'))
                    logging.getLogger('ctw').addHandler(_log_handler)

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

                    # Step 1 — XML (runs first so max_build_height is available for layout)
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
                        # Non-fatal: continue without XML (layout will run without height cap)

                    # Step 2 — Layout (receives max_build_height from XML context)
                    send("step", {"step": "layout", "status": "running", "label": "Layout"})
                    try:
                        mbh = xml_context.map_data.max_build_height if xml_context else None
                        parquet_files = analyze_layout(
                            map_folder,
                            force_rerun=force,
                            output_dir=map_output_dir,
                            map_layout_config=map_layout_cfg,
                            max_build_height=mbh,
                        )
                        n = len(parquet_files) if parquet_files else 0
                        send("step", {"step": "layout", "status": "done", "label": "Layout",
                                      "detail": f"{n} file(s) written"})
                    except Exception as exc:
                        send("step", {"step": "layout", "status": "error", "label": "Layout",
                                      "detail": str(exc)})
                        send("error", {"message": f"Layout failed: {exc}"})
                        return

                    # Step 3 — Islands
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

                    # Step 4 — Symmetry
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
                    if _log_handler is not None:
                        logging.getLogger('ctw').removeHandler(_log_handler)
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

    # ── Minecraft player lookup (username ↔ UUID via Mojang API) ─────────────

    @app.route("/api/minecraft/player")
    def minecraft_player():
        """Resolve a Minecraft username → UUID or UUID → name via Mojang APIs.

        Query params (exactly one required):
          name=<username>  — calls api.mojang.com to get UUID
          uuid=<uuid>      — calls sessionserver to get canonical name
                             (checks uuid_name_cache first)
        Returns: { uuid, name }
        """
        import urllib.request
        import urllib.error
        from datetime import datetime as _dt

        username = request.args.get("name", "").strip()
        uuid_arg  = request.args.get("uuid", "").strip()

        if username:
            url = f"https://api.mojang.com/users/profiles/minecraft/{username}"
            try:
                with urllib.request.urlopen(url, timeout=5) as resp:
                    data = json.loads(resp.read())
            except urllib.error.HTTPError as exc:
                return jsonify({"error": "not_found"}), (404 if exc.code == 404 else 502)
            except Exception:
                return jsonify({"error": "upstream_error"}), 502

            raw_id = data.get("id", "")
            if len(raw_id) == 32:
                uuid = (f"{raw_id[:8]}-{raw_id[8:12]}-{raw_id[12:16]}-"
                        f"{raw_id[16:20]}-{raw_id[20:]}")
            else:
                uuid = raw_id
            name = data.get("name", username)

        elif uuid_arg:
            # Check cache first
            try:
                import duckdb as _duckdb
                _db = Path("match_analysis/metadata.db")
                if _db.exists():
                    _c = _duckdb.connect(str(_db), read_only=True)
                    cached = _c.execute(
                        "SELECT name FROM uuid_name_cache WHERE uuid = ?",
                        [uuid_arg.lower()],
                    ).fetchone()
                    _c.close()
                    if cached and cached[0]:
                        return jsonify({"uuid": uuid_arg, "name": cached[0]})
            except Exception:
                pass

            uuid_nodashes = uuid_arg.replace("-", "")
            url = f"https://sessionserver.mojang.com/session/minecraft/profile/{uuid_nodashes}"
            try:
                with urllib.request.urlopen(url, timeout=5) as resp:
                    data = json.loads(resp.read())
            except urllib.error.HTTPError as exc:
                return jsonify({"error": "not_found"}), (404 if exc.code == 404 else 502)
            except Exception:
                return jsonify({"error": "upstream_error"}), 502

            name = data.get("name", "")
            uuid = uuid_arg

        else:
            abort(400)

        # Cache result
        try:
            import duckdb as _duckdb
            _db = Path("match_analysis/metadata.db")
            if _db.exists():
                _c = _duckdb.connect(str(_db))
                _c.execute(
                    """INSERT INTO uuid_name_cache (uuid, name, fetched_at) VALUES (?, ?, ?)
                       ON CONFLICT (uuid) DO UPDATE
                       SET name = excluded.name, fetched_at = excluded.fetched_at""",
                    [uuid.lower(), name, _dt.now()],
                )
                _c.close()
        except Exception:
            pass

        return jsonify({"uuid": uuid, "name": name})

    # ── Editor map list (maps with map_context.json) ─────────────────────────

    @app.route("/api/maps")
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

    # ── Map data endpoints (used by editor) ──────────────────────────────────

    @app.route("/api/map/<name>/map-data")
    def map_data_raw(name: str):
        data_path = get_output_root() / name / "map_data.json"
        if not data_path.exists():
            abort(404)
        data = json.loads(data_path.read_text(encoding="utf-8"))
        return jsonify(data)

    _METADATA_FIELDS = {
        "name", "version", "objective", "max_build_height", "gamemode",
        "phase", "authors", "symmetry_status",
    }

    @app.route("/api/map/<name>/metadata", methods=["PATCH"])
    def patch_map_metadata(name: str):
        data_path = get_output_root() / name / "map_data.json"
        if not data_path.exists():
            abort(404)
        data = json.loads(data_path.read_text(encoding="utf-8"))
        payload = request.get_json(force=True)
        for key, value in payload.items():
            if key in _METADATA_FIELDS:
                data[key] = value
        data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return jsonify({"ok": True})

    @app.route("/api/map/<name>/symmetry")
    def map_symmetry(name: str):
        sym_path = get_output_root() / name / "symmetry.json"
        if not sym_path.exists():
            abort(404)
        return jsonify(json.loads(sym_path.read_text(encoding="utf-8")))

    @app.route("/api/map/<name>/context")
    def map_context(name: str):
        ctx_path = get_output_root() / name / "map_context.json"
        if not ctx_path.exists():
            abort(404)
        return jsonify(json.loads(ctx_path.read_text(encoding="utf-8")))

    @app.route("/api/map/<name>/regions")
    def map_regions(name: str):
        data_path = get_output_root() / name / "map_data.json"
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
        data_path = get_output_root() / name / "map_data.json"
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
            "xs":    df["world_x"].tolist(),
            "zs":    df["world_z"].tolist(),
            "colors": colors,
            "min_x": int(df["world_x"].min()), "min_z": int(df["world_z"].min()),
            "max_x": int(df["world_x"].max()), "max_z": int(df["world_z"].max()),
        })

    @app.route("/api/source-map/<name>/query/wool-in-region")
    def api_query_wool_in_region(name: str):
        """Return wool chests and wool blocks within a rectangular bounding box.

        Query params: min_x, min_z, max_x, max_z (all required, numeric).
        """
        from layout_analysis.wool_query import query_wool_in_region
        try:
            min_x = float(request.args["min_x"])
            min_z = float(request.args["min_z"])
            max_x = float(request.args["max_x"])
            max_z = float(request.args["max_z"])
        except (KeyError, ValueError) as exc:
            return jsonify({"error": f"Invalid or missing parameter: {exc}"}), 400

        out_dir = get_output_root() / name
        if not out_dir.exists():
            return jsonify({"error": "Map not found or not preprocessed"}), 404

        result = query_wool_in_region(out_dir, min_x, min_z, max_x, max_z)
        return jsonify(result)

    @app.route("/api/source-map/<name>/query/resources-in-region")
    def api_query_resources_in_region(name: str):
        """Return all resource blocks and wool chests within a rectangular bounding box.

        Covers wool blocks (with color), iron/gold/diamond blocks, and chests
        containing wool items.  Designed for the region-inspector UI so a single
        call reveals everything that needs configuring in a selected area.

        Query params: min_x, min_z, max_x, max_z (all required, numeric).
        """
        from layout_analysis.wool_query import query_resources_in_region
        try:
            min_x = float(request.args["min_x"])
            min_z = float(request.args["min_z"])
            max_x = float(request.args["max_x"])
            max_z = float(request.args["max_z"])
        except (KeyError, ValueError) as exc:
            return jsonify({"error": f"Invalid or missing parameter: {exc}"}), 400

        out_dir = get_output_root() / name
        if not out_dir.exists():
            return jsonify({"error": "Map not found or not preprocessed"}), 404

        result = query_resources_in_region(out_dir, min_x, min_z, max_x, max_z)
        return jsonify(result)

    _SUPPORTED_CREATE_TYPES = {"rectangle", "cuboid", "point", "block", "cylinder", "circle"}

    @app.route("/api/map/<name>/regions", methods=["POST"])
    def create_region(name: str) -> tuple:
        body = request.get_json(silent=True) or {}
        region_type = body.get("type", "rectangle")
        if region_type not in _SUPPORTED_CREATE_TYPES:
            return jsonify({"error": f"unsupported type '{region_type}'"}), 400

        data_path = get_output_root() / name / "map_data.json"
        if not data_path.exists():
            abort(404)

        data    = json.loads(data_path.read_text(encoding="utf-8"))
        regions = data.setdefault("regions", {})

        region_id = (body.get("id") or "").strip()
        if not region_id:
            prefix = region_type if region_type != "rectangle" else "region"
            i = 1
            while f"{prefix}_{i}" in regions:
                i += 1
            region_id = f"{prefix}_{i}"
        elif region_id in regions:
            return jsonify({"error": f"id {region_id!r} already in use"}), 409

        try:
            if region_type in ("rectangle", "cuboid"):
                min_x = int(round(float(body["min_x"])))
                min_z = int(round(float(body["min_z"])))
                max_x = int(round(float(body["max_x"])))
                max_z = int(round(float(body["max_z"])))
                new_region: dict = {
                    "id": region_id, "type": region_type,
                    "min_x": min_x, "min_z": min_z,
                    "max_x": max_x, "max_z": max_z,
                    "bounds_2d": {"min": {"x": min_x, "z": min_z}, "max": {"x": max_x, "z": max_z}},
                }
                if region_type == "cuboid":
                    new_region["min_y"] = int(round(float(body.get("min_y", 0))))
                    new_region["max_y"] = int(round(float(body.get("max_y", 256))))

            elif region_type in ("point", "block"):
                px = int(round(float(body["x"])))
                pz = int(round(float(body["z"])))
                py = int(round(float(body.get("y", 64))))
                if region_type == "block":
                    bounds_2d = {"min": {"x": px, "z": pz}, "max": {"x": px + 1, "z": pz + 1}}
                else:
                    bounds_2d = {"min": {"x": px - 0.5, "z": pz - 0.5},
                                 "max": {"x": px + 0.5, "z": pz + 0.5}}
                new_region = {
                    "id": region_id, "type": region_type,
                    "position": {"x": px, "y": py, "z": pz},
                    "bounds_2d": bounds_2d,
                }

            elif region_type == "cylinder":
                bx = float(body["base_x"])
                bz = float(body["base_z"])
                by = float(body.get("base_y", 64))
                r  = float(body["radius"])
                h  = float(body.get("height", 10))
                new_region = {
                    "id": region_id, "type": "cylinder",
                    "base": {"x": bx, "y": by, "z": bz},
                    "radius": r, "height": h,
                    "bounds_2d": {"min": {"x": bx - r, "z": bz - r},
                                  "max": {"x": bx + r, "z": bz + r}},
                }

            else:  # circle
                cx = float(body["center_x"])
                cz = float(body["center_z"])
                r  = float(body["radius"])
                new_region = {
                    "id": region_id, "type": "circle",
                    "center": {"x": cx, "z": cz},
                    "radius": r,
                    "bounds_2d": {"min": {"x": cx - r, "z": cz - r},
                                  "max": {"x": cx + r, "z": cz + r}},
                }

        except (KeyError, TypeError, ValueError) as exc:
            return jsonify({"error": f"Missing or invalid field: {exc}"}), 400

        regions[region_id] = new_region
        category = body.get("category", "other")
        data.setdefault("region_categories", {}).setdefault(category, []).append(region_id)

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

        data_path = get_output_root() / name / "map_data.json"
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
        data_path = get_output_root() / name / "map_data.json"
        if not data_path.exists():
            abort(404)
        data    = json.loads(data_path.read_text(encoding="utf-8"))
        regions = data.get("regions", {})

        if region_id in regions:
            # ── Top-level region ─────────────────────────────────────────────
            subtree_ids = collect_region_subtree_ids(regions, region_id)

            category = "other"
            for cat_name, cat_list in data.get("region_categories", {}).items():
                if region_id in cat_list:
                    category = cat_name
                    break

            region_entries = {rid: regions[rid] for rid in subtree_ids if rid in regions}

            for rid in subtree_ids:
                regions.pop(rid, None)
                for cat_list in data.get("region_categories", {}).values():
                    if rid in cat_list:
                        cat_list.remove(rid)
            remove_inline_children(regions, set(subtree_ids))
            data_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return jsonify({
                "ok": True,
                "snapshot": {
                    "root_id":        region_id,
                    "category":       category,
                    "region_entries": region_entries,
                },
            })

        # ── Inline-only child (synthetic baked id, not a top-level region) ──
        # Named children (e.g. orange-wool-room) are always top-level; only
        # pipeline-assigned synthetic ids (parent__n) land here.
        found = find_parent_of_child(regions, region_id)
        if found is None:
            return jsonify({"error": f"region {region_id!r} not found"}), 404

        parent_dict, child_dict, child_index = found
        remove_inline_children(regions, {region_id})
        data_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return jsonify({
            "ok": True,
            "snapshot": {
                "root_id":        region_id,
                "category":       None,
                "parent_id":      parent_dict.get("id"),
                "child_index":    child_index,
                "region_entries": {region_id: child_dict},
            },
        })

    @app.route("/api/map/<name>/regions/restore", methods=["POST"])
    def restore_region(name: str) -> tuple:
        body     = request.get_json(silent=True) or {}
        snapshot = body.get("snapshot")
        if not snapshot:
            return jsonify({"error": "snapshot required"}), 400

        root_id        = snapshot.get("root_id", "")
        category       = snapshot.get("category", "other")
        region_entries = snapshot.get("region_entries", {})

        if not root_id or not region_entries:
            return jsonify({"error": "invalid snapshot"}), 400

        data_path = get_output_root() / name / "map_data.json"
        if not data_path.exists():
            abort(404)

        data    = json.loads(data_path.read_text(encoding="utf-8"))
        regions = data.setdefault("regions", {})

        parent_id = snapshot.get("parent_id")
        if parent_id is not None:
            # ── Restore inline child ─────────────────────────────────────────
            parent_dict = regions.get(parent_id)
            if parent_dict is None:
                return jsonify({"error": f"parent region {parent_id!r} not found"}), 404
            child_dict  = region_entries.get(root_id)
            child_index = snapshot.get("child_index", 0)
            children = parent_dict.setdefault("children", [])
            children.insert(child_index, child_dict)
            data_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return jsonify({"ok": True, "id": root_id})

        # ── Restore top-level region ─────────────────────────────────────────
        conflicts = [rid for rid in region_entries if rid in regions]
        if conflicts:
            return jsonify({"error": f"id(s) already in use: {conflicts}"}), 409

        regions.update(region_entries)
        data.setdefault("region_categories", {}).setdefault(category, []).append(root_id)

        data_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return jsonify({"ok": True, "id": root_id})

    @app.route("/api/map/<name>/region/<region_id>", methods=["PATCH"])
    def patch_region(name: str, region_id: str) -> tuple:
        body   = request.get_json(silent=True) or {}
        bounds = body.get("bounds") if isinstance(body.get("bounds"), dict) else None
        coords = body.get("coords") if isinstance(body.get("coords"), dict) else None
        if not body.get("id") and bounds is None and coords is None:
            return jsonify({"error": "provide 'id', 'bounds', or 'coords'"}), 400

        data_path = get_output_root() / name / "map_data.json"
        if not data_path.exists():
            abort(404)

        data    = json.loads(data_path.read_text(encoding="utf-8"))
        regions = data.get("regions", {})

        # Top-level lookup first; fall back to recursive child search for synthetic ids.
        region = regions.get(region_id)
        is_top_level = region is not None
        if not is_top_level:
            region = find_child_region(regions, region_id)
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
                    rename_in_children(r, region_id, new_id)
                for container_key in ("spawns", "wools"):
                    rename_embedded_region(data.get(container_key, []), region_id, new_id)
                obs = data.get("observer_spawn")
                if obs:
                    rename_embedded_region([obs], region_id, new_id)
                region_id = new_id
                region = regions[region_id]

        # ── optional bounds update ────────────────────────────────────────────
        updated_bounds_2d = None
        if bounds:
            updated_bounds_2d = {
                "min": {"x": bounds["min_x"], "z": bounds["min_z"]},
                "max": {"x": bounds["max_x"], "z": bounds["max_z"]},
            }
            region["bounds_2d"] = updated_bounds_2d
            if is_top_level:
                patch_embedded_region(data.get("spawns", []), region_id, updated_bounds_2d)
                patch_embedded_region(data.get("wools", []), region_id, updated_bounds_2d)
                obs = data.get("observer_spawn")
                if obs:
                    patch_embedded_region([obs], region_id, updated_bounds_2d)

        # ── optional coords update ────────────────────────────────────────────
        if coords:
            region_type = region.get("type", "")
            updated_bounds_2d = apply_coord_update(region, region_type, coords)
            if updated_bounds_2d and is_top_level:
                patch_embedded_region(data.get("spawns", []), region_id, updated_bounds_2d)
                patch_embedded_region(data.get("wools", []), region_id, updated_bounds_2d)
                obs = data.get("observer_spawn")
                if obs:
                    patch_embedded_region([obs], region_id, updated_bounds_2d)

        data_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        response: dict = {"ok": True}
        if updated_bounds_2d:
            b = updated_bounds_2d
            response["bounds"] = {
                "min_x": b["min"]["x"], "min_z": b["min"]["z"],
                "max_x": b["max"]["x"], "max_z": b["max"]["z"],
            }
        return jsonify(response)

    # ── Team CRUD endpoints ───────────────────────────────────────────────────

    @app.route("/api/map/<name>/teams", methods=["POST"])
    def add_team(name: str) -> tuple:
        body = request.get_json(silent=True) or {}
        team_id = (body.get("id") or "").strip()
        if not team_id:
            return jsonify({"error": "id is required"}), 400

        data_path = get_output_root() / name / "map_data.json"
        if not data_path.exists():
            abort(404)

        data = json.loads(data_path.read_text(encoding="utf-8"))
        teams: list = data.setdefault("teams", [])

        if any(t.get("id") == team_id for t in teams):
            return jsonify({"error": f"team id {team_id!r} already in use"}), 409

        new_team = {
            "id":          team_id,
            "name":        body.get("name", team_id),
            "color":       body.get("color", "red"),
            "max_players": int(body.get("max_players", 20)),
            "min_players": int(body.get("min_players", 0)),
        }
        if body.get("dye_color"):
            new_team["dye_color"] = str(body["dye_color"])

        teams.append(new_team)
        data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return jsonify({"ok": True, "team": new_team}), 201

    @app.route("/api/map/<name>/teams/<team_id>", methods=["PATCH"])
    def update_team(name: str, team_id: str) -> tuple:
        body = request.get_json(silent=True) or {}
        data_path = get_output_root() / name / "map_data.json"
        if not data_path.exists():
            abort(404)

        data = json.loads(data_path.read_text(encoding="utf-8"))
        teams: list = data.setdefault("teams", [])

        team = next((t for t in teams if t.get("id") == team_id), None)
        if team is None:
            return jsonify({"error": f"team {team_id!r} not found"}), 404

        # Handle optional id rename
        new_id = (body.get("id") or "").strip()
        if new_id and new_id != team_id:
            if any(t.get("id") == new_id for t in teams if t is not team):
                return jsonify({"error": f"team id {new_id!r} already in use"}), 409
            # Update references in spawns
            for spawn in data.get("spawns", []):
                if spawn.get("team") == team_id:
                    spawn["team"] = new_id
            obs = data.get("observer_spawn")
            if obs and obs.get("team") == team_id:
                obs["team"] = new_id
            team["id"] = new_id

        for field in ("name", "color", "dye_color"):
            if field in body:
                team[field] = str(body[field])
        for field in ("max_players", "min_players"):
            if field in body:
                team[field] = int(body[field])

        data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return jsonify({"ok": True, "team": team})

    @app.route("/api/map/<name>/teams/<team_id>", methods=["DELETE"])
    def delete_team(name: str, team_id: str) -> tuple:
        data_path = get_output_root() / name / "map_data.json"
        if not data_path.exists():
            abort(404)

        data = json.loads(data_path.read_text(encoding="utf-8"))
        teams: list = data.setdefault("teams", [])

        if not any(t.get("id") == team_id for t in teams):
            return jsonify({"error": f"team {team_id!r} not found"}), 404

        data["teams"] = [t for t in teams if t.get("id") != team_id]
        # Remove spawns referencing this team
        data["spawns"] = [s for s in data.get("spawns", []) if s.get("team") != team_id]

        data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return jsonify({"ok": True})

    # ── Spawn link endpoints ──────────────────────────────────────────────────

    @app.route("/api/map/<name>/spawns", methods=["POST"])
    def add_spawn_link(name: str) -> tuple:
        """Create a spawn link connecting a region to a team + metadata."""
        body = request.get_json(silent=True) or {}
        region_id = (body.get("region_id") or "").strip()
        if not region_id:
            return jsonify({"error": "region_id is required"}), 400

        data_path = get_output_root() / name / "map_data.json"
        if not data_path.exists():
            abort(404)

        data = json.loads(data_path.read_text(encoding="utf-8"))
        spawns: list = data.setdefault("spawns", [])
        regions: dict = data.get("regions", {})

        if region_id not in regions:
            return jsonify({"error": f"region {region_id!r} not found"}), 404

        if any(spawn_region_id(s) == region_id for s in spawns):
            return jsonify({"error": f"spawn for region {region_id!r} already exists"}), 409

        region_obj = regions[region_id]
        new_spawn: dict = {
            "team":   str(body.get("team", "")),
            "kit":    str(body.get("kit", "")),
            "yaw":    float(body.get("yaw", 0.0)),
            "region": region_obj,
        }
        spawns.append(new_spawn)
        data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return jsonify({"ok": True}), 201

    @app.route("/api/map/<name>/spawn/<region_id>", methods=["PATCH"])
    def update_spawn_link(name: str, region_id: str) -> tuple:
        """Update team, yaw, and kit for the spawn linked to *region_id*."""
        body = request.get_json(silent=True) or {}
        data_path = get_output_root() / name / "map_data.json"
        if not data_path.exists():
            abort(404)

        data = json.loads(data_path.read_text(encoding="utf-8"))
        spawns: list = data.setdefault("spawns", [])

        spawn = next((s for s in spawns if _spawn_region_id(s) == region_id), None)
        if spawn is None:
            return jsonify({"error": f"no spawn for region {region_id!r}"}), 404

        if "team" in body:
            spawn["team"] = str(body["team"])
        if "yaw" in body:
            spawn["yaw"] = float(body["yaw"])
        if "kit" in body:
            spawn["kit"] = str(body["kit"])

        data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return jsonify({"ok": True})

    @app.route("/api/map/<name>/spawn/<region_id>", methods=["DELETE"])
    def delete_spawn_link(name: str, region_id: str) -> tuple:
        """Remove the spawn link for *region_id*."""
        data_path = get_output_root() / name / "map_data.json"
        if not data_path.exists():
            abort(404)

        data = json.loads(data_path.read_text(encoding="utf-8"))
        spawns: list = data.setdefault("spawns", [])

        if not any(_spawn_region_id(s) == region_id for s in spawns):
            return jsonify({"error": f"no spawn for region {region_id!r}"}), 404

        data["spawns"] = [s for s in spawns if _spawn_region_id(s) != region_id]
        data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return jsonify({"ok": True})

    # ── Wool endpoints ────────────────────────────────────────────────────────

    @app.route("/api/map/<name>/wools", methods=["POST"])
    def add_wool(name: str) -> tuple:
        """Create a new wool entry identified by (team, color)."""
        body = request.get_json(silent=True) or {}
        team_id = (body.get("team") or "").strip()
        color   = (body.get("color") or "").strip()
        if not team_id:
            return jsonify({"error": "team is required"}), 400
        if not color:
            return jsonify({"error": "color is required"}), 400

        data_path = get_output_root() / name / "map_data.json"
        if not data_path.exists():
            abort(404)

        data  = json.loads(data_path.read_text(encoding="utf-8"))
        wools: list = data.setdefault("wools", [])

        if any(w.get("team") == team_id and w.get("color") == color for w in wools):
            return jsonify({"error": f"wool ({team_id!r}, {color!r}) already exists"}), 409

        loc_raw = body.get("location") or {}
        mon_raw = body.get("monument") or {}
        new_wool = {
            "team":     team_id,
            "color":    color,
            "location": {
                "x": float(loc_raw.get("x", 0)),
                "y": float(loc_raw.get("y", 0)),
                "z": float(loc_raw.get("z", 0)),
            },
            "monument": {
                "x": float(mon_raw.get("x", 0)),
                "y": float(mon_raw.get("y", 0)),
                "z": float(mon_raw.get("z", 0)),
            },
        }
        wools.append(new_wool)
        data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return jsonify({"ok": True, "wool": new_wool}), 201

    @app.route("/api/map/<name>/wool/<team_id>/<color>", methods=["PATCH"])
    def update_wool(name: str, team_id: str, color: str) -> tuple:
        """Update a wool entry by its (team, color) composite key.

        If `location` is in the body, all entries sharing the same (color,
        old_location) are updated (room-level location change).  Other fields
        (team rename, color rename) apply only to the matched entry.
        """
        body = request.get_json(silent=True) or {}
        data_path = get_output_root() / name / "map_data.json"
        if not data_path.exists():
            abort(404)

        data  = json.loads(data_path.read_text(encoding="utf-8"))
        wools: list = data.setdefault("wools", [])

        wool = next(
            (w for w in wools if w.get("team") == team_id and w.get("color") == color),
            None,
        )
        if wool is None:
            return jsonify({"error": f"wool ({team_id!r}, {color!r}) not found"}), 404

        # ── location update: apply to all entries sharing (color, old_location) ──
        if "location" in body:
            loc_raw  = body["location"]
            new_loc  = {
                "x": float(loc_raw.get("x", 0)),
                "y": float(loc_raw.get("y", 0)),
                "z": float(loc_raw.get("z", 0)),
            }
            old_loc = wool["location"]
            for entry in wools:
                if (entry.get("color") == color
                        and entry.get("location") == old_loc):
                    entry["location"] = new_loc

        # ── team rename ──
        new_team = (body.get("team") or "").strip()
        if new_team and new_team != team_id:
            if any(w.get("team") == new_team and w.get("color") == wool.get("color")
                   for w in wools if w is not wool):
                return jsonify({"error": f"wool ({new_team!r}, {wool['color']!r}) already exists"}), 409
            wool["team"] = new_team

        # ── color rename ──
        new_color = (body.get("color") or "").strip()
        if new_color and new_color != wool.get("color"):
            if any(w.get("team") == wool.get("team") and w.get("color") == new_color
                   for w in wools if w is not wool):
                return jsonify({"error": f"wool ({wool['team']!r}, {new_color!r}) already exists"}), 409
            wool["color"] = new_color

        # ── wool_room_region update: apply to all entries sharing the same location ──
        # Explicit None in the body means "clear the assignment"; absent key means "no change".
        if "wool_room_region" in body:
            new_region_id = body["wool_room_region"]   # str | None
            current_loc = wool["location"]
            for entry in wools:
                if entry.get("location") == current_loc:
                    entry["wool_room_region"] = new_region_id

        data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return jsonify({"ok": True, "wool": wool})

    @app.route("/api/map/<name>/wool/<team_id>/<color>", methods=["DELETE"])
    def delete_wool(name: str, team_id: str, color: str) -> tuple:
        """Delete the single wool entry identified by (team, color)."""
        data_path = get_output_root() / name / "map_data.json"
        if not data_path.exists():
            abort(404)

        data  = json.loads(data_path.read_text(encoding="utf-8"))
        wools: list = data.setdefault("wools", [])

        if not any(w.get("team") == team_id and w.get("color") == color for w in wools):
            return jsonify({"error": f"wool ({team_id!r}, {color!r}) not found"}), 404

        data["wools"] = [
            w for w in wools
            if not (w.get("team") == team_id and w.get("color") == color)
        ]
        data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return jsonify({"ok": True})

    @app.route("/api/map/<name>/wool/<team_id>/<color>/room-status")
    def wool_room_status(name: str, team_id: str, color: str):
        """Return the respawn mechanism detected for a wool's room.

        Checks (in priority order):
          1. PGM spawner module  — <spawners> element in map_data.json
          2. Mob spawner block   — block ID 52 in layout_resource_blocks.parquet
          3. Renewable wool block — wool block in a <renewable> region
          4. Chest wool          — wool item in a chest inside the room
          5. unknown             — nothing detected

        The wool room bounding box is derived from the wool's wool_room_region
        field plus the region's bounds_2d stored in map_data.json.  If the
        region has no resolvable bounds (mirror/translate maps), only the
        XML-based checks (PGM spawner) are performed.

        Returns:
            {
                "respawn_type": str,        # one of the five labels above
                "pgm_spawner": dict | null, # spawner data if matched
                "chest_wool_count": int,
                "block_wool_count": int,
                "mob_spawner_count": int,
            }
        """
        from layout_analysis.wool_query import query_wool_in_region

        out_dir   = get_output_root() / name
        data_path = out_dir / "map_data.json"
        if not data_path.exists():
            abort(404)

        data  = json.loads(data_path.read_text(encoding="utf-8"))
        wools: list = data.get("wools", [])

        wool = next(
            (w for w in wools if w.get("team") == team_id and w.get("color") == color),
            None,
        )
        if wool is None:
            return jsonify({"error": f"wool ({team_id!r}, {color!r}) not found"}), 404

        # ── 1. PGM spawner check (XML-only, no layout files needed) ──────────
        wool_room_region = wool.get("wool_room_region")
        matched_spawner  = None
        wool_color_damage = wool_color_to_damage(color)

        for spawner in data.get("spawners", []):
            # Match by player_region == wool_room_region
            if wool_room_region and spawner.get("player_region") == wool_room_region:
                matched_spawner = spawner
                break
            # Fallback: spawner items include this wool color
            for item in spawner.get("items", []):
                if (item.get("material", "").lower() == "wool"
                        and item.get("damage") == wool_color_damage):
                    matched_spawner = spawner
                    break
            if matched_spawner:
                break

        # ── 2-4. Layout-based checks (require layout parquet files) ──────────
        chest_wool_count = 0
        block_wool_count = 0
        mob_spawners: list[dict] = []
        layout_result: dict = {}

        room_bounds = resolve_region_bounds(data, wool_room_region)
        if room_bounds is not None:
            min_x, min_z, max_x, max_z = room_bounds
            try:
                layout_result = query_wool_in_region(out_dir, min_x, min_z, max_x, max_z)
                chest_wool_count = len(layout_result.get("chest_wool",   []))
                block_wool_count = len(layout_result.get("block_wool",   []))
                mob_spawners     = layout_result.get("mob_spawners", [])
            except Exception:
                pass  # layout files may not exist; leave counts at zero

        mob_spawner_count = len(mob_spawners)

        # Collect a human-readable label per spawner type.
        # For Item-entity spawners (wool drops) prefer spawn_item_id over entity_id.
        mob_entity_labels: set[str] = set()
        for s in mob_spawners:
            item_id = s.get("spawn_item_id")  # e.g. 'minecraft:wool'
            entity_id = s.get("entity_id")    # e.g. 'Item', 'Zombie'
            if item_id:
                label = item_id.replace("minecraft:", "")
            elif entity_id:
                label = entity_id
            else:
                continue
            mob_entity_labels.add(label)
        mob_entity_types: list[str] = sorted(mob_entity_labels)

        # ── Determine primary respawn type by priority ────────────────────────
        if matched_spawner:
            respawn_type = "pgm_spawner"
        elif mob_spawner_count > 0:
            respawn_type = "mob_spawner"
        elif block_wool_count > 0:
            respawn_type = "renewable"
        elif chest_wool_count > 0:
            respawn_type = "chest"
        else:
            respawn_type = "unknown"

        # ── Renewables matching the wool room region ──────────────────────────
        # Return any renewable rules whose region_id matches the wool room, plus
        # any whose bounds_2d spatially contains a block_wool position.
        all_renewables: list[dict] = data.get("renewables", [])
        regions_dict: dict = data.get("regions", {})
        relevant_renewables: list[dict] = []
        seen_region_ids: set[str] = set()
        for ren in all_renewables:
            rid = ren.get("region_id", "")
            if rid in seen_region_ids:
                continue
            matched = rid == wool_room_region
            if not matched:
                # Check whether any block_wool falls inside this region
                region_bounds = regions_dict.get(rid, {}).get("bounds_2d")
                if region_bounds:
                    mn = region_bounds["min"]
                    mx_ = region_bounds["max"]
                    for bw in layout_result.get("block_wool", []):
                        if mn["x"] <= bw["x"] <= mx_["x"] and mn["z"] <= bw["z"] <= mx_["z"]:
                            matched = True
                            break
            if matched:
                relevant_renewables.append(ren)
                seen_region_ids.add(rid)

        # ── Block-drop rules matching the wool room region ────────────────────
        relevant_drop_rules: list[dict] = [
            rule for rule in data.get("block_drop_rules", [])
            if wool_room_region and rule.get("region_id") == wool_room_region
        ]

        return jsonify({
            "respawn_type":      respawn_type,
            "pgm_spawner":       matched_spawner,
            "chest_wool":        layout_result.get("chest_wool", []),
            "chest_wool_count":  chest_wool_count,
            "block_wool_count":  block_wool_count,
            "mob_spawners":      mob_spawners,
            "mob_spawner_count": mob_spawner_count,
            "mob_entity_types":  mob_entity_types,
            "renewables":        relevant_renewables,
            "block_drop_rules":  relevant_drop_rules,
        })

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
