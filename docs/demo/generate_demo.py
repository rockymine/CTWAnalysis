#!/usr/bin/env python3
"""Generate demo images for a CTW map.

Creates a set of clean, legend-free images showcasing the analysis pipeline
output. Images are saved with stable numbered filenames so the Markdown
showcase page never breaks when internal naming changes.

Usage:
    python docs/demo/generate_demo.py --map Ingwaz
    python docs/demo/generate_demo.py --map Ingwaz --match 57 --player 0
    python docs/demo/generate_demo.py --map Ingwaz --output docs/demo/assets/ingwaz
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path so imports work when running directly
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import matplotlib.pyplot as plt
import numpy as np

from ctw.common import resolve_map_folder, resolve_output_dir, ensure_match_db
from visualization.map_primitives import (
    draw_block_base,
    draw_build_region,
    draw_island_outlines,
    draw_pois,
    BlockBaseStyle,
    IslandOutlineStyle,
)


# ── Shared figure helpers ───────────────────────────────────────────────

def _new_figure(figsize=(16, 10)):
    """Create a clean figure with no decorations."""
    fig, ax = plt.subplots(figsize=figsize)
    ax.set_aspect('equal')
    ax.axis('off')
    return fig, ax


def _save(fig, path, dpi=200):
    """Save figure and close."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    fig.savefig(str(path), dpi=dpi, bbox_inches='tight', pad_inches=0.05)
    plt.close(fig)
    print(f"  Saved {path}")


def _set_bounds_from_context(ax, map_context, padding=2):
    """Set axis limits from map bounding box with some padding."""
    bbox = map_context.get('bounding_box')
    if bbox:
        min_x, max_x, min_z, max_z = bbox
        ax.set_xlim(min_x - padding, max_x + padding)
        ax.set_ylim(min_z - padding, max_z + padding)


# ── Skeleton / connectivity layer helpers ───────────────────────────────

def _draw_skeleton_edges(ax, map_context, map_graph):
    """Draw skeleton edge pixel paths from map_graph JSON data."""
    graph_islands_by_id = {
        ie['island_id']: ie for ie in map_graph.get('islands', [])
    }
    for island in map_context.get('islands', []):
        iid = island['id']
        graph_island = graph_islands_by_id.get(iid, {})
        skeleton = graph_island.get('skeleton')
        if skeleton is None:
            continue

        edge_pixels = skeleton.get('edge_pixels', {})
        for edge_key, ep_data in edge_pixels.items():
            pixels = ep_data.get('pixels', [])
            if len(pixels) < 2:
                continue
            px = np.array(pixels)
            ax.plot(
                px[:, 0], px[:, 1],
                color='lightblue',
                linewidth=1,
                alpha=0.8,
                zorder=2,
            )


def _draw_skeleton_nodes(ax, map_context, map_graph):
    """Draw skeleton nodes (endpoints + junctions) from map_graph JSON data."""
    graph_islands_by_id = {
        ie['island_id']: ie for ie in map_graph.get('islands', [])
    }
    for island in map_context.get('islands', []):
        iid = island['id']
        graph_island = graph_islands_by_id.get(iid, {})
        skeleton = graph_island.get('skeleton')
        if skeleton is None:
            continue

        for node in skeleton['nodes']:
            if node['type'] == 'endpoint':
                ax.scatter(
                    node['x'], node['z'],
                    s=30, c='#1d3557',
                    edgecolors='white', linewidths=0.6,
                    zorder=7,
                )
            else:
                ax.scatter(
                    node['x'], node['z'],
                    s=12, c='#555555',
                    alpha=0.5, zorder=3,
                )


def _draw_void_links(ax, map_graph):
    """Draw void link edges (dashed red) from map_graph JSON data."""
    graph_section = map_graph.get('map_graph', {})
    node_lookup = {
        n['map_node_id']: n for n in graph_section.get('nodes', [])
    }

    void_edges = [
        e for e in graph_section.get('edges', [])
        if e['edge_type'] == 'void_link'
    ]
    if not void_edges:
        return

    max_dist = max(e['distance'] for e in void_edges)
    for edge in void_edges:
        src_c = edge.get('src_coords', node_lookup.get(edge['src'], {}).get('coords'))
        dst_c = edge.get('dst_coords', node_lookup.get(edge['dst'], {}).get('coords'))
        if src_c is None or dst_c is None:
            continue

        thickness = 1.0 + 2.0 * (1.0 - edge['distance'] / max_dist)
        ax.plot(
            [src_c[0], dst_c[0]],
            [src_c[1], dst_c[1]],
            color='#e63946',
            linestyle='--',
            linewidth=thickness,
            alpha=0.8,
            zorder=5,
        )


def _draw_map_nodes(ax, map_graph):
    """Draw map-level endpoint nodes (orange dots)."""
    graph_section = map_graph.get('map_graph', {})
    for node in graph_section.get('nodes', []):
        x, z = node['coords']
        ax.scatter(
            x, z,
            s=20, c='orange',
            edgecolors='black', linewidths=0.4,
            zorder=9,
        )


# ── Image generators ───────────────────────────────────────────────────

def gen_blocks(map_folder, map_context, output_path):
    """01 — Block layout colored by island with POI markers."""
    fig, ax = _new_figure()
    draw_block_base(ax, map_folder, map_context,
                    style=BlockBaseStyle(fill_alpha=0.25, edge_alpha=0.4))
    draw_pois(ax, map_context)
    _set_bounds_from_context(ax, map_context)
    ax.invert_yaxis()
    _save(fig, output_path)


def gen_regions(map_context, output_path):
    """02 — XML regions: build region + island outlines + POIs."""
    fig, ax = _new_figure()
    draw_build_region(ax, map_context)
    draw_island_outlines(ax, map_context)
    draw_pois(ax, map_context)
    _set_bounds_from_context(ax, map_context)
    ax.invert_yaxis()
    _save(fig, output_path)


def gen_skeleton(map_context, map_graph, output_path):
    """03 — Skeleton overlay: island outlines + skeleton edges/nodes + POIs."""
    fig, ax = _new_figure()
    draw_island_outlines(ax, map_context)
    _draw_skeleton_edges(ax, map_context, map_graph)
    _draw_skeleton_nodes(ax, map_context, map_graph)
    draw_pois(ax, map_context)
    _set_bounds_from_context(ax, map_context)
    ax.invert_yaxis()
    _save(fig, output_path)


def gen_outline(map_context, output_path):
    """04 — Polygon outlines only (thicker lines)."""
    fig, ax = _new_figure()
    draw_island_outlines(
        ax, map_context,
        style=IslandOutlineStyle(
            exterior_linewidth=1.5, exterior_alpha=1.0,
            hole_linewidth=1.0, hole_alpha=0.8,
        ),
    )
    draw_pois(ax, map_context)
    _set_bounds_from_context(ax, map_context)
    ax.invert_yaxis()
    _save(fig, output_path)


def gen_connectivity(map_context, map_graph, output_path):
    """05 — Full connectivity graph (all layers, no legend/text)."""
    fig, ax = _new_figure()
    draw_build_region(ax, map_context)
    draw_island_outlines(ax, map_context)
    _draw_skeleton_edges(ax, map_context, map_graph)
    _draw_skeleton_nodes(ax, map_context, map_graph)
    draw_pois(ax, map_context)
    _draw_void_links(ax, map_graph)
    _draw_map_nodes(ax, map_graph)
    _set_bounds_from_context(ax, map_context)
    ax.invert_yaxis()
    _save(fig, output_path)


def gen_trace_single(map_context, match_file, player_id, map_graph, map_folder,
                     output_path):
    """06 — Single player trace (no legend/stats/title)."""
    from match_analysis.visualization import plot_player_traces

    plot_player_traces(
        map_context, str(match_file), [player_id], output_path,
        map_graph=map_graph,
        show_legend=False,
        show_stats=False,
        show_title=False,
        map_base='outline',
        map_folder=map_folder,
    )
    print(f"  Saved {output_path}")


def gen_trace_team(map_context, match_file, player_ids, map_graph, map_folder,
                   output_path):
    """07 — All players with team coloring (no legend/stats/title)."""
    from match_analysis.visualization import plot_player_traces

    plot_player_traces(
        map_context, str(match_file), player_ids, output_path,
        map_graph=map_graph,
        show_legend=False,
        show_stats=False,
        show_title=False,
        color_mode='team',
        map_base='outline',
        map_folder=map_folder,
    )
    print(f"  Saved {output_path}")


# ── Main ────────────────────────────────────────────────────────────────

STABLE_NAMES = [
    '01_blocks.png',
    '02_regions.png',
    '03_skeleton.png',
    '04_outline.png',
    '05_connectivity.png',
    '06_trace_single.png',
    '07_trace_team.png',
]


def main():
    parser = argparse.ArgumentParser(
        description='Generate demo images for a CTW map.',
    )
    parser.add_argument('--map', required=True,
                        help='Map name or path (e.g. Ingwaz)')
    parser.add_argument('--output',
                        help='Output directory (default: docs/demo/assets/<map>)')
    parser.add_argument('--match', type=int, default=57,
                        help='Match ID for trace images (default: 57)')
    parser.add_argument('--player', type=int, default=0,
                        help='Player ID for single-player trace (default: 0)')
    args = parser.parse_args()

    # Resolve paths
    map_folder = resolve_map_folder(args.map)
    map_name = map_folder.name
    map_output_dir = resolve_output_dir(map_folder, create=False)
    output_dir = Path(args.output) if args.output else (
        _SCRIPT_DIR / 'assets' / map_name
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    def _find(rel_path):
        """Check map_output_dir first, fall back to map_folder."""
        p = map_output_dir / rel_path
        if p.exists():
            return p
        p = map_folder / rel_path
        if p.exists():
            return p
        return None

    print(f"Generating demo images for {map_name}")
    print(f"Output: {output_dir}")

    # Load shared data
    context_path = _find('island_analysis/map_context.json')
    if context_path is None:
        print(f"Error: map_context.json not found. Run 'ctw islands --map {map_name}' first.")
        sys.exit(1)
    with open(context_path) as f:
        map_context = json.load(f)

    graph_path = _find('map_graph.json')
    if graph_path is None:
        print(f"Error: map_graph.json not found. Run 'ctw islands --map {map_name}' first.")
        sys.exit(1)
    with open(graph_path) as f:
        map_graph = json.load(f)

    # Load match data for trace images
    ensure_match_db()
    from match_analysis.services import get_match_file, get_match_player_ids

    match_file = None
    all_player_ids = []
    try:
        match_file_str, _ = get_match_file(args.match)
        match_file = Path(match_file_str)
        if not match_file.exists():
            print(f"Warning: match file {match_file} not found, skipping trace images")
            match_file = None
        else:
            all_player_ids = get_match_player_ids(str(match_file))
    except ValueError:
        print(f"Warning: match {args.match} not in DB, skipping trace images")

    # Resolve layout dir (where layout_bedrock.parquet lives)
    layout_dir = map_output_dir if (map_output_dir / 'layout_bedrock.parquet').exists() else map_folder

    # Generate images
    outputs = []

    print("\n[1/7] Block layout...")
    path = output_dir / STABLE_NAMES[0]
    gen_blocks(layout_dir, map_context, path)
    outputs.append(path)

    print("[2/7] XML regions...")
    path = output_dir / STABLE_NAMES[1]
    gen_regions(map_context, path)
    outputs.append(path)

    print("[3/7] Skeleton overlay...")
    path = output_dir / STABLE_NAMES[2]
    gen_skeleton(map_context, map_graph, path)
    outputs.append(path)

    print("[4/7] Polygon outlines...")
    path = output_dir / STABLE_NAMES[3]
    gen_outline(map_context, path)
    outputs.append(path)

    print("[5/7] Connectivity graph...")
    path = output_dir / STABLE_NAMES[4]
    gen_connectivity(map_context, map_graph, path)
    outputs.append(path)

    if match_file:
        print(f"[6/7] Single player trace (player {args.player}, match {args.match})...")
        path = output_dir / STABLE_NAMES[5]
        gen_trace_single(map_context, match_file, args.player, map_graph,
                         layout_dir, path)
        outputs.append(path)

        print(f"[7/7] Team trace ({len(all_player_ids)} players, match {args.match})...")
        path = output_dir / STABLE_NAMES[6]
        gen_trace_team(map_context, match_file, all_player_ids, map_graph,
                       layout_dir, path)
        outputs.append(path)
    else:
        print("[6/7] Skipped (no match data)")
        print("[7/7] Skipped (no match data)")

    print(f"\nDone. Generated {len(outputs)} images in {output_dir}")


if __name__ == '__main__':
    main()
