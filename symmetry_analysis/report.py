"""
Console report formatting for symmetry analysis results.

Public entry point:
- run(args): run symmetry analysis for one map (detailed) or all maps (summary table)
"""

import sys
from pathlib import Path


def format_symmetry_report(result: dict) -> str:
    """Format symmetry analysis results as a human-readable console report.

    Args:
        result: Dict returned by detect_symmetry()

    Returns:
        Formatted string for console output.
    """
    lines = []
    w = 70

    lines.append("=" * w)
    lines.append(f"SYMMETRY ANALYSIS: {result['map_name']}")
    lines.append("=" * w)

    # --- Center ---
    center = result["center"]
    lines.append("")
    lines.append("Map Center")
    lines.append("-" * w)
    lines.append(f"  Map dimensions:  {center['map_width_x']} x {center['map_width_z']} blocks")
    lines.append(f"  Center point:    ({center['center_x']}, {center['center_z']})")
    lines.append(f"  Center type:     {center['description']}")
    blocks_str = ", ".join(f"({x}, {z})" for x, z in center["blocks"])
    lines.append(f"  Center blocks:   {blocks_str}")

    # --- Pair Analysis ---
    pair = result["pair_analysis"]
    lines.append("")
    lines.append("Island Pair Analysis")
    lines.append("-" * w)
    lines.append(f"  Canonical pairs found: {pair['total_pairs']}")

    if pair["pairs"]:
        for p in pair["pairs"]:
            t_str = ", ".join(p["transforms"]) if p["transforms"] else "none"
            lines.append(
                f"    Island {p['island_a']:>2} <-> {p['island_b']:>2}  "
                f"(area={p['area']:>5})  transforms: {t_str}"
            )
    else:
        lines.append("    No symmetric island pairs detected")

    if pair["transform_counts"]:
        lines.append("")
        lines.append("  Transform vote tally:")
        for t_name, count in sorted(pair["transform_counts"].items()):
            lines.append(f"    {t_name:<12} {count} pair(s)")

    # --- Global Symmetry ---
    lines.append("")
    lines.append("Global Symmetry")
    lines.append("-" * w)

    detected_global = [s for s in result["global_symmetry"] if s["detected"]]
    not_detected = [s for s in result["global_symmetry"] if not s["detected"]]

    if detected_global:
        for s in sorted(detected_global, key=lambda x: -x["confidence"]):
            lines.append(f"  [DETECTED]  {s['description']}")
            lines.append(f"              pair support: {s['pair_support']:.1%}  "
                         f"polygon IoU: {s['polygon_iou']:.1%}  "
                         f"confidence: {s['confidence']:.1%}")
    else:
        lines.append("  No global symmetry detected")

    if not_detected:
        lines.append("")
        for s in not_detected:
            lines.append(f"  [   ---  ]  {s['description']}")
            lines.append(f"              pair support: {s['pair_support']:.1%}  "
                         f"polygon IoU: {s['polygon_iou']:.1%}  "
                         f"confidence: {s['confidence']:.1%}")

    # --- Intra-Team Symmetry ---
    intra = result.get("intra_team_symmetry", [])
    if intra:
        lines.append("")
        lines.append("Intra-Team Symmetry")
        lines.append("-" * w)

        for t in intra:
            team_label = t["team"]
            ids_str = ", ".join(str(i) for i in t["island_ids"])
            lines.append(f"  Team: {team_label}  ({t['island_count']} islands: [{ids_str}])")

            check_type = t.get("check_type", "mirror_split")

            if check_type == "canonical_coverage":
                covered = t.get("groups_covered", 0)
                total = t.get("canonical_groups", 0)
                if t.get("symmetry_detected"):
                    lines.append(f"    [DETECTED]  canonical coverage: "
                                 f"{covered}/{total} groups")
                else:
                    lines.append(f"    [   ---  ]  canonical coverage: "
                                 f"{covered}/{total} groups")
            else:
                axis_info = ""
                if t.get("intra_axis"):
                    axis_label = "X" if t["intra_axis"] == "mirror_x" else "Z"
                    axis_info = f", split axis: {axis_label}={t.get('axis_value', '?')}"

                if t.get("symmetry_detected"):
                    sym_type = t.get("best_symmetry_type", "?")
                    iou = t.get("best_iou", 0)
                    lines.append(f"    [DETECTED]  {sym_type}  "
                                 f"(IoU: {iou:.1%}{axis_info})")
                else:
                    detail = t.get("detail", "")
                    if detail:
                        lines.append(f"    [   ---  ]  {detail}")
                    else:
                        iou = t.get("best_iou", 0)
                        lines.append(f"    [   ---  ]  Best IoU: {iou:.1%} "
                                     f"(below threshold{axis_info})")

    # --- Overall Confidence ---
    lines.append("")
    lines.append("Summary")
    lines.append("-" * w)

    if detected_global:
        primary = max(detected_global, key=lambda x: x["confidence"])
        lines.append(f"  Primary symmetry: {primary['description']}")
        lines.append(f"  Confidence:       {primary['confidence']:.1%}")

        # Consistency indicator
        if primary["confidence"] >= 0.90:
            indicator = "HIGH - geometry is highly symmetric"
        elif primary["confidence"] >= 0.75:
            indicator = "MEDIUM - geometry is mostly symmetric"
        elif primary["confidence"] >= 0.60:
            indicator = "LOW - some symmetry present but imperfect"
        else:
            indicator = "NONE - no clear symmetry"
        lines.append(f"  Consistency:      {indicator}")
    else:
        lines.append("  No symmetry detected")
        lines.append("  Consistency:      NONE - no clear symmetry")

    # Intra-team summary
    if intra:
        sym_teams = [t["team"] for t in intra if t.get("symmetry_detected")]
        if sym_teams:
            lines.append(f"  Intra-team symmetry: detected for {', '.join(sym_teams)}")
        else:
            lines.append(f"  Intra-team symmetry: not detected")

    lines.append("")
    lines.append("=" * w)

    return "\n".join(lines)


def run(args: object) -> None:
    """Run symmetry analysis for one map (detailed + image) or all maps (summary table)."""
    root = Path(args.dir)
    threshold: float | None = getattr(args, 'threshold', None)

    if args.map is not None:
        if threshold is not None:
            print("Error: --threshold cannot be used with --map.", file=sys.stderr)
            sys.exit(1)
        _run_single(root, args.map)
    else:
        _run_all(root, threshold)


def _run_single(root: Path, map_name: str) -> None:
    """Full detailed text report + symmetry debug image for a single map."""
    from symmetry_analysis import detect_symmetry

    ctx_path = root / map_name / 'map_context.json'
    if not ctx_path.exists():
        ctx_path = Path(map_name) / 'map_context.json'
        if not ctx_path.exists():
            print(f"Error: map_context.json not found for '{map_name}'", file=sys.stderr)
            print(f"  Tried: {root / map_name / 'map_context.json'}", file=sys.stderr)
            print(f"  Run island analysis first: python ctw.py run --map {map_name}",
                  file=sys.stderr)
            sys.exit(1)

    result = detect_symmetry(str(ctx_path)).to_dict()
    report = format_symmetry_report(result)
    print(report)

    save_path = root / map_name / 'images' / 'symmetry_debug.png'
    _generate_symmetry_plot(map_name, root, save_path)
    print(f"  Image: {save_path}")


def _generate_symmetry_plot(map_name: str, root: Path, save_path: Path) -> None:
    """Render the two-panel layout + island debug figure for symmetry investigation."""
    import json as _json

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np

    from common.visualization import draw_layout_image
    from common.visualization.map_primitives import (
        BuildRegionStyle, IslandOutlineStyle, POIStyle,
        draw_build_region, draw_island_outlines, draw_pois,
        map_base_legend_handles,
    )
    from layout_analysis.map_layout_config import get_map_layout

    output_root = root
    map_dir = output_root / map_name

    # ── Resolve best layout parquet ──────────────────────────────────────
    _LAYER_FILES = {
        'y0':           'layout_y0.parquet',
        'bedrock':      'layout_bedrock.parquet',
        'lowest_solid': 'layout_lowest_solid.parquet',
        'top_surface':  'layout_top_surface.parquet',
    }

    def _decided_layout_path() -> Path | None:
        decided = map_dir / 'layout_decided.parquet'
        if decided.exists():
            return decided
        cfg = get_map_layout(map_name)
        if cfg and not cfg.skip:
            fname = _LAYER_FILES.get(cfg.layer)
            if fname:
                candidate = map_dir / fname
                if candidate.exists():
                    return candidate
        fallback = map_dir / 'layout_bedrock.parquet'
        return fallback if fallback.exists() else None

    def _layer_label(layout_path: Path) -> str:
        cfg = get_map_layout(map_name)
        if layout_path == map_dir / 'layout_decided.parquet':
            layer = cfg.layer if cfg else '?'
            excl = f', excl {cfg.exclude}' if cfg and cfg.exclude else ''
            return f'layout_decided  [{layer}{excl}]'
        stem = layout_path.stem.replace('layout_', '')
        if cfg and not cfg.skip:
            return f'{stem}  (decided not yet generated — using configured layer)'
        return stem

    # ── Load map_context ─────────────────────────────────────────────────
    ctx_path = map_dir / 'map_context.json'
    ctx: dict | None = None
    if ctx_path.exists():
        with open(ctx_path) as f:
            ctx = _json.load(f)

    layout_path = _decided_layout_path()
    if layout_path is None and ctx is None:
        print(f"  Warning: no layout or map_context found for '{map_name}', skipping image.")
        return

    # ── Figure ───────────────────────────────────────────────────────────
    import pandas as pd

    cfg = get_map_layout(map_name)
    layer_str = cfg.layer if (cfg and not cfg.skip) else 'bedrock (default)'
    fig, (ax_l, ax_r) = plt.subplots(1, 2, figsize=(18, 9), layout='constrained')
    fig.suptitle(
        f'{map_name}   |   configured layer: {layer_str}',
        fontsize=11, fontweight='bold',
    )

    # Left panel: coloured block image
    if layout_path is not None:
        df = pd.read_parquet(layout_path)
        draw_layout_image(ax_l, df)
        ax_l.set_title(_layer_label(layout_path), fontsize=8)
    else:
        ax_l.text(0.5, 0.5, 'No layout data', transform=ax_l.transAxes,
                  ha='center', va='center', color='gray')
        ax_l.set_title('layout — no data', fontsize=8)
    ax_l.set_xlabel('X')
    ax_l.set_ylabel('Z')

    # Right panel: island polygons + POIs + block-count annotations
    if ctx is not None:
        has_build = draw_build_region(ax_r, ctx, style=BuildRegionStyle())

        observer_ids = {isl['id'] for isl in ctx.get('islands', [])
                        if isl.get('is_observer_island')}
        ctx_no_obs = dict(ctx, islands=[isl for isl in ctx.get('islands', [])
                                        if isl['id'] not in observer_ids])
        draw_island_outlines(
            ax_r, ctx_no_obs,
            style=IslandOutlineStyle(exterior_linewidth=1.0, exterior_alpha=0.95),
        )
        draw_pois(ax_r, ctx, style=POIStyle(spawn_size=120, wool_size=80))

        for isl in ctx.get('islands', []):
            if isl.get('is_observer_island'):
                poly = isl.get('simplified_polygon')
                if poly and poly.get('exterior'):
                    pts = np.array(poly['exterior'])
                    ax_r.fill(pts[:, 0], pts[:, 1],
                              facecolor='none', edgecolor='grey', linewidth=1.5,
                              hatch='////', alpha=0.8, zorder=3)
                ax_r.text(
                    isl['center'][0], isl['center'][1],
                    'OBS', color='white', fontsize=5.5, ha='center', va='center',
                    fontweight='bold', zorder=9,
                    bbox=dict(boxstyle='round,pad=0.1', fc='grey', alpha=0.8, lw=0),
                )

        for isl in ctx.get('islands', []):
            cx, cz = isl['center']
            ax_r.text(
                cx, cz,
                f"#{isl['id']}\n{isl['area']}bl",
                fontsize=4.5, ha='center', va='center', color='white',
                bbox=dict(boxstyle='round,pad=0.1', fc='black', alpha=0.45, lw=0),
                zorder=10,
            )

        ax_r.axis('equal')
        ax_r.invert_yaxis()

        # Symmetry confidence from symmetry.json if present
        n_islands = len(ctx.get('islands', []))
        symmetry_desc = ''
        sym_path = map_dir / 'symmetry.json'
        if sym_path.exists():
            with open(sym_path) as sym_f:
                sym_data = _json.load(sym_f)
            detected = [s for s in sym_data.get('global_symmetry', []) if s.get('detected')]
            if detected:
                primary = max(detected, key=lambda s: s.get('confidence', 0.0))
                symmetry_desc = (
                    f"  |  symmetry: {primary.get('description', primary.get('type', '?'))}"
                    f" ({primary['confidence']:.0%})"
                )

        ax_r.set_title(f'Islands ({n_islands}){symmetry_desc}', fontsize=8)
        ax_r.legend(handles=map_base_legend_handles(has_build_region=has_build),
                    loc='upper right', fontsize=5.5, framealpha=0.8, ncol=2)
    else:
        ax_r.text(0.5, 0.5, 'No map_context.json', transform=ax_r.transAxes,
                  ha='center', va='center', color='gray')
        ax_r.set_title('Islands — no data', fontsize=8)
    ax_r.set_xlabel('X')
    ax_r.set_ylabel('Z')

    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(save_path), dpi=150, bbox_inches='tight')
    plt.close(fig)


def _run_all(root: Path, threshold: float | None = None) -> None:
    """Compact summary table across all maps, optionally filtered by symmetry confidence."""
    from symmetry_analysis import detect_symmetry

    if not root.is_dir():
        print(f"Error: directory not found: {root}", file=sys.stderr)
        sys.exit(1)

    # threshold is in percentage (e.g. 90.0); convert to 0-1 for comparison
    threshold_frac: float | None = threshold / 100.0 if threshold is not None else None

    rows: list[tuple[str, str, str, str]] = []
    skipped: list[str] = []

    for map_dir in sorted(root.iterdir()):
        if not map_dir.is_dir():
            continue
        ctx_path = map_dir / 'map_context.json'
        if not ctx_path.exists():
            skipped.append(map_dir.name)
            continue

        try:
            result = detect_symmetry(str(ctx_path)).to_dict()
        except Exception as e:
            rows.append((map_dir.name, f"ERROR: {e}", "", ""))
            continue

        detected_global = [s for s in result["global_symmetry"] if s["detected"]]
        if detected_global:
            primary = max(detected_global, key=lambda s: s["confidence"])
            primary_confidence: float = primary["confidence"]
            global_str = f"{primary['type']} ({primary_confidence:.0%})"
        else:
            primary_confidence = 0.0
            global_str = "none"

        # Apply threshold filter: skip maps at or above the threshold
        if threshold_frac is not None and detected_global:
            if round(primary_confidence * 100) >= round(threshold):
                continue

        center_str = result["center"]["type"]

        intra = result.get("intra_team_symmetry", [])
        sym_teams = [t for t in intra if t.get("symmetry_detected")]
        if not intra:
            intra_str = "-"
        elif len(sym_teams) == len(intra) and intra:
            check = intra[0].get("check_type", "mirror_split")
            if check == "canonical_coverage":
                groups = intra[0].get("canonical_groups", "?")
                intra_str = f"all teams ({groups} groups)"
            else:
                iou = min(t.get("best_iou", 0) for t in sym_teams)
                intra_str = f"all teams (IoU>={iou:.0%})"
        elif sym_teams:
            names = ", ".join(t["team"] for t in sym_teams)
            intra_str = names
        else:
            intra_str = "none"

        rows.append((map_dir.name, global_str, center_str, intra_str))

    if not rows and not skipped:
        print(f"No map output folders found in {root}/")
        return

    if threshold is not None:
        print(f"  Maps with symmetry confidence < {threshold:.0f}%  ({len(rows)} found)\n")

    if rows:
        col_w = [
            max(len(r[0]) for r in rows),
            max(len(r[1]) for r in rows),
            max(len(r[2]) for r in rows),
            max(len(r[3]) for r in rows),
        ]
        headers = ("map", "global symmetry", "center", "intra-team")
        col_w = [max(col_w[i], len(headers[i])) for i in range(4)]

        hdr = (f"  {headers[0]:<{col_w[0]}}  {headers[1]:<{col_w[1]}}  "
               f"{headers[2]:<{col_w[2]}}  {headers[3]}")
        sep = f"  {'-' * col_w[0]}  {'-' * col_w[1]}  {'-' * col_w[2]}  {'-' * col_w[3]}"
        print(hdr)
        print(sep)
        for name, gs, ct, it in rows:
            print(f"  {name:<{col_w[0]}}  {gs:<{col_w[1]}}  {ct:<{col_w[2]}}  {it}")

    if skipped and threshold is None:
        print(f"\n  Skipped (no map_context.json): {', '.join(skipped)}")

    print(f"\n  {len(rows)} maps{'  (filtered)' if threshold is not None else ''} analyzed")
