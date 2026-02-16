"""JSON exporter for symmetry analysis results."""

from pathlib import Path
from typing import Dict

from json_export import save_json


def save_symmetry_json(result: Dict, output_path) -> Path:
    """Save symmetry analysis results to JSON.

    Args:
        result: Dict returned by :func:`detect_symmetry`.
        output_path: Destination file path.

    Returns:
        Path to the written file.
    """
    path = save_json(result, output_path)
    print(f"  Saved JSON: {path}")
    return path
