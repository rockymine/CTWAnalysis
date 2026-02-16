"""Common JSON export utilities.

Provides a shared numpy-aware JSON serializer and a standardized
save_json helper used by all analysis modules.
"""

import json
from pathlib import Path

import numpy as np


def numpy_json_default(obj):
    """JSON serializer for numpy types.

    Intended for use as the ``default`` argument to :func:`json.dump`.
    Handles numpy integers, floats, and ndarrays.
    """
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def save_json(data: dict, output_path, *, indent: int = 2) -> Path:
    """Save a dictionary to a JSON file.

    * Creates parent directories if they don't exist.
    * Uses :func:`numpy_json_default` so numpy scalars/arrays are
      transparently converted.

    Args:
        data: JSON-serializable dictionary.
        output_path: Destination file path (str or Path).
        indent: JSON indentation level (default 2).

    Returns:
        Resolved :class:`~pathlib.Path` of the written file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=indent, default=numpy_json_default)
    return output_path
