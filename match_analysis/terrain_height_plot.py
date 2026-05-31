"""Terrain-height diagnostic plot for a single map.

Public entry point:
- run(args): load data from the DB and render the 4×2 diagnostic figure
"""

import json
import sys
from pathlib import Path


def run(args: object) -> None:
    """Plot height_above_terrain distribution as a 4×2 visual grid."""
    map_name = args.map
    output_root = Path(args.output)
    map_dir = output_root / map_name
    ctx_path = map_dir / 'map_context.json'

    if not ctx_path.exists():
        print(f"Error: map_context.json not found: {ctx_path}", file=sys.stderr)
        sys.exit(1)

    with open(ctx_path) as f:
        map_context = json.load(f)

    save_path = (
        Path(args.save_path) if args.save_path
        else map_dir / 'images' / 'terrain_height_debug.png'
    )
    save_path.parent.mkdir(parents=True, exist_ok=True)

    db_path = Path('match_analysis/metadata.db')
    if not db_path.exists():
        print(f"Error: database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    import duckdb
    conn = duckdb.connect(str(db_path), read_only=True)

    try:
        n_terrain = conn.execute(
            "SELECT COUNT(*) FROM map_terrain_height th "
            "JOIN maps m ON m.map_id = th.map_id WHERE m.map_slug = ?",
            [map_name],
        ).fetchone()[0]
    except Exception:
        n_terrain = 0
    if n_terrain == 0:
        conn.close()
        print(
            f"No terrain height data for '{map_name}'. "
            f"Run 'ctw maps terrain-height --map {map_name}' first."
        )
        return

    map_id = conn.execute(
        "SELECT map_id FROM maps WHERE map_slug = ?", [map_name]
    ).fetchone()[0]

    all_cells_df = conn.execute("""
        SELECT world_x, world_z, surface_y
        FROM map_terrain_height
        WHERE map_id = ?
    """, [map_id]).df()

    hat_df = conn.execute("""
        SELECT
            th.world_x,
            th.world_z,
            MAX(pe.y - (th.surface_y + 1)) AS max_hat,
            MIN(pe.y - (th.surface_y + 1)) AS min_hat,
            COUNT(*) AS event_count
        FROM position_events pe
        JOIN matches mat ON mat.match_id = pe.match_id
        JOIN map_terrain_height th
            ON  th.map_id  = mat.map_id
            AND th.world_x = CAST(pe.x AS INT)
            AND th.world_z = CAST(pe.z AS INT)
        WHERE mat.map_id = ?
          AND pe.y >= 0
        GROUP BY th.world_x, th.world_z
    """, [map_id]).df()

    loc_df = conn.execute("""
        SELECT world_x, world_z,
               arg_max(location_type, n) AS location_type
        FROM (
            SELECT CAST(pe.x AS INT) AS world_x,
                   CAST(pe.z AS INT) AS world_z,
                   pe.location_type,
                   COUNT(*) AS n
            FROM position_events pe
            JOIN matches mat ON mat.match_id = pe.match_id
            WHERE mat.map_id = ?
              AND pe.location_type IS NOT NULL
            GROUP BY world_x, world_z, pe.location_type
        )
        GROUP BY world_x, world_z
    """, [map_id]).df()

    conn.close()

    if hat_df.empty and loc_df.empty:
        print(f"No position events found for '{map_name}' — nothing to plot.")
        return

    plot_terrain_height(map_name, map_context, all_cells_df, hat_df, loc_df, save_path)
    print(f"Saved: {save_path}")


def plot_terrain_height(
    map_name: str,
    map_context: dict,
    all_cells_df: 'pd.DataFrame',
    hat_df: 'pd.DataFrame',
    loc_df: 'pd.DataFrame',
    save_path: Path,
) -> None:
    """Render a 4×2 grid of terrain-height diagnostic panels.

    Panels:
      [0,0] Above terrain   — per-cell MAX height_above_terrain > 0  (YlOrRd)
      [0,1] Below terrain   — per-cell MAX depth (abs MIN hat < 0)   (Blues)
      [1,0] Data coverage   — event count per island cell; absent cells distinct
      [1,1] Vertical range  — diverging: red=highest above, blue=deepest below
      [2,0] Location type   — dominant location_type per cell
      [2,1] Reference map   — island outlines + POIs
      [3,0] Terrain height  — surface_y per island cell (map topography)
      [3,1] (empty)
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.cm as cm
    import matplotlib.colors as mcolors
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    from matplotlib.collections import PolyCollection

    from common.geometry import blocks_to_unit_squares
    from common.visualization.map_primitives import (
        BuildRegionStyle,
        IslandOutlineStyle,
        draw_build_region,
        draw_island_outlines,
        draw_map_base,
        POIStyle,
    )

    # ── Derived frames ──────────────────────────────────────────────────
    above = hat_df[hat_df['max_hat'] > 0].copy() if not hat_df.empty else pd.DataFrame()
    below = hat_df[hat_df['min_hat'] < 0].copy() if not hat_df.empty else pd.DataFrame()

    if not hat_df.empty and not all_cells_df.empty:
        coverage_df = all_cells_df.merge(
            hat_df[['world_x', 'world_z', 'event_count']],
            on=['world_x', 'world_z'], how='left',
        )
    else:
        coverage_df = all_cells_df.copy()
        coverage_df['event_count'] = float('nan')

    if not hat_df.empty:
        hat_df = hat_df.copy()
        hat_df['max_hat'] = hat_df['max_hat'].fillna(0)
        hat_df['min_hat'] = hat_df['min_hat'].fillna(0)
        use_above = hat_df['max_hat'].abs() >= hat_df['min_hat'].abs()
        hat_df['dominant'] = np.where(use_above, hat_df['max_hat'], hat_df['min_hat'])

    # ── Shared spatial extent ───────────────────────────────────────────
    ref = loc_df if not loc_df.empty else hat_df
    if ref.empty:
        return
    x_min = int(ref['world_x'].min()) - 2
    x_max = int(ref['world_x'].max()) + 3
    z_min = int(ref['world_z'].min()) - 2
    z_max = int(ref['world_z'].max()) + 3

    # ── Style constants ─────────────────────────────────────────────────
    _LOC_COLORS = {
        'island':       '#2ecc71',
        'build_region': '#f39c12',
        'void':         '#e74c3c',
    }
    _THIN_ISLAND = IslandOutlineStyle(
        exterior_linewidth=0.6, exterior_alpha=0.45,
        hole_linewidth=0.5, hole_alpha=0.35,
    )
    _THIN_BUILD = BuildRegionStyle(fill_alpha=0.07, linewidth=0.5)

    # ── Figure setup ────────────────────────────────────────────────────
    fig, axes = plt.subplots(4, 2, figsize=(20, 40), dpi=150)
    fig.suptitle(
        f'{map_name} — height_above_terrain diagnostics',
        fontsize=15, fontweight='bold', y=0.995,
    )

    def _setup_ax(ax: object, title: str) -> None:
        ax.set_xlim(x_min, x_max)
        ax.set_ylim(z_min, z_max)
        ax.invert_yaxis()
        ax.set_aspect('equal')
        ax.set_title(title, fontsize=11, fontweight='bold', pad=6)
        ax.set_xlabel('world x', fontsize=8)
        ax.set_ylabel('world z', fontsize=8)
        ax.tick_params(labelsize=7)
        draw_build_region(ax, map_context, style=_THIN_BUILD)
        draw_island_outlines(ax, map_context, style=_THIN_ISLAND)

    def _poly_collection(
        xs: 'np.ndarray', zs: 'np.ndarray', facecolors: list
    ) -> PolyCollection:
        squares = blocks_to_unit_squares(xs, zs)
        return PolyCollection(
            squares, facecolors=facecolors,
            edgecolors='none', linewidths=0, antialiased=False,
        )

    def _stat_label(ax: object, text: str) -> None:
        ax.text(
            0.02, 0.98, text,
            transform=ax.transAxes, fontsize=8, va='top',
            bbox=dict(facecolor='white', alpha=0.7, edgecolor='none', pad=2),
        )

    # ── Panel [0,0]: Above terrain ──────────────────────────────────────
    ax = axes[0, 0]
    _setup_ax(ax, 'Above terrain — highest position per cell')
    if not above.empty:
        vals = above['max_hat'].values.astype(float)
        vmax = max(float(np.percentile(vals, 95)), 1.0)
        norm = mcolors.Normalize(vmin=0, vmax=vmax)
        cmap = cm.get_cmap('YlOrRd')
        facecolors = [cmap(norm(v)) for v in np.clip(vals, 0, vmax)]
        ax.add_collection(_poly_collection(above['world_x'].values, above['world_z'].values, facecolors))
        sm = cm.ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        fig.colorbar(sm, ax=ax, fraction=0.03, pad=0.02, label='blocks above terrain')
        _stat_label(ax, f'{len(above):,} cells  ·  max {int(vals.max())} blocks')
    else:
        ax.text(0.5, 0.5, 'No data', transform=ax.transAxes,
                ha='center', va='center', color='gray', fontsize=12)

    # ── Panel [0,1]: Below terrain ──────────────────────────────────────
    ax = axes[0, 1]
    _setup_ax(ax, 'Below terrain — deepest position per cell')
    if not below.empty:
        depths = (-below['min_hat'].values).astype(float)
        vmax = max(float(np.percentile(depths, 95)), 1.0)
        norm = mcolors.Normalize(vmin=0, vmax=vmax)
        cmap = cm.get_cmap('Blues')
        facecolors = [cmap(norm(v)) for v in np.clip(depths, 0, vmax)]
        ax.add_collection(_poly_collection(below['world_x'].values, below['world_z'].values, facecolors))
        sm = cm.ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        fig.colorbar(sm, ax=ax, fraction=0.03, pad=0.02, label='blocks below terrain')
        _stat_label(ax, f'{len(below):,} cells  ·  max depth {int(depths.max())} blocks')
    else:
        ax.text(0.5, 0.5, 'No data', transform=ax.transAxes,
                ha='center', va='center', color='gray', fontsize=12)

    # ── Panel [1,0]: Data coverage ──────────────────────────────────────
    ax = axes[1, 0]
    _setup_ax(ax, 'Data coverage — position events per island cell')
    if not coverage_df.empty:
        no_data = coverage_df[coverage_df['event_count'].isna()]
        has_data = coverage_df[coverage_df['event_count'].notna()].copy()

        if not no_data.empty:
            squares = blocks_to_unit_squares(no_data['world_x'].values, no_data['world_z'].values)
            ax.add_collection(PolyCollection(
                squares, facecolors='#d1d5db',
                edgecolors='none', linewidths=0, antialiased=False,
            ))

        if not has_data.empty:
            counts = has_data['event_count'].values.astype(float)
            norm = mcolors.LogNorm(vmin=max(counts.min(), 1), vmax=counts.max())
            cmap = cm.get_cmap('plasma')
            facecolors = [cmap(norm(v)) for v in counts]
            ax.add_collection(_poly_collection(
                has_data['world_x'].values, has_data['world_z'].values, facecolors,
            ))
            sm = cm.ScalarMappable(cmap=cmap, norm=norm)
            sm.set_array([])
            fig.colorbar(sm, ax=ax, fraction=0.03, pad=0.02, label='event count (log scale)')

        n_absent = len(no_data)
        n_covered = len(has_data)
        pct = 100 * n_covered / max(len(coverage_df), 1)
        _stat_label(ax, f'{n_covered:,} covered  ·  {n_absent:,} absent  ({pct:.0f}%)')

        handles = [
            mpatches.Patch(facecolor='#d1d5db', label='no data'),
            mpatches.Patch(facecolor=cm.get_cmap('plasma')(0.6), label='has data (log scale)'),
        ]
        ax.legend(handles=handles, loc='lower right', fontsize=9, framealpha=0.85)

    # ── Panel [1,1]: Diverging extremes ─────────────────────────────────
    ax = axes[1, 1]
    _setup_ax(ax, 'Vertical extremes — furthest from terrain per cell')
    if not hat_df.empty and 'dominant' in hat_df.columns:
        dom = hat_df['dominant'].values.astype(float)
        abs_vals = np.abs(dom)
        vlim = max(float(np.percentile(abs_vals, 95)), 1.0)
        norm = mcolors.TwoSlopeNorm(vmin=-vlim, vcenter=0, vmax=vlim)
        cmap = cm.get_cmap('RdBu_r')
        facecolors = [cmap(norm(np.clip(v, -vlim, vlim))) for v in dom]
        ax.add_collection(_poly_collection(hat_df['world_x'].values, hat_df['world_z'].values, facecolors))
        sm = cm.ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=ax, fraction=0.03, pad=0.02, label='blocks from terrain')
        cbar.ax.axhline(0, color='black', linewidth=0.8)
        _stat_label(ax,
            f'red = above terrain  ·  blue = below\n'
            f'max above {int(hat_df["max_hat"].max())}  ·  '
            f'max depth {int(-hat_df["min_hat"].min())} blocks'
        )

    # ── Panel [2,0]: Location type ──────────────────────────────────────
    ax = axes[2, 0]
    _setup_ax(ax, 'Location type — dominant classification per cell')
    if not loc_df.empty:
        for loc_type, color in _LOC_COLORS.items():
            sub = loc_df[loc_df['location_type'] == loc_type]
            if sub.empty:
                continue
            squares = blocks_to_unit_squares(sub['world_x'].values, sub['world_z'].values)
            ax.add_collection(PolyCollection(
                squares, facecolors=color,
                edgecolors='none', linewidths=0, antialiased=False, alpha=0.75,
            ))
        handles = [
            mpatches.Patch(facecolor=c, alpha=0.75, label=lt.replace('_', ' '))
            for lt, c in _LOC_COLORS.items()
        ]
        ax.legend(handles=handles, loc='lower right', fontsize=9, framealpha=0.85)
        _stat_label(ax, f'{len(loc_df):,} cells')

    # ── Panel [2,1]: Reference map ──────────────────────────────────────
    ax = axes[2, 1]
    draw_map_base(
        ax, map_context,
        island_style=IslandOutlineStyle(exterior_linewidth=1.2, exterior_alpha=0.9),
        poi_style=POIStyle(zorder=8),
    )
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(z_min, z_max)
    ax.invert_yaxis()
    ax.set_aspect('equal')
    ax.set_title('Reference map', fontsize=11, fontweight='bold', pad=6)
    ax.set_xlabel('world x', fontsize=8)
    ax.set_ylabel('world z', fontsize=8)
    ax.tick_params(labelsize=7)

    # ── Panel [3,0]: Terrain elevation ──────────────────────────────────
    ax = axes[3, 0]
    _setup_ax(ax, 'Terrain elevation — surface_y per island cell')
    if not all_cells_df.empty and 'surface_y' in all_cells_df.columns:
        elev = all_cells_df['surface_y'].values.astype(float)
        norm = mcolors.Normalize(vmin=elev.min(), vmax=elev.max())
        cmap = cm.get_cmap('terrain')
        facecolors = [cmap(norm(v)) for v in elev]
        ax.add_collection(_poly_collection(
            all_cells_df['world_x'].values, all_cells_df['world_z'].values, facecolors,
        ))
        sm = cm.ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        fig.colorbar(sm, ax=ax, fraction=0.03, pad=0.02, label='surface_y (world height)')
        _stat_label(ax,
            f'{len(all_cells_df):,} cells  ·  '
            f'y {int(elev.min())}–{int(elev.max())}'
        )
    else:
        ax.text(0.5, 0.5, 'No terrain data', transform=ax.transAxes,
                ha='center', va='center', color='gray', fontsize=12)

    # ── Panel [3,1]: unused ──────────────────────────────────────────────
    axes[3, 1].set_visible(False)

    fig.tight_layout(rect=[0, 0, 1, 0.995])
    fig.savefig(str(save_path), dpi=150, bbox_inches='tight')
    plt.close(fig)
