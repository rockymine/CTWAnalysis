"""
Layout layer case study — scatter plots coloured by block type.

Usage:
    python scripts/plot_layout_case_study.py
Outputs one PNG per map to output/<map>/layout_case_study.png
"""

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ---------------------------------------------------------------------------
# Block colour table
# ---------------------------------------------------------------------------
# Base RGB colours from Minecraft's MapColor enum (1.8/1.9 source).
# Stained blocks (wool=35, stained glass=95, stained clay=159, carpet=171)
# use their damage value to select a colour from STAIN_COLORS.

STAIN_COLORS: dict[int, tuple[int, int, int]] = {
    0:  (221, 221, 221),   # white
    1:  (216, 127,  51),   # orange
    2:  (178,  76, 216),   # magenta
    3:  (102, 153, 216),   # light blue
    4:  (229, 229,  51),   # yellow
    5:  (127, 204,  25),   # lime
    6:  (242, 127, 165),   # pink
    7:  ( 76,  76,  76),   # gray
    8:  (153, 153, 153),   # light gray
    9:  ( 76, 127, 153),   # cyan
    10: (127,  63, 178),   # purple
    11: ( 51,  76, 178),   # blue
    12: (102,  76,  51),   # brown
    13: (102, 127,  51),   # green
    14: (153,  51,  51),   # red
    15: ( 25,  25,  25),   # black
}

# (block_id, block_data) → (r, g, b).  block_data=-1 means any data value.
_BLOCK_COLORS: dict[tuple[int, int], tuple[int, int, int]] = {}


def _add(bid: int, r: int, g: int, b: int, data: int = -1) -> None:
    _BLOCK_COLORS[(bid, data)] = (r, g, b)


def _add_stained(bid: int) -> None:
    for meta, rgb in STAIN_COLORS.items():
        _BLOCK_COLORS[(bid, meta)] = rgb
    _BLOCK_COLORS[(bid, -1)] = STAIN_COLORS[0]   # fallback: white


# Air / void — transparent (handled separately)
_add(0,  0,   0,   0)     # air

# Terrain
_add(1,  112, 112, 112)   # stone
_add(2,  127, 178,  56)   # grass
_add(3,  151,  94,  61)   # dirt
_add(4,  112, 112, 112)   # cobblestone
_add(7,   80,  80,  80)   # bedrock (slightly lighter than stone for contrast)
_add(9,   64,  64, 255)   # water (stationary)
_add(8,   64,  64, 255)   # water (flowing)
_add(10, 255,  90,   0)   # lava stationary
_add(11, 255,  90,   0)   # lava flowing
_add(12, 247, 214, 163)   # sand
_add(13, 150, 140, 130)   # gravel
_add(14, 143, 119,  72)   # gold ore (looks like stone+gold)
_add(15, 112, 112, 112)   # iron ore
_add(16, 112, 112, 112)   # coal ore
_add(17, 143, 119,  72)   # wood log
_add(18,   0, 124,   0)   # leaves
_add(19, 200, 200,  80)   # sponge
_add(20, 180, 210, 230)   # glass
_add(21,  51,  76, 178)   # lapis ore
_add(22,  74, 144, 226)   # lapis block
_add(24, 230, 200, 140)   # sandstone
_add(25, 143, 119,  72)   # note block
_add(26, 180, 100, 100)   # bed
_add(30, 220, 220, 220)   # cobweb
_add(31,   0, 160,   0)   # tall grass
_add(35,  -1,  -1,  -1)   # wool — stained (overridden below)
_add(36, 255,   0, 255)   # piston extension / block36 — vibrant magenta for visibility
_add(41, 250, 238,  77)   # gold block
_add(42, 200, 200, 210)   # iron block
_add(43, 120, 120, 120)   # stone double slab
_add(44, 120, 120, 120)   # stone slab
_add(45, 168,  70,  55)   # brick
_add(46, 255,  40,  40)   # TNT
_add(47, 143, 119,  72)   # bookshelf
_add(48, 100, 130, 100)   # mossy cobblestone
_add(49,  35,  20,  55)   # obsidian
_add(53, 143, 119,  72)   # oak stairs
_add(54, 143, 100,  50)   # chest
_add(55, 200,   0,   0)   # redstone wire
_add(57,  94, 237, 255)   # diamond block
_add(58, 143, 100,  50)   # crafting table
_add(61,  80,  80,  80)   # furnace
_add(67, 112, 112, 112)   # cobblestone stairs
_add(77, 112, 112, 112)   # stone button
_add(80, 240, 240, 255)   # snow block
_add(85, 143, 119,  72)   # oak fence
_add(87, 112,   2,   0)   # netherrack
_add(88, 100,  80,  50)   # soul sand
_add(89, 240, 200, 100)   # glowstone
_add(91, 240, 150,  20)   # jack o lantern
_add(95,  -1,  -1,  -1)   # stained glass — stained (overridden below)
_add(96, 143, 119,  72)   # trapdoor
_add(97, 112, 112, 112)   # monster egg
_add(98, 112, 112, 112)   # stone bricks
_add(103, 100, 170,  40)  # melon
_add(106,   0, 160,   0)  # vine
_add(107, 143, 119,  72)  # fence gate
_add(108, 168,  70,  55)  # brick stairs
_add(109, 112, 112, 112)  # stone brick stairs
_add(111,  60, 130,  40)  # lily pad
_add(112,  45,  20,  20)  # nether brick
_add(120,  80,  80,  40)  # end portal frame
_add(121, 220, 220, 180)  # end stone
_add(123, 100,  80,  40)  # redstone lamp off
_add(124, 240, 200, 100)  # redstone lamp on
_add(125, 143, 119,  72)  # wood double slab
_add(126, 143, 119,  72)  # wood slab
_add(128, 230, 200, 140)  # sandstone stairs
_add(129, 100, 200, 100)  # emerald ore
_add(130, 143, 100,  50)  # ender chest
_add(131, 143, 119,  72)  # tripwire hook
_add(133,   0, 200,  60)  # emerald block
_add(134, 110,  80,  50)  # spruce stairs
_add(135, 143, 119,  72)  # birch stairs
_add(136, 120,  80,  40)  # jungle stairs
_add(138,  80, 220, 240)  # beacon
_add(139, 112, 112, 112)  # cobblestone wall
_add(143, 143, 119,  72)  # wood button
_add(144, 100, 100, 100)  # mob head
_add(145, 200, 200, 210)  # anvil
_add(146, 143, 100,  50)  # trapped chest
_add(148, 200, 200, 210)  # heavy pressure plate
_add(155, 240, 235, 220)  # quartz block
_add(156, 240, 235, 220)  # quartz stairs
_add(159,  -1,  -1,  -1)  # stained hardened clay — stained (overridden below)
_add(160,  -1,  -1,  -1)  # stained glass pane — stained (overridden below)
_add(161,   0, 124,   0)  # acacia leaves
_add(162, 143, 119,  72)  # acacia/dark oak log
_add(163, 110,  80,  50)  # acacia stairs
_add(164, 110,  60,  30)  # dark oak stairs
_add(165, 200, 220,  80)  # slime block
_add(166, 255,   0,   0)  # barrier
_add(167, 200, 200, 210)  # iron trapdoor
_add(168,  66, 140, 120)  # prismarine
_add(169,  80, 220, 240)  # sea lantern
_add(170, 215, 185,  35)  # hay bale
_add(171,  -1,  -1,  -1)  # carpet — stained (overridden below)
_add(172, 160,  90,  40)  # hardened clay (uncoloured)
_add(173,  25,  25,  25)  # coal block
_add(174, 200, 220, 255)  # packed ice
_add(179, 230, 200, 140)  # red sandstone
_add(180, 230, 200, 140)  # red sandstone stairs
_add(181, 230, 200, 140)  # double red sandstone slab
_add(182, 230, 200, 140)  # red sandstone slab
_add(183, 110,  60,  30)  # spruce fence gate
_add(184, 190, 160, 100)  # birch fence gate
_add(185, 120,  80,  40)  # jungle fence gate
_add(186, 110,  60,  30)  # dark oak fence gate
_add(187, 143, 119,  72)  # acacia fence gate
_add(188, 110,  80,  50)  # spruce fence
_add(189, 190, 160, 100)  # birch fence
_add(190, 120,  80,  40)  # jungle fence
_add(191, 110,  60,  30)  # dark oak fence
_add(192, 143, 119,  72)  # acacia fence
_add(193, 190, 160, 100)  # spruce door
_add(196, 110,  60,  30)  # dark oak door

# Apply stained overrides
for _bid in (35, 95, 159, 160, 171):
    _add_stained(_bid)


def block_color(block_id: int, block_data: int) -> tuple[int, int, int]:
    """Return (r, g, b) for a block ID + data value."""
    key = (block_id, block_data)
    if key in _BLOCK_COLORS:
        return _BLOCK_COLORS[key]
    key2 = (block_id, -1)
    if key2 in _BLOCK_COLORS:
        return _BLOCK_COLORS[key2]
    # Unknown block: hash to a deterministic colour
    rng = np.random.default_rng(block_id * 1000 + block_data)
    return tuple(int(x) for x in rng.integers(80, 220, size=3))


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

LAYERS = [
    ('layout_y0',           'Y=0 layer'),
    ('layout_bedrock',      'Lowest bedrock'),
    ('layout_top_surface',  'Top surface'),
    ('layout_lowest_solid', 'Lowest solid'),
]

MAPS = [
    ('arabia',               'Arabia (baseline)'),
    ('super_mario_warp_zone','Super Mario Warp Zone'),
    ('bungee_coorde',        'BungEE Coordé'),
    ('dragons_hearth',       "Dragon's Hearth"),
    ('oumuamua',             'Oumuamua'),
]


def maps_with_matches(db_path: str = 'match_analysis/metadata.db') -> list[tuple[str, str]]:
    """Return (map_slug, map_name) for every map that has at least one match."""
    import duckdb
    con = duckdb.connect(db_path, read_only=True)
    rows = con.execute("""
        SELECT m.map_slug, m.map_name
        FROM maps m
        JOIN matches mt ON m.map_id = mt.map_id
        GROUP BY m.map_slug, m.map_name
        ORDER BY m.map_name
    """).fetchall()
    con.close()
    return [(slug, name) for slug, name in rows]


def _load_layer(map_slug: str, layer_key: str) -> pd.DataFrame | None:
    path = Path(f'output/{map_slug}/{layer_key}.parquet')
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if df.empty:
        return None
    return df


def _make_image(
    df: pd.DataFrame,
    default_block_id: int = 0,
) -> tuple[np.ndarray, list[float]]:
    """Build an RGBA image (H×W×4 uint8) from block data.

    Each block at integer index (x, z) occupies exactly one pixel, which
    covers the world-space square [x, x+1] × [z, z+1].

    Returns (rgba, extent) where extent=[x_min, x_max+1, z_max+1, z_min]
    is suitable for ``ax.imshow(..., origin='upper', extent=extent)``.
    """
    xs = df['world_x'].values.astype(int)
    zs = df['world_z'].values.astype(int)
    data_col = (df['block_data'].values.astype(int)
                if 'block_data' in df.columns
                else np.zeros(len(df), dtype=int))
    ids = (df['block_id'].values.astype(int)
           if 'block_id' in df.columns
           else np.full(len(df), default_block_id, dtype=int))

    x_min, x_max = int(xs.min()), int(xs.max())
    z_min, z_max = int(zs.min()), int(zs.max())

    rgba = np.full((z_max - z_min + 1, x_max - x_min + 1, 4), 255, dtype=np.uint8)

    rows = zs - z_min
    cols = xs - x_min
    rgb = np.array(
        [block_color(int(bid), int(dat)) for bid, dat in zip(ids, data_col)],
        dtype=np.uint8,
    )
    rgba[rows, cols, :3] = rgb

    # extent=[left, right, bottom, top] with origin='upper':
    # row 0 sits at z=z_min (top), row H-1 sits at z=z_max+1 (bottom).
    extent = [x_min, x_max + 1, z_max + 1, z_min]
    return rgba, extent


def _legend_patches(df: pd.DataFrame, max_entries: int = 15) -> list[mpatches.Patch]:
    """Build colour legend from the most common (block_id, block_data) pairs."""
    if 'block_id' not in df.columns:
        return []
    data_col = df['block_data'].values.astype(int) if 'block_data' in df.columns else np.zeros(len(df), int)
    pairs = list(zip(df['block_id'].values.astype(int), data_col))
    from collections import Counter
    top = Counter(pairs).most_common(max_entries)
    patches = []
    for (bid, bdata), count in top:
        rgb = tuple(c / 255.0 for c in block_color(bid, bdata))
        label = f'ID {bid}' + (f':{bdata}' if bdata else '') + f'  ({count:,})'
        patches.append(mpatches.Patch(color=rgb, label=label))
    return patches


def plot_map(map_slug: str, map_label: str, output_dir: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(16, 14))
    fig.suptitle(f'Layout layers — {map_label}', fontsize=14, fontweight='bold', y=0.98)

    for ax, (layer_key, layer_label) in zip(axes.flat, LAYERS):
        df = _load_layer(map_slug, layer_key)
        ax.set_title(layer_label, fontsize=10)
        ax.set_xlabel('X')
        ax.set_ylabel('Z')

        if df is None or df.empty:
            ax.text(0.5, 0.5, 'No data', transform=ax.transAxes,
                    ha='center', va='center', color='gray')
            continue

        # Default block_id for layers that don't store it (e.g. bedrock → 7)
        default_id = 7 if layer_key == 'layout_bedrock' else 0
        rgba, extent = _make_image(df, default_block_id=default_id)
        # origin='upper' puts z increasing downward; extent aligns each pixel
        # to exactly one 1×1 world-space block square.
        ax.imshow(rgba, origin='upper', extent=extent,
                  interpolation='nearest', aspect='equal')

        patches = _legend_patches(df)
        if patches:
            ax.legend(handles=patches, loc='upper left',
                      bbox_to_anchor=(1.02, 1), borderaxespad=0,
                      fontsize=5, framealpha=0.85,
                      title='block id (count)', title_fontsize=5)

        # x label: include height info if present
        if 'y' in df.columns:
            y_min, y_max = int(df['y'].min()), int(df['y'].max())
            ax.set_xlabel(f'X   (y range {y_min}–{y_max})')

    plt.tight_layout(rect=[0, 0, 0.85, 0.97])
    out_path = output_dir / 'layout_case_study.png'
    fig.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f'  Saved: {out_path}')


def _plot_one(args: tuple[str, str]) -> str:
    """Worker-safe wrapper — returns a status string."""
    map_slug, map_label = args
    out_dir = Path(f'output/{map_slug}')
    if not out_dir.exists():
        return f'SKIP {map_slug} (no output dir)'
    plot_map(map_slug, map_label, out_dir)
    return f'OK   {map_slug}'


def main() -> None:
    import argparse
    from concurrent.futures import ProcessPoolExecutor, as_completed

    parser = argparse.ArgumentParser(description='Plot layout layer case studies')
    parser.add_argument('--all-matches', action='store_true',
                        help='Plot every map that has matches in the database')
    parser.add_argument('--workers', type=int, default=4,
                        help='Parallel workers (default: 4)')
    args = parser.parse_args()

    if args.all_matches:
        map_list = maps_with_matches()
        print(f'Found {len(map_list)} maps with matches')
    else:
        map_list = MAPS

    if args.workers > 1 and len(map_list) > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(_plot_one, item): item for item in map_list}
            for i, future in enumerate(as_completed(futures), 1):
                status = future.result()
                print(f'[{i:3d}/{len(map_list)}] {status}')
    else:
        for i, item in enumerate(map_list, 1):
            status = _plot_one(item)
            print(f'[{i:3d}/{len(map_list)}] {status}')

    print('Done.')


if __name__ == '__main__':
    main()
