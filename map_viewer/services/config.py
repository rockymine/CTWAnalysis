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


def save_config(updates: dict) -> None:
    """Merge *updates* into the persisted config (only known keys are accepted)."""
    config = load_config()
    for key in ("maps_folder", "output_folder"):
        if key in updates:
            config[key] = str(updates[key]).strip()
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")