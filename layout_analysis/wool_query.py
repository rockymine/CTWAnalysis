"""Region-based wool detection: chests containing wool and wool blocks.

Used by the CTW authoring UI to determine, given a user-drawn rectangular
region, whether a wool objective is already configured (chest-based pickup),
needs to be broken as a block, or requires a spawner module.

Also provides a generic query for all resource block types (wool, iron, gold,
diamond) in a region, for configuring respawn modules.
"""

from pathlib import Path
import json
import pandas as pd

WOOL_COLORS: dict[int, str] = {
    0: 'white',      1: 'orange',     2: 'magenta',    3: 'light_blue',
    4: 'yellow',     5: 'lime',       6: 'pink',        7: 'gray',
    8: 'light_gray', 9: 'cyan',       10: 'purple',    11: 'blue',
    12: 'brown',     13: 'green',     14: 'red',        15: 'black',
}


def query_wool_in_region(
    output_dir: Path,
    min_x: float,
    min_z: float,
    max_x: float,
    max_z: float,
) -> dict:
    """Return wool chests, renewable wool blocks, and mob spawners in a bbox.

    Reads layout_chest_contents.parquet and layout_resource_blocks.parquet from
    output_dir.  Returns empty lists gracefully if either file is absent.

    Wool blocks (block_wool) are filtered to only those inside a region covered
    by a <renewable> rule, using bounds_2d data from map_data.json.  If no
    renewables are defined (or map_data.json is absent), all wool blocks in the
    bbox are returned.

    Returns:
        {
            'chest_wool': [{'x', 'z', 'y', 'color_id', 'color_name', 'count'}, ...],
            'block_wool': [{'x', 'z', 'y', 'color_id', 'color_name'}, ...],
            'mob_spawners': [{'x', 'z', 'y'}, ...],
            'summary': {
                'has_chest_wool':  bool,
                'has_block_wool':  bool,
                'has_mob_spawner': bool,
                'colors_found': [str, ...],   # sorted distinct color names
            },
        }
    """
    chest_wool   = _find_chest_wool(output_dir, min_x, min_z, max_x, max_z)
    all_block_wool = _find_block_wool(output_dir, min_x, min_z, max_x, max_z)
    mob_spawners = _find_mob_spawners(output_dir, min_x, min_z, max_x, max_z)

    # Filter wool blocks to those inside a renewable region.  If no renewables
    # are defined we return all wool blocks (conservative: shows the block exists).
    renewable_bounds = _load_renewable_region_bounds(output_dir)
    if renewable_bounds:
        block_wool = [
            w for w in all_block_wool
            if _point_in_any_bounds(w['x'], w['z'], renewable_bounds)
        ]
    else:
        block_wool = all_block_wool

    colors = sorted({r['color_name'] for r in chest_wool + block_wool})
    return {
        'chest_wool':   chest_wool,
        'block_wool':   block_wool,
        'mob_spawners': mob_spawners,
        'summary': {
            'has_chest_wool':  bool(chest_wool),
            'has_block_wool':  bool(block_wool),
            'has_mob_spawner': bool(mob_spawners),
            'colors_found':    colors,
        },
    }


def query_resources_in_region(
    output_dir: Path,
    min_x: float,
    min_z: float,
    max_x: float,
    max_z: float,
) -> dict:
    """Return all resource blocks and wool chests inside [min_x, max_x] × [min_z, max_z].

    Covers every type tracked by ResourceBlockExtractor (wool, iron_block,
    gold_block, mob_spawner, diamond_block) plus chests containing wool items.
    Designed for the region-inspector UI: a single call tells the editor everything
    about what needs to be configured in a selected area.

    Returns:
        {
            'chest_wool': [{'x', 'z', 'y', 'color_id', 'color_name', 'count'}, ...],
            'resource_blocks': [
                {'type': str, 'x', 'z', 'y',
                 'block_data': int,
                 # wool only:
                 'color_id': int, 'color_name': str},
                ...
            ],
            'summary': {
                'has_chest_wool': bool,
                'has_block_wool': bool,
                'types_found': [str, ...],       # sorted distinct resource_type values
                'wool_colors_found': [str, ...], # sorted distinct wool color names
            },
        }
    """
    chest_wool = _find_chest_wool(output_dir, min_x, min_z, max_x, max_z)
    resource_blocks = _find_all_resource_blocks(output_dir, min_x, min_z, max_x, max_z)

    types_found = sorted({b['type'] for b in resource_blocks})
    wool_blocks = [b for b in resource_blocks if b['type'] == 'wool']
    wool_colors = sorted(
        {r['color_name'] for r in chest_wool}
        | {b['color_name'] for b in wool_blocks if 'color_name' in b}
    )
    return {
        'chest_wool': chest_wool,
        'resource_blocks': resource_blocks,
        'summary': {
            'has_chest_wool':    bool(chest_wool),
            'has_block_wool':    bool(wool_blocks),
            'types_found':       types_found,
            'wool_colors_found': wool_colors,
        },
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _bbox_filter(df: pd.DataFrame, min_x: float, min_z: float, max_x: float, max_z: float) -> pd.DataFrame:
    return df[
        (df['world_x'] >= min_x) & (df['world_x'] <= max_x) &
        (df['world_z'] >= min_z) & (df['world_z'] <= max_z)
    ]


def _find_chest_wool(output_dir: Path, min_x: float, min_z: float, max_x: float, max_z: float) -> list[dict]:
    path = output_dir / 'layout_chest_contents.parquet'
    if not path.exists():
        return []
    df = pd.read_parquet(path)
    wool = _bbox_filter(df[df['item_id'] == 'minecraft:wool'], min_x, min_z, max_x, max_z)
    results = []
    for (wx, wz, wy), grp in wool.groupby(['world_x', 'world_z', 'y']):
        for _, row in grp.iterrows():
            color_id = int(row['item_damage']) & 0xF
            results.append({
                'x':          int(wx),
                'z':          int(wz),
                'y':          int(wy),
                'color_id':   color_id,
                'color_name': WOOL_COLORS.get(color_id, 'unknown'),
                'count':      int(row['count']),
            })
    return results


def _find_block_wool(output_dir: Path, min_x: float, min_z: float, max_x: float, max_z: float) -> list[dict]:
    path = output_dir / 'layout_resource_blocks.parquet'
    if not path.exists():
        return []
    df = pd.read_parquet(path)
    if 'resource_type' not in df.columns:
        return []
    wool = _bbox_filter(df[df['resource_type'] == 'wool'], min_x, min_z, max_x, max_z)
    has_block_data = 'block_data' in wool.columns
    results = []
    for _, row in wool.iterrows():
        entry: dict = {
            'x': int(row['world_x']),
            'z': int(row['world_z']),
            'y': int(row['y']),
        }
        if has_block_data:
            color_id = int(row['block_data']) & 0xF
            entry['color_id']   = color_id
            entry['color_name'] = WOOL_COLORS.get(color_id, 'unknown')
        results.append(entry)
    return results


def _find_mob_spawners(output_dir: Path, min_x: float, min_z: float, max_x: float, max_z: float) -> list[dict]:
    """Return mob spawner blocks (resource_type='mob_spawner') in the bbox.

    Only present in layout_resource_blocks.parquet files generated after
    mob_spawner (block ID 52) was added to DEFAULT_RESOURCE_BLOCKS.
    """
    path = output_dir / 'layout_resource_blocks.parquet'
    if not path.exists():
        return []
    df = pd.read_parquet(path)
    if 'resource_type' not in df.columns:
        return []
    spawners = _bbox_filter(df[df['resource_type'] == 'mob_spawner'], min_x, min_z, max_x, max_z)
    results = []
    for _, row in spawners.iterrows():
        results.append({
            'x': int(row['world_x']),
            'z': int(row['world_z']),
            'y': int(row['y']),
        })
    return results


def _find_all_resource_blocks(output_dir: Path, min_x: float, min_z: float, max_x: float, max_z: float) -> list[dict]:
    path = output_dir / 'layout_resource_blocks.parquet'
    if not path.exists():
        return []
    df = pd.read_parquet(path)
    filtered = _bbox_filter(df, min_x, min_z, max_x, max_z)
    has_block_data = 'block_data' in filtered.columns
    results = []
    for _, row in filtered.iterrows():
        bd = int(row['block_data']) & 0xF if has_block_data else 0
        entry: dict = {
            'type':       str(row['resource_type']),
            'x':          int(row['world_x']),
            'z':          int(row['world_z']),
            'y':          int(row['y']),
            'block_data': bd,
        }
        if entry['type'] == 'wool':
            entry['color_id']   = bd
            entry['color_name'] = WOOL_COLORS.get(bd, 'unknown')
        results.append(entry)
    return results


def _load_renewable_region_bounds(output_dir: Path) -> list[tuple[float, float, float, float]]:
    """Return a list of (min_x, min_z, max_x, max_z) bounding boxes for all
    renewable regions defined in map_data.json.

    Returns an empty list if map_data.json is absent, has no renewables, or
    if no renewable's region has a resolvable bounds_2d entry.
    """
    data_path = output_dir / 'map_data.json'
    if not data_path.exists():
        return []
    try:
        data = json.loads(data_path.read_text(encoding='utf-8'))
    except Exception:
        return []

    renewables = data.get('renewables', [])
    if not renewables:
        return []

    regions = data.get('regions', {})
    bounds_list: list[tuple[float, float, float, float]] = []
    for renewable in renewables:
        region_id = renewable.get('region_id', '')
        if not region_id:
            continue
        region = regions.get(region_id, {})
        bounds_2d = region.get('bounds_2d')
        if bounds_2d:
            min_x = bounds_2d['min']['x']
            min_z = bounds_2d['min']['z']
            max_x = bounds_2d['max']['x']
            max_z = bounds_2d['max']['z']
            bounds_list.append((min_x, min_z, max_x, max_z))

    return bounds_list


def _point_in_any_bounds(
    x: float,
    z: float,
    bounds_list: list[tuple[float, float, float, float]],
) -> bool:
    """Return True if (x, z) falls within any bounding box in bounds_list."""
    return any(
        min_x <= x <= max_x and min_z <= z <= max_z
        for min_x, min_z, max_x, max_z in bounds_list
    )
