"""Resource block and chest location visualization for one or more maps.

Public entry point:
- run(args): load map data and render the resources overview plot
"""

import json
import sys
from pathlib import Path


def run(args: object) -> None:
    """Plot chest and resource block locations for one or more maps."""
    map_names = [m.strip() for m in args.map.split(',') if m.strip()]
    output_root = Path(args.output)
    defense_buffer: float = args.defense_buffer
    near_spawn_buffer: float = args.near_spawn_buffer

    for map_name in map_names:
        map_output = output_root / map_name
        ctx_path = map_output / 'map_context.json'
        data_path = map_output / 'map_data.json'
        res_path = map_output / 'layout_resource_blocks.parquet'
        chest_path = map_output / 'layout_chest_contents.parquet'

        missing = [p for p in (ctx_path, data_path) if not p.exists()]
        if missing:
            print(f"[{map_name}] missing files: {[str(p) for p in missing]}", file=sys.stderr)
            continue

        with open(ctx_path) as f:
            map_context = json.load(f)
        with open(data_path) as f:
            map_data = json.load(f)

        images_dir = map_output / 'images'
        images_dir.mkdir(exist_ok=True)
        save_path = images_dir / 'resources_overview.png'
        _plot_resources_figure(
            map_name=map_name,
            map_context=map_context,
            map_data=map_data,
            res_path=res_path,
            chest_path=chest_path,
            save_path=save_path,
            defense_buffer=defense_buffer,
            near_spawn_buffer=near_spawn_buffer,
        )
        print(f"[{map_name}] saved: {save_path}")


def _plot_resources_figure(
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
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import pandas as pd
    from shapely.plotting import plot_polygon

    from common.visualization.map_primitives import draw_map_base, map_base_legend_handles
    from layout_analysis.features import ZoneClassifier, ChestExtractor, detect_double_chests
    from common.geometry import block_centers

    res_df: pd.DataFrame | None = None
    chest_df: pd.DataFrame | None = None
    if res_path.exists():
        res_df = pd.read_parquet(res_path)
    if chest_path.exists():
        chest_df = pd.read_parquet(chest_path)

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
    ax.set_aspect('equal')
    ax.invert_yaxis()
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
        'gold_block':    '#FFD700',
        'iron_block':    '#B8B8B8',
        'diamond_block': '#00BFFF',
    }
    res_handles: list = []
    if res_df is not None and not res_df.empty:
        for rtype, color in _RES_COLOR.items():
            mask = res_df['resource_type'] == rtype
            if not mask.any():
                continue
            sub = res_df[mask]
            xs = block_centers(sub['world_x'].to_numpy())
            zs = block_centers(sub['world_z'].to_numpy())
            ax.scatter(xs, zs, c=color, s=18, marker='s', zorder=4, label=rtype,
                       edgecolors='black', linewidths=0.3)
            res_handles.append(
                mpatches.Patch(facecolor=color, edgecolor='black', label=rtype.replace('_', ' '))
            )

    _ZONE_CHEST_COLOR = {
        'spawn':      '#3399FF',
        'near_spawn': '#88CCFF',
        'wool_room':  '#FF44AA',
        'defense':    '#FF8800',
        'field':      '#888888',
    }
    chest_handles: list = []
    if chest_positions is not None and not chest_positions.empty:
        for zone_val, color in _ZONE_CHEST_COLOR.items():
            for is_double, marker, size, suffix in ((False, 'o', 40, ''), (True, 'D', 55, ' (double)')):
                mask = (chest_positions['zone'] == zone_val) & (chest_positions['is_double'] == is_double)
                if not mask.any():
                    continue
                sub = chest_positions[mask]
                xs = block_centers(sub['world_x'].to_numpy())
                zs = block_centers(sub['world_z'].to_numpy())
                ax.scatter(xs, zs, c=color, s=size, marker=marker, zorder=5,
                           edgecolors='black', linewidths=0.5)
            label = f'Chest ({zone_val.replace("_", " ")})'
            chest_handles.append(
                mpatches.Patch(facecolor=color, edgecolor='black', label=label)
            )

    base_handles = map_base_legend_handles(has_build_region=has_build)
    all_handles = base_handles + zone_handles + res_handles + chest_handles
    if all_handles:
        ax.legend(handles=all_handles, loc='upper right', fontsize=7,
                  framealpha=0.85, ncol=2)

    fig.tight_layout()
    fig.savefig(str(save_path), dpi=150, bbox_inches='tight')
    plt.close(fig)
