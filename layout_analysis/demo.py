"""Build and assemble demo assets for the traffic graph documentation.

Public entry point:
- run(args): build traffic graph assets for a map and copy to docs/demo/assets/<slug>/
"""

import sys
from pathlib import Path


_DEMO_ROLES = [
    'deep_attacker', 'defender', 'roamer', 'traversal',
    'high_killer', 'skybridge', 'bow_archer', 'builder',
]

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run(args: object) -> None:
    """Build traffic graph assets for a map and copy to docs/demo/assets/<slug>/."""
    import glob as glob_mod
    import shutil
    import subprocess

    map_slug = args.map
    output_dir = _PROJECT_ROOT / args.output_root / map_slug
    assets_dir = _PROJECT_ROOT / args.assets_dir / map_slug

    if not output_dir.is_dir():
        print(f"Error: output directory not found: {output_dir}")
        print(f"  Run 'ctw run --map {map_slug}' first.")
        sys.exit(1)

    ctw_script = str(_PROJECT_ROOT / 'ctw.py')

    # ── Step 1: build / refresh traffic graph ────────────────────────────
    print(f"\n[1/3] Building traffic graph for '{map_slug}' ...")
    cmd = [sys.executable, ctw_script, 'matches', 'traffic-graph', '--map', map_slug]
    if args.force:
        cmd.append('--force')
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("  Error: traffic-graph build failed.")
        sys.exit(result.returncode)

    # ── Step 2: strategy comparison plot ─────────────────────────────────
    print(f"\n[2/3] Building strategy comparison for '{map_slug}' ...")
    cmd_cmp = [sys.executable, ctw_script, 'matches', 'traffic-graph',
               '--map', map_slug, '--compare']
    result = subprocess.run(cmd_cmp)
    if result.returncode != 0:
        print("  Error: strategy comparison failed.")
        sys.exit(result.returncode)

    # ── Step 3: life-segment diagnostics ─────────────────────────────────
    print(f"\n[3/3] Running life-segment diagnostics for '{map_slug}' ...")
    diag_script = _PROJECT_ROOT / 'scripts' / 'run_traffic_diagnostics.py'
    result = subprocess.run([sys.executable, str(diag_script), '--map', map_slug])
    if result.returncode != 0:
        print("  Error: diagnostics failed.")
        sys.exit(result.returncode)

    # ── Copy assets ───────────────────────────────────────────────────────
    assets_dir.mkdir(parents=True, exist_ok=True)
    copies: list[str] = []

    def _copy(src: Path, dst: Path) -> None:
        if src.exists():
            shutil.copy2(src, dst)
            copies.append(dst.name)
        else:
            print(f"  Warning: expected file not found: {src.name}")

    _copy(output_dir / 'images' / 'traffic_graph.png',
          assets_dir / 'traffic_graph_overview.png')
    _copy(output_dir / 'images' / 'traffic_strategy_comparison.png',
          assets_dir / 'traffic_strategy_comparison.png')

    diag_dir = output_dir / 'traffic_graph_diagnostics'
    newest_per_role: dict[str, Path] = {}
    for png in glob_mod.glob(str(diag_dir / '*.png')):
        png_path = Path(png)
        for role in _DEMO_ROLES:
            if role in png_path.name:
                prev = newest_per_role.get(role)
                if prev is None or png_path.stat().st_mtime > prev.stat().st_mtime:
                    newest_per_role[role] = png_path
                break
    for role, src_path in newest_per_role.items():
        _copy(src_path, assets_dir / f'life_{role}.png')

    print(f"\nAssets written to: {assets_dir}")
    print(f"  {len(copies)} files copied: {', '.join(copies)}")
