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

from common.geometry import get_grid_extent, block_unit_square


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


# Colors for well-known block IDs
_BLOCK_COLORS = {
    7:  '#888888',   # BEDROCK — gray
    36: '#FF2222',   # PISTON_MOVING_PIECE — bright red
    8:  '#3366CC',   # WATER — blue
    9:  '#3366CC',   # STATIONARY_WATER — blue
    10: '#FF6600',   # LAVA — orange
    11: '#FF6600',   # STATIONARY_LAVA — orange
    1:  '#AAAAAA',   # STONE — light gray
    4:  '#999977',   # COBBLESTONE — tan
    35: '#EEEEEE',   # WOOL — white
    0:  '#000000',   # AIR — black
}

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

def _block_color(block_id: int, cmap, n_unique: int, idx: int):
    """Return RGBA color for a block_id."""
    if block_id in _BLOCK_COLORS:
        from matplotlib.colors import to_rgba
        return to_rgba(_BLOCK_COLORS[block_id])
    return cmap(idx / max(n_unique - 1, 1))


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
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    from matplotlib.patches import Patch

    stats = _collect_layout_stats(map_name, map_dir)
    if stats is None:
        return None

    y0_df  = _read_parquet_safe(map_dir / 'layout_y0.parquet')
    bed_df = _read_parquet_safe(map_dir / 'layout_bedrock.parquet')

    all_x, all_z = [], []
    if y0_df is not None:
        mn_x, mx_x, mn_z, mx_z = get_grid_extent(y0_df['world_x'], y0_df['world_z'])
        all_x.extend([mn_x, mx_x])
        all_z.extend([mn_z, mx_z])
    if bed_df is not None:
        mn_x, mx_x, mn_z, mx_z = get_grid_extent(bed_df['world_x'], bed_df['world_z'])
        all_x.extend([mn_x, mx_x])
        all_z.extend([mn_z, mx_z])
    if not all_x:
        return stats

    x_min, x_max = min(all_x), max(all_x)
    z_min, z_max = min(all_z), max(all_z)
    pad = max((x_max - x_min) * 0.02, (z_max - z_min) * 0.02, 1)

    fig, axes = plt.subplots(1, 3, figsize=(20, 7))
    fig.suptitle(f'Layout Comparison: {map_name}', fontsize=14, fontweight='bold')

    mat = _load_material_names()

    for ax in axes:
        ax.set_xlim(x_min - pad, x_max + pad)
        ax.set_ylim(z_min - pad, z_max + pad)
        ax.set_aspect('equal')
        ax.invert_yaxis()

    # --- Panel 1: Y0 layer colored by block_id ---
    ax = axes[0]
    if y0_df is not None and 'block_id' in y0_df.columns:
        unique_ids  = sorted(y0_df['block_id'].unique())
        cmap        = plt.get_cmap('tab20')
        id_to_color = {bid: _block_color(bid, cmap, len(unique_ids), i)
                       for i, bid in enumerate(unique_ids)}

        verts  = [block_unit_square(row['world_x'], row['world_z']) for _, row in y0_df.iterrows()]
        colors = [id_to_color[row['block_id']] for _, row in y0_df.iterrows()]

        ax.add_collection(PolyCollection(verts, facecolors=colors, edgecolors='none', linewidths=0))
        legend_patches = [
            Patch(facecolor=id_to_color[bid], label=f"{bid} {mat.get(bid, '?')}")
            for bid in unique_ids[:12]
        ]
        ax.legend(handles=legend_patches, fontsize=6, loc='upper right', framealpha=0.8)
        ax.set_title(f'Y0 Layer — {len(y0_df)} blocks, {len(unique_ids)} types', fontsize=10)
    else:
        ax.text(0.5, 0.5, 'No Y0 data', transform=ax.transAxes,
                ha='center', va='center', fontsize=14, color='gray')
        ax.set_title('Y0 Layer — empty', fontsize=10)

    # --- Panel 2: Bedrock layer colored by y level ---
    ax = axes[1]
    if bed_df is not None and 'y' in bed_df.columns:
        y_vals   = bed_df['y'].values
        y_lo, y_hi = y_vals.min(), y_vals.max()
        cmap_bed = plt.get_cmap('YlOrBr')

        verts  = []
        colors = []
        for _, row in bed_df.iterrows():
            verts.append(block_unit_square(row['world_x'], row['world_z']))
            norm_y = (row['y'] - y_lo) / max(y_hi - y_lo, 1)
            colors.append(cmap_bed(norm_y))

        ax.add_collection(PolyCollection(verts, facecolors=colors, edgecolors='none', linewidths=0))
        sm = plt.cm.ScalarMappable(cmap=cmap_bed, norm=plt.Normalize(vmin=y_lo, vmax=y_hi))
        sm.set_array([])
        cb = fig.colorbar(sm, ax=ax, shrink=0.6, pad=0.02)
        cb.set_label('Y level', fontsize=8)
        ax.set_title(f'Bedrock Layer — {len(bed_df)} blocks, y={y_lo}..{y_hi}', fontsize=10)
    else:
        ax.text(0.5, 0.5, 'No bedrock data', transform=ax.transAxes,
                ha='center', va='center', fontsize=14, color='gray')
        ax.set_title('Bedrock Layer — empty', fontsize=10)

    # --- Panel 3: Difference / overlap ---
    ax = axes[2]
    y0_set  = set(zip(y0_df['world_x'],  y0_df['world_z']))  if y0_df  is not None else set()
    bed_set = set(zip(bed_df['world_x'], bed_df['world_z'])) if bed_df is not None else set()

    overlap  = y0_set & bed_set
    y0_only  = y0_set - bed_set
    bed_only = bed_set - y0_set

    for coords, color, label in [
        (overlap,  '#88BB88', 'shared'),
        (y0_only,  '#CC4444', 'y0 only'),
        (bed_only, '#4444CC', 'bedrock only'),
    ]:
        if not coords:
            continue
        verts = [block_unit_square(x, z) for x, z in coords]
        ax.add_collection(PolyCollection(verts, facecolors=color, edgecolors='none',
                                         linewidths=0, alpha=0.7, label=label))

    ax.legend(fontsize=8, loc='upper right', framealpha=0.8)
    ax.set_title(f'Difference — shared={len(overlap)}, '
                 f'y0-only={len(y0_only)}, bed-only={len(bed_only)}', fontsize=10)

    plt.tight_layout()
    fig.savefig(str(save_path), dpi=150, bbox_inches='tight')
    plt.close(fig)

    return stats


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
