import json
from pathlib import Path

from flask import abort

from map_viewer.services.config import get_output_root


def load_map_data(name: str) -> tuple[dict, Path]:
    data_path = get_output_root() / name / "map_data.json"
    if not data_path.exists():
        abort(404)
    return json.loads(data_path.read_text(encoding="utf-8")), data_path


def save_map_data(data: dict, data_path: Path) -> None:
    data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
