"""Per-map layout configuration loaded from map_layouts.json.

Provides access to the decided extraction layer and block exclusion list
for each map.  Maps marked skip=true should be excluded from the pipeline.
"""

import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_SAVE_LOCK = threading.Lock()

_DEFAULT_CONFIG_PATH = Path('map_layouts.json')

# Valid layer names accepted in the config
VALID_LAYERS = frozenset({'y0', 'bedrock', 'lowest_solid', 'top_surface'})


@dataclass
class MapLayoutConfig:
    """Layout configuration for a single map."""
    layer: str                              # extraction mode: y0 | bedrock | lowest_solid | top_surface
    exclude: list[int] = field(default_factory=list)
    skip: bool = False
    exclude_islands: list[int] = field(default_factory=list)
    # Island IDs to exclude from symmetry analysis (scenery, extra observer
    # platforms, etc.).  Set via the configure page after visually reviewing
    # detected islands.
    playable_bbox: Optional[tuple[float, float, float, float]] = None
    # (min_x, min_z, max_x, max_z) — islands whose center falls outside
    # this box are excluded from symmetry analysis.


def load_map_layouts(config_path: Optional[Path] = None) -> dict[str, MapLayoutConfig]:
    """Load all per-map layout configs from map_layouts.json.

    Args:
        config_path: Path to map_layouts.json.  Defaults to map_layouts.json
                     in the current working directory.

    Returns:
        Dict mapping map slug → MapLayoutConfig.  Empty dict if the file is
        absent or contains no maps.
    """
    path = config_path or _DEFAULT_CONFIG_PATH
    if not path.exists():
        return {}

    with open(path, 'r', encoding='utf-8') as fh:
        raw: Any = json.load(fh)

    if not isinstance(raw, dict) or 'maps' not in raw:
        return {}

    maps_raw = raw['maps']
    if not isinstance(maps_raw, dict):
        return {}

    configs: dict[str, MapLayoutConfig] = {}
    for slug, entry in maps_raw.items():
        if not isinstance(entry, dict):
            continue
        if entry.get('skip', False):
            configs[slug] = MapLayoutConfig(layer='', skip=True)
            continue
        layer = str(entry.get('layer', ''))
        if layer not in VALID_LAYERS:
            continue
        exclude_raw = entry.get('exclude', []) or []
        exclude = [int(v) for v in exclude_raw]
        exclude_islands_raw = entry.get('exclude_islands', []) or []
        exclude_islands = [int(v) for v in exclude_islands_raw]
        bbox_raw = entry.get('playable_bbox')
        playable_bbox: Optional[tuple[float, float, float, float]] = (
            tuple(float(v) for v in bbox_raw) if bbox_raw else None  # type: ignore[assignment]
        )
        configs[slug] = MapLayoutConfig(
            layer=layer,
            exclude=exclude,
            exclude_islands=exclude_islands,
            playable_bbox=playable_bbox,
        )

    return configs


def get_map_layout(
    map_name: str,
    config_path: Optional[Path] = None,
) -> Optional[MapLayoutConfig]:
    """Return the layout config for *map_name*, or None if not configured.

    Args:
        map_name: Map slug (e.g. ``'tumbleweed'``).
        config_path: Optional override path to map_layouts.json.

    Returns:
        MapLayoutConfig if the map appears in map_layouts.json, else None.
    """
    return load_map_layouts(config_path).get(map_name)


def save_map_layout(
    name: str,
    cfg: dict,
    config_path: Optional[Path] = None,
) -> None:
    """Write or update the layout config entry for *name* in map_layouts.json.

    Args:
        name: Map slug.
        cfg: Dict with keys from the JSON schema (layer, exclude, skip,
             exclude_islands, playable_bbox).  Written as-is; caller is
             responsible for valid values.
        config_path: Optional override path.  Defaults to map_layouts.json.
    """
    path = config_path or _DEFAULT_CONFIG_PATH
    with _SAVE_LOCK:
        if path.exists():
            with open(path, 'r', encoding='utf-8') as fh:
                raw: Any = json.load(fh)
            if not isinstance(raw, dict):
                raw = {}
        else:
            raw = {}

        if 'maps' not in raw or not isinstance(raw['maps'], dict):
            raw['maps'] = {}

        raw['maps'][name] = cfg

        text = json.dumps(raw, indent=2) + '\n'
        tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
        try:
            with os.fdopen(tmp_fd, 'w', encoding='utf-8') as fh:
                fh.write(text)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
