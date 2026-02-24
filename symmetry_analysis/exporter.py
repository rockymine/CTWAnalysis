"""JSON exporter for symmetry analysis results.

Public API:
    save(result, output_path)  — write symmetry results to a JSON file
"""

import logging
from pathlib import Path

from common.json_export import save_json as _save_json
from symmetry_analysis.datatypes import SymmetryResult

logger = logging.getLogger('ctw')


def save(result: SymmetryResult, output_path) -> Path:
    """Save symmetry analysis results to JSON.

    Args:
        result: SymmetryResult returned by :func:`detect_symmetry`.
        output_path: Destination file path.

    Returns:
        Path to the written file.
    """
    path = _save_json(result.to_dict(), output_path)
    logger.debug(f"  Saved: {path}")
    return path
