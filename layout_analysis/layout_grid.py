"""Layout layer grid visualization — 2×2 panel of all four layout layers.

Public entry point:
    run(args: argparse.Namespace) -> None

Expected args attributes:
    map          (str | None) – single map name, or None when --all-matches
    all_matches  (bool)       – plot every map that has matches in the DB
    workers      (int)        – parallel worker count (only used with --all-matches)
    output       (str)        – root output directory (default: output)
"""

import sys
from pathlib import Path


_LAYERS = [
    ('layout_y0',           'Y=0 layer'),
    ('layout_bedrock',      'Lowest bedrock'),
    ('layout_top_surface',  'Top surface'),
    ('layout_lowest_solid', 'Lowest solid'),
]


def run(args: object) -> None:
    """Plot the 2×2 layout layer grid for one map or all maps with matches."""
    from concurrent.futures import ProcessPoolExecutor, as_completed

    output_root = Path(args.output)

    if args.all_matches:
        map_list = _maps_with_matches()
        print(f'Found {len(map_list)} maps with matches')
        if not map_list:
            return
        if args.workers > 1:
            with ProcessPoolExecutor(max_workers=args.workers) as pool:
                futures = {
                    pool.submit(_plot_one, map_slug, map_label, output_root): map_slug
                    for map_slug, map_label in map_list
                }
                for i, future in enumerate(as_completed(futures), 1):
                    print(f'[{i:3d}/{len(map_list)}] {future.result()}')
        else:
            for i, (map_slug, map_label) in enumerate(map_list, 1):
                status = _plot_one(map_slug, map_label, output_root)
                print(f'[{i:3d}/{len(map_list)}] {status}')
    else:
        map_slug = args.map
        out_dir = output_root / map_slug
        if not out_dir.is_dir():
            print(f"Error: output dir not found: {out_dir}", file=sys.stderr)
            print(f"  Run 'ctw run --map {map_slug}' first.", file=sys.stderr)
            sys.exit(1)
        _plot_map(map_slug, map_slug, out_dir, output_root)

    print('Done.')


def _maps_with_matches(db_path: str = 'match_analysis/metadata.db') -> list[tuple[str, str]]:
    """Return (map_slug, map_name) for every map that has at least one match."""
    import duckdb
    conn = duckdb.connect(db_path, read_only=True)
    rows = conn.execute("""
        SELECT m.map_slug, m.map_name
        FROM maps m
        JOIN matches mt ON m.map_id = mt.map_id
        GROUP BY m.map_slug, m.map_name
        ORDER BY m.map_name
    """).fetchall()
    conn.close()
    return [(slug, name) for slug, name in rows]


def _load_layer(output_root: Path, map_slug: str, layer_key: str):
    """Load a layout parquet for one map/layer. Returns None if missing or empty."""
    import pandas as pd
    path = output_root / map_slug / f'{layer_key}.parquet'
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    return df if not df.empty else None


def _legend_patches(df) -> list:
    """Build colour legend from the most common (block_id, block_data) pairs."""
    import matplotlib.patches as mpatches
    import numpy as np
    from collections import Counter
    from common.visualization.block_colors import block_color

    if 'block_id' not in df.columns:
        return []
    data_col = (df['block_data'].values.astype(int)
                if 'block_data' in df.columns
                else np.zeros(len(df), dtype=int))
    pairs = list(zip(df['block_id'].values.astype(int), data_col))
    top = Counter(pairs).most_common(15)
    patches = []
    for (bid, bdata), count in top:
        rgb = tuple(c / 255.0 for c in block_color(bid, bdata))
        label = f'ID {bid}' + (f':{bdata}' if bdata else '') + f'  ({count:,})'
        patches.append(mpatches.Patch(color=rgb, label=label))
    return patches


def _plot_one(map_slug: str, map_label: str, output_root: Path) -> str:
    """Worker-safe wrapper for parallel execution. Returns a status string."""
    import matplotlib
    matplotlib.use('Agg')
    out_dir = output_root / map_slug
    if not out_dir.is_dir():
        return f'SKIP {map_slug} (no output dir)'
    from layout_analysis.visualization import plot_layout_grid
    plot_layout_grid(map_slug, map_label, out_dir, output_root)
    return f'OK   {map_slug}'
