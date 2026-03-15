"""
Layout layer case study — scatter plots coloured by block type.

Usage:
    python scripts/plot_layout_case_study.py
Outputs one PNG per map to output/<map>/layout_case_study.png
"""

from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from common.visualization import block_color, draw_layout_image

# ---------------------------------------------------------------------------
# Maps / layers
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


def _legend_patches(df: pd.DataFrame, max_entries: int = 15) -> list[mpatches.Patch]:
    """Build colour legend from the most common (block_id, block_data) pairs."""
    if 'block_id' not in df.columns:
        return []
    data_col = df['block_data'].values.astype(int) if 'block_data' in df.columns else np.zeros(len(df), int)
    pairs = list(zip(df['block_id'].values.astype(int), data_col))
    top = Counter(pairs).most_common(max_entries)
    patches = []
    for (bid, bdata), count in top:
        rgb = tuple(c / 255.0 for c in block_color(bid, bdata))
        label = f'ID {bid}' + (f':{bdata}' if bdata else '') + f'  ({count:,})'
        patches.append(mpatches.Patch(color=rgb, label=label))
    return patches


def plot_map(map_slug: str, map_label: str, output_dir: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(16, 14), layout='constrained')
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

        default_id = 7 if layer_key == 'layout_bedrock' else 0
        draw_layout_image(ax, df, default_block_id=default_id)

        patches = _legend_patches(df)
        if patches:
            ax.legend(handles=patches, loc='upper left',
                      bbox_to_anchor=(1.02, 1), borderaxespad=0,
                      fontsize=5, framealpha=0.85,
                      title='block id (count)', title_fontsize=5)

        if 'y' in df.columns:
            y_min, y_max = int(df['y'].min()), int(df['y'].max())
            ax.set_xlabel(f'X   (y range {y_min}–{y_max})')

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
