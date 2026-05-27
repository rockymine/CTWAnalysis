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
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from flask import Flask, Response, abort, jsonify, render_template, request, send_file, stream_with_context

from common.visualization.block_colors import block_color
from layout_analysis.wool_query import query_resources_in_region, query_wool_in_region
from map_viewer.services import region_editor, spawn_editor, team_editor, wool_editor
from map_viewer.services.config import get_output_root, load_config, save_config as _save_config
from map_viewer.services.map_data import load_map_data, save_map_data
from map_viewer.services.pipeline import check_pipeline_status, run_pipeline_steps
from map_viewer.services.region_editor import InvalidRegionPayload, RegionConflict, RegionNotFound
from map_viewer.services.region_tree import encode_region_tree_categorized
from map_viewer.services.region_xml import regions_to_xml
from map_viewer.services.regions import resolve_region_bounds
from map_viewer.services.spawn_editor import InvalidSpawnPayload, SpawnConflict, SpawnNotFound
from map_viewer.services.team_editor import InvalidTeamPayload, TeamConflict, TeamNotFound
from map_viewer.services.wool_editor import InvalidWoolPayload, WoolConflict, WoolNotFound
from map_viewer.services.wools import (
    collect_mob_entity_types,
    determine_respawn_type,
    find_pgm_spawner,
    find_relevant_renewables,
    wool_color_to_damage,
)


_METADATA_FIELDS = {
    "name", "version", "objective", "max_build_height", "gamemode",
    "phase", "authors", "symmetry_status",
}


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
        _save_config(body)
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
                try:
                    run_pipeline_steps(map_folder, map_output_dir, name, force, send)
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
        data, _ = load_map_data(name)
        return jsonify(data)

    @app.route("/api/map/<name>/metadata", methods=["PATCH"])
    def patch_map_metadata(name: str):
        data, data_path = load_map_data(name)
        payload = request.get_json(force=True)
        for key, value in payload.items():
            if key in _METADATA_FIELDS:
                data[key] = value
        save_map_data(data, data_path)
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
        data, _ = load_map_data(name)
        groups = encode_region_tree_categorized(
            data.get("regions", {}),
            data.get("region_categories", {}),
        )
        return jsonify(groups)

    @app.route("/api/map/<name>/export/xml")
    def export_xml(name: str):
        data, _ = load_map_data(name)
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

    @app.route("/api/map/<name>/regions", methods=["POST"])
    def create_region(name: str) -> tuple:
        body = request.get_json(silent=True) or {}
        data, data_path = load_map_data(name)
        try:
            result = region_editor.create_region(data, body)
        except InvalidRegionPayload as exc:
            return jsonify({"error": str(exc)}), 400
        except RegionConflict as exc:
            return jsonify({"error": str(exc)}), 409
        save_map_data(data, data_path)
        return jsonify({"ok": True, **result}), 201

    @app.route("/api/map/<name>/regions/group", methods=["POST"])
    def group_regions(name: str) -> tuple:
        body = request.get_json(silent=True) or {}
        data, data_path = load_map_data(name)
        try:
            result = region_editor.group_regions(data, body)
        except InvalidRegionPayload as exc:
            return jsonify({"error": str(exc)}), 400
        except RegionNotFound as exc:
            return jsonify({"error": str(exc)}), 404
        except RegionConflict as exc:
            return jsonify({"error": str(exc)}), 409
        save_map_data(data, data_path)
        return jsonify({"ok": True, **result}), 201

    @app.route("/api/map/<name>/region/<region_id>", methods=["DELETE"])
    def delete_region(name: str, region_id: str) -> tuple:
        data, data_path = load_map_data(name)
        try:
            result = region_editor.delete_region(data, region_id)
        except RegionNotFound as exc:
            return jsonify({"error": str(exc)}), 404
        save_map_data(data, data_path)
        return jsonify({"ok": True, **result})

    @app.route("/api/map/<name>/regions/restore", methods=["POST"])
    def restore_region(name: str) -> tuple:
        body     = request.get_json(silent=True) or {}
        snapshot = body.get("snapshot")
        if not snapshot:
            return jsonify({"error": "snapshot required"}), 400
        data, data_path = load_map_data(name)
        try:
            result = region_editor.restore_region(data, snapshot)
        except InvalidRegionPayload as exc:
            return jsonify({"error": str(exc)}), 400
        except RegionNotFound as exc:
            return jsonify({"error": str(exc)}), 404
        except RegionConflict as exc:
            return jsonify({"error": str(exc)}), 409
        save_map_data(data, data_path)
        return jsonify({"ok": True, **result})

    @app.route("/api/map/<name>/region/<region_id>", methods=["PATCH"])
    def patch_region(name: str, region_id: str) -> tuple:
        body = request.get_json(silent=True) or {}
        data, data_path = load_map_data(name)
        try:
            result = region_editor.patch_region(data, region_id, body)
        except InvalidRegionPayload as exc:
            return jsonify({"error": str(exc)}), 400
        except RegionNotFound as exc:
            return jsonify({"error": str(exc)}), 404
        except RegionConflict as exc:
            return jsonify({"error": str(exc)}), 409
        save_map_data(data, data_path)
        return jsonify({"ok": True, **result})

    # ── Team CRUD endpoints ───────────────────────────────────────────────────

    @app.route("/api/map/<name>/teams", methods=["POST"])
    def add_team(name: str) -> tuple:
        body = request.get_json(silent=True) or {}
        data, data_path = load_map_data(name)
        try:
            result = team_editor.add_team(data, body)
        except InvalidTeamPayload as exc:
            return jsonify({"error": str(exc)}), 400
        except TeamConflict as exc:
            return jsonify({"error": str(exc)}), 409
        save_map_data(data, data_path)
        return jsonify({"ok": True, **result}), 201

    @app.route("/api/map/<name>/teams/<team_id>", methods=["PATCH"])
    def update_team(name: str, team_id: str) -> tuple:
        body = request.get_json(silent=True) or {}
        data, data_path = load_map_data(name)
        try:
            result = team_editor.update_team(data, team_id, body)
        except TeamNotFound as exc:
            return jsonify({"error": str(exc)}), 404
        except TeamConflict as exc:
            return jsonify({"error": str(exc)}), 409
        save_map_data(data, data_path)
        return jsonify({"ok": True, **result})

    @app.route("/api/map/<name>/teams/<team_id>", methods=["DELETE"])
    def delete_team(name: str, team_id: str) -> tuple:
        data, data_path = load_map_data(name)
        try:
            team_editor.delete_team(data, team_id)
        except TeamNotFound as exc:
            return jsonify({"error": str(exc)}), 404
        save_map_data(data, data_path)
        return jsonify({"ok": True})

    # ── Spawn link endpoints ──────────────────────────────────────────────────

    @app.route("/api/map/<name>/spawns", methods=["POST"])
    def add_spawn_link(name: str) -> tuple:
        body = request.get_json(silent=True) or {}
        data, data_path = load_map_data(name)
        try:
            spawn_editor.add_spawn_link(data, body)
        except InvalidSpawnPayload as exc:
            return jsonify({"error": str(exc)}), 400
        except SpawnNotFound as exc:
            return jsonify({"error": str(exc)}), 404
        except SpawnConflict as exc:
            return jsonify({"error": str(exc)}), 409
        save_map_data(data, data_path)
        return jsonify({"ok": True}), 201

    @app.route("/api/map/<name>/spawn/<region_id>", methods=["PATCH"])
    def update_spawn_link(name: str, region_id: str) -> tuple:
        body = request.get_json(silent=True) or {}
        data, data_path = load_map_data(name)
        try:
            spawn_editor.update_spawn_link(data, region_id, body)
        except SpawnNotFound as exc:
            return jsonify({"error": str(exc)}), 404
        save_map_data(data, data_path)
        return jsonify({"ok": True})

    @app.route("/api/map/<name>/spawn/<region_id>", methods=["DELETE"])
    def delete_spawn_link(name: str, region_id: str) -> tuple:
        data, data_path = load_map_data(name)
        try:
            spawn_editor.delete_spawn_link(data, region_id)
        except SpawnNotFound as exc:
            return jsonify({"error": str(exc)}), 404
        save_map_data(data, data_path)
        return jsonify({"ok": True})

    # ── Wool endpoints ────────────────────────────────────────────────────────

    @app.route("/api/map/<name>/wools", methods=["POST"])
    def add_wool(name: str) -> tuple:
        body = request.get_json(silent=True) or {}
        data, data_path = load_map_data(name)
        try:
            result = wool_editor.add_wool(data, body)
        except InvalidWoolPayload as exc:
            return jsonify({"error": str(exc)}), 400
        except WoolConflict as exc:
            return jsonify({"error": str(exc)}), 409
        save_map_data(data, data_path)
        return jsonify({"ok": True, **result}), 201

    @app.route("/api/map/<name>/wool/<team_id>/<color>", methods=["PATCH"])
    def update_wool(name: str, team_id: str, color: str) -> tuple:
        body = request.get_json(silent=True) or {}
        data, data_path = load_map_data(name)
        try:
            result = wool_editor.update_wool(data, team_id, color, body)
        except WoolNotFound as exc:
            return jsonify({"error": str(exc)}), 404
        except WoolConflict as exc:
            return jsonify({"error": str(exc)}), 409
        save_map_data(data, data_path)
        return jsonify({"ok": True, **result})

    @app.route("/api/map/<name>/wool/<team_id>/<color>", methods=["DELETE"])
    def delete_wool(name: str, team_id: str, color: str) -> tuple:
        data, data_path = load_map_data(name)
        try:
            wool_editor.delete_wool(data, team_id, color)
        except WoolNotFound as exc:
            return jsonify({"error": str(exc)}), 404
        save_map_data(data, data_path)
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
        out_dir = get_output_root() / name
        data, _ = load_map_data(name)
        wools: list = data.get("wools", [])

        wool = next(
            (w for w in wools if w.get("team") == team_id and w.get("color") == color),
            None,
        )
        if wool is None:
            return jsonify({"error": f"wool ({team_id!r}, {color!r}) not found"}), 404

        wool_room_region = wool.get("wool_room_region")
        matched_spawner  = find_pgm_spawner(data, wool_room_region, wool_color_to_damage(color))

        chest_wool_count = 0
        block_wool_count = 0
        mob_spawners: list[dict] = []
        layout_result: dict = {}

        room_bounds = resolve_region_bounds(data, wool_room_region)
        if room_bounds is not None:
            min_x, min_z, max_x, max_z = room_bounds
            try:
                layout_result = query_wool_in_region(out_dir, min_x, min_z, max_x, max_z)
                chest_wool_count = len(layout_result.get("chest_wool", []))
                block_wool_count = len(layout_result.get("block_wool", []))
                mob_spawners     = layout_result.get("mob_spawners", [])
            except Exception:
                pass  # layout files may not exist; leave counts at zero

        mob_spawner_count    = len(mob_spawners)
        respawn_type         = determine_respawn_type(matched_spawner, mob_spawner_count, block_wool_count, chest_wool_count)
        mob_entity_types     = collect_mob_entity_types(mob_spawners)
        relevant_renewables  = find_relevant_renewables(data, wool_room_region, layout_result)
        relevant_drop_rules  = [
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
