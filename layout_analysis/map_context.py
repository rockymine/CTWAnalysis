"""
MapContext: aggregated map information dataclass.

Re-exports MapContext, build_map_context, and build_skeleton_dicts from
ctw.core.models for backward compatibility.
"""

from ctw.core.models.context import MapContext
from ctw.core.builders import (
    build_map_context,
    build_skeleton_dicts,
    json_default as _json_default,
)

__all__ = [
    "MapContext",
    "build_map_context",
    "build_skeleton_dicts",
]
