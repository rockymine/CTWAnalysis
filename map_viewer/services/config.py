from pathlib import Path

from flask import json

from map_viewer.constants import _DEFAULT_OUTPUT_ROOT, CONFIG_PATH

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