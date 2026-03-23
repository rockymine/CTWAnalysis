"""Publication-quality match coverage overview visualization.

Shows how many matches are recorded per map, with a histogram of the
distribution, summary breakdowns by size/teams/wools, and a full per-map
directory sorted by match count.
"""

from __future__ import annotations

import json
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec, GridSpecFromSubplotSpec
from pathlib import Path

import duckdb


# ---------------------------------------------------------------------------
# Bucket definitions: (label, min_inclusive, max_exclusive_or_inf, bar_color)
# ColorBrewer 6-class YlOrRd — for the histogram bars only
# ---------------------------------------------------------------------------
BUCKETS: list[tuple[str, int, int, str]] = [
    ("1",     1,   2,  "#FFFFB2"),
    ("2–5",   2,   6,  "#FED976"),
    ("6–15",  6,  16,  "#FEB24C"),
    ("16–30", 16, 31,  "#FD8D3C"),
    ("31–60", 31, 61,  "#F03B20"),
    ("61+",   61, 10_000, "#BD0026"),
]

# Grayscale text colours for the directory panel: few = light, many = dark
_BUCKET_GRAY: list[str] = [
    "#C0C0C0",  # 1        — light gray
    "#989898",  # 2–5      — medium-light
    "#707070",  # 6–15     — medium
    "#484848",  # 16–30    — medium-dark
    "#282828",  # 31–60    — dark
    "#080808",  # 61+      — near-black
]

# Summary table: (column label, min match count for the column)
# threshold=0 means "count all maps in this group regardless of match count"
_THRESH_LABELS: list[str] = ["Total", "≥1", "≥5", "≥10", "≥20"]
_THRESH_VALUES: list[int]  = [0,       1,    5,    10,    20]

# Canonical size tier order (smallest → largest)
_TIER_ORDER: list[str] = ["pico", "nano", "micro", "centi", "milli"]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _bucket_index(count: int) -> int:
    for i, (_, lo, hi, _) in enumerate(BUCKETS):
        if lo <= count < hi:
            return i
    return len(BUCKETS) - 1


def _format_name(slug: str, max_len: int = 24) -> str:
    """Replace underscores with spaces and truncate with ellipsis if needed."""
    name = slug.replace("_", " ")
    if len(name) > max_len:
        return name[: max_len - 1] + "…"
    return name


def _wools_per_team(map_slug: str, output_dir: Path) -> int | None:
    """Read map_data.json and return rounded wools-per-team, or None."""
    p = output_dir / map_slug / "map_data.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        wools = data.get("wools", [])
        if not wools:
            return None
        wool_teams = {w.get("team") for w in wools if w.get("team")}
        if not wool_teams:
            return None
        return round(len(wools) / len(wool_teams))
    except Exception:
        return None


def _build_table_rows(
    records: list[tuple[str, int]],  # (group_key, match_count)
    key_order: list[str] | None = None,
) -> tuple[list[tuple[str, list[int]]], list[int]]:
    """Aggregate records by group key and apply match-count thresholds.

    Returns:
        rows:      list of (label, [count_per_threshold]) sorted by key_order
        total_row: [count_per_threshold] across all records
    """
    groups: dict[str, list[int]] = defaultdict(list)
    for key, cnt in records:
        groups[key].append(cnt)

    if key_order:
        sorted_keys = [k for k in key_order if k in groups]
        sorted_keys += sorted(k for k in groups if k not in key_order)
    else:
        def _sort_key(k: str) -> tuple[int, str]:
            return (int(k) if k.lstrip("-").isdigit() else 999, k)
        sorted_keys = sorted(groups, key=_sort_key)

    rows = []
    for key in sorted_keys:
        cnts = groups[key]
        row_vals = [
            len(cnts) if thresh == 0 else sum(1 for c in cnts if c >= thresh)
            for thresh in _THRESH_VALUES
        ]
        rows.append((key, row_vals))

    all_cnts = [c for _, c in records]
    total_row = [
        len(all_cnts) if thresh == 0 else sum(1 for c in all_cnts if c >= thresh)
        for thresh in _THRESH_VALUES
    ]
    return rows, total_row


# ---------------------------------------------------------------------------
# Table renderer
# ---------------------------------------------------------------------------

def _draw_summary_table(
    ax: plt.Axes,
    title: str,
    group_label: str,
    rows: list[tuple[str, list[int]]],
    total_row: list[int],
    x0: float,
    y0: float,
    table_w: float,
    row_h: float,
    spine_color: str,
    note: str | None = None,
) -> None:
    """Draw a compact summary table into ax using transAxes coordinates."""
    HDR        = "#222222"
    DATA       = "#444444"
    MUTED      = "#999999"
    TITLE_FS   = 8.5
    HDR_FS     = 7.5
    DATA_FS    = 7.5

    label_w = table_w * 0.36
    count_w = (table_w - label_w) / len(_THRESH_LABELS)

    def _col_pos(col_idx: int) -> tuple[float, str]:
        if col_idx == 0:
            return x0, "left"
        return x0 + label_w + count_w * col_idx, "right"

    y = y0

    # Title (+ optional note)
    title_text = title if not note else f"{title}  ({note})"
    ax.text(x0, y, title_text, fontsize=TITLE_FS, fontweight="bold", color=HDR,
            va="top", ha="left", transform=ax.transAxes)
    y -= row_h * 1.15

    # Column headers
    for col_idx, hdr in enumerate([group_label] + _THRESH_LABELS):
        xp, ha = _col_pos(col_idx)
        ax.text(xp, y, hdr, fontsize=HDR_FS, color=MUTED,
                va="top", ha=ha, transform=ax.transAxes)
    y -= row_h * 0.85

    # Top separator
    ax.plot([x0, x0 + table_w], [y + row_h * 0.4, y + row_h * 0.4],
            color=spine_color, lw=0.7, transform=ax.transAxes, clip_on=False)
    y -= row_h * 0.2

    # Data rows
    for label, cnts in rows:
        for col_idx, val in enumerate([label] + [str(c) for c in cnts]):
            xp, ha = _col_pos(col_idx)
            ax.text(xp, y, val, fontsize=DATA_FS, color=DATA,
                    va="top", ha=ha, transform=ax.transAxes)
        y -= row_h

    # Bottom separator
    ax.plot([x0, x0 + table_w], [y + row_h * 0.6, y + row_h * 0.6],
            color=spine_color, lw=0.5, transform=ax.transAxes, clip_on=False)
    y -= row_h * 0.05

    # Total row
    for col_idx, val in enumerate(["Total"] + [str(c) for c in total_row]):
        xp, ha = _col_pos(col_idx)
        ax.text(xp, y, val, fontsize=DATA_FS, fontweight="semibold", color=HDR,
                va="top", ha=ha, transform=ax.transAxes)


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------

def render_match_coverage(
    output_path: Path,
    db_path: str,
    min_matches: int = 1,
    sampling: int | None = None,
    output_dir: str = "output",
) -> None:
    """Query the database and write the coverage figure to *output_path*.

    Args:
        output_path: Destination PNG file.
        db_path:     Path to the DuckDB metadata database.
        min_matches: Exclude maps with fewer than this many qualifying matches
                     (applies to histogram and directory panel only).
        sampling:    If set, only count matches whose log_interval equals this
                     value (2 or 5).  NULL log_interval rows are excluded when
                     this filter is active.
        output_dir:  Root output directory for reading map_data.json files
                     (used for wools-per-team table).
    """
    # ---- main query (histogram + directory) ---------------------------------
    conn = duckdb.connect(db_path, read_only=True)

    params: list = []
    sampling_clause = ""
    if sampling is not None:
        sampling_clause = "AND ma.log_interval = ?"
        params.append(sampling)

    rows = conn.execute(
        f"""
        SELECT mp.map_slug, COUNT(ma.match_id) AS match_count,
               mp.stub, mp.size_tier
        FROM maps mp
        LEFT JOIN matches ma ON mp.map_id = ma.map_id {sampling_clause}
        GROUP BY mp.map_slug, mp.stub, mp.size_tier
        HAVING COUNT(ma.match_id) >= ?
        ORDER BY match_count DESC, mp.map_slug ASC
        """,
        params + [min_matches],
    ).fetchall()

    # ---- summary query (tables — all processed maps, unfiltered) ------------
    summary_rows = conn.execute("""
        WITH mc AS (
            SELECT map_id, COUNT(*) AS match_count FROM matches GROUP BY map_id
        ),
        tc AS (
            SELECT map_id, COUNT(DISTINCT team) AS team_count
            FROM map_spawns GROUP BY map_id
        )
        SELECT mp.map_slug,
               COALESCE(mc.match_count, 0) AS match_count,
               COALESCE(tc.team_count,  0) AS team_count,
               mp.size_tier
        FROM maps mp
        LEFT JOIN mc ON mp.map_id = mc.map_id
        LEFT JOIN tc ON mp.map_id = tc.map_id
        WHERE mp.stub IS NOT TRUE
        ORDER BY mp.map_slug
    """).fetchall()

    conn.close()

    # ---- parse results -------------------------------------------------------
    maps: list[tuple[str, int, bool, str | None]] = [
        (slug, int(cnt), bool(stub), tier)
        for slug, cnt, stub, tier in rows
    ]
    counts = np.array([c for _, c, _, _ in maps], dtype=float)

    n_maps        = len(maps)
    total_matches = int(counts.sum())
    mean_val      = float(counts.mean())
    median_val    = float(np.median(counts))
    max_val       = int(counts.max())

    summary_data: list[tuple[str, int, int, str | None]] = [
        (slug, int(cnt), int(team_cnt), tier)
        for slug, cnt, team_cnt, tier in summary_rows
    ]

    # ---- wools per team (from map_data.json) --------------------------------
    out_root = Path(output_dir)
    wools_map: dict[str, int | None] = {
        slug: _wools_per_team(slug, out_root)
        for slug, *_ in summary_data
    }

    # ---- build table data ---------------------------------------------------
    # Table 1: by size tier
    tier_records = [(tier or "?", cnt) for slug, cnt, _, tier in summary_data]
    tier_rows, tier_total = _build_table_rows(tier_records, key_order=_TIER_ORDER)

    # Table 2: by team count (skip maps with 0 = spawns not loaded)
    team_records = [
        (str(team_cnt), cnt)
        for slug, cnt, team_cnt, _ in summary_data
        if team_cnt > 0
    ]
    team_rows, team_total = _build_table_rows(team_records)

    # Table 3: by wools per team (group 4+ together)
    def _wpt_key(wpt: int) -> str:
        return str(wpt) if wpt <= 3 else "4+"

    wool_records = [
        (_wpt_key(wpt), cnt)
        for slug, cnt, _, _ in summary_data
        if (wpt := wools_map.get(slug)) is not None
    ]
    wool_rows, wool_total = _build_table_rows(
        wool_records, key_order=["1", "2", "3", "4+"]
    )
    n_with_wools = len(wool_records)
    n_total_proc = len(summary_data)

    # ---- colour / style constants -------------------------------------------
    BG          = "#FAFAF8"
    SPINE_COLOR = "#cccccc"
    LABEL_COLOR = "#444444"
    bucket_colors = [b[3] for b in BUCKETS]
    bucket_labels = [b[0] for b in BUCKETS]

    # ---- figure layout -------------------------------------------------------
    fig = plt.figure(figsize=(24, 16), facecolor=BG, dpi=150)

    gs_outer = GridSpec(
        2, 1, figure=fig,
        height_ratios=[0.35, 0.65],
        hspace=0.06,
        left=0.03, right=0.97,
        top=0.95, bottom=0.02,
    )
    gs_top = GridSpecFromSubplotSpec(
        1, 2, subplot_spec=gs_outer[0],
        width_ratios=[0.44, 0.56],
        wspace=0.07,
    )

    ax_hist = fig.add_subplot(gs_top[0])
    ax_tbl  = fig.add_subplot(gs_top[1])
    ax_dir  = fig.add_subplot(gs_outer[1])

    # =========================================================================
    # TOP-LEFT — histogram
    # =========================================================================
    ax_hist.set_facecolor(BG)

    bin_width = 5
    bin_edges = np.arange(1, max_val + bin_width + 1, bin_width, dtype=float)
    hist_counts, edges = np.histogram(counts, bins=bin_edges)
    bin_mids = (edges[:-1] + edges[1:]) / 2

    bar_colors = [bucket_colors[_bucket_index(int(m))] for m in bin_mids]
    ax_hist.bar(
        bin_mids, hist_counts,
        width=bin_width * 0.82,
        color=bar_colors,
        edgecolor="white",
        linewidth=0.6,
        zorder=2,
    )

    y_top = int(hist_counts.max())
    ax_hist.axvline(mean_val,   color="#333333", lw=1.8, ls="--", zorder=3)
    ax_hist.axvline(median_val, color="#888888", lw=1.2, ls=":",  zorder=3)
    ax_hist.text(mean_val + 1,   y_top * 0.97, f"mean {mean_val:.1f}",
                 fontsize=9, color="#333333", va="top")
    ax_hist.text(median_val + 1, y_top * 0.82, f"median {median_val:.0f}",
                 fontsize=9, color="#888888", va="top")

    stats = (
        f"{n_maps} maps   ·   {total_matches:,} total matches   ·   "
        f"mean {mean_val:.1f}   ·   median {median_val:.0f}   ·   max {max_val}"
    )
    ax_hist.text(
        0.995, 0.97, stats,
        transform=ax_hist.transAxes,
        fontsize=9, ha="right", va="top", color="#333333",
        bbox=dict(facecolor="white", edgecolor=SPINE_COLOR,
                  boxstyle="round,pad=0.35", alpha=0.9),
    )

    legend_patches = [
        mpatches.Patch(
            facecolor=color, edgecolor="#bbbbbb",
            label=f"{lbl} match{'es' if lbl != '1' else ''}",
        )
        for lbl, color in zip(bucket_labels, bucket_colors)
    ]
    ax_hist.legend(
        handles=legend_patches, loc="upper right",
        ncol=3, fontsize=8.5, framealpha=0.9,
        edgecolor=SPINE_COLOR, frameon=True,
        bbox_to_anchor=(0.995, 0.94),
    )

    ax_hist.set_xlabel("Matches per map", fontsize=10, color=LABEL_COLOR, labelpad=4)
    ax_hist.set_ylabel("Number of maps",  fontsize=10, color=LABEL_COLOR, labelpad=4)

    qualifiers = []
    if sampling is not None:
        qualifiers.append(f"{sampling}s sampling")
    if min_matches > 1:
        qualifiers.append(f"min {min_matches} matches")
    title = "CTW Analysis — Match Coverage by Map"
    if qualifiers:
        title += f"  ({', '.join(qualifiers)})"
    ax_hist.set_title(title, fontsize=14, fontweight="bold", color="#111111", pad=10)

    ax_hist.spines[["top", "right"]].set_visible(False)
    ax_hist.spines[["left", "bottom"]].set_color(SPINE_COLOR)
    ax_hist.tick_params(colors="#666666", labelsize=8.5)
    ax_hist.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax_hist.grid(axis="y", color="#e8e8e8", lw=0.7, zorder=0)
    ax_hist.set_xlim(left=0)

    # =========================================================================
    # TOP-RIGHT — summary tables (processed maps only)
    # =========================================================================
    ax_tbl.set_facecolor(BG)
    ax_tbl.set_xlim(0, 1)
    ax_tbl.set_ylim(0, 1)
    ax_tbl.axis("off")

    # Three tables side by side
    gap      = 0.03
    table_w  = (1.0 - 0.01 - gap * 2) / 3   # ≈ 0.30
    row_h    = 0.10
    y0_tbl   = 0.96

    _draw_summary_table(
        ax_tbl, "By size tier", "Size",
        tier_rows, tier_total,
        x0=0.01, y0=y0_tbl,
        table_w=table_w, row_h=row_h,
        spine_color=SPINE_COLOR,
    )
    _draw_summary_table(
        ax_tbl, "By team count", "Teams",
        team_rows, team_total,
        x0=0.01 + table_w + gap, y0=y0_tbl,
        table_w=table_w, row_h=row_h,
        spine_color=SPINE_COLOR,
    )
    wool_note = f"{n_with_wools}/{n_total_proc} maps" if n_with_wools < n_total_proc else None
    _draw_summary_table(
        ax_tbl, "By wools / team", "Wools",
        wool_rows, wool_total,
        x0=0.01 + 2 * (table_w + gap), y0=y0_tbl,
        table_w=table_w, row_h=row_h,
        spine_color=SPINE_COLOR,
        note=wool_note,
    )

    # =========================================================================
    # BOTTOM — per-map directory, grayscale text, no backgrounds
    # =========================================================================
    ax_dir.set_facecolor(BG)
    ax_dir.set_xlim(0, 1)
    ax_dir.set_ylim(0, 1)
    ax_dir.axis("off")

    N_COLS    = 6
    col_w     = 1.0 / N_COLS
    n_per_col = int(np.ceil(n_maps / N_COLS))
    row_h_dir = 1.0 / (n_per_col + 1.5)
    font_size = 8.5
    pad_x     = col_w * 0.03

    for col_idx in range(N_COLS):
        start       = col_idx * n_per_col
        end         = min(start + n_per_col, n_maps)
        col_entries = maps[start:end]

        x_left  = col_idx * col_w
        x_right = x_left + col_w - pad_x * 0.5

        if col_idx > 0:
            ax_dir.axvline(x_left, color="#e0e0e0", lw=0.8, zorder=0)

        hdr_y = 1.0 - row_h_dir * 0.7
        ax_dir.text(
            x_left + pad_x, hdr_y,
            f"#{start + 1} – #{start + len(col_entries)}",
            fontsize=7.5, color="#aaaaaa", va="center", ha="left",
            transform=ax_dir.transAxes,
        )

        for row_idx, (slug, count, is_stub, size_tier) in enumerate(col_entries):
            y_center = 1.0 - row_h_dir * (row_idx + 1.5) - row_h_dir * 0.5

            text_color = "#D8D8D8" if is_stub else _BUCKET_GRAY[_bucket_index(count)]

            # Map name
            ax_dir.text(
                x_left + pad_x, y_center,
                _format_name(slug),
                fontsize=font_size, color=text_color,
                va="center", ha="left",
                transform=ax_dir.transAxes,
                clip_on=False,
            )

            # Size tier badge (processed maps only)
            if not is_stub and size_tier:
                ax_dir.text(
                    x_left + col_w * 0.55, y_center,
                    size_tier,
                    fontsize=6.5, color="#aaaaaa",
                    va="center", ha="left",
                    transform=ax_dir.transAxes,
                    clip_on=False,
                )

            # Match count
            ax_dir.text(
                x_right, y_center,
                str(count),
                fontsize=font_size, color=text_color,
                va="center", ha="right",
                fontweight="semibold",
                transform=ax_dir.transAxes,
                clip_on=False,
            )

    # ---- save ---------------------------------------------------------------
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"Saved: {output_path}")
