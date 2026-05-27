from pathlib import Path

import json

from map_viewer.constants import _DEFAULT_OUTPUT_ROOT, CONFIG_PATH

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "maps_folder": "",
        "output_folder": str(_DEFAULT_OUTPUT_ROOT),
    }


def get_output_root() -> Path:
    cfg = load_config()
    folder = cfg.get("output_folder", "").strip()
    return Path(folder) if folder else _DEFAULT_OUTPUT_ROOT