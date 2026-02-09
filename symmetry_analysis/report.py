"""
Console report formatting for symmetry analysis results.
"""


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
