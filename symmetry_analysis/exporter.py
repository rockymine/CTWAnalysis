"""JSON exporter for symmetry analysis results.

Public API:
    save(result, output_path)  — write symmetry results to a JSON file
"""

from pathlib import Path
from typing import Dict

from json_export import save_json as _save_json


def save(result: Dict, output_path) -> Path:
    """Save symmetry analysis results to JSON.

    Args:
        result: Dict returned by :func:`detect_symmetry`.
        output_path: Destination file path.

    Returns:
        Path to the written file.
    """
    path = _save_json(result, output_path)
    print(f"  Saved JSON: {path}")
    return path
