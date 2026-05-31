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
        import matplotlib; matplotlib.use('Agg')
        from layout_analysis.visualization import plot_resources
        plot_resources(
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

