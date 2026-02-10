"""
JSON and data serialization helpers.

Dependency tier: standalone (only uses numpy).
"""

import numpy as np


def json_default(obj):
    """JSON serializer for numpy types.

    Use as: json.dump(data, f, default=json_default)
    """
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
