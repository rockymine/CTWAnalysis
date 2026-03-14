"""
Plot layout_lowest_solid (= layout_decided for these maps) for mini_drought,
lupa, and golden_drought side by side, with observer spawn and island
outlines overlaid.

Usage:
    python scripts/plot_observer_islands.py
Output:
    output/observer_island_investigation.png
"""

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

# Reuse block-colour logic from the case-study script
sys.path.insert(0, str(Path(__file__).parent))
from plot_layout_case_study import _make_image, block_color

MAPS = [
    ('mini_drought',  'Mini Drought',   (-9.5,   -330.5)),
    ('lupa',          'Lupa',           (-28.5,   75.5)),
    ('golden_drought','Golden Drought', (116.5,  -461.5)),
]

OUTPUT = Path('output/observer_island_investigation.png')


def _load_islands(map_slug: str) -> list[dict]:
    path = Path(f'output/{map_slug}/map_context.json')
    if not path.exists():
        return []
    with open(path) as f:
        ctx = json.load(f)
    return ctx.get('islands', [])


def _island_distance(island: dict, cx: float, cz: float) -> float:
    ic = island['center']
    return ((ic[0] - cx) ** 2 + (ic[1] - cz) ** 2) ** 0.5


def plot_map(ax, map_slug: str, title: str, obs_x: float, obs_z: float) -> None:
    layer_path = Path(f'output/{map_slug}/layout_lowest_solid.parquet')
    if not layer_path.exists():
        ax.text(0.5, 0.5, 'No data', transform=ax.transAxes,
                ha='center', va='center', color='gray')
        ax.set_title(title)
        return

    df = pd.read_parquet(layer_path)
    rgba, extent = _make_image(df)
    ax.imshow(rgba, origin='upper', extent=extent,
              interpolation='nearest', aspect='equal')

    islands = _load_islands(map_slug)

    # Draw island outlines and label by id + distance
    for isl in islands:
        poly = isl.get('simplified_polygon')
        dist = _island_distance(isl, obs_x, obs_z)
        within_50 = dist <= 50

        if poly and poly.get('exterior'):
            pts = np.array(poly['exterior'])
            if len(pts) >= 2:
                color = 'red' if within_50 else 'white'
                lw = 1.5 if within_50 else 0.6
                ax.plot(
                    np.append(pts[:, 0], pts[0, 0]),
                    np.append(pts[:, 1], pts[0, 1]),
                    color=color, linewidth=lw, alpha=0.85,
                )

        # Label islands within 80 blocks with id + distance
        if dist <= 80:
            ic = isl['center']
            ax.text(
                ic[0], ic[1],
                f"#{isl['id']}\n{dist:.0f}b\n{isl['area']}bl",
                color='yellow', fontsize=5.5, ha='center', va='center',
                fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.15', fc='black', alpha=0.5, lw=0),
            )

    # Observer spawn marker
    ax.plot(obs_x, obs_z, marker='*', markersize=14, color='cyan',
            markeredgecolor='black', markeredgewidth=0.8, zorder=10,
            label='Observer spawn')

    # 10-block radius ring around observer spawn
    theta = np.linspace(0, 2 * np.pi, 120)
    ax.plot(obs_x + 10 * np.cos(theta), obs_z + 10 * np.sin(theta),
            color='cyan', linewidth=0.8, linestyle='--', alpha=0.7,
            label='10-block radius')
    # 35-block radius ring
    ax.plot(obs_x + 35 * np.cos(theta), obs_z + 35 * np.sin(theta),
            color='orange', linewidth=0.8, linestyle='--', alpha=0.7,
            label='35-block radius')

    ax.set_title(f'{title}\nobs spawn ({obs_x:.1f}, {obs_z:.1f})', fontsize=9)
    ax.set_xlabel('X')
    ax.set_ylabel('Z')

    legend_elements = [
        mpatches.Patch(color='red',    label='Island outline (≤50b)'),
        mpatches.Patch(color='white',  label='Island outline (>50b)'),
        plt.Line2D([0], [0], marker='*', color='cyan', markersize=9,
                   markeredgecolor='black', label='Observer spawn', linestyle='None'),
        plt.Line2D([0], [0], color='cyan',   linestyle='--', label='10-block radius'),
        plt.Line2D([0], [0], color='orange', linestyle='--', label='35-block radius'),
    ]
    ax.legend(handles=legend_elements, loc='upper right', fontsize=5.5,
              framealpha=0.8)


def main() -> None:
    fig, axes = plt.subplots(1, 3, figsize=(22, 9))
    fig.suptitle(
        'Observer island investigation — lowest_solid layer\n'
        'Red outlines = islands within 50b of observer spawn  |  '
        'Labels: #id / distance / area',
        fontsize=10, fontweight='bold',
    )

    for ax, (slug, title, (obs_x, obs_z)) in zip(axes, MAPS):
        plot_map(ax, slug, title, obs_x, obs_z)

    plt.tight_layout()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f'Saved: {OUTPUT}')


if __name__ == '__main__':
    main()
