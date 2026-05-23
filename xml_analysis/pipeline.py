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
        map_data_exporter.save(map_data, str(json_file), categories)
        logger.debug(f"    Saved {json_file.name}")
    else:
        logger.debug(f"  Map data already exists: {json_file.name}")

    logger.debug(f"  Teams: {len(map_data.teams)}, Spawns: {len(map_data.spawns)}, "
                 f"Wools: {len(map_data.wools)}, Regions: {len(map_data.regions)}")

    return MapXmlContext(map_data=map_data, region_categories=categories)
