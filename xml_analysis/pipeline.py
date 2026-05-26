"""XML analysis pipeline — step 1 of the map analysis pipeline."""

import logging
from pathlib import Path
from typing import Optional

from .datatypes import MapXmlContext
from .builder import MapXMLParser
from . import exporter as map_data_exporter

logger = logging.getLogger('ctw')


def analyze_xml(
    map_folder: Path,
    force_rerun: bool = False,
    output_dir: Optional[Path] = None,
) -> Optional[MapXmlContext]:
    """Step 1: Parse XML configuration and return a typed pipeline object.

    Always parses map.xml and returns a MapXmlContext for downstream
    pipeline stages.  The JSON artifact (map_data.json) is written as a
    side-effect only when it does not already exist or force_rerun is set;
    it is for human inspection and is not read back by any pipeline step.

    Args:
        map_folder: Path to map folder (read-only input).
        force_rerun: If True, overwrite outputs even if they exist.
        output_dir: Where to write outputs (default: map_folder).

    Returns:
        MapXmlContext on success, None if map.xml is missing or unparseable.
    """
    out = Path(output_dir) if output_dir else map_folder

    logger.debug(f"[1/5] XML Analysis: {map_folder.name}")

    xml_file = map_folder / 'map.xml'
    json_file = out / 'map_data.json'

    if not xml_file.exists():
        logger.debug(f"  No XML file found at {xml_file}")
        return None

    logger.debug(f"  Parsing XML: {xml_file.name}")

    try:
        parser = MapXMLParser(str(xml_file))
        map_data = parser.parse()
        parser.inject_anonymous_region_ids(map_data)
        categories = parser.identify_region_categories(map_data)
    except Exception as e:
        logger.warning(f"  Failed to parse XML: {e}")
        return None

    # Write JSON artifact (skip if already up-to-date)
    if force_rerun or not json_file.exists():
        # Serialise first so the detection helpers can work on the plain-dict
        # representation (same form used by zone_classifier at runtime).
        data_dict = map_data_exporter.to_dict(map_data, categories)

        # Detect wool room regions and embed in the serialised dict.
        # Priority: spawner player_region → chest spatial search → wool location search.
        _assign_wool_room_regions(data_dict, output_dir=out)

        # Propagate detected region IDs back onto the in-memory Wool objects so
        # that downstream pipeline stages see up-to-date data without re-reading
        # the JSON file.
        for wool_dict, wool_obj in zip(data_dict['wools'], map_data.wools):
            wool_obj.wool_room_region = wool_dict.get('wool_room_region')

        from common.json_export import save_json as _save_json
        _save_json(data_dict, str(json_file))
        logger.debug(f"    Saved {json_file.name}")
    else:
        logger.debug(f"  Map data already exists: {json_file.name}")

    n_spawners = len(map_data.spawners)
    n_resolved = sum(1 for w in map_data.wools if w.wool_room_region is not None)
    logger.debug(
        f"  Teams: {len(map_data.teams)}, Spawns: {len(map_data.spawns)}, "
        f"Wools: {len(map_data.wools)}, Regions: {len(map_data.regions)}, "
        f"Spawners: {n_spawners}, WoolRooms: {n_resolved}/{len(map_data.wools)}"
    )

    return MapXmlContext(map_data=map_data, region_categories=categories)


def _assign_wool_room_regions(data_dict: dict, output_dir: Path) -> None:
    """Run wool room detection on the serialised map data dict in-place."""
    from layout_analysis.features.zone_classifier import assign_wool_room_regions

    assign_wool_room_regions(
        wools=data_dict.get('wools', []),
        regions=data_dict.get('regions', {}),
        spawners=data_dict.get('spawners', []),
        output_dir=output_dir,
    )
