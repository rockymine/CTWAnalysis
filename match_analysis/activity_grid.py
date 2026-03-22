"""Match activity heatmap: 24 rows (hours, local time) × one column per day,
grouped into ISO weeks (Mon–Sun) with a visible gap between weeks.

Cell colour  → fraction of that hour occupied by CTW matches (coverage).
Cell number  → count of distinct matches that touched that hour slot.

The maximum display window is 8 weeks (~2 months). Wider ranges are clipped
to 8 weeks from the start date with a warning.

All timestamps stored in the DB are UTC; the grid is displayed in Europe/Berlin.
"""
import argparse
import collections
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import duckdb
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import pandas as pd

# ── Constants ──────────────────────────────────────────────────────────────────

DB_PATH    = 'match_analysis/metadata.db'
DISPLAY_TZ = ZoneInfo('Europe/Berlin')

MAX_WEEKS = 8  # hard ceiling (~2 months)

# Mirrors _SIZE_TIERS in ctw/commands/maps.py — largest first
SIZE_TIER_ORDER = ['giga', 'mega', 'hecto', 'centi', 'milli', 'micro', 'nano', 'pico']

DAY_LETTERS = ['M', 'T', 'W', 'T', 'F', 'S', 'S']

# GitHub-style green ramp: index 0 = no activity
COVERAGE_PALETTE = ['#ebedf0', '#9be9a8', '#40c463', '#30a14e', '#216e39']

# Coverage fraction thresholds that step to the next palette entry
COVERAGE_STEPS = [0.0, 0.01, 0.25, 0.50, 0.75]


# ── Colour helpers ─────────────────────────────────────────────────────────────

def _color_index(fraction: float) -> int:
    index = 0
    for step_index, threshold in enumerate(COVERAGE_STEPS):
        if fraction >= threshold:
            index = step_index
    return index


def _text_color(color_index: int) -> str:
    return 'white' if color_index >= 3 else '#24292e'


# ── Week / duration helpers ────────────────────────────────────────────────────

def _week_monday(day: date) -> date:
    """Return the Monday of the ISO week containing day."""
    return day - timedelta(days=day.weekday())


def _week_header(monday: date) -> str:
    """Compact range label: 'Jan 19–25' or 'Jan 26 – Feb 1'."""
    sunday = monday + timedelta(days=6)
    if monday.month == sunday.month:
        return f"{monday.strftime('%b')} {monday.day}–{sunday.day}"
    return f"{monday.strftime('%b')} {monday.day} – {sunday.strftime('%b')} {sunday.day}"


def _weeks_in_range(start_date: date, end_date: date) -> list[date]:
    """Return list of Mondays for every week that overlaps [start_date, end_date]."""
    monday = _week_monday(start_date)
    weeks: list[date] = []
    while monday <= end_date:
        weeks.append(monday)
        monday += timedelta(weeks=1)
    return weeks


def _fmt_duration(seconds: float) -> str:
    """Format a duration in seconds as '47m36s' or '1h20m'."""
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m{secs:02d}s"


# ── Data loading ───────────────────────────────────────────────────────────────

def _load_date_bounds() -> tuple[date, date]:
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        row = conn.execute("""
            SELECT
                MIN(match_start AT TIME ZONE 'Europe/Berlin')::DATE,
                MAX(match_start AT TIME ZONE 'Europe/Berlin')::DATE
            FROM matches
            WHERE match_start IS NOT NULL
        """).fetchone()
    finally:
        conn.close()
    return row[0], row[1]


def _load_matches(start_date: date, end_date: date,
                  min_duration: float | None = None) -> pd.DataFrame:
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        df = conn.execute("""
            SELECT
                mat.match_id,
                mat.match_start,
                mat.match_duration,
                ma.map_name,
                ma.size_tier
            FROM matches mat
            JOIN maps ma ON mat.map_id = ma.map_id
            WHERE mat.match_start IS NOT NULL
              AND mat.match_duration IS NOT NULL
              AND mat.match_duration > 0
            ORDER BY mat.match_start
        """).df()
    finally:
        conn.close()

    df['start_local'] = (
        pd.to_datetime(df['match_start'])
        .dt.tz_localize('UTC')
        .dt.tz_convert('Europe/Berlin')
    )
    df['end_local'] = (
        df['start_local'] + pd.to_timedelta(df['match_duration'], unit='s')
    )

    range_start = pd.Timestamp(start_date, tz='Europe/Berlin')
    range_end   = pd.Timestamp(end_date,   tz='Europe/Berlin') + pd.Timedelta(days=1)
    mask = (df['end_local'] > range_start) & (df['start_local'] < range_end)
    df = df[mask].copy().reset_index(drop=True)

    if min_duration is not None:
        df = df[df['match_duration'] >= min_duration].reset_index(drop=True)

    return df


# ── Aggregation ────────────────────────────────────────────────────────────────

def _build_cells(df: pd.DataFrame) -> dict[tuple[date, int], dict]:
    """
    Returns (local_date, hour) → cell dict.
    cell: { 'seconds': float, 'match_ids': set[int], 'tiers': list[str] }
    A match spanning multiple hours is counted in every overlapping slot.
    """
    cells: dict = collections.defaultdict(
        lambda: {'seconds': 0.0, 'match_ids': set(), 'tiers': []}
    )
    for _, row in df.iterrows():
        start_dt = row['start_local']
        end_dt   = row['end_local']
        match_id = int(row['match_id'])
        tier     = row['size_tier']

        slot = start_dt.floor('h')
        while slot < end_dt:
            slot_end = slot + pd.Timedelta(hours=1)
            overlap  = (min(end_dt, slot_end) - max(start_dt, slot)).total_seconds()
            if overlap > 0:
                key = (slot.date(), slot.hour)
                cells[key]['seconds']    += overlap
                cells[key]['match_ids'].add(match_id)
                cells[key]['tiers'].append(tier)
            slot = slot_end

    return dict(cells)


def _dominant_tier(tiers: list[str]) -> str | None:
    if not tiers:
        return None
    counts = collections.Counter(tiers)
    for tier in SIZE_TIER_ORDER:
        if tier in counts:
            return tier
    return None


def _build_daily_summary(df: pd.DataFrame) -> list[dict]:
    """One row per active day: date, match count, unique map count, dominant tier."""
    daily: dict[date, dict] = collections.defaultdict(
        lambda: {'match_ids': set(), 'map_names': set(), 'tiers': []}
    )
    for _, row in df.iterrows():
        day = row['start_local'].date()
        mid = int(row['match_id'])
        daily[day]['match_ids'].add(mid)
        daily[day]['map_names'].add(row['map_name'])
        daily[day]['tiers'].append(row['size_tier'])

    return [
        {
            'date':        day,
            'matches':     len(info['match_ids']),
            'unique_maps': len(info['map_names']),
            'tier':        _dominant_tier(info['tiers']) or '—',
        }
        for day, info in sorted(daily.items())
    ]


def _build_weekly_longest(df: pd.DataFrame) -> dict[date, list[dict]]:
    """Returns week_monday → top-3 longest matches (desc) as list of {duration_s, map_name}."""
    weekly: dict[date, list[dict]] = collections.defaultdict(list)
    for _, row in df.iterrows():
        monday = _week_monday(row['start_local'].date())
        weekly[monday].append({
            'duration_s': float(row['match_duration']),
            'map_name':   row['map_name'],
        })
    return {
        monday: sorted(matches, key=lambda entry: entry['duration_s'], reverse=True)[:3]
        for monday, matches in weekly.items()
    }


# ── Layout helpers ─────────────────────────────────────────────────────────────

# Layout constants (inches)
_CELL_W       = 0.21
_CELL_H       = 0.20
_WEEK_GAP     = 0.07
_LEFT_MARGIN  = 0.55
_RIGHT_MARGIN = 0.25
_TOP_MARGIN   = 0.75
_GRID_PAD     = 0.12
_LEGEND_H     = 0.35
_SECTION_GAP  = 0.22
_TABLE_H      = 1.80
_BOT_MARGIN   = 0.30

# Summary section (in grid coordinate units)
_SUMMARY_LINES  = 10     # ylim depth (0 = top)
_SUMMARY_HDR_Y  = 0.50   # y of global header
_SUMMARY_ROW_Y0 = 1.40   # y of first day row
_SUMMARY_ROW_DY = 0.78   # vertical step per day row
_SUMMARY_SEP_DY = 0.50   # extra gap below last day row before separator
_SUMMARY_LONG_DY = 0.60  # vertical step between longest-match lines
_SUMMARY_FONT   = 4.8
_SUMMARY_HDR_FS = 5.5


def _x_total(n_weeks: int) -> float:
    return n_weeks * 7 + max(0, n_weeks - 1) * (_WEEK_GAP / _CELL_W)


def _week_x(week_idx: int) -> float:
    return week_idx * (7 + _WEEK_GAP / _CELL_W)


# ── Drawing ────────────────────────────────────────────────────────────────────

def _draw_heatmap(
    ax,
    cells: dict,
    weeks: list[date],
    start_date: date,
    end_date: date,
) -> None:
    xtotal = _x_total(len(weeks))
    ax.set_xlim(0, xtotal)
    ax.set_ylim(24, 0)
    ax.axis('off')

    INSET = 0.06

    for week_idx, monday in enumerate(weeks):
        wx = _week_x(week_idx)

        ax.text(
            wx + 3.5, -0.62,
            _week_header(monday),
            ha='center', va='bottom',
            fontsize=6.5, color='#57606a',
            clip_on=False,
        )

        for dow in range(7):
            current_day = monday + timedelta(days=dow)
            col_x = wx + dow

            ax.text(
                col_x + 0.5, -0.18,
                DAY_LETTERS[dow],
                ha='center', va='bottom',
                fontsize=4.5, color='#8c959f',
                clip_on=False,
            )

            in_range = start_date <= current_day <= end_date

            for hour in range(24):
                if not in_range:
                    rect = mpatches.Rectangle(
                        (col_x + INSET, hour + INSET),
                        1 - 2 * INSET, 1 - 2 * INSET,
                        facecolor='#f6f8fa', edgecolor='none',
                        clip_on=False,
                    )
                    ax.add_patch(rect)
                    continue

                cell_data = cells.get((current_day, hour))
                if cell_data:
                    fraction  = min(cell_data['seconds'] / 3600.0, 1.0)
                    cidx      = _color_index(fraction)
                    n_matches = len(cell_data['match_ids'])
                else:
                    cidx      = 0
                    n_matches = 0

                rect = mpatches.Rectangle(
                    (col_x + INSET, hour + INSET),
                    1 - 2 * INSET, 1 - 2 * INSET,
                    facecolor=COVERAGE_PALETTE[cidx], edgecolor='none',
                    clip_on=False,
                )
                ax.add_patch(rect)

                if n_matches > 0:
                    ax.text(
                        col_x + 0.5, hour + 0.5,
                        str(n_matches),
                        ha='center', va='center',
                        fontsize=3.8, color=_text_color(cidx),
                        fontweight='bold',
                        clip_on=False,
                    )

    for hour in range(0, 24, 3):
        ax.text(
            -0.18, hour + 0.5,
            f'{hour:02d}h',
            ha='right', va='center',
            fontsize=6, color='#57606a',
            clip_on=False,
        )


def _draw_legend(ax, n_weeks: int) -> None:
    xtotal = _x_total(n_weeks)
    ax.set_xlim(0, xtotal)
    ax.set_ylim(0, 1)
    ax.axis('off')

    sq_w      = xtotal / 55          # compact squares
    sq_gap    = 0.35 * sq_w          # gap between squares
    sq_size_h = 0.42                 # square height in y-units (0–1 scale)
    n_items   = len(COVERAGE_PALETTE)

    squares_w = n_items * sq_w + (n_items - 1) * sq_gap
    right_end = xtotal - 0.3        # small right margin
    sq_start  = right_end - squares_w

    ax.text(
        sq_start - 0.4, 0.5,
        'Coverage',
        ha='right', va='center',
        fontsize=6.5, color='#57606a',
    )
    for palette_idx, color in enumerate(COVERAGE_PALETTE):
        sq_x = sq_start + palette_idx * (sq_w + sq_gap)
        rect = mpatches.Rectangle(
            (sq_x, (1 - sq_size_h) / 2),
            sq_w, sq_size_h,
            facecolor=color, edgecolor='none',
        )
        ax.add_patch(rect)


def _draw_summary_table(
    ax,
    summary: list[dict],
    weeks: list[date],
    weekly_longest: dict[date, list[dict]],
    start_date: date,
    end_date: date,
) -> None:
    xtotal = _x_total(len(weeks))
    ax.set_xlim(0, xtotal)
    ax.set_ylim(_SUMMARY_LINES, 0)
    ax.axis('off')

    rows_by_day: dict[date, dict] = {row['date']: row for row in summary}

    ax.text(
        0, _SUMMARY_HDR_Y,
        'Daily summary  ·  matches  ·  maps  ·  dominant tier',
        ha='left', va='center',
        fontsize=_SUMMARY_HDR_FS, color='#57606a',
        style='italic',
        clip_on=False,
    )

    for week_idx, monday in enumerate(weeks):
        wx = _week_x(week_idx)

        for dow in range(7):
            current_day = monday + timedelta(days=dow)
            ypos        = _SUMMARY_ROW_Y0 + dow * _SUMMARY_ROW_DY
            day_str     = current_day.strftime('%a %d')
            row_data    = rows_by_day.get(current_day)

            if row_data:
                line = (
                    f"{day_str:<6}"
                    f"  {row_data['matches']:>3}"
                    f"  {row_data['unique_maps']:>3}"
                    f"  {row_data['tier']:<5}"
                )
                color = '#24292e'
            else:
                line  = f"{day_str:<6}   —    —   —"
                color = '#a8b2bf'

            ax.text(
                wx + 0.15, ypos, line,
                ha='left', va='center',
                fontsize=_SUMMARY_FONT, color=color,
                fontfamily='monospace',
                clip_on=False,
            )

        # Top-3 longest matches below the day rows (separator always at same y)
        top_matches = weekly_longest.get(monday, [])
        if top_matches:
            sep_y = _SUMMARY_ROW_Y0 + 7 * _SUMMARY_ROW_DY + _SUMMARY_SEP_DY
            ax.text(
                wx + 0.15, sep_y,
                '─' * 11,
                ha='left', va='center',
                fontsize=_SUMMARY_FONT, color='#d0d7de',
                fontfamily='monospace',
                clip_on=False,
            )
            for match_idx, match_info in enumerate(top_matches):
                match_y     = sep_y + (match_idx + 1) * _SUMMARY_LONG_DY
                dur_str     = _fmt_duration(match_info['duration_s'])
                map_display = match_info['map_name'][:16]
                ax.text(
                    wx + 0.15, match_y,
                    f"{dur_str}  {map_display}",
                    ha='left', va='center',
                    fontsize=_SUMMARY_FONT, color='#57606a',
                    fontfamily='monospace',
                    clip_on=False,
                )


def _render(
    cells: dict,
    weeks: list[date],
    start_date: date,
    end_date: date,
    summary: list[dict],
    weekly_longest: dict[date, dict],
    output_path: str,
) -> None:
    n_weeks = len(weeks)
    xtotal  = _x_total(n_weeks)
    axes_w  = xtotal * _CELL_W
    axes_h  = 24 * _CELL_H

    fig_w = _LEFT_MARGIN + axes_w + _RIGHT_MARGIN
    fig_h = (
        _TOP_MARGIN + axes_h + _GRID_PAD
        + _LEGEND_H + _SECTION_GAP
        + _TABLE_H + _BOT_MARGIN
    )

    def norm_rect(left_in: float, bottom_in: float, width_in: float, height_in: float):
        return [left_in / fig_w, bottom_in / fig_h, width_in / fig_w, height_in / fig_h]

    fig = plt.figure(figsize=(fig_w, fig_h), dpi=150)
    fig.patch.set_facecolor('white')

    title_y = (
        _BOT_MARGIN + _TABLE_H + _SECTION_GAP + _LEGEND_H + _GRID_PAD + axes_h + _TOP_MARGIN * 0.3
    ) / fig_h
    fig.text(
        _LEFT_MARGIN / fig_w, title_y,
        f"CTW Match Activity  ·  {start_date.strftime('%d %b %Y')} – "
        f"{end_date.strftime('%d %b %Y')}  ·  Europe/Berlin",
        ha='left', va='bottom',
        fontsize=9, color='#24292e', fontweight='bold',
    )

    grid_bottom = _BOT_MARGIN + _TABLE_H + _SECTION_GAP + _LEGEND_H + _GRID_PAD
    grid_ax = fig.add_axes(norm_rect(_LEFT_MARGIN, grid_bottom, axes_w, axes_h))
    _draw_heatmap(grid_ax, cells, weeks, start_date, end_date)

    legend_bottom = _BOT_MARGIN + _TABLE_H + _SECTION_GAP
    legend_ax = fig.add_axes(norm_rect(_LEFT_MARGIN, legend_bottom, axes_w, _LEGEND_H))
    _draw_legend(legend_ax, n_weeks)

    table_ax = fig.add_axes(norm_rect(_LEFT_MARGIN, _BOT_MARGIN, axes_w, _TABLE_H))
    _draw_summary_table(table_ax, summary, weeks, weekly_longest, start_date, end_date)

    fig.savefig(output_path, bbox_inches='tight', dpi=150, facecolor='white')
    plt.close(fig)


# ── Public entry point ─────────────────────────────────────────────────────────

def generate(args: argparse.Namespace) -> None:
    """Generate the activity grid PNG from a parsed argparse Namespace.

    Expected attributes on args:
        start  (str | None)  – ISO date string or None (→ earliest match in DB)
        end    (str | None)  – ISO date string or None (→ latest match in DB)
        output (str)         – output PNG path
        min_duration (int | None) – minimum match duration in seconds to include
    """
    db_start, db_end = _load_date_bounds()
    start_date = date.fromisoformat(args.start) if args.start else db_start
    end_date   = date.fromisoformat(args.end)   if args.end   else db_end

    max_end = start_date + timedelta(weeks=MAX_WEEKS) - timedelta(days=1)
    if end_date > max_end:
        print(f"Warning: range exceeds {MAX_WEEKS} weeks — clipping end to {max_end}")
        end_date = max_end

    min_duration = getattr(args, 'min_duration', None)

    print(f"Range:  {start_date} – {end_date}")

    df = _load_matches(start_date, end_date, min_duration=min_duration)
    print(f"Loaded: {len(df)} matches"
          + (f" (>= {min_duration}s)" if min_duration else ""))

    cells          = _build_cells(df)
    summary        = _build_daily_summary(df)
    weekly_longest = _build_weekly_longest(df)
    weeks          = _weeks_in_range(start_date, end_date)
    print(f"Weeks:  {len(weeks)}  |  Active days: {len(summary)}")

    _render(cells, weeks, start_date, end_date, summary, weekly_longest, args.output)
    print(f"Saved:  {args.output}")
