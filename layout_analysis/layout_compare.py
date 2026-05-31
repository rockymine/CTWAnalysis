"""Compare layout layers (y0, bedrock, top_surface) for one or all maps.

Public entry point:
    run(args: argparse.Namespace) -> None

Expected args attributes:
    map         (str | None)   – single map name, or None for batch
    dir         (str)          – root output directory
    output_dir  (str | None)   – where to save PNGs (default: <dir>/diagnostics/)
    summary     (bool)         – text-only summary table, no plots (batch only)
"""
import csv
import sys
from pathlib import Path
from typing import Optional

import numpy as np

from common.geometry import get_grid_extent, blocks_to_unit_squares
from common.visualization.block_colors import block_color


# ---------------------------------------------------------------------------
# Module-level cache for materials
# ---------------------------------------------------------------------------

_MATERIAL_NAMES: Optional[dict[int, str]] = None


def _load_material_names() -> dict[int, str]:
    """Load block ID → name mapping from materials.txt."""
    global _MATERIAL_NAMES
    if _MATERIAL_NAMES is not None:
        return _MATERIAL_NAMES

    _MATERIAL_NAMES = {}
    mat_path = Path(__file__).resolve().parent.parent / 'materials.txt'
    if not mat_path.exists():
        return _MATERIAL_NAMES
    with open(mat_path, 'r') as f:
        for line in f:
            line = line.strip()
            if ':' not in line:
                continue
            parts = line.split(':', 1)
            try:
                _MATERIAL_NAMES[int(parts[0])] = parts[1]
            except ValueError:
                continue
    return _MATERIAL_NAMES


_CATEGORY_LABELS = {
    'A': 'y0 only has block 36 — bedrock-only is essential',
    'B': 'y0 has block 36 mixed with other blocks — needs block 36 subtraction',
    'C': 'y0 only bedrock — y0 ~ bedrock, either works',
    'D': 'y0 empty — void/sky maps, need bedrock or top_surface',
    'E': 'y0 has diverse blocks, no 36 — y0 works well',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_parquet_safe(path: Path):
    """Read a parquet file, returning None on missing/error."""
    import pandas as pd
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        return df if not df.empty else None
    except Exception:
        return None


def _collect_layout_stats(map_name: str, map_dir: Path) -> Optional[dict]:
    """Collect layout statistics for a single map. Returns None if no data."""
    y0_df  = _read_parquet_safe(map_dir / 'layout_y0.parquet')
    bed_df = _read_parquet_safe(map_dir / 'layout_bedrock.parquet')
    top_df = _read_parquet_safe(map_dir / 'layout_top_surface.parquet')

    if y0_df is None and bed_df is None:
        return None

    y0_blocks  = len(y0_df) if y0_df is not None else 0
    y0_ids     = (sorted(y0_df['block_id'].unique().tolist())
                  if y0_df is not None and 'block_id' in y0_df.columns else [])
    bed_blocks = len(bed_df) if bed_df is not None else 0
    bed_y_range = ''
    if bed_df is not None and 'y' in bed_df.columns:
        bed_y_range = f"{bed_df['y'].min()}-{bed_df['y'].max()}"
    top_blocks = len(top_df) if top_df is not None else 0

    y0_set  = set(zip(y0_df['world_x'],  y0_df['world_z']))  if y0_df  is not None else set()
    bed_set = set(zip(bed_df['world_x'], bed_df['world_z'])) if bed_df is not None else set()

    overlap  = y0_set & bed_set
    y0_only  = y0_set - bed_set
    bed_only = bed_set - y0_set

    has_block36   = 36 in y0_ids
    block36_count = int((y0_df['block_id'] == 36).sum()) if has_block36 and y0_df is not None else 0
    has_water9    = 9 in y0_ids or 8 in y0_ids

    return {
        'map_name':          map_name,
        'y0_blocks':         y0_blocks,
        'y0_block_ids':      y0_ids,
        'bedrock_blocks':    bed_blocks,
        'bedrock_y_range':   bed_y_range,
        'top_blocks':        top_blocks,
        'y0_only_count':     len(y0_only),
        'bedrock_only_count': len(bed_only),
        'overlap_count':     len(overlap),
        'has_block36':       has_block36,
        'block36_count':     block36_count,
        'has_water9':        has_water9,
    }


def _categorize(stats: dict) -> str:
    """Assign a map to category A-E based on y0 characteristics."""
    y0_ids = stats['y0_block_ids']
    if stats['y0_blocks'] == 0:
        return 'D'
    if y0_ids == [36]:
        return 'A'
    if 36 in y0_ids and len(y0_ids) > 1:
        return 'B'
    if y0_ids == [7]:
        return 'C'
    return 'E'


def _print_single_stats(map_name: str, stats: dict) -> None:
    mat      = _load_material_names()
    id_names = [f"{bid}({mat.get(bid, '?')})" for bid in stats['y0_block_ids']]
    cat      = _categorize(stats)
    print(f"\n  Map:            {map_name}")
    print(f"  Category:       {cat} — {_CATEGORY_LABELS[cat]}")
    print(f"  Y0 blocks:      {stats['y0_blocks']}  ids={', '.join(id_names)}")
    print(f"  Bedrock blocks: {stats['bedrock_blocks']}  y_range={stats['bedrock_y_range']}")
    print(f"  Top blocks:     {stats['top_blocks']}")
    print(f"  Overlap:        {stats['overlap_count']}  "
          f"y0-only={stats['y0_only_count']}  bedrock-only={stats['bedrock_only_count']}")
    if stats['has_block36']:
        print(f"  Block 36 count: {stats['block36_count']}")


def _print_summary_table(all_stats: list[dict]) -> None:
    from collections import defaultdict
    by_cat: dict[str, list] = defaultdict(list)
    for s in all_stats:
        by_cat[_categorize(s)].append(s)

    for cat in 'ABCDE':
        maps = by_cat.get(cat, [])
        print(f"\nCategory {cat}: {_CATEGORY_LABELS[cat]}")
        print(f"  Count: {len(maps)}")
        if not maps:
            continue
        nw = max(max(len(s['map_name']) for s in maps), 8)
        print(f"  {'map':<{nw}}  y0_blk  bed_blk  y0only  bedonly  overlap  block36  water")
        print(f"  {'-'*nw}  ------  -------  ------  -------  -------  -------  -----")
        for s in maps:
            b36 = str(s['block36_count']) if s['has_block36'] else '-'
            w   = 'yes' if s['has_water9'] else '-'
            print(f"  {s['map_name']:<{nw}}  {s['y0_blocks']:>6}  {s['bedrock_blocks']:>7}  "
                  f"{s['y0_only_count']:>6}  {s['bedrock_only_count']:>7}  "
                  f"{s['overlap_count']:>7}  {b36:>7}  {w:>5}")

    print(f"\nTotal: {len(all_stats)} maps")


def _write_summary_csv(all_stats: list[dict], csv_path: Path) -> None:
    fields = [
        'map_name', 'category', 'y0_blocks', 'y0_block_ids', 'bedrock_blocks',
        'bedrock_y_range', 'top_blocks', 'y0_only_count', 'bedrock_only_count',
        'overlap_count', 'has_block36', 'block36_count', 'has_water9',
    ]
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for s in all_stats:
            row = dict(s)
            row['category']    = _categorize(s)
            row['y0_block_ids'] = ' '.join(str(x) for x in s['y0_block_ids'])
            writer.writerow(row)


def _plot_layout_comparison(map_name: str, map_dir: Path, save_path: Path) -> Optional[dict]:
    """Generate a 3-panel layout comparison figure. Returns stats dict or None."""
    import matplotlib
    matplotlib.use('Agg')
    from layout_analysis.visualization import plot_layout_comparison
    return plot_layout_comparison(map_name, map_dir, save_path)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(args) -> None:
    """Compare layout layers for one or all maps."""
    root = Path(args.dir)
    if not root.is_dir():
        print(f"Error: directory not found: {root}", file=sys.stderr)
        sys.exit(1)

    diag_dir = Path(args.output_dir) if args.output_dir else root / 'diagnostics'
    diag_dir.mkdir(parents=True, exist_ok=True)

    if args.map is not None:
        map_dir = root / args.map
        if not map_dir.is_dir():
            print(f"Error: map directory not found: {map_dir}", file=sys.stderr)
            sys.exit(1)
        save_path = diag_dir / f'{args.map}_layout.png'
        stats = _plot_layout_comparison(args.map, map_dir, save_path)
        if stats:
            print(f"Saved: {save_path}")
            _print_single_stats(args.map, stats)
    else:
        all_stats = []
        for map_dir in sorted(root.iterdir()):
            if not map_dir.is_dir():
                continue
            stats = _collect_layout_stats(map_dir.name, map_dir)
            if stats is None:
                continue
            all_stats.append(stats)

            if not args.summary:
                save_path = diag_dir / f'{map_dir.name}_layout.png'
                _plot_layout_comparison(map_dir.name, map_dir, save_path)
                print(f"  {map_dir.name}: saved {save_path}")

        if not all_stats:
            print("No maps with layout parquets found.")
            return

        if args.summary:
            _print_summary_table(all_stats)
        else:
            csv_path = diag_dir / 'layout_compare_summary.csv'
            _write_summary_csv(all_stats, csv_path)
            print(f"\n{len(all_stats)} maps processed. Summary CSV: {csv_path}")
