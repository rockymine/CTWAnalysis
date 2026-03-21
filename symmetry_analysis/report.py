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
    """Run symmetry analysis for one map (detailed) or all maps (summary table)."""
    root = Path(args.dir)

    if args.map is not None:
        _run_single(root, args.map)
    else:
        _run_all(root)


def _run_single(root: Path, map_name: str) -> None:
    """Full detailed report for a single map."""
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

    result = detect_symmetry(str(ctx_path))
    report = format_symmetry_report(result)
    print(report)


def _run_all(root: Path) -> None:
    """Compact summary table across all maps."""
    from symmetry_analysis import detect_symmetry

    if not root.is_dir():
        print(f"Error: directory not found: {root}", file=sys.stderr)
        sys.exit(1)

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
            result = detect_symmetry(str(ctx_path))
        except Exception as e:
            rows.append((map_dir.name, f"ERROR: {e}", "", ""))
            continue

        detected_global = [s for s in result["global_symmetry"] if s["detected"]]
        if detected_global:
            primary = max(detected_global, key=lambda s: s["confidence"])
            global_str = f"{primary['type']} ({primary['confidence']:.0%})"
        else:
            global_str = "none"

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

    if skipped:
        print(f"\n  Skipped (no map_context.json): {', '.join(skipped)}")

    print(f"\n  {len(rows)} maps analyzed")
