"""
Island Visualization

Visualization functions for displaying detected islands and their polygons,
and for visualizing island profile classifications.
"""

import logging
import math
import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Polygon, PathPatch
from matplotlib.path import Path as MplPath
from matplotlib.collections import PatchCollection, PolyCollection
from typing import Any, Optional

import colorsys

from common.geometry import block_centers
from common.visualization.map_primitives import draw_build_region, draw_island_outlines, island_path
from island_analysis.datatypes import Island
from island_analysis.profile import (
    IslandProfile,
    _TYPE_COLORS, _ALL_TYPES,
    _TYPE_SORT_METRIC, _TYPE_SORT_SCORE,
    _ARCHETYPE_COLORS, _ARCHETYPE_SORT_METRIC,
)

logger = logging.getLogger('ctw')


def generate_distinct_colors(n: int) -> list[tuple[float, float, float]]:
    """Generate n visually distinct colors."""
    colors = []
    for i in range(n):
        hue = i / n
        saturation = 0.7 + (i % 3) * 0.1
        lightness = 0.5
        rgb = colorsys.hls_to_rgb(hue, lightness, saturation)
        colors.append(rgb)
    return colors


def plot_islands(
    islands: list[Island],
    ax: Optional[Any] = None,
    title: str = "Detected Islands",
    show_blocks: bool = False,
    show_hulls: bool = True,
    show_labels: bool = True,
    show_centers: bool = True,
    alpha: float = 0.5,
    figsize: tuple[int, int] = (14, 10),
) -> tuple[Any, Any]:
    """
    Plot detected islands with various visualization options.

    Args:
        islands: List of Island objects
        ax: Optional matplotlib axes
        title: Plot title
        show_blocks: Show individual block positions
        show_hulls: Show polygon outlines
        show_labels: Show island IDs
        show_centers: Show island centers
        alpha: Transparency level
        figsize: Figure size if creating new figure
    """
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.figure

    colors = generate_distinct_colors(len(islands))

    for i, island in enumerate(islands):
        color = colors[i]

        # Plot blocks as scatter (centred on each block)
        if show_blocks:
            bc = block_centers(island.blocks)
            ax.scatter(
                bc[:, 0],
                bc[:, 1],
                c=[color],
                s=3,
                alpha=alpha * 0.5,
                label=f'Island {island.id}' if i < 10 else None
            )

        # Plot simplified polygon outline
        if show_hulls and island.simplified_polygon is not None:
            exterior = np.array(island.simplified_polygon['exterior'])
            ax.fill(exterior[:, 0], exterior[:, 1], color=color, alpha=alpha, edgecolor='black', linewidth=1)
            for hole_coords in island.simplified_polygon.get('holes', []):
                hole = np.array(hole_coords)
                ax.fill(hole[:, 0], hole[:, 1], color='white', edgecolor='black', linewidth=1, alpha=0.9)

        # Plot center
        if show_centers:
            ax.scatter(*island.center, c='black', s=50, marker='x', zorder=5)

        # Add label
        if show_labels:
            ax.annotate(
                f'{island.id}',
                island.center,
                fontsize=12,
                fontweight='bold',
                ha='center',
                va='center',
                color='white',
                bbox=dict(boxstyle='circle', facecolor=color, edgecolor='black')
            )

    ax.set_xlabel('X')
    ax.set_ylabel('Z')
    ax.set_title(title)
    ax.axis('equal')
    ax.invert_yaxis()
    ax.tick_params(colors='#666666')
    for spine in ax.spines.values():
        spine.set_edgecolor('#cccccc')

    return fig, ax


def plot_island_polygons(
    islands: list[Island],
    ax: Optional[Any] = None,
    title: str = "Island Polygons",
    show_blocks: bool = True,
    show_holes: bool = True,
    alpha: float = 0.6,
    figsize: tuple[int, int] = (14, 10),
) -> tuple[Any, Any]:
    """
    Plot island polygon outlines with optional hole visualization.

    Args:
        islands: List of Island objects with simplified_polygon
        ax: Optional matplotlib axes
        title: Plot title
        show_blocks: Show original block positions
        show_holes: Show detected internal holes
        alpha: Transparency level
        figsize: Figure size
    """
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.figure

    colors = generate_distinct_colors(len(islands))

    for i, island in enumerate(islands):
        color = colors[i]

        # Plot blocks as light background (centred on each block)
        if show_blocks:
            bc = block_centers(island.blocks)
            ax.scatter(
                bc[:, 0],
                bc[:, 1],
                c=[(*color, 0.2)],
                s=1,
                alpha=0.3
            )

        # Plot polygon outline
        if island.simplified_polygon is not None:
            exterior = np.array(island.simplified_polygon['exterior'])
            ax.fill(exterior[:, 0], exterior[:, 1], color=color, alpha=alpha, edgecolor='black', linewidth=1)
            for hole_coords in island.simplified_polygon.get('holes', []):
                hole = np.array(hole_coords)
                ax.fill(hole[:, 0], hole[:, 1], color='white', edgecolor='red',
                        linewidth=2, alpha=0.8)

        # Plot holes from detection
        if show_holes and island.holes:
            for hole in island.holes:
                hole_closed = np.vstack([hole, hole[0]])
                ax.fill(hole_closed[:, 0], hole_closed[:, 1],
                       color='white', edgecolor='red',
                       linewidth=2, alpha=0.8)

        # Label
        ax.annotate(
            f'{island.id}',
            island.center,
            fontsize=9,
            ha='center',
            va='center',
            color='white',
            fontweight='bold',
            bbox=dict(boxstyle='round', facecolor=color, edgecolor='black', alpha=0.8)
        )

    ax.set_xlabel('X')
    ax.set_ylabel('Z')
    ax.set_title(title)
    ax.axis('equal')
    ax.invert_yaxis()
    ax.tick_params(colors='#666666')
    for spine in ax.spines.values():
        spine.set_edgecolor('#cccccc')

    return fig, ax


def plot_island_detail(
    islands: list[Island],
    output_path: Optional[str] = None,
    figsize: tuple[int, int] = (20, 16),
    cols: int = 3,
) -> Any:
    """
    Create detailed view of each island's polygon.

    Args:
        islands: List of Island objects
        output_path: Path to save figure
        figsize: Figure size
        cols: Number of columns in grid
    """
    n_islands = len(islands)
    rows = (n_islands + cols - 1) // cols

    fig, axes = plt.subplots(rows, cols, figsize=figsize)
    axes = np.array(axes).flatten()

    colors = generate_distinct_colors(len(islands))

    for i, island in enumerate(islands):
        ax = axes[i]
        color = colors[i]

        # Plot the actual blocks as background (centred on each block)
        bc = block_centers(island.blocks)
        ax.scatter(
            bc[:, 0],
            bc[:, 1],
            c='lightgray',
            s=2,
            alpha=0.5,
            label='Blocks'
        )

        # Plot simplified polygon (filled)
        if island.simplified_polygon is not None:
            exterior = np.array(island.simplified_polygon['exterior'])
            ax.fill(exterior[:, 0], exterior[:, 1], color=color, alpha=0.4, edgecolor='black', linewidth=1.5)
            for hole_coords in island.simplified_polygon.get('holes', []):
                hole = np.array(hole_coords)
                ax.fill(hole[:, 0], hole[:, 1], color='white', edgecolor='red', linewidth=1.5, alpha=0.9)

        ax.set_title(f'Island {island.id}\n{island.area:,} blocks')
        ax.axis('equal')
        ax.invert_yaxis()

    # Hide unused subplots
    for i in range(n_islands, len(axes)):
        axes[i].set_visible(False)

    fig.suptitle('Island Polygon Detail View', fontsize=16, fontweight='bold')
    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        logger.debug(f"  Island detail: {output_path}")
    plt.close(fig)
    return fig



# ---------------------------------------------------------------------------
# Profile visualization (moved from island_analysis/profile.py)
# ---------------------------------------------------------------------------


def plot_island_profiles(
    map_context: dict,
    profiles: list[IslandProfile],
    output_path: str,
) -> None:
    """Two-panel per-map profile visualization.

    Left panel: Map canvas with island outlines filled by type color.
    Right panel: Feature scatter — rugosity vs compactness, bubble size ∝ area.
    """
    profile_by_id: dict[int, IslandProfile] = {
        island_id: p
        for p in profiles
        for island_id in p.raw_island_ids
    }

    fig, (ax_map, ax_scatter) = plt.subplots(1, 2, figsize=(18, 9))
    map_name = map_context.get('map_name', '')
    fig.suptitle(f'Island Profiles — {map_name}', fontsize=14, fontweight='bold')

    ax_map.set_aspect('equal')
    ax_map.invert_yaxis()
    ax_map.set_title('Island types (world view)', fontsize=11)
    draw_build_region(ax_map, map_context)

    for isl in map_context.get('islands', []):
        if isl.get('is_observer_island', False):
            continue
        profile = profile_by_id.get(isl['id'])
        color = _TYPE_COLORS.get(profile.island_type, '#cccccc') if profile else '#cccccc'
        poly = isl.get('simplified_polygon') or {}
        path = island_path(poly.get('exterior', []), poly.get('holes', []))
        if path is not None:
            ax_map.add_patch(PathPatch(path, facecolor=color, alpha=0.55,
                                       edgecolor='#333333', linewidth=0.7, zorder=2))
        cx, cz = isl.get('center', [0, 0])
        key_label = profile.canonical_key[:8] if profile else '?'
        ax_map.text(cx, cz, key_label, fontsize=5, ha='center', va='center',
                    color='#111111', zorder=3, clip_on=True)

    ax_map.autoscale_view()
    ax_map.set_xlabel('X', color='#444444')
    ax_map.set_ylabel('Z', color='#444444')
    ax_map.tick_params(colors='#666666')
    for spine in ax_map.spines.values():
        spine.set_edgecolor('#cccccc')

    map_legend = [
        mpatches.Patch(facecolor=_TYPE_COLORS[t], edgecolor='#333333', linewidth=0.5,
                       alpha=0.55, label=t)
        for t in _ALL_TYPES if t in {p.island_type for p in profiles}
    ]
    if map_legend:
        ax_map.legend(handles=map_legend, fontsize=7, loc='lower left',
                      title='Island type', title_fontsize=7)

    ax_scatter.set_title('rugosity vs compactness', fontsize=11)
    ax_scatter.set_xlabel('Rugosity (perimeter / bbox perimeter)')
    ax_scatter.set_ylabel('Compactness')

    plotted_types: set[str] = set()
    for profile in profiles:
        feat = profile.features
        color = _TYPE_COLORS.get(profile.island_type, '#cccccc')
        bubble_size = max(20, min(800, feat.area / 5))
        ax_scatter.scatter(feat.rugosity, feat.compactness, s=bubble_size,
                           c=color, alpha=0.75, edgecolors='#333333', linewidths=0.5, zorder=3)
        ax_scatter.annotate(profile.canonical_key[:8], (feat.rugosity, feat.compactness),
                            fontsize=5, ha='left', va='bottom', color='#333333')
        plotted_types.add(profile.island_type)

    ax_scatter.axvline(1.2, color='#c0392b', linestyle='--', linewidth=0.7,
                       alpha=0.5, label='rugged threshold (rugosity=1.2)')
    ax_scatter.axhline(0.88, color='#e74c3c', linestyle='--', linewidth=0.7,
                       alpha=0.5, label='circle threshold (convexity=0.88)')

    legend_patches = [
        mpatches.Patch(facecolor=_TYPE_COLORS[t], edgecolor='#333333', linewidth=0.5, label=t)
        for t in _ALL_TYPES if t in plotted_types
    ]
    ax_scatter.legend(handles=legend_patches, fontsize=7, loc='upper right')

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    plt.savefig(output_path, dpi=120, bbox_inches='tight')
    plt.close(fig)
    logger.debug('  island profiling: saved %s', output_path)


def plot_profile_landscape(
    all_profiles: list[tuple[str, IslandProfile]],
    feature_x: str,
    feature_y: str,
    output_path: str,
) -> None:
    """Cross-map scatter: all canonical islands from all maps on feature axes."""
    fig, ax = plt.subplots(figsize=(14, 10))
    ax.set_title(f'Island landscape — {feature_x} vs {feature_y}', fontsize=13)
    ax.set_xlabel(feature_x.replace('_', ' ').title())
    ax.set_ylabel(feature_y.replace('_', ' ').title())

    plotted_types: set[str] = set()
    for map_slug, profile in all_profiles:
        feat = profile.features
        x_val = getattr(feat, feature_x, None)
        y_val = getattr(feat, feature_y, None)
        if x_val is None or y_val is None:
            continue
        color = _TYPE_COLORS.get(profile.island_type, '#cccccc')
        ax.scatter(x_val, y_val, s=60, c=color, alpha=0.7,
                   edgecolors='#555555', linewidths=0.4, zorder=3)
        ax.annotate(f'{map_slug[:6]}\n{profile.canonical_key[:6]}',
                    (x_val, y_val), fontsize=4, ha='left', va='bottom', color='#333333')
        plotted_types.add(profile.island_type)

    if feature_x == 'aspect_ratio':
        ax.axvline(2.5, color='#16a085', linestyle='--', linewidth=0.7,
                   alpha=0.5, label='linear threshold (AR=2.5)')
    if feature_x == 'rugosity':
        ax.axvline(1.5, color='#c0392b', linestyle='--', linewidth=0.7,
                   alpha=0.5, label='rugged threshold (rugosity=1.5)')
    if feature_y == 'compactness':
        ax.axhline(0.65, color='#e74c3c', linestyle='--', linewidth=0.7,
                   alpha=0.5, label='circle threshold (comp=0.65)')

    legend_patches = [
        mpatches.Patch(facecolor=_TYPE_COLORS[t], edgecolor='#555555', linewidth=0.5, label=t)
        for t in _ALL_TYPES if t in plotted_types
    ]
    ax.legend(handles=legend_patches, fontsize=8, loc='upper right')

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    plt.savefig(output_path, dpi=130, bbox_inches='tight')
    plt.close(fig)
    logger.info('Saved landscape plot: %s', output_path)


def save_profile_examples(
    all_profiles: list[tuple[str, IslandProfile, dict]],
    output_dir: str,
    n_per_type: int = 5,
) -> list[dict]:
    """Render a labeled mosaic strip of n_per_type diverse examples per type."""
    os.makedirs(output_dir, exist_ok=True)

    by_type: dict[str, list[tuple[str, IslandProfile, dict]]] = {}
    for map_slug, profile, island_dict in all_profiles:
        if profile.island_type not in _ALL_TYPES:
            continue
        by_type.setdefault(profile.island_type, []).append((map_slug, profile, island_dict))

    metadata: list[dict] = []

    for island_type, entries in by_type.items():
        if not entries:
            continue

        if island_type in _TYPE_SORT_SCORE:
            score_fn = _TYPE_SORT_SCORE[island_type]
            entries.sort(key=lambda e: (-score_fn(e[1].features), e[0]))
        else:
            sort_attr, sort_desc = _TYPE_SORT_METRIC.get(island_type, ('compactness', True))
            entries.sort(key=lambda e: (
                -getattr(e[1].features, sort_attr) if sort_desc
                else getattr(e[1].features, sort_attr), e[0],
            ))

        n = len(entries)
        if n == 1:
            indices = [0]
        elif n <= n_per_type:
            indices = list(range(n))
        elif n_per_type >= 2:
            tail_count = n_per_type - 2
            if tail_count <= 0:
                indices = [0, 1]
            else:
                tail_step = (n - 1 - 1) / tail_count
                tail = [round(1 + (i + 1) * tail_step) for i in range(tail_count)]
                indices = list(dict.fromkeys([0, 1] + tail))
        else:
            indices = [0]

        selected = [entries[i] for i in indices]
        cols = len(selected)
        color = _TYPE_COLORS.get(island_type, '#cccccc')

        fig, axes = plt.subplots(1, cols, figsize=(cols * 2.5, 2.8))
        fig.suptitle(f'{island_type}  —  {cols} diverse examples  (of {n} total)',
                     fontsize=9, fontweight='bold')
        axes_flat = [axes] if cols == 1 else list(axes)

        for cell_idx, (map_slug, profile, island_dict) in enumerate(selected):
            ax = axes_flat[cell_idx]
            ax.set_aspect('equal')
            ax.axis('off')

            poly = island_dict.get('simplified_polygon') or {}
            exterior = poly.get('exterior') or []
            holes = poly.get('holes') or []

            if len(exterior) >= 3:
                pts = np.asarray(exterior, dtype=float)
                min_xy = pts.min(axis=0)
                scale = max(float(np.ptp(pts, axis=0).max()), 1.0)
                pts_n = ((pts - min_xy) / scale).tolist()
                holes_n = [
                    ((np.asarray(h, dtype=float) - min_xy) / scale).tolist()
                    for h in holes if len(h) >= 3
                ]
                path = island_path(pts_n, holes_n)
                if path is not None:
                    ax.add_patch(PathPatch(path, facecolor=color, alpha=0.6,
                                           edgecolor='#333333', linewidth=0.8))
                    ax.set_xlim(-0.05, 1.05)
                    ax.set_ylim(-0.05, 1.05)
                    ax.invert_yaxis()

            ax.set_title(f'{map_slug[:8]}\n{profile.canonical_key[:8]}', fontsize=5.5, pad=2)

            f = profile.features
            features_summary: dict = {
                'area': f.area, 'aspect_ratio': f.aspect_ratio,
                'bbox_fill_ratio': f.bbox_fill_ratio, 'convexity': f.convexity,
                'rugosity': f.rugosity, 'compactness': round(f.compactness, 4),
                'hole_count': f.hole_count, 'bbox_width': f.bbox_width,
                'bbox_height': f.bbox_height,
            }
            if f.bbox_cutout_count is not None:
                features_summary['bbox_cutout_count'] = f.bbox_cutout_count
                features_summary['bbox_cutout_coverage'] = f.bbox_cutout_coverage
            if f.skeleton_topology is not None:
                features_summary['skeleton_topology'] = f.skeleton_topology
                features_summary['skeleton_junction_count'] = f.skeleton_junction_count
                features_summary['skeleton_endpoint_count'] = f.skeleton_endpoint_count
            if f.circle_fit_residual is not None:
                features_summary['circle_fit_residual'] = f.circle_fit_residual
            if f.ellipse_residual is not None:
                features_summary['ellipse_residual'] = f.ellipse_residual

            metadata.append({
                'type': island_type, 'n': cell_idx + 1,
                'filename': f'{island_type}.png',
                'canonical_key': profile.canonical_key, 'map_slug': map_slug,
                'features': features_summary,
            })

        out_path = os.path.join(output_dir, f'{island_type}.png')
        plt.tight_layout()
        plt.savefig(out_path, dpi=130, bbox_inches='tight')
        plt.close(fig)
        logger.info('Saved examples: %s', out_path)

    return metadata


def plot_profile_mosaic(
    all_profiles: list[tuple[str, IslandProfile, dict]],
    island_type_filter: Optional[str],
    output_path_template: str,
) -> list[str]:
    """Island shape mosaic grouped by archetype, one PNG per archetype."""
    by_archetype: dict[str, list[tuple[str, IslandProfile, dict]]] = {}
    for map_slug, profile, island_dict in all_profiles:
        if island_type_filter:
            if profile.archetype != island_type_filter and profile.island_type != island_type_filter:
                continue
        by_archetype.setdefault(profile.archetype, []).append((map_slug, profile, island_dict))

    output_files: list[str] = []
    for archetype, entries in by_archetype.items():
        n = len(entries)
        if n == 0:
            continue

        sort_attr, sort_desc = _ARCHETYPE_SORT_METRIC.get(archetype, ('compactness', True))
        entries.sort(key=lambda e: (
            -getattr(e[1].features, sort_attr) if sort_desc
            else getattr(e[1].features, sort_attr), e[0],
        ))

        cols = min(6, n)
        rows = math.ceil(n / cols)
        fig, axes = plt.subplots(rows, cols, figsize=(cols * 2.5, rows * 2.5))
        fig.suptitle(f'Island mosaic — {archetype} ({n} shapes)',
                     fontsize=13, fontweight='bold')

        if rows == 1 and cols == 1:
            axes_flat = [axes]
        else:
            axes_flat = list(axes.flat)

        color = _ARCHETYPE_COLORS.get(archetype, '#cccccc')

        for idx, (map_slug, profile, island_dict) in enumerate(entries):
            ax = axes_flat[idx]
            ax.set_aspect('equal')
            ax.axis('off')

            poly = island_dict.get('simplified_polygon') or {}
            exterior = poly.get('exterior') or []
            holes = poly.get('holes') or []

            if len(exterior) >= 3:
                pts = np.asarray(exterior, dtype=float)
                min_xy = pts.min(axis=0)
                scale = max(np.ptp(pts, axis=0).max(), 1.0)
                pts_n = ((pts - min_xy) / scale).tolist()
                holes_n = [
                    ((np.asarray(h, dtype=float) - min_xy) / scale).tolist()
                    for h in holes if len(h) >= 3
                ]
                path = island_path(pts_n, holes_n)
                if path is not None:
                    ax.add_patch(PathPatch(path, facecolor=color, alpha=0.6,
                                           edgecolor='#333333', linewidth=0.8))
                    ax.set_xlim(-0.05, 1.05)
                    ax.set_ylim(-0.05, 1.05)
                    ax.invert_yaxis()

            boundary_tag = f' [{profile.boundary}]' if profile.boundary != 'clean' else ''
            ax.set_title(f'{map_slug[:8]}\n{profile.canonical_key[:8]}{boundary_tag}',
                         fontsize=5.5, pad=2)

        for idx in range(len(entries), len(axes_flat)):
            axes_flat[idx].axis('off')

        out_path = output_path_template.replace('{type}', archetype)
        plt.tight_layout()
        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
        plt.savefig(out_path, dpi=130, bbox_inches='tight')
        plt.close(fig)
        output_files.append(out_path)
        logger.info('Saved mosaic: %s', out_path)

    return output_files


def plot_feature_distributions(
    all_profiles: list[tuple[str, IslandProfile]],
    output_path: str,
) -> None:
    """Feature distribution histograms across all canonical islands from all maps."""
    numeric_features: list[tuple[str, str]] = [
        ('bbox_fill_ratio', 'BBox Fill Ratio'), ('rugosity', 'Rugosity'),
        ('aspect_ratio', 'Aspect Ratio'), ('compactness', 'Compactness'),
        ('convexity', 'Convexity'), ('pca_elongation', 'PCA Elongation'),
    ]

    fig, axes = plt.subplots(1, len(numeric_features), figsize=(5 * len(numeric_features), 5))
    fig.suptitle('Island feature distributions (all maps)', fontsize=13, fontweight='bold')

    type_data: dict[str, dict[str, list[float]]] = {
        t: {fname: [] for fname, _ in numeric_features} for t in _ALL_TYPES
    }
    for _map_slug, profile in all_profiles:
        feat = profile.features
        if profile.island_type not in type_data:
            continue
        for fname, _ in numeric_features:
            val = getattr(feat, fname, None)
            if val is not None:
                type_data[profile.island_type][fname].append(float(val))

    for col_idx, (fname, flabel) in enumerate(numeric_features):
        ax = axes[col_idx]
        ax.set_title(flabel, fontsize=10)
        ax.set_xlabel(flabel)
        if col_idx == 0:
            ax.set_ylabel('Count')

        all_vals = [v for t in _ALL_TYPES for v in type_data[t][fname]]
        if not all_vals:
            continue
        bins = np.linspace(min(all_vals), max(all_vals), 25)
        bottom = np.zeros(len(bins) - 1)
        for island_type in _ALL_TYPES:
            vals = type_data[island_type][fname]
            if not vals:
                continue
            counts, _ = np.histogram(vals, bins=bins)
            ax.bar(bins[:-1], counts, width=np.diff(bins), bottom=bottom,
                   color=_TYPE_COLORS[island_type], alpha=0.85, align='edge', label=island_type)
            bottom += counts

    axes[0].axvline(0.85, color='#2980b9', linestyle='--', linewidth=1.0, alpha=0.7)
    axes[1].axvline(1.2, color='#c0392b', linestyle='--', linewidth=1.0, alpha=0.7)
    axes[2].axvline(2.5, color='#16a085', linestyle='--', linewidth=1.0, alpha=0.7)
    axes[4].axvline(0.88, color='#e74c3c', linestyle='--', linewidth=1.0, alpha=0.7)

    legend_patches = [
        mpatches.Patch(facecolor=_TYPE_COLORS[t], edgecolor='#555555', linewidth=0.5, label=t)
        for t in _ALL_TYPES
    ]
    axes[-1].legend(handles=legend_patches, fontsize=7, loc='upper right', bbox_to_anchor=(1.0, 1.0))

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    plt.savefig(output_path, dpi=130, bbox_inches='tight')
    plt.close(fig)
    logger.info('Saved distribution plot: %s', output_path)
