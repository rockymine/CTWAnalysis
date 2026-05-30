"""
One-time migration: normalize legacy numeric item IDs in map_chest_contents.

Older CTW maps were built with Minecraft 1.7 or earlier world editors, so their
chest NBT stores item IDs as plain integers ("322", "35", etc.) instead of the
namespaced strings ("minecraft:golden_apple", "minecraft:wool") introduced in
1.8.  This script replaces every numeric item_id with its canonical namespaced
equivalent so that all queries and classifiers can use a single ID scheme.

After running this script, re-run `ctw maps chest-classify` to fix any chests
that were previously misclassified because their armor / weapon IDs were not
matched by the LIKE patterns in the classifier.

Usage (from repo root):
    python scripts/migrate_normalize_item_ids.py
"""

import json
import logging
from pathlib import Path

import duckdb

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "match_analysis" / "metadata.db"
ITEM_IDS_JSON = PROJECT_ROOT / "documents" / "minecraft_1_8_item_ids_clean.json"


def build_id_mapping(json_path: Path) -> dict[str, str]:
    """
    Return a mapping {numeric_id_str: namespaced_id} for every Minecraft 1.8.9
    item ID found in the reference JSON.  When multiple entries share the same
    numeric ID (e.g. potion variants), the first entry's namespaced name is used
    — the actual variant is already captured in the item_damage column.
    """
    with open(json_path, encoding="utf-8") as fh:
        entries = json.load(fh)

    mapping: dict[str, str] = {}
    for entry in entries:
        numeric_key = str(entry["minecraft_id"])
        if numeric_key not in mapping:
            mapping[numeric_key] = entry["minecraft_id_name"]
    return mapping


def main() -> None:
    id_map = build_id_mapping(ITEM_IDS_JSON)
    logger.info(f"Loaded {len(id_map)} numeric→namespaced ID mappings from JSON.")

    conn = duckdb.connect(str(DB_PATH))

    # Find which numeric IDs are actually present in the database
    present: list[tuple[str, int]] = conn.execute("""
        SELECT item_id, COUNT(*) AS slots
        FROM map_chest_contents
        WHERE TRY_CAST(item_id AS INTEGER) IS NOT NULL
        GROUP BY item_id
        ORDER BY CAST(item_id AS INTEGER)
    """).fetchall()

    if not present:
        logger.info("No numeric item IDs found — database is already normalized.")
        conn.close()
        return

    logger.info(f"Found {len(present)} distinct numeric item IDs across "
                f"{sum(s for _, s in present)} slots:")

    unknown: list[str] = []
    to_update: list[tuple[str, str, int]] = []  # (numeric_id, namespaced_id, slot_count)
    for numeric_id, slots in present:
        namespaced = id_map.get(numeric_id)
        if namespaced:
            to_update.append((numeric_id, namespaced, slots))
            logger.info(f"  {numeric_id:>6} -> {namespaced}  ({slots} slots)")
        else:
            unknown.append(numeric_id)
            logger.warning(f"  {numeric_id:>6} -> NOT FOUND in reference JSON  ({slots} slots)")

    if unknown:
        logger.warning(f"\n{len(unknown)} IDs could not be mapped and will be left unchanged.")

    if not to_update:
        logger.info("Nothing to update.")
        conn.close()
        return

    logger.info(f"\nUpdating {sum(s for _, _, s in to_update)} slots...")
    updated_total = 0
    for numeric_id, namespaced_id, _ in to_update:
        result = conn.execute(
            "UPDATE map_chest_contents SET item_id = ? WHERE item_id = ?",
            [namespaced_id, numeric_id],
        )
        updated_total += result.rowcount if hasattr(result, 'rowcount') else 0

    conn.close()
    logger.info(f"Done. Normalize {len(to_update)} ID types.")
    logger.info("Next step: run `python ctw.py maps chest-classify` to reclassify chests.")


if __name__ == "__main__":
    main()
