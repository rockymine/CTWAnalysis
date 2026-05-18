"""Region-based wool detection: chests containing wool and wool blocks.

Used by the CTW authoring UI to determine, given a user-drawn rectangular
region, whether a wool objective is already configured (chest-based pickup),
needs to be broken as a block, or requires a spawner module.

Also provides a generic query for all resource block types (wool, iron, gold,
diamond) in a region, for configuring respawn modules.
"""

from pathlib import Path
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
    """Return wool chests and wool blocks found inside [min_x, max_x] × [min_z, max_z].

    Reads layout_chest_contents.parquet and layout_resource_blocks.parquet from
    output_dir.  Returns empty lists gracefully if either file is absent.

    Returns:
        {
            'chest_wool': [{'x', 'z', 'y', 'color_id', 'color_name', 'count'}, ...],
            'block_wool': [{'x', 'z', 'y', 'color_id', 'color_name'}, ...],
            'summary': {
                'has_chest_wool': bool,
                'has_block_wool': bool,
                'colors_found': [str, ...],   # sorted distinct color names
            },
        }
    """
    chest_wool = _find_chest_wool(output_dir, min_x, min_z, max_x, max_z)
    block_wool = _find_block_wool(output_dir, min_x, min_z, max_x, max_z)
    colors = sorted({r['color_name'] for r in chest_wool + block_wool})
    return {
        'chest_wool': chest_wool,
        'block_wool': block_wool,
        'summary': {
            'has_chest_wool': bool(chest_wool),
            'has_block_wool': bool(block_wool),
            'colors_found':   colors,
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
    gold_block, diamond_block) plus chests containing wool items.  Designed
    for the region-inspector UI: a single call tells the editor everything
    about what needs to be configured for a selected area.

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
