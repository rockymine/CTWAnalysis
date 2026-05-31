"""Visualization functions for all layout analysis output.

Covers: point-density plots, layout layer grids, layer comparison,
fork analysis summary, and resource/chest overlay maps.
"""

import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

from common.visualization.colors import NEUTRAL_COLOR
from common.visualization.map_primitives import (
    draw_layout_image,
    draw_map_base,
    map_base_legend_handles,
)

logger = logging.getLogger('ctw')


def save_point_plot(
    df: pd.DataFrame,
    output_path: str,
    title: str,
    use_binned: bool | None = None,
    bin_size: int = 1
) -> None:
    """
    Save a 2D plot of world_x vs world_z points.

    Args:
        df: DataFrame with 'world_x' and 'world_z' columns
        output_path: Path to save the plot image
        title: Plot title
        use_binned: If True, use binned/pixel plot. If None, auto-decide based on point count.
        bin_size: Size of bins in blocks (for binned plots)
    """
    if df.empty:
        logger.warning(f"No points to plot for {title}")
        # Create an empty plot
        fig, ax = plt.subplots(figsize=(10, 10))
        ax.text(0.5, 0.5, 'No data points', ha='center', va='center', fontsize=16)
        ax.set_title(title)
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        return

    x = df['world_x'].values
    z = df['world_z'].values

    # Auto-decide whether to use binned plot
    if use_binned is None:
        use_binned = len(df) > 100000

    # Create figure
    fig, ax = plt.subplots(figsize=(12, 12))

    if use_binned:
        # Binned/pixel plot for large datasets
        x_min, x_max = x.min(), x.max()
        z_min, z_max = z.min(), z.max()

        # Create bins
        x_bins = np.arange(x_min, x_max + bin_size, bin_size)
        z_bins = np.arange(z_min, z_max + bin_size, bin_size)

        # Create 2D histogram
        hist, x_edges, z_edges = np.histogram2d(x, z, bins=[x_bins, z_bins])

        # Plot as image
        extent = [x_edges[0], x_edges[-1], z_edges[0], z_edges[-1]]
        im = ax.imshow(
            hist.T,
            origin='lower',
            extent=extent,
            cmap='viridis',
            aspect='equal',
            interpolation='nearest'
        )
        plt.colorbar(im, ax=ax, label='Point count per bin')

    else:
        # Scatter plot for smaller datasets
        ax.scatter(x, z, s=1, alpha=0.5, c='blue', marker='.')

    # Set labels and title
    ax.set_xlabel('X', color='#444444')
    ax.set_ylabel('Z', color='#444444')
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_aspect('equal')
    ax.invert_yaxis()
    ax.tick_params(colors='#666666')
    for spine in ax.spines.values():
        spine.set_edgecolor('#cccccc')

    # Save
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()

    logger.debug(f"  Saved plot: {output_path}")


def save_all_plots(
    y0_df: pd.DataFrame,
    top_surface_df: pd.DataFrame,
    density_dfs: dict[str, pd.DataFrame],
    bedrock_df: pd.DataFrame,
    output_dir: str
) -> None:
    """
    Save all plots to the output directory.

    Args:
        y0_df: Y0 layer extraction results
        top_surface_df: Top surface extraction results
        density_dfs: Dictionary mapping mode names to density extraction results
                     e.g., {'run_N10': df, 'count_N10': df}
        bedrock_df: Lowest bedrock extraction results
        output_dir: Directory to save plots
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    logger.debug("Generating plots...")

    # Y0 layer plot
    save_point_plot(
        y0_df,
        str(output_path / 'y0_layer.png'),
        'Y0 Layer - Non-air blocks at world y=0'
    )

    # Top surface plot
    save_point_plot(
        top_surface_df,
        str(output_path / 'top_surface.png'),
        'Top Surface - Highest non-air block per column'
    )

    # Density plots
    for mode_name, df in density_dfs.items():
        save_point_plot(
            df,
            str(output_path / f'density_{mode_name}.png'),
            f'Vertical Density - {mode_name.replace("_", " ").title()}'
        )

    # Bedrock plot
    save_point_plot(
        bedrock_df,
        str(output_path / 'lowest_bedrock.png'),
        'Lowest Bedrock - Lowest bedrock block per column'
    )

    logger.debug("All plots saved successfully!")


# ---------------------------------------------------------------------------
# Fork layout analysis summary (moved from layout_analysis/fork_analysis.py)
# ---------------------------------------------------------------------------


def plot_fork_analysis(results: list, save_path: Path) -> None:
    """Render the 4-panel fork layout summary figure and save to save_path."""
    from collections import defaultdict
    from layout_analysis.fork_analysis import _TIER_COLORS, _TIER_ORDER

    BG = "#FAFAF8"
    SPINE_COLOR = "#cccccc"
    LABEL_COLOR = "#444444"

    n_maps   = len({r.map_slug for r in results})
    n_halves = len(results)

    fig, axes = plt.subplots(
        2, 2, figsize=(18, 12), facecolor=BG,
        gridspec_kw={"hspace": 0.38, "wspace": 0.30,
                     "left": 0.07, "right": 0.97, "top": 0.93, "bottom": 0.07},
    )
    for ax in axes.flat:
        ax.set_facecolor(BG)
        ax.spines[["top", "right"]].set_visible(False)
        ax.spines[["left", "bottom"]].set_color(SPINE_COLOR)
        ax.tick_params(colors="#666666", labelsize=8.5)

    tier_patches = [
        mpatches.Patch(facecolor=_TIER_COLORS.get(t, NEUTRAL_COLOR), label=t)
        for t in _TIER_ORDER if any(r.size_tier == t for r in results)
    ]

    # Panel 1: arm length symmetry scatter
    ax = axes[0, 0]
    for r in results:
        col = _TIER_COLORS.get(r.size_tier or "", NEUTRAL_COLOR)
        ax.scatter(r.d_graph[0], r.d_graph[1], color=col, s=28, alpha=0.65, linewidths=0)
    lim_max = max(max(r.d_graph) for r in results) * 1.05
    ax.plot([0, lim_max], [0, lim_max], color="#cccccc", lw=1, ls="--", zorder=0)
    ax.set_xlim(0, lim_max); ax.set_ylim(0, lim_max)
    ax.set_xlabel("Graph dist: spawn → wool (left)", fontsize=10, color=LABEL_COLOR)
    ax.set_ylabel("Graph dist: spawn → wool (right)", fontsize=10, color=LABEL_COLOR)
    ax.set_title("Arm length symmetry  (diagonal = equal arms)",
                 fontsize=10, fontweight="bold", color="#111111")
    ax.legend(handles=tier_patches, fontsize=8, framealpha=0.9, edgecolor=SPINE_COLOR)

    # Panel 2: fork angle histogram
    ax = axes[0, 1]
    angles = [r.fork_angle_deg for r in results]
    ax.hist(angles, bins=30, color="#5B8DB8", edgecolor="white", linewidth=0.5)
    med = float(np.median(angles))
    ax.axvline(med, color="#333333", lw=1.4, ls="--")
    ax.text(med + 1, ax.get_ylim()[1] * 0.92, f"median {med:.0f}°",
            fontsize=8.5, color="#333333", va="top")
    ax.set_xlabel("Fork angle at spawn (degrees)", fontsize=10, color=LABEL_COLOR)
    ax.set_ylabel("Team-halves", fontsize=10, color=LABEL_COLOR)
    ax.set_title("Fork opening angle", fontsize=10, fontweight="bold", color="#111111")

    # Panel 3: arm asymmetry histogram
    ax = axes[1, 0]
    asym = [r.arm_asymmetry for r in results]
    ax.hist(asym, bins=25, color="#E8835A", edgecolor="white", linewidth=0.5)
    med_a = float(np.median(asym))
    ax.axvline(med_a, color="#333333", lw=1.4, ls="--")
    ax.text(med_a + 0.01, ax.get_ylim()[1] * 0.92, f"median {med_a:.2f}",
            fontsize=8.5, color="#333333", va="top")
    pct_sym = 100 * sum(1 for a in asym if a < 0.20) / len(asym)
    ax.text(0.97, 0.92, f"{pct_sym:.0f}% within 20% asymmetry",
            transform=ax.transAxes, fontsize=8.5, ha="right", va="top", color="#333333",
            bbox=dict(facecolor="white", edgecolor=SPINE_COLOR, boxstyle="round,pad=0.3", alpha=0.9))
    ax.set_xlabel("|d_left − d_right| / max(d_left, d_right)", fontsize=10, color=LABEL_COLOR)
    ax.set_ylabel("Team-halves", fontsize=10, color=LABEL_COLOR)
    ax.set_title("Arm length asymmetry  (0 = perfectly equal)",
                 fontsize=10, fontweight="bold", color="#111111")

    # Panel 4: spawn→wool distance by tier
    ax = axes[1, 1]
    tier_data: dict[str, list[float]] = defaultdict(list)
    for r in results:
        tier_data[r.size_tier or "?"].extend(r.d_graph)
    tiers_present = [t for t in _TIER_ORDER if t in tier_data]
    positions = range(len(tiers_present))
    bp = ax.boxplot(
        [tier_data[t] for t in tiers_present], positions=list(positions), widths=0.55,
        patch_artist=True, medianprops=dict(color="#333333", linewidth=1.5),
        whiskerprops=dict(color=SPINE_COLOR), capprops=dict(color=SPINE_COLOR),
        flierprops=dict(marker="o", markersize=3, alpha=0.4,
                        markerfacecolor=NEUTRAL_COLOR, markeredgewidth=0),
        boxprops=dict(linewidth=0),
    )
    for patch, tier in zip(bp["boxes"], tiers_present):
        patch.set_facecolor(_TIER_COLORS.get(tier, NEUTRAL_COLOR))
        patch.set_alpha(0.75)
    ax.set_xticks(list(positions)); ax.set_xticklabels(tiers_present)
    ax.set_xlabel("Size tier", fontsize=10, color=LABEL_COLOR)
    ax.set_ylabel("Graph distance (blocks)", fontsize=10, color=LABEL_COLOR)
    ax.set_title("Spawn → defending wool distance by tier",
                 fontsize=10, fontweight="bold", color="#111111")
    ax.grid(axis="y", color="#e8e8e8", lw=0.7, zorder=0)

    fig.suptitle(
        f"CTW Fork Layout Analysis — {n_maps} maps, {n_halves} team-halves"
        f"  (2 teams, 2 wools each)",
        fontsize=13, fontweight="bold", color="#111111", y=0.975,
    )
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(save_path), dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    logger.info("Saved fork analysis plot: %s", save_path)


# ---------------------------------------------------------------------------
# Layout layer grid (moved from layout_analysis/layout_grid.py)
# ---------------------------------------------------------------------------


def plot_layout_grid(
    map_slug: str,
    map_label: str,
    out_dir: Path,
    output_root: Path,
) -> None:
    """Render a 2×2 layout layer grid and save to out_dir/images/layout_case_study.png."""
    from layout_analysis.layout_grid import _LAYERS, _load_layer, _legend_patches

    fig, axes = plt.subplots(2, 2, figsize=(16, 14), layout='constrained')
    fig.suptitle(f'Layout layers — {map_label}', fontsize=14, fontweight='bold', y=0.98)

    for ax, (layer_key, layer_label) in zip(axes.flat, _LAYERS):
        df = _load_layer(output_root, map_slug, layer_key)
        ax.set_title(layer_label, fontsize=10)
        ax.set_xlabel('X'); ax.set_ylabel('Z')

        if df is None:
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
            ax.set_xlabel(f'X  (y {y_min}–{y_max})')

    images_dir = out_dir / 'images'
    images_dir.mkdir(exist_ok=True)
    out_path = images_dir / 'layout_case_study.png'
    fig.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    logger.info("Saved layout grid: %s", out_path)


# ---------------------------------------------------------------------------
# Resource and chest overlay (moved from layout_analysis/resources_plot.py)
# ---------------------------------------------------------------------------


def plot_resources(
    map_name: str,
    map_context: dict,
    map_data: dict,
    res_path: Path,
    chest_path: Path,
    save_path: Path,
    defense_buffer: float = 10.0,
    near_spawn_buffer: float = 15.0,
) -> None:
    """Draw resource block and chest locations on top of the map base layer."""
    from shapely.plotting import plot_polygon
    from layout_analysis.features import ZoneClassifier, detect_double_chests
    from common.geometry import block_centers

    res_df = pd.read_parquet(res_path) if res_path.exists() else None
    chest_df = pd.read_parquet(chest_path) if chest_path.exists() else None

    clf = ZoneClassifier(map_data, defense_buffer=defense_buffer,
                         near_spawn_buffer=near_spawn_buffer)
    if res_df is not None and not res_df.empty:
        res_df = clf.classify_dataframe(res_df)
    if chest_df is not None and not chest_df.empty:
        chest_df = clf.classify_dataframe(chest_df)
        chest_df = detect_double_chests(chest_df)
        chest_positions = (
            chest_df[['world_x', 'world_z', 'zone', 'team', 'is_double', 'chest_group_id']]
            .drop_duplicates(subset=['world_x', 'world_z'])
        )
    else:
        chest_positions = None

    fig, ax = plt.subplots(figsize=(14, 14))
    has_build = draw_map_base(ax, map_context)
    ax.set_aspect('equal'); ax.invert_yaxis()
    ax.set_title(f'Resources: {map_name}', fontsize=14, fontweight='bold')

    _ZONE_FILL = {
        'spawn':      ('#3399FF', 0.20, 'Spawn region'),
        'wool_room':  ('#FF44AA', 0.20, 'Wool room region'),
        'defense':    ('#FF8800', 0.12, 'Defense zone'),
        'near_spawn': ('#88CCFF', 0.12, 'Near-spawn zone'),
    }
    zone_handles: list = []
    for zone_key, (color, alpha, label) in _ZONE_FILL.items():
        geom = getattr(clf, f'_{zone_key}_geom', None)
        if geom is not None and not geom.is_empty:
            plot_polygon(geom, ax=ax, add_points=False, facecolor=color, edgecolor=color,
                         alpha=alpha, linewidth=0.5)
            zone_handles.append(mpatches.Patch(facecolor=color, alpha=0.5, label=label))

    _RES_COLOR = {
        'gold_block': '#FFD700', 'iron_block': '#B8B8B8', 'diamond_block': '#00BFFF',
    }
    res_handles: list = []
    if res_df is not None and not res_df.empty:
        for rtype, color in _RES_COLOR.items():
            mask = res_df['resource_type'] == rtype
            if not mask.any():
                continue
            sub = res_df[mask]
            ax.scatter(block_centers(sub['world_x'].to_numpy()),
                       block_centers(sub['world_z'].to_numpy()),
                       c=color, s=18, marker='s', zorder=4,
                       edgecolors='black', linewidths=0.3)
            res_handles.append(mpatches.Patch(facecolor=color, edgecolor='black',
                                              label=rtype.replace('_', ' ')))

    _ZONE_CHEST_COLOR = {
        'spawn': '#3399FF', 'near_spawn': '#88CCFF',
        'wool_room': '#FF44AA', 'defense': '#FF8800', 'field': NEUTRAL_COLOR,
    }
    chest_handles: list = []
    if chest_positions is not None and not chest_positions.empty:
        for zone_val, color in _ZONE_CHEST_COLOR.items():
            for is_double, marker, size in ((False, 'o', 40), (True, 'D', 55)):
                mask = ((chest_positions['zone'] == zone_val) &
                        (chest_positions['is_double'] == is_double))
                if not mask.any():
                    continue
                sub = chest_positions[mask]
                ax.scatter(block_centers(sub['world_x'].to_numpy()),
                           block_centers(sub['world_z'].to_numpy()),
                           c=color, s=size, marker=marker, zorder=5,
                           edgecolors='black', linewidths=0.5)
            chest_handles.append(mpatches.Patch(facecolor=color, edgecolor='black',
                                                label=f'Chest ({zone_val.replace("_", " ")})'))

    base_handles = map_base_legend_handles(has_build_region=has_build, map_context=map_context)
    all_handles = base_handles + zone_handles + res_handles + chest_handles
    if all_handles:
        ax.legend(handles=all_handles, loc='upper right', fontsize=7, framealpha=0.85, ncol=2)

    fig.tight_layout()
    fig.savefig(str(save_path), dpi=150, bbox_inches='tight')
    plt.close(fig)
    logger.info("Saved resources plot: %s", save_path)
