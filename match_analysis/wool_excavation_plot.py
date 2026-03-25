"""Wool excavation diagnostic plot.

For each wool on a map, renders a top-down panel showing below-terrain player
positions from match data.

Coloring — two modes depending on available data:

**Excavation completeness** (preferred, requires bedrock_ceiling_y in DB):
    completeness = (surface_y - floor_y) / (surface_y - bedrock_ceiling_y)
    Range [0, 1]: 0 = barely scratched surface, 1 = dug to bedrock ceiling.
    Uses Blues colormap — dark = fully excavated, light = barely touched.
    This removes both terrain-height bias AND bedrock-topography bias, so
    cells near the wool (higher bedrock) and cells far from the wool (lower
    bedrock) are comparably coloured when equally excavated.

**Floor y fallback** (when bedrock_ceiling_y is NULL for the map):
    Raw absolute floor_y using Blues_r — lower floor_y = darker.
    Retains bedrock-topography bias; valid for flat-bedrock maps only.

Static cells (floor_range = 0 across matches — building interiors, terrain edges)
receive a grey outline so they remain visible but are distinguishable from cells
where the floor actively varied across matches.

Overlays per panel:
- XML wool room polygon — orange filled rectangle
- Vertical guide lines at the wool room x-extent — dashed orange
- Active bounding box (floor_range >= min_floor_range, extended to cover wool room)
- Wool position (star) and defending team's spawn (triangle)

Public entry point:
- run(args): load data from the DB and render the multi-panel figure
"""

import sys
from pathlib import Path
from typing import Optional


_WOOL_COLORS: dict[str, str] = {
    'white':      '#dddddd',
    'orange':     '#e87400',
    'magenta':    '#cc44cc',
    'light_blue': '#6ec3e0',
    'yellow':     '#f0c000',
    'lime':       '#60c030',
    'pink':       '#f080a0',
    'gray':       '#888888',
    'light_gray': '#bbbbbb',
    'cyan':       '#30a0b0',
    'purple':     '#8040c0',
    'blue':       '#3050d0',
    'brown':      '#8b5a2b',
    'green':      '#4a8c2a',
    'red':        '#c43030',
    'black':      '#444444',
}


def run(args: object) -> None:
    """Load match data for a map and render the wool excavation diagnostic plot."""
    map_name: str = args.map
    output_root = Path(args.output)
    min_floor_range: int = args.min_floor_range
    map_dir = output_root / map_name
    ctx_path = map_dir / 'map_context.json'

    if not ctx_path.exists():
        print(f"Error: map_context.json not found: {ctx_path}", file=sys.stderr)
        sys.exit(1)

    import json
    with open(ctx_path) as f:
        map_context = json.load(f)

    map_data_path = map_dir / 'map_data.json'
    map_data: Optional[dict] = None
    if map_data_path.exists():
        with open(map_data_path) as f:
            map_data = json.load(f)

    save_path = (
        Path(args.save_path) if args.save_path
        else map_dir / 'images' / 'wool_excavation.png'
    )
    save_path.parent.mkdir(parents=True, exist_ok=True)

    db_path = Path('match_analysis/metadata.db')
    if not db_path.exists():
        print(f"Error: database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    import duckdb
    conn = duckdb.connect(str(db_path), read_only=True)

    try:
        row = conn.execute(
            "SELECT map_id FROM maps WHERE map_slug = ? OR map_name = ?",
            [map_name, map_name],
        ).fetchone()
        if row is None:
            print(f"Error: map '{map_name}' not found in database.", file=sys.stderr)
            conn.close()
            sys.exit(1)
        map_id: int = row[0]

        wools_df = conn.execute("""
            SELECT DISTINCT ON (wool_id)
                wool_id, wool_color,
                CAST(wool_x AS INT) AS wool_x,
                CAST(wool_z AS INT) AS wool_z,
                defending_team, defending_side
            FROM map_wool_attack_relations
            WHERE map_id = ?
            ORDER BY wool_id
        """, [map_id]).df()

        if wools_df.empty:
            print(f"No wool data found for '{map_name}'.")
            conn.close()
            return

        has_terrain = conn.execute(
            "SELECT COUNT(*) FROM map_terrain_height WHERE map_id = ?",
            [map_id],
        ).fetchone()[0] > 0

        # Check whether bedrock_ceiling_y is populated for this map
        has_bedrock_ceiling = False
        if has_terrain:
            bedrock_ceiling_count = conn.execute(
                "SELECT COUNT(*) FROM map_terrain_height "
                "WHERE map_id = ? AND bedrock_ceiling_y IS NOT NULL",
                [map_id],
            ).fetchone()[0]
            has_bedrock_ceiling = bedrock_ceiling_count > 0

        if has_terrain:
            excavation_df = conn.execute("""
                WITH per_match_cell AS (
                    SELECT
                        th.world_x, th.world_z, th.surface_y,
                        th.bedrock_ceiling_y,
                        pe.match_id,
                        MIN(pe.y) AS match_floor_y
                    FROM position_events pe
                    JOIN matches mat ON mat.match_id = pe.match_id
                    JOIN map_terrain_height th
                        ON  th.map_id  = mat.map_id
                        AND th.world_x = CAST(pe.x AS INT)
                        AND th.world_z = CAST(pe.z AS INT)
                    WHERE mat.map_id = ?
                      AND pe.y >= 1
                      AND (pe.y - (th.surface_y + 1)) < 0
                    GROUP BY th.world_x, th.world_z, th.surface_y,
                             th.bedrock_ceiling_y, pe.match_id
                )
                SELECT
                    world_x, world_z, surface_y,
                    ANY_VALUE(bedrock_ceiling_y)                    AS bedrock_ceiling_y,
                    MIN(match_floor_y)                             AS floor_y,
                    surface_y - MIN(match_floor_y)                 AS excavation_depth,
                    COUNT(DISTINCT match_id)                       AS match_count,
                    MAX(match_floor_y) - MIN(match_floor_y)        AS floor_range,
                    ROUND(STDDEV(match_floor_y), 2)                AS floor_stddev
                FROM per_match_cell
                GROUP BY world_x, world_z, surface_y
            """, [map_id]).df()
        else:
            excavation_df = conn.execute("""
                WITH surface AS (
                    SELECT CAST(pe.x AS INT) AS world_x,
                           CAST(pe.z AS INT) AS world_z,
                           MAX(pe.y)         AS surface_y
                    FROM position_events pe
                    JOIN matches mat ON mat.match_id = pe.match_id
                    WHERE mat.map_id = ? AND pe.y >= 1
                    GROUP BY world_x, world_z
                ),
                per_match_cell AS (
                    SELECT
                        s.world_x, s.world_z, s.surface_y,
                        pe.match_id,
                        MIN(pe.y) AS match_floor_y
                    FROM position_events pe
                    JOIN matches mat ON mat.match_id = pe.match_id
                    JOIN surface s
                        ON s.world_x = CAST(pe.x AS INT)
                        AND s.world_z = CAST(pe.z AS INT)
                    WHERE mat.map_id = ?
                      AND pe.y >= 1
                      AND (pe.y - (s.surface_y + 1)) < 0
                    GROUP BY s.world_x, s.world_z, s.surface_y, pe.match_id
                )
                SELECT
                    world_x, world_z, surface_y,
                    NULL::INTEGER                            AS bedrock_ceiling_y,
                    MIN(match_floor_y)                      AS floor_y,
                    surface_y - MIN(match_floor_y)          AS excavation_depth,
                    COUNT(DISTINCT match_id)                AS match_count,
                    MAX(match_floor_y) - MIN(match_floor_y) AS floor_range,
                    ROUND(STDDEV(match_floor_y), 2)         AS floor_stddev
                FROM per_match_cell
                GROUP BY world_x, world_z, surface_y
            """, [map_id, map_id]).df()

    finally:
        conn.close()

    if excavation_df.empty:
        print(f"No below-terrain position events found for '{map_name}'.")
        return

    wool_room_polygons = _load_wool_room_polygons(map_data)
    defending_spawns = _load_defending_spawns(map_data)

    _plot_figure(
        map_name, map_context, wools_df, excavation_df,
        wool_room_polygons, defending_spawns,
        min_floor_range, save_path, has_terrain, has_bedrock_ceiling,
    )
    print(f"Saved: {save_path}")


def _load_wool_room_polygons(map_data: Optional[dict]) -> list:
    """Return list of Shapely polygons — one per wool room."""
    if map_data is None:
        return []
    try:
        from layout_analysis.features.zone_classifier import ZoneClassifier
        clf = ZoneClassifier(map_data)
        geom = clf._wool_room_geom
        if geom is None:
            return []
        return list(geom.geoms) if hasattr(geom, 'geoms') else [geom]
    except Exception:
        return []


def _load_defending_spawns(map_data: Optional[dict]) -> dict[str, tuple[int, int]]:
    """Return {team_name: (spawn_x, spawn_z)} from map_data['spawns']."""
    if map_data is None:
        return {}
    result: dict[str, tuple[int, int]] = {}
    for spawn in map_data.get('spawns', []):
        team = spawn.get('team')
        base = spawn.get('region', {}).get('base', {})
        if team and 'x' in base and 'z' in base:
            result[team] = (int(base['x']), int(base['z']))
    return result


def _plot_figure(
    map_name: str,
    map_context: dict,
    wools_df: 'pd.DataFrame',
    excavation_df: 'pd.DataFrame',
    wool_room_polygons: list,
    defending_spawns: dict,
    min_floor_range: int,
    save_path: Path,
    used_terrain_table: bool,
    has_bedrock_ceiling: bool,
) -> None:
    """Render one panel per wool in a 2-column grid with a shared figure legend."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.cm as cm
    import matplotlib.colors as mcolors
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt
    import numpy as np

    from matplotlib.collections import PolyCollection
    from shapely.geometry import Point

    from common.geometry import blocks_to_unit_squares
    from common.visualization.map_primitives import (
        BuildRegionStyle,
        IslandOutlineStyle,
        draw_build_region,
        draw_island_outlines,
    )

    n_wools = len(wools_df)
    n_cols = 2
    n_rows = (n_wools + 1) // 2

    # Extra bottom space for the shared legend
    fig = plt.figure(figsize=(11 * n_cols, 10 * n_rows + 1.2), dpi=120)
    gs = fig.add_gridspec(
        n_rows, n_cols,
        top=0.97, bottom=0.07,
        hspace=0.28, wspace=0.25,
    )
    axes = [[fig.add_subplot(gs[r, c]) for c in range(n_cols)] for r in range(n_rows)]

    if has_bedrock_ceiling:
        colour_mode = 'completeness'
        colour_desc = 'excavation completeness (1 = dug to bedrock ceiling)'
    elif used_terrain_table:
        colour_mode = 'floor_y'
        colour_desc = 'floor_y reached, darker = deeper  (bedrock_ceiling_y unavailable)'
    else:
        colour_mode = 'floor_y'
        colour_desc = 'floor_y reached, darker = deeper  (surface via MAX(y) fallback)'

    fig.suptitle(
        f'{map_name} — wool excavation  (colour = {colour_desc})',
        fontsize=13, fontweight='bold',
    )

    _THIN_ISLAND = IslandOutlineStyle(
        exterior_linewidth=0.7, exterior_alpha=0.45,
        hole_linewidth=0.4, hole_alpha=0.3,
    )
    _THIN_BUILD = BuildRegionStyle(fill_alpha=0.05, linewidth=0.35)

    # Colormap:
    #   completeness mode → Blues: 0 (light, barely scratched) → 1 (dark, fully dug)
    #   floor_y fallback  → Blues_r: low floor_y (deep) = dark, high = light
    floor_cmap = cm.get_cmap('Blues' if colour_mode == 'completeness' else 'Blues_r')

    # Shared legend handles — built once, added to figure after the loop
    legend_handles: list = []
    legend_built = False

    # Pre-compute the wool room polygon for each wool (in wools_df order) so
    # we can use polygon distance for cell assignment rather than point distance.
    # This prevents diagonal Voronoi bisectors when wool positions are offset.
    wool_room_polys_by_idx: list = []
    for wool_row in wools_df.itertuples():
        wool_pt_pre = Point(wool_row.wool_x + 0.5, wool_row.wool_z + 0.5)
        poly = next(
            (p for p in wool_room_polygons
             if p.contains(wool_pt_pre) or p.distance(wool_pt_pre) < 5),
            None,
        )
        wool_room_polys_by_idx.append(poly)

    # Assign each excavation cell to its nearest wool room polygon (falling back
    # to wool-point distance when no polygon is available).  Using the room
    # polygon produces axis-aligned assignment boundaries that follow the room
    # geometry rather than diagonal perpendicular bisectors between wool points.
    if not excavation_df.empty and n_wools > 1:
        cell_xs = excavation_df['world_x'].values.astype(float)
        cell_zs = excavation_df['world_z'].values.astype(float)
        dist_sq_cols: list[np.ndarray] = []

        for widx, wool_row in enumerate(wools_df.itertuples()):
            poly = wool_room_polys_by_idx[widx]
            if poly is not None:
                # AABB distance: exact for rectangular rooms, fully vectorised
                xr_min, zr_min, xr_max, zr_max = poly.bounds
                dx_poly = np.maximum(0.0, np.maximum(xr_min - cell_xs,
                                                      cell_xs - xr_max))
                dz_poly = np.maximum(0.0, np.maximum(zr_min - cell_zs,
                                                      cell_zs - zr_max))
                dist_sq_cols.append(dx_poly**2 + dz_poly**2)
            else:
                dx_pt = cell_xs - float(wool_row.wool_x)
                dz_pt = cell_zs - float(wool_row.wool_z)
                dist_sq_cols.append(dx_pt**2 + dz_pt**2)

        dist_sq_matrix = np.stack(dist_sq_cols, axis=1)  # (n_cells, n_wools)
        nearest_wool_idx = np.argmin(dist_sq_matrix, axis=1)
        excavation_df = excavation_df.copy()
        excavation_df['_nearest_wool'] = nearest_wool_idx
    elif not excavation_df.empty:
        excavation_df = excavation_df.copy()
        excavation_df['_nearest_wool'] = 0

    for panel_idx, wool_row in enumerate(wools_df.itertuples()):
        row_idx = panel_idx // n_cols
        col_idx = panel_idx % n_cols
        ax = axes[row_idx][col_idx]

        wool_x: int = wool_row.wool_x
        wool_z: int = wool_row.wool_z
        wool_color_name: str = wool_row.wool_color
        wool_id: int = wool_row.wool_id
        defending_side: Optional[str] = getattr(wool_row, 'defending_side', None)
        defending_team: Optional[str] = getattr(wool_row, 'defending_team', None)

        # Defending team's spawn (close to their wool room)
        def_spawn: Optional[tuple[int, int]] = (
            defending_spawns.get(defending_team) if defending_team else None
        )

        # Show all cells nearest to this wool room — no radius cutoff so the
        # full lane extent and its natural coverage drop-off are both visible.
        if '_nearest_wool' in excavation_df.columns:
            panel_df = excavation_df[excavation_df['_nearest_wool'] == panel_idx].copy()
        else:
            panel_df = excavation_df.iloc[0:0].copy()  # empty fallback

        # Wool room polygon for this wool (pre-computed before the loop)
        wool_room_poly = wool_room_polys_by_idx[panel_idx]

        # ── Axis limits: tight around data + wool room + defending spawn ──
        pad = 4
        if not panel_df.empty:
            xlim_min = int(panel_df['world_x'].min()) - pad
            xlim_max = int(panel_df['world_x'].max()) + 1 + pad
            zlim_min = int(panel_df['world_z'].min()) - pad
            zlim_max = int(panel_df['world_z'].max()) + 1 + pad
        else:
            xlim_min = wool_x - 20
            xlim_max = wool_x + 20
            zlim_min = wool_z - 20
            zlim_max = wool_z + 20

        if wool_room_poly is not None:
            xr_min, zr_min, xr_max, zr_max = wool_room_poly.bounds
            xlim_min = min(xlim_min, int(xr_min) - pad)
            xlim_max = max(xlim_max, int(xr_max) + pad)
            zlim_min = min(zlim_min, int(zr_min) - pad)
            zlim_max = max(zlim_max, int(zr_max) + pad)

        if def_spawn is not None:
            sx, sz = def_spawn
            # Include spawn in view if it lies within the data extent already
            # established (plus padding), so we never pull the view far out to
            # reach a spawn that isn't part of this lane's area.
            spawn_in_data_extent = (
                (xlim_min - pad * 4) <= sx <= (xlim_max + pad * 4) and
                (zlim_min - pad * 4) <= sz <= (zlim_max + pad * 4)
            )
            if spawn_in_data_extent:
                xlim_min = min(xlim_min, sx - pad)
                xlim_max = max(xlim_max, sx + 1 + pad)
                zlim_min = min(zlim_min, sz - pad)
                zlim_max = max(zlim_max, sz + 1 + pad)

        ax.set_xlim(xlim_min, xlim_max)
        ax.set_ylim(zlim_min, zlim_max)
        ax.invert_yaxis()
        ax.set_aspect('equal')

        side_str = f' ({defending_side} side)' if defending_side else ''
        team_str = f' — {defending_team}' if defending_team else ''
        ax.set_title(
            f'Wool {wool_id} ({wool_color_name}){side_str}{team_str}',
            fontsize=10, fontweight='bold', pad=4,
        )
        ax.set_xlabel('world x', fontsize=8)
        ax.set_ylabel('world z', fontsize=8)
        ax.tick_params(labelsize=7)

        draw_build_region(ax, map_context, style=_THIN_BUILD)
        draw_island_outlines(ax, map_context, style=_THIN_ISLAND)

        # ── Wool room outline + corridor guide lines ──
        if wool_room_poly is not None:
            xr_min, zr_min, xr_max, zr_max = (
                int(wool_room_poly.bounds[0]), int(wool_room_poly.bounds[1]),
                int(wool_room_poly.bounds[2]), int(wool_room_poly.bounds[3]),
            )
            ax.add_patch(mpatches.Rectangle(
                (xr_min, zr_min), xr_max - xr_min, zr_max - zr_min,
                linewidth=1.6, edgecolor='#e08000', facecolor='#ffe0a0',
                alpha=0.25, zorder=2,
            ))
            ax.add_patch(mpatches.Rectangle(
                (xr_min, zr_min), xr_max - xr_min, zr_max - zr_min,
                linewidth=1.6, edgecolor='#e08000', facecolor='none',
                zorder=7,
            ))

            # Determine corridor axis: compare the centroid of active excavation
            # cells against the wool room centre.  The lane runs in whichever
            # direction the excavation mass is offset from the room.
            # Fall back to room aspect ratio when no active data is available.
            active_cells = panel_df[panel_df['floor_range'] >= min_floor_range]
            if not active_cells.empty:
                room_cx = (xr_min + xr_max) / 2.0
                room_cz = (zr_min + zr_max) / 2.0
                exc_cx = active_cells['world_x'].mean()
                exc_cz = active_cells['world_z'].mean()
                corridor_in_x = abs(exc_cx - room_cx) > abs(exc_cz - room_cz)
            else:
                # Room wider in x → lane exits in z; taller in z → lane exits in x
                corridor_in_x = (zr_max - zr_min) > (xr_max - xr_min)

            if corridor_in_x:
                # Lane runs in x — guide lines bound the corridor in z
                for zg in (zr_min, zr_max):
                    ax.axhline(zg, color='#e08000', linewidth=0.7,
                               linestyle='--', alpha=0.6, zorder=6)
            else:
                # Lane runs in z — guide lines bound the corridor in x
                for xg in (xr_min, xr_max):
                    ax.axvline(xg, color='#e08000', linewidth=0.7,
                               linestyle='--', alpha=0.6, zorder=6)

        # ── Excavation cells ──
        if not panel_df.empty:
            if colour_mode == 'completeness' and 'bedrock_ceiling_y' in panel_df.columns:
                # completeness = (surface_y - floor_y) / (surface_y - bedrock_ceiling_y)
                # clamp denominator to ≥ 1 to avoid div-by-zero on flat-bedrock columns
                denom = (panel_df['surface_y'] - panel_df['bedrock_ceiling_y']).clip(lower=1)
                colour_vals = (
                    (panel_df['surface_y'] - panel_df['floor_y']) / denom
                ).clip(0.0, 1.0).values.astype(float)
                # Fill NaN (bedrock_ceiling_y NULL) with 0
                colour_vals = np.where(np.isfinite(colour_vals), colour_vals, 0.0)
                norm = mcolors.Normalize(vmin=0.0, vmax=1.0)
                cbar_label = 'excavation completeness (0 = none, 1 = to bedrock)'
            else:
                floor_vals = panel_df['floor_y'].values.astype(float)
                colour_vals = floor_vals
                vmin = max(1.0, float(floor_vals.min()))
                vmax = float(np.percentile(floor_vals, 90))
                if vmax <= vmin:
                    vmax = vmin + 1.0
                norm = mcolors.Normalize(vmin=vmin, vmax=vmax)
                cbar_label = 'floor_y (lower = deeper)'

            facecolors = floor_cmap(norm(np.clip(colour_vals,
                                                  norm.vmin, norm.vmax)))
            ax.add_collection(PolyCollection(
                blocks_to_unit_squares(panel_df['world_x'].values,
                                       panel_df['world_z'].values),
                facecolors=facecolors,
                edgecolors='none', linewidths=0, antialiased=False, zorder=3,
            ))

            # Grey outline on static (floor_range == 0) cells
            static_df = panel_df[panel_df['floor_range'] == 0]
            if not static_df.empty:
                ax.add_collection(PolyCollection(
                    blocks_to_unit_squares(static_df['world_x'].values,
                                          static_df['world_z'].values),
                    facecolors='none', edgecolors='#aaaaaa',
                    linewidths=0.35, antialiased=False, zorder=4,
                ))

            # Per-panel colorbar (right side)
            sm = cm.ScalarMappable(cmap=floor_cmap, norm=norm)
            sm.set_array([])
            cbar = fig.colorbar(sm, ax=ax, fraction=0.03, pad=0.02, shrink=0.85)
            cbar.set_label(cbar_label, fontsize=7)
            if colour_mode != 'completeness':
                cbar.ax.invert_yaxis()

            # ── Active bounding box — extend to cover wool room ──
            active_df = panel_df[panel_df['floor_range'] >= min_floor_range]
            if not active_df.empty or wool_room_poly is not None:
                bbox_x_min = int(active_df['world_x'].min()) if not active_df.empty else wool_x
                bbox_x_max = int(active_df['world_x'].max()) + 1 if not active_df.empty else wool_x + 1
                bbox_z_min = int(active_df['world_z'].min()) if not active_df.empty else wool_z
                bbox_z_max = int(active_df['world_z'].max()) + 1 if not active_df.empty else wool_z + 1

                if wool_room_poly is not None:
                    bbox_x_min = min(bbox_x_min, int(wool_room_poly.bounds[0]))
                    bbox_x_max = max(bbox_x_max, int(wool_room_poly.bounds[2]))
                    bbox_z_min = min(bbox_z_min, int(wool_room_poly.bounds[1]))
                    bbox_z_max = max(bbox_z_max, int(wool_room_poly.bounds[3]))

                ax.add_patch(mpatches.Rectangle(
                    (bbox_x_min, bbox_z_min),
                    bbox_x_max - bbox_x_min, bbox_z_max - bbox_z_min,
                    linewidth=1.6, edgecolor='#222222', facecolor='none',
                    linestyle='-', zorder=8,
                ))

                n_active = len(active_df)
                n_static = int((panel_df['floor_range'] == 0).sum())
                floor_line = (
                    f'completeness: {colour_vals.min():.2f}–{colour_vals.max():.2f}'
                    if colour_mode == 'completeness'
                    else f'floor_y: {int(panel_df["floor_y"].min())}–{int(panel_df["floor_y"].max())}'
                )
                stats_text = (
                    f'{len(panel_df):,} cells  ({n_active:,} active, {n_static:,} static)\n'
                    f'{floor_line}\n'
                    f'active bbox: '
                    f'x {bbox_x_min}–{bbox_x_max - 1} '
                    f'({bbox_x_max - bbox_x_min} blk), '
                    f'z {bbox_z_min}–{bbox_z_max - 1} '
                    f'({bbox_z_max - bbox_z_min} blk)'
                )
            else:
                floor_line = (
                    f'completeness: {colour_vals.min():.2f}–{colour_vals.max():.2f}'
                    if colour_mode == 'completeness'
                    else f'floor_y: {int(panel_df["floor_y"].min())}–{int(panel_df["floor_y"].max())}'
                )
                stats_text = f'{len(panel_df):,} cells\n{floor_line}'
        else:
            stats_text = 'No below-terrain events'

        ax.text(
            0.02, 0.98, stats_text,
            transform=ax.transAxes, fontsize=7, va='top', fontfamily='monospace',
            bbox=dict(facecolor='white', alpha=0.85, edgecolor='#cccccc', pad=2),
            zorder=10,
        )

        # ── Wool marker ──
        wool_mpl_color = _WOOL_COLORS.get(wool_color_name, '#cc00cc')
        ax.plot(
            wool_x + 0.5, wool_z + 0.5,
            marker='*', markersize=13, color=wool_mpl_color,
            markeredgecolor='black', markeredgewidth=0.8, zorder=9,
        )

        # ── Defending spawn ──
        if def_spawn is not None:
            sx, sz = def_spawn
            ax_xmin, ax_xmax = ax.get_xlim()
            ax_zmin, ax_zmax = ax.get_ylim()
            # ax.get_ylim() with invert_yaxis returns (max, min) — normalise
            z_lo = min(ax_zmin, ax_zmax)
            z_hi = max(ax_zmin, ax_zmax)
            if ax_xmin <= sx <= ax_xmax and z_lo <= sz <= z_hi:
                ax.plot(
                    sx + 0.5, sz + 0.5,
                    marker='^', markersize=10, color='#ff6600',
                    markeredgecolor='black', markeredgewidth=0.8, zorder=9,
                )
                ax.annotate(
                    'def. spawn',
                    xy=(sx + 0.5, sz + 0.5),
                    xytext=(5, 4), textcoords='offset points',
                    fontsize=7, color='black',
                    bbox=dict(facecolor='white', alpha=0.7, edgecolor='none', pad=1),
                    zorder=10,
                )

        # ── Build shared legend once ──
        if not legend_built:
            if colour_mode == 'completeness':
                deep_label = 'fully excavated (completeness ≈ 1)'
                shallow_label = 'barely touched / building interior (completeness ≈ 0)'
            else:
                deep_label = 'deep (floor near bedrock)'
                shallow_label = 'shallow / building interior'
            legend_handles = [
                mpatches.Patch(facecolor=floor_cmap(0.95), label=deep_label),
                mpatches.Patch(facecolor=floor_cmap(0.15), label=shallow_label),
                mpatches.Patch(facecolor='none', edgecolor='#aaaaaa', linewidth=0.8,
                               label='static across matches (floor_range = 0)'),
                mpatches.Patch(facecolor='#ffe0a0', edgecolor='#e08000', linewidth=1.4,
                               label='XML wool room region'),
                mpatches.Patch(facecolor='none', edgecolor='#222222', linewidth=1.4,
                               label=f'active excavation bbox (floor_range ≥ {min_floor_range}, incl. wool room)'),
                plt.Line2D([0], [0], marker='*', color='w', markerfacecolor='#888888',
                           markeredgecolor='black', markersize=10, label='wool position'),
                plt.Line2D([0], [0], marker='^', color='w', markerfacecolor='#ff6600',
                           markeredgecolor='black', markersize=9, label='defending team spawn'),
            ]
            legend_built = True

    # Hide unused panels
    for unused_idx in range(n_wools, n_rows * n_cols):
        axes[unused_idx // n_cols][unused_idx % n_cols].set_visible(False)

    # Single shared legend at the bottom of the figure
    fig.legend(
        handles=legend_handles,
        loc='lower center',
        ncol=4,
        fontsize=8,
        framealpha=0.9,
        bbox_to_anchor=(0.5, 0.0),
    )

    fig.savefig(str(save_path), dpi=120, bbox_inches='tight')
    plt.close(fig)
