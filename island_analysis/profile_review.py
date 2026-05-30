"""Interactive web review server for island profile classification.

Starts a local HTTP server that renders all canonical islands grouped by
profile type.  Each cell shows an SVG thumbnail, a copyable canonical_key,
key metrics, and a dropdown to reassign the classification.  Changes are
saved immediately to island_profile_overrides.json.

Usage (via CLI):
    python ctw.py islands profile-review [--map <name>] [--type <profile>] [--port 7890]
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional

import numpy as np

from island_analysis.profile import (
    IslandProfile,
    _ALL_TYPES,
    _TYPE_COLORS,
    load_override_data,
    load_overrides,
    save_override_data,
)


# ---------------------------------------------------------------------------
# SVG coordinate helpers (shared between initial render and live endpoints)
# ---------------------------------------------------------------------------


def _make_svg_normalizer(
    exterior: list,
    size: int = 144,
) -> tuple[np.ndarray, float, int, float]:
    """Compute SVG normalisation constants from an island polygon exterior.

    Returns (min_xy, extent, padding, draw_size) so that any coordinate array
    can be mapped into the SVG viewport via :func:`_apply_svg_norm`.
    """
    pts = np.asarray(exterior, dtype=float)
    min_xy = pts.min(axis=0)
    max_xy = pts.max(axis=0)
    extent = max(float((max_xy - min_xy).max()), 1.0)
    padding = 5
    draw_size = float(size - 2 * padding)
    return min_xy, extent, padding, draw_size


def _apply_svg_norm(
    coords: list | np.ndarray,
    min_xy: np.ndarray,
    extent: float,
    padding: int,
    draw_size: float,
) -> np.ndarray:
    """Map world-space coordinates into SVG viewport space."""
    arr = np.asarray(coords, dtype=float)
    return (arr - min_xy) / extent * draw_size + padding


def _blocks_from_exact_polygon(poly_data: dict) -> np.ndarray:
    """Reconstruct integer block positions from an exact union polygon.

    Tests whether the centre of each candidate block (x+0.5, z+0.5) lies
    inside the polygon.  Used to feed the live polygon-smoothing and
    skeleton-from-polygon endpoints.

    Returns an Nx2 int array of (x, z) block indices, or an empty array
    if the polygon has fewer than 3 vertices.
    """
    from shapely.geometry import Polygon, Point

    exterior = poly_data.get('exterior') or []
    holes = poly_data.get('holes') or []
    if len(exterior) < 3:
        return np.empty((0, 2), dtype=int)

    shapely_poly = Polygon(exterior, holes)
    minx, minz, maxx, maxz = shapely_poly.bounds
    blocks = [
        [x, z]
        for x in range(int(np.floor(minx)), int(np.ceil(maxx)))
        for z in range(int(np.floor(minz)), int(np.ceil(maxz)))
        if shapely_poly.contains(Point(x + 0.5, z + 0.5))
    ]
    if not blocks:
        return np.empty((0, 2), dtype=int)
    return np.array(blocks, dtype=int)


def _polygon_data_to_svg_path(
    poly_data: dict,
    min_xy: np.ndarray,
    extent: float,
    padding: int,
    draw_size: float,
) -> str:
    """Convert a polygon coords dict to an SVG path d string."""
    exterior = poly_data.get('exterior') or []
    holes = poly_data.get('holes') or []
    if len(exterior) < 3:
        return ''

    def ring_to_segment(ring: list) -> str:
        coords = _apply_svg_norm(ring, min_xy, extent, padding, draw_size)
        pairs = ' '.join(f'{x:.1f},{y:.1f}' for x, y in coords)
        return f'M {pairs} Z'

    path_d = ring_to_segment(exterior)
    for hole in holes:
        if len(hole) >= 3:
            path_d += ' ' + ring_to_segment(hole)
    return path_d


def _skeleton_result_to_svg_polylines(
    skel_result: object,
    min_xy: np.ndarray,
    extent: float,
    padding: int,
    draw_size: float,
) -> list[str]:
    """Convert an IslandSkeleton result to a list of SVG polyline points strings.

    Converts each edge's pixel path from raster → canonical → world block
    indices, then applies +0.5 (block-centres rule) before normalising to SVG
    space.
    """
    transform = skel_result.canonical.transform
    raster = skel_result.raster
    polylines = []
    for edge in skel_result.graph.edges:
        if len(edge.pixel_path) < 2:
            continue
        path_canonical = np.array(
            [raster.rc_to_canonical(r, c) for r, c in edge.pixel_path],
            dtype=float,
        )
        path_world = transform.to_original(path_canonical)  # world block indices
        # +0.5: shift from lower-left corner to block centre (block-centres rule)
        coords = _apply_svg_norm(path_world + 0.5, min_xy, extent, padding, draw_size)
        polylines.append(' '.join(f'{x:.1f},{y:.1f}' for x, y in coords))
    return polylines


# ---------------------------------------------------------------------------
# SVG renderer
# ---------------------------------------------------------------------------


def _island_svg(island_dict: dict, color: str, size: int = 110, traffic_svg: str = '') -> str:
    """Render island polygon as a self-contained SVG element.

    Normalizes the polygon to fill the viewport with padding so all shapes
    are displayed at comparable scale.  Uses SVG path fill-rule=evenodd so
    holes render correctly.

    Includes hidden overlay groups for:
    - .skel-overlay         block-raster skeleton (toggled by existing JS)
    - .smooth-overlay       smoothed/simplified polygon outline (toggled by sliders)
    - .smooth-skel-overlay  skeleton computed from the smoothed polygon
    """
    poly = island_dict.get('simplified_polygon') or {}
    exterior = poly.get('exterior') or []
    holes = poly.get('holes') or []

    if len(exterior) < 3:
        return (
            f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
            f'xmlns="http://www.w3.org/2000/svg" style="display:block">'
            f'<rect width="{size}" height="{size}" fill="#eee"/>'
            f'<text x="{size // 2}" y="{size // 2 + 4}" text-anchor="middle" '
            f'font-size="11" fill="#aaa">?</text></svg>'
        )

    min_xy, extent, padding, draw_size = _make_svg_normalizer(exterior, size)

    def to_svg(coords: list | np.ndarray) -> np.ndarray:
        return _apply_svg_norm(coords, min_xy, extent, padding, draw_size)

    def ring_to_path_segment(ring_pts: list | np.ndarray) -> str:
        coords = to_svg(ring_pts)
        pairs = ' '.join(f'{x:.1f},{y:.1f}' for x, y in coords)
        return f'M {pairs} Z'

    # Base polygon (exact unit shape).
    path_d = ring_to_path_segment(exterior)
    for hole in holes:
        if len(hole) >= 3:
            path_d += ' ' + ring_to_path_segment(hole)

    # Block-raster skeleton overlay (hidden by default).
    skeleton_group = ''
    skeleton = island_dict.get('skeleton') or {}
    edge_pixels: dict = skeleton.get('edge_pixels') or {}
    if edge_pixels:
        polylines = []
        for edge_data in edge_pixels.values():
            pixels = edge_data.get('pixels') or []
            if len(pixels) < 2:
                continue
            # Skeleton pixels are world-space block indices (lower-left corner
            # of each unit square).  Add 0.5 to reach block centres, so they
            # align with the polygon boundary which uses extent coordinates.
            coords = to_svg(np.asarray(pixels, dtype=float) + 0.5)
            points_str = ' '.join(f'{x:.1f},{y:.1f}' for x, y in coords)
            polylines.append(
                f'<polyline points="{points_str}" fill="none" '
                f'stroke="#4a9eda" stroke-width="1.5" '
                f'stroke-linecap="round" stroke-linejoin="round"/>'
            )
        if polylines:
            skeleton_group = (
                '<g class="skel-overlay" style="display:none">'
                + ''.join(polylines)
                + '</g>'
            )

    # Smooth polygon overlay — initially populated from smoothed_polygon if
    # pre-computed by the pipeline; otherwise empty path updated live by JS.
    smooth_poly_data = island_dict.get('smoothed_polygon') or {}
    smooth_path_d = _polygon_data_to_svg_path(
        smooth_poly_data, min_xy, extent, padding, draw_size
    ) if smooth_poly_data else ''
    smooth_display = '' if smooth_path_d else 'display:none;'
    smooth_group = (
        f'<g class="smooth-overlay" style="{smooth_display}">'
        f'<path class="smooth-path" d="{smooth_path_d}" fill="none" '
        f'stroke="#4a9eda" stroke-width="1.5" stroke-dasharray="3,2" fill-rule="evenodd"/>'
        f'</g>'
    )

    # Smooth-skeleton overlay — empty initially, populated on demand by JS.
    smooth_skel_group = '<g class="smooth-skel-overlay" style="display:none"></g>'

    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
        f'xmlns="http://www.w3.org/2000/svg" style="display:block">'
        f'<path d="{path_d}" fill="{color}" fill-opacity="0.30" '
        f'stroke="#333" stroke-width="0.8" fill-rule="evenodd"/>'
        f'{traffic_svg}'
        f'{skeleton_group}'
        f'{smooth_group}'
        f'{smooth_skel_group}'
        f'</svg>'
    )


# ---------------------------------------------------------------------------
# Traffic heatmap builder
# ---------------------------------------------------------------------------


def _build_traffic_overlays(
    entries: list[tuple[str, IslandProfile, dict]],
    svg_norm: dict[str, tuple],
    db_path: Path,
) -> dict[str, str]:
    """Build per-canonical-key player traffic heatmap SVG groups.

    Queries position_events grouped by (map_slug, island_id, x, z) and
    accumulates visit counts across all matches for each canonical shape.
    Each canonical key maps to a hidden <g class="traffic-overlay"> with one
    <rect> per visited block, coloured by log-scaled visit density.

    Returns canonical_key -> SVG group string.  Keys with no data are absent.
    """
    import math
    import duckdb
    import logging
    _log = logging.getLogger('ctw')

    # Build (map_slug, island_id) -> (canonical_key, min_x, min_z).
    # min_x/min_z from bounding_box allow positions to be expressed relative
    # to each instance's own origin before mapping into the SVG viewport.
    instance_meta: dict[tuple[str, int], tuple[str, float, float]] = {}
    for map_slug, profile, island_dict in entries:
        key = profile.canonical_key
        if key not in svg_norm:
            continue
        island_id = island_dict.get('id')
        bbox = island_dict.get('bounding_box')   # [min_x, max_x, min_z, max_z]
        if island_id is None or not bbox:
            continue
        instance_meta[(map_slug, island_id)] = (key, float(bbox[0]), float(bbox[2]))

    if not instance_meta:
        return {}

    # One bulk query: visit counts per (map_slug, island_id, x, z).
    try:
        con = duckdb.connect(str(db_path), read_only=True)
        rows = con.execute("""
            SELECT m.map_slug, pe.island_id, pe.x, pe.z, COUNT(*) AS visits
            FROM position_events pe
            JOIN matches mt ON pe.match_id = mt.match_id
            JOIN maps   m  ON mt.map_id   = m.map_id
            WHERE pe.location_type = 'island'
            GROUP BY m.map_slug, pe.island_id, pe.x, pe.z
        """).fetchall()
        con.close()
    except Exception as exc:
        _log.warning(f'Traffic overlay query failed: {exc}')
        return {}

    # Accumulate visit counts per canonical key using relative coords (offset
    # from each instance's bbox origin).  Instances of the same canonical shape
    # have the same extents so their relative grids overlay correctly.
    grids: dict[str, dict[tuple[int, int], int]] = {}
    for map_slug, island_id, px, pz, visits in rows:
        meta = instance_meta.get((map_slug, island_id))
        if meta is None:
            continue
        key, min_x, min_z = meta
        rel_x = int(px) - int(min_x)
        rel_z = int(pz) - int(min_z)
        if rel_x < 0 or rel_z < 0:
            continue
        grid = grids.setdefault(key, {})
        coord = (rel_x, rel_z)
        grid[coord] = grid.get(coord, 0) + visits

    # Render each key's grid as SVG <rect> elements with log-scaled opacity.
    result: dict[str, str] = {}
    for key, grid in grids.items():
        if not grid or key not in svg_norm:
            continue
        _min_xy, extent, padding, draw_size = svg_norm[key]
        block_px = draw_size / extent   # SVG pixels per one world block

        max_count = max(grid.values())
        log_max = math.log(max_count + 1)

        rects: list[str] = []
        for (rel_x, rel_z), count in grid.items():
            svg_x = rel_x / extent * draw_size + padding
            svg_y = rel_z / extent * draw_size + padding
            opacity = 0.08 + 0.62 * math.log(count + 1) / log_max
            rects.append(
                f'<rect x="{svg_x:.1f}" y="{svg_y:.1f}" '
                f'width="{block_px:.1f}" height="{block_px:.1f}" '
                f'fill="#4a9eda" opacity="{opacity:.2f}"/>'
            )

        if rects:
            result[key] = (
                '<g class="traffic-overlay" style="display:none">'
                + ''.join(rects)
                + '</g>'
            )

    return result


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------


def _build_html(
    entries: list[tuple[str, IslandProfile, dict]],
    override_data: dict[str, dict[str, str]],
    type_filter: Optional[str] = None,
    key_has_matches: Optional[dict[str, bool]] = None,
    traffic_svg_by_key: Optional[dict[str, str]] = None,
) -> str:
    """Generate the full review page HTML.

    Parameters
    ----------
    entries:
        (map_slug, IslandProfile, representative_island_dict) triples.
    override_data:
        Full override data: canonical_key → {profile, note}.
    type_filter:
        If set, only show islands of this type.
    key_has_matches:
        canonical_key → bool; True if the shape appears in a map with recorded
        match data.  When None or empty, the matches-only toggle is hidden.
    traffic_svg_by_key:
        canonical_key → pre-rendered SVG traffic heatmap group string.
        When None or empty, the position data toggle is hidden.
    """
    key_has_matches = key_has_matches or {}
    traffic_svg_by_key = traffic_svg_by_key or {}
    # Build a lookup from canonical_key to all map slugs where it appears
    key_maps: dict[str, list[str]] = {}
    for map_slug, profile, _ in entries:
        key_maps.setdefault(profile.canonical_key, []).append(map_slug)

    # Group entries by effective island_type, de-duplicating by canonical_key
    # (show one cell per canonical shape, not one per map instance)
    seen_keys: set[str] = set()
    by_type: dict[str, list[tuple[str, IslandProfile, dict]]] = {}
    for map_slug, profile, island_dict in entries:
        if type_filter and profile.island_type != type_filter:
            continue
        if profile.canonical_key in seen_keys:
            continue
        seen_keys.add(profile.canonical_key)
        by_type.setdefault(profile.island_type, []).append((map_slug, profile, island_dict))

    total_shapes = len(seen_keys)
    total_maps = len({map_slug for map_slug, _, _ in entries})
    entry_keys = {profile.canonical_key for _, profile, _ in entries}
    active_override_count = sum(
        1 for key, entry in override_data.items()
        if key in entry_keys and entry.get('profile')
    )

    all_options_html = '\n'.join(
        f'<option value="{t}">{t}</option>' for t in _ALL_TYPES
    )

    sections_html = _build_sections(by_type, override_data, key_maps, all_options_html, key_has_matches, traffic_svg_by_key)

    nav_links = ' | '.join(
        f'<a href="#{t}">{t} ({len(by_type[t])})</a>'
        for t in _ALL_TYPES
        if t in by_type
    )

    filter_note = f' — filtered to <b>{type_filter}</b>' if type_filter else ''
    matches_btn = (
        '<button id="matches-only" class="hdr-btn">hide maps &lt;10 matches</button>'
        if key_has_matches else ''
    )
    traffic_btn = (
        '<button id="traffic-all" class="hdr-btn">show position data</button>'
        if traffic_svg_by_key else ''
    )

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Island Profile Review</title>
<style>
* {{ box-sizing: border-box; }}
body {{ font-family: monospace; font-size: 12px; background: #e8e8e8; margin: 0; padding: 16px; }}
header {{ background: #222; color: #eee; padding: 10px 16px; margin: -16px -16px 16px; position: sticky; top: 0; z-index: 10; }}
header h1 {{ font-size: 14px; margin: 0 0 6px; }}
header .summary {{ font-size: 11px; color: #aaa; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
header .nav {{ font-size: 11px; margin-top: 4px; }}
header .nav a {{ color: #7ec8e3; text-decoration: none; }}
header .nav a:hover {{ text-decoration: underline; }}
section {{ margin-bottom: 28px; }}
section h2 {{ font-size: 13px; font-weight: bold; border-bottom: 3px solid; padding-bottom: 3px; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }}
section h2 .swatch {{ display: inline-block; width: 14px; height: 14px; border-radius: 2px; border: 1px solid #555; }}
.grid {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.cell {{ background: #fff; border: 1px solid #ccc; border-radius: 5px; padding: 7px; width: 192px; transition: border-color 0.15s; }}
.cell.overridden {{ border: 2px solid #e67e22; background: #fffaf4; }}
.cell.manual {{ border: 2px solid #8e44ad; background: #fdf4ff; }}
.cell svg {{ margin: 0 auto 4px; }}
code.key {{ display: block; text-align: center; font-size: 11px; user-select: all; cursor: text; padding: 2px 4px; background: #f0f0f0; border-radius: 3px; margin: 2px 0 4px; letter-spacing: 0.03em; }}
.meta {{ font-size: 10px; color: #999; text-align: center; line-height: 1.3; margin-bottom: 3px; }}
.auto-badge {{ font-size: 10px; color: #2ecc71; display: block; }}
.override-badge {{ font-size: 10px; color: #e67e22; font-weight: bold; display: block; }}
.symm-badge {{ font-size: 10px; color: #9b59b6; display: block; }}
.metrics {{ font-size: 9px; color: #aaa; line-height: 1.5; }}
select.reclassify {{ font-size: 10px; width: 100%; margin-top: 5px; padding: 2px; }}
textarea.note-input {{ font-size: 9px; width: 100%; margin-top: 4px; padding: 2px; resize: vertical; min-height: 36px; border: 1px solid #ddd; border-radius: 2px; font-family: monospace; color: #555; background: #fafafa; }}
textarea.note-input:focus {{ border-color: #7ec8e3; outline: none; background: #fff; }}
textarea.note-input.has-note {{ background: #fffef0; border-color: #f0c040; }}
.flash {{ outline: 2px solid #27ae60; outline-offset: 1px; }}
.svg-wrap {{ position: relative; display: inline-block; margin: 0 auto 4px; }}
.skel-toggle {{ position: absolute; bottom: 3px; right: 3px; font-size: 9px; font-family: monospace; padding: 1px 4px; background: rgba(0,0,0,0.45); color: #eee; border: none; border-radius: 2px; cursor: pointer; line-height: 1.4; }}
.skel-toggle:hover {{ background: rgba(0,0,0,0.7); }}
.skel-toggle.active {{ background: #4a9eda; color: #fff; }}
.hdr-btn {{ font-size: 11px; font-family: monospace; padding: 2px 8px; background: rgba(255,255,255,0.12); color: #eee; border: 1px solid #555; border-radius: 3px; cursor: pointer; white-space: nowrap; }}
.hdr-btn:hover {{ background: rgba(255,255,255,0.22); }}
.hdr-btn.active {{ background: transparent; border-color: #4a9eda; color: #4a9eda; }}
.hdr-btn.active:hover {{ background: rgba(74,158,218,0.12); }}
.hdr-btn:disabled {{ opacity: 0.4; cursor: default; }}
.smooth-ctrl {{ display: flex; align-items: center; gap: 4px; font-size: 11px; color: #aaa; }}
.smooth-ctrl input[type=range] {{ width: 72px; accent-color: #4a9eda; }}
.smooth-ctrl .val {{ min-width: 28px; text-align: right; color: #fff; }}
.smooth-status {{ font-size: 10px; min-width: 56px; color: #666; font-style: italic; }}
.smooth-status.busy {{ color: #4a9eda; font-style: normal; }}
</style>
</head>
<body>
<header>
  <h1>Island Profile Review{filter_note}</h1>
  <div class="summary">
    {total_maps} maps &nbsp;|&nbsp;
    {total_shapes} unique shapes &nbsp;|&nbsp;
    {active_override_count} active overrides &nbsp;|&nbsp;
    <a style="color:#7ec8e3" href="/overrides.json">overrides.json</a>
    &nbsp;|&nbsp;
    {matches_btn}
    {traffic_btn}
    <button id="skel-all" class="hdr-btn">show skeletons</button>
    &nbsp;|&nbsp;
    <div class="smooth-ctrl">
      buf <input id="global-buf" type="range" min="0" max="2" step="0.25" value="0">
      <span id="buf-val" class="val">0.00</span>
      &nbsp;sim <input id="global-sim" type="range" min="0" max="3" step="0.5" value="0">
      <span id="sim-val" class="val">0.00</span>
      &nbsp;<span id="smooth-status" class="smooth-status">—</span>
    </div>
    <button id="smooth-compute" class="hdr-btn">compute polygons</button>
    <button id="smooth-show" class="hdr-btn" disabled>show overlay</button>
    <button id="smooth-skel-compute" class="hdr-btn">compute skeleton</button>
    <button id="smooth-skel-show" class="hdr-btn" disabled>show skel</button>
  </div>
  <div class="nav">{nav_links}</div>
</header>
{sections_html}
<script>
// ── utilities ────────────────────────────────────────────────────────────────
function debounce(fn, ms) {{
  let t;
  return function(...args) {{ clearTimeout(t); t = setTimeout(() => fn.apply(this, args), ms); }};
}}

async function postJSON(url, payload) {{
  const resp = await fetch(url, {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload),
  }});
  if (!resp.ok) throw new Error('HTTP ' + resp.status);
  return resp.json();
}}

// All canonical keys currently in the page (in DOM order).
const allKeys = [...document.querySelectorAll('.cell[data-key]')].map(c => c.dataset.key);

// ── reclassify / notes ────────────────────────────────────────────────────────
document.querySelectorAll('select.reclassify').forEach(sel => {{
  sel.addEventListener('change', async function() {{
    const key = this.dataset.key;
    const profile = this.value;
    const autoProfile = this.dataset.auto;
    const cell = this.closest('.cell');
    try {{
      await postJSON('/reclassify', {{key, profile}});
      const isOverridden = profile && profile !== autoProfile;
      const isManual = profile === 'manual';
      cell.classList.toggle('overridden', isOverridden && !isManual);
      cell.classList.toggle('manual', isManual);
      const badge = cell.querySelector('.badge');
      if (isManual) {{
        badge.className = 'override-badge badge';
        badge.textContent = '\u2753 manual';
      }} else if (isOverridden) {{
        badge.className = 'override-badge badge';
        badge.textContent = '\u2192 ' + profile;
      }} else {{
        badge.className = 'auto-badge badge';
        badge.textContent = 'auto: ' + autoProfile;
      }}
      cell.classList.add('flash');
      setTimeout(() => cell.classList.remove('flash'), 600);
    }} catch(e) {{
      alert('Save failed: ' + e.message);
    }}
  }});
}});

document.querySelectorAll('textarea.note-input').forEach(ta => {{
  ta.addEventListener('blur', async function() {{
    const key = this.dataset.key;
    const note = this.value;
    const cell = this.closest('.cell');
    try {{
      await postJSON('/reclassify', {{key, note}});
      this.classList.toggle('has-note', note.trim().length > 0);
      cell.classList.add('flash');
      setTimeout(() => cell.classList.remove('flash'), 400);
    }} catch(e) {{
      alert('Note save failed: ' + e.message);
    }}
  }});
}});

// ── position data (traffic heatmap) toggle ───────────────────────────────────
const trafficBtn = document.getElementById('traffic-all');
if (trafficBtn) {{
  trafficBtn.addEventListener('click', function() {{
    const visible = !this.classList.contains('active');
    this.classList.toggle('active', visible);
    this.textContent = visible ? 'hide position data' : 'show position data';
    document.querySelectorAll('.traffic-overlay').forEach(g => {{
      g.style.display = visible ? '' : 'none';
    }});
  }});
}}

// ── block-raster skeleton toggle ──────────────────────────────────────────────
function setSkelVisible(visible) {{
  document.querySelectorAll('.skel-overlay').forEach(el => {{
    el.style.display = visible ? '' : 'none';
  }});
  document.querySelectorAll('button.skel-toggle').forEach(btn => {{
    btn.classList.toggle('active', visible);
  }});
}}

document.getElementById('skel-all').addEventListener('click', function() {{
  const turningOn = !this.classList.contains('active');
  this.classList.toggle('active', turningOn);
  this.textContent = turningOn ? 'hide skeletons' : 'show skeletons';
  setSkelVisible(turningOn);
}});

document.querySelectorAll('button.skel-toggle').forEach(btn => {{
  btn.addEventListener('click', function() {{
    const overlay = this.closest('.svg-wrap').querySelector('.skel-overlay');
    if (!overlay) return;
    const visible = overlay.style.display !== 'none';
    overlay.style.display = visible ? 'none' : '';
    this.classList.toggle('active', !visible);
  }});
}});

// ── matches-only filter ───────────────────────────────────────────────────────
const matchesOnlyBtn = document.getElementById('matches-only');
if (matchesOnlyBtn) {{
  matchesOnlyBtn.addEventListener('click', function() {{
    const turningOn = !this.classList.contains('active');
    this.classList.toggle('active', turningOn);
    this.textContent = turningOn ? 'show all maps' : 'hide maps \u003c10 matches';
    document.querySelectorAll('.cell[data-has-matches="0"]').forEach(cell => {{
      cell.style.display = turningOn ? 'none' : '';
    }});
    // Hide sections that become entirely empty.
    document.querySelectorAll('section').forEach(sec => {{
      const anyVisible = [...sec.querySelectorAll('.cell')].some(c => c.style.display !== 'none');
      sec.style.display = anyVisible ? '' : 'none';
    }});
  }});
}}

// ── smooth polygon overlay ────────────────────────────────────────────────────
const smoothStatus = document.getElementById('smooth-status');
let polygonsReady = false;
let skelSmoothedReady = false;

// Sliders only update displayed values and mark existing computed data as stale.
// No network request fires until the user explicitly clicks a compute button.
function onSliderInput() {{
  const buf = +document.getElementById('global-buf').value;
  const sim = +document.getElementById('global-sim').value;
  document.getElementById('buf-val').textContent = buf.toFixed(2);
  document.getElementById('sim-val').textContent = sim.toFixed(2);

  smoothStatus.textContent = (buf > 0 || sim > 0) ? 'pending\u2026' : '\u2014';
  smoothStatus.className = (buf > 0 || sim > 0) ? 'smooth-status busy' : 'smooth-status';

  // Stale data: disable show-buttons and hide any visible overlays.
  if (polygonsReady) {{
    polygonsReady = false;
    document.getElementById('smooth-show').disabled = true;
    document.querySelectorAll('.smooth-overlay').forEach(el => el.style.display = 'none');
    const showBtn = document.getElementById('smooth-show');
    showBtn.classList.remove('active');
    showBtn.textContent = 'show overlay';
  }}
  if (skelSmoothedReady) {{
    skelSmoothedReady = false;
    document.getElementById('smooth-skel-show').disabled = true;
    document.querySelectorAll('.smooth-skel-overlay').forEach(g => g.style.display = 'none');
    const skelShowBtn = document.getElementById('smooth-skel-show');
    skelShowBtn.classList.remove('active');
    skelShowBtn.textContent = 'show skel';
  }}
}}

document.getElementById('global-buf').addEventListener('input', onSliderInput);
document.getElementById('global-sim').addEventListener('input', onSliderInput);

// "compute polygons": fetch all smoothed polygon paths for the current parameter
// pair.  Does not show anything — visibility is controlled by "show overlay".
document.getElementById('smooth-compute').addEventListener('click', async function() {{
  const buf = +document.getElementById('global-buf').value;
  const sim = +document.getElementById('global-sim').value;
  if (buf === 0 && sim === 0) {{
    smoothStatus.textContent = 'set buf or sim \u003e 0';
    return;
  }}

  this.disabled = true;
  smoothStatus.textContent = 'computing\u2026';
  smoothStatus.className = 'smooth-status busy';

  try {{
    const paths = await postJSON('/polygon_batch', {{keys: allKeys, buffer: buf, simplify: sim}});
    for (const [key, path_d] of Object.entries(paths)) {{
      const cell = document.querySelector('.cell[data-key="' + key + '"]');
      if (!cell) continue;
      const path = cell.querySelector('.smooth-path');
      if (path) path.setAttribute('d', path_d);
    }}
    polygonsReady = true;
    document.getElementById('smooth-show').disabled = false;
    smoothStatus.textContent = 'ready';
    smoothStatus.className = 'smooth-status';
  }} catch(e) {{
    console.error('Polygon compute failed:', e);
    smoothStatus.textContent = 'error';
    smoothStatus.className = 'smooth-status busy';
  }} finally {{
    this.disabled = false;
  }}
}});

// "show overlay" / "hide overlay": visibility toggle, only enabled after compute.
document.getElementById('smooth-show').addEventListener('click', function() {{
  if (!polygonsReady) return;
  const visible = !this.classList.contains('active');
  document.querySelectorAll('.smooth-overlay').forEach(el => {{
    el.style.display = visible ? '' : 'none';
  }});
  this.classList.toggle('active', visible);
  this.textContent = visible ? 'hide overlay' : 'show overlay';
}});

// ── skeleton-from-smoothed-polygon ───────────────────────────────────────────

// "compute skeleton": run the skeleton pipeline per key from the smoothed
// polygon blocks.  Populates smooth-skel-overlay groups but does not show them.
document.getElementById('smooth-skel-compute').addEventListener('click', async function() {{
  const buf = +document.getElementById('global-buf').value;
  const sim = +document.getElementById('global-sim').value;

  // Reset previous results.
  skelSmoothedReady = false;
  document.getElementById('smooth-skel-show').disabled = true;
  document.querySelectorAll('.smooth-skel-overlay').forEach(g => {{
    g.innerHTML = '';
    g.style.display = 'none';
  }});
  const skelShowBtn = document.getElementById('smooth-skel-show');
  skelShowBtn.classList.remove('active');
  skelShowBtn.textContent = 'show skel';

  this.disabled = true;
  let done = 0;
  for (const key of allKeys) {{
    this.textContent = 'computing ' + (done + 1) + '/' + allKeys.length + '\u2026';
    try {{
      const data = await postJSON('/skeleton_from_polygon', {{key, buffer: buf, simplify: sim}});
      const cell = document.querySelector('.cell[data-key="' + key + '"]');
      if (cell && data.polylines && data.polylines.length > 0) {{
        const grp = cell.querySelector('.smooth-skel-overlay');
        grp.innerHTML = data.polylines.map(pts =>
          '<polyline points="' + pts + '" fill="none" stroke="#4a9eda" ' +
          'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
        ).join('');
      }}
    }} catch(e) {{
      console.warn('Skeleton failed for ' + key + ':', e);
    }}
    done++;
  }}

  this.disabled = false;
  this.textContent = 'compute skeleton';
  skelSmoothedReady = true;
  document.getElementById('smooth-skel-show').disabled = false;
}});

// "show skel" / "hide skel": visibility toggle, only enabled after compute.
document.getElementById('smooth-skel-show').addEventListener('click', function() {{
  if (!skelSmoothedReady) return;
  const visible = !this.classList.contains('active');
  document.querySelectorAll('.smooth-skel-overlay').forEach(g => {{
    g.style.display = visible ? '' : 'none';
  }});
  this.classList.toggle('active', visible);
  this.textContent = visible ? 'hide skel' : 'show skel';
}});
</script>
</body>
</html>'''


def _build_sections(
    by_type: dict[str, list[tuple[str, IslandProfile, dict]]],
    override_data: dict[str, dict[str, str]],
    key_maps: dict[str, list[str]],
    all_options_html: str,
    key_has_matches: dict[str, bool],
    traffic_svg_by_key: dict[str, str],
) -> str:
    """Build the per-type section HTML blocks."""
    import html as _html
    sections_html = ''
    for island_type in _ALL_TYPES:
        if island_type not in by_type:
            continue
        type_entries = by_type[island_type]
        color = _TYPE_COLORS.get(island_type, '#cccccc')

        cells_html = ''
        for map_slug, profile, island_dict in type_entries:
            key = profile.canonical_key
            auto = profile.auto_profile
            entry = override_data.get(key, {})
            override_profile = entry.get('profile', '')
            is_overridden = bool(override_profile)
            # Use the override value from the file — not profile.island_type, which
            # comes from island_profiles.json and may be stale if overrides were set
            # after the last `ctw islands profile` run.
            effective = override_profile if is_overridden else auto
            note = entry.get('note', '')
            feat = profile.features
            maps_for_key = key_maps.get(key, [map_slug])
            map_label = map_slug if len(maps_for_key) == 1 else f'{map_slug} +{len(maps_for_key) - 1}'

            svg = _island_svg(island_dict, color, size=144, traffic_svg=traffic_svg_by_key.get(key, ''))
            has_skeleton = bool(
                (island_dict.get('skeleton') or {}).get('edge_pixels')
            )

            is_manual = effective == 'manual'
            if is_manual:
                badge_html = '<span class="override-badge badge">\u2753 manual</span>'
            elif is_overridden:
                badge_html = f'<span class="override-badge badge">\u2192 {effective}</span>'
            else:
                badge_html = f'<span class="auto-badge badge">auto: {auto}</span>'

            # Build dropdown: reset + algorithmic types + separator + manual
            reset_selected = '' if is_overridden else 'selected'
            dropdown_options = f'<option value="" {reset_selected}>-- auto ({auto}) --</option>\n'
            for atype in _ALL_TYPES:
                sel = 'selected' if (is_overridden and effective == atype) else ''
                dropdown_options += f'<option value="{atype}" {sel}>{atype}</option>\n'
            dropdown_options += '<option disabled>──────────</option>\n'
            manual_sel = 'selected' if (is_overridden and effective == 'manual') else ''
            dropdown_options += f'<option value="manual" {manual_sel}>manual (uncertain)</option>\n'

            note_class = 'note-input has-note' if note.strip() else 'note-input'
            note_escaped = _html.escape(note)

            if is_manual:
                cell_class = 'cell manual'
            elif is_overridden:
                cell_class = 'cell overridden'
            else:
                cell_class = 'cell'
            skel_btn = (
                '<button class="skel-toggle" title="Show/hide skeleton">skel</button>'
                if has_skeleton else ''
            )
            _axis_label_map = {'x': 'x', 'z': 'z', 'diag': 'x/z', 'rot': 'rot',
                               'x~': 'x~', 'z~': 'z~', 'diag~': 'x/z~'}
            _axis_sort_order = {'x': 0, 'z': 1, 'diag': 2, 'rot': 3,
                                'x~': 4, 'z~': 5, 'diag~': 6}
            _axis_labels = [
                _axis_label_map[axis]
                for axis in sorted(feat.axis_symmetry, key=lambda a: _axis_sort_order.get(a, 9))
            ]
            symm_html = (
                f'<span class="symm-badge">symmetry: {", ".join(_axis_labels)}</span>'
                if _axis_labels else ''
            )

            cells_html += f'''
<div class="{cell_class}" data-key="{key}" data-has-matches="{'1' if key_has_matches.get(key) else '0'}">
  <div class="svg-wrap">{svg}{skel_btn}</div>
  <code class="key">{key[:8]}</code>
  <div class="meta">{map_label}</div>
  {badge_html}
  {symm_html}
  <div class="metrics">
    conv:{feat.convexity:.3f}  ar:{feat.aspect_ratio:.2f}<br>
    cfr:{feat.circle_fit_residual:.3f}  er:{feat.ellipse_residual:.3f}<br>
    fill:{feat.bbox_fill_ratio:.3f}  bends:{'?' if feat.skeleton_path_bends is None else feat.skeleton_path_bends}<br>
    cuts:{'–' if feat.bbox_cutout_count is None else feat.bbox_cutout_count}({'–' if feat.bbox_cutout_coverage is None else f'{feat.bbox_cutout_coverage:.2f}'})  area:{feat.area}
  </div>
  <select class="reclassify" data-key="{key}" data-auto="{auto}">
    {dropdown_options}
  </select>
  <textarea class="{note_class}" data-key="{key}" placeholder="notes...">{note_escaped}</textarea>
</div>'''

        sections_html += f'''
<section id="{island_type}">
  <h2 style="border-color:{color}">
    <span class="swatch" style="background:{color}"></span>
    {island_type} &nbsp;({len(type_entries)})
  </h2>
  <div class="grid">{cells_html}</div>
</section>'''

    return sections_html


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------


class _ReviewHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for the profile review server."""

    # Set by run_review_server before the server starts.
    server_entries: list[tuple[str, IslandProfile, dict]]
    overrides_path: Path
    type_filter: Optional[str]
    # canonical_key → (min_xy, extent, padding, draw_size) — for SVG conversion.
    svg_norm: dict[str, tuple]
    # canonical_key → island_dict — for quick POST handler lookup.
    island_dict_by_key: dict[str, dict]
    # canonical_key → blocks array — lazily populated, cached across requests.
    _blocks_cache: dict[str, np.ndarray]
    # canonical_key → True if any map containing this shape has match data.
    # Empty dict when DB was unavailable (toggle hidden in that case).
    key_has_matches: dict[str, bool]
    # canonical_key → pre-rendered SVG traffic heatmap group.
    # Empty dict when DB was unavailable or query returned no rows.
    traffic_svg_by_key: dict[str, str]

    def do_GET(self) -> None:
        if self.path in ('/', '/index.html'):
            override_data = load_override_data(self.__class__.overrides_path)
            html = _build_html(
                self.__class__.server_entries,
                override_data,
                self.__class__.type_filter,
                self.__class__.key_has_matches,
                self.__class__.traffic_svg_by_key,
            )
            self._respond(200, 'text/html; charset=utf-8', html.encode('utf-8'))

        elif self.path == '/overrides.json':
            override_data = load_override_data(self.__class__.overrides_path)
            data = json.dumps(override_data, indent=2).encode('utf-8')
            self._respond(200, 'application/json', data)

        else:
            self._respond(404, 'text/plain', b'Not found')

    def do_POST(self) -> None:
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length))

        if self.path == '/reclassify':
            self._handle_reclassify(body)
        elif self.path == '/polygon_batch':
            self._handle_polygon_batch(body)
        elif self.path == '/skeleton_from_polygon':
            self._handle_skeleton_from_polygon(body)
        else:
            self._respond(404, 'text/plain', b'Not found')

    def _handle_reclassify(self, body: dict) -> None:
        canonical_key = body.get('key', '')
        new_profile: Optional[str] = body.get('profile')   # None = don't change
        new_note: Optional[str] = body.get('note')         # None = don't change

        override_data = load_override_data(self.__class__.overrides_path)
        entry = override_data.setdefault(canonical_key, {'profile': '', 'note': ''})
        if new_profile is not None:
            entry['profile'] = new_profile
        if new_note is not None:
            entry['note'] = new_note

        # Remove entries that have neither a profile override nor a note
        if not entry.get('profile') and not entry.get('note'):
            override_data.pop(canonical_key, None)

        save_override_data(self.__class__.overrides_path, override_data)
        self._respond(200, 'application/json', b'{"ok":true}')

    def _handle_polygon_batch(self, body: dict) -> None:
        """Recompute smoothed/simplified polygon for each key and return path strings.

        Body: {keys: [...], buffer: float, simplify: float}
        Response: {key: svg_path_d_string, ...}
        """
        from island_analysis.polygon import _build_union_polygon, _extract_polygon_coords

        keys: list[str] = body.get('keys', [])
        buffer_distance = float(body.get('buffer', 0.0))
        simplify_tolerance = float(body.get('simplify', 0.0))

        cls = self.__class__
        result: dict[str, str] = {}

        for key in keys:
            island_dict = cls.island_dict_by_key.get(key)
            norm = cls.svg_norm.get(key)
            if island_dict is None or norm is None:
                continue

            blocks = self._get_blocks(key, island_dict)
            if len(blocks) < 3:
                continue

            poly = _build_union_polygon(blocks, buffer_distance, simplify_tolerance)
            if poly is None:
                continue

            poly_data = _extract_polygon_coords(poly)
            min_xy, extent, padding, draw_size = norm
            path_d = _polygon_data_to_svg_path(poly_data, min_xy, extent, padding, draw_size)
            result[key] = path_d

        self._respond(200, 'application/json', json.dumps(result).encode('utf-8'))

    def _handle_skeleton_from_polygon(self, body: dict) -> None:
        """Compute skeleton from the smoothed polygon block set.

        Body: {key: str, buffer: float, simplify: float}
        Response: {polylines: [points_str, ...]}
        """
        from island_analysis.polygon import _build_union_polygon, _extract_polygon_coords
        from skeleton_analysis.pipeline import process_island

        key: str = body.get('key', '')
        buffer_distance = float(body.get('buffer', 0.0))
        simplify_tolerance = float(body.get('simplify', 0.0))

        cls = self.__class__
        island_dict = cls.island_dict_by_key.get(key)
        norm = cls.svg_norm.get(key)
        if island_dict is None or norm is None:
            self._respond(404, 'text/plain', b'Key not found')
            return

        raw_blocks = self._get_blocks(key, island_dict)
        if len(raw_blocks) < 3:
            self._respond(200, 'application/json', b'{"polylines":[]}')
            return

        # Build the smoothed polygon and reconstruct a block set from it.
        smooth_poly = _build_union_polygon(raw_blocks, buffer_distance, simplify_tolerance)
        if smooth_poly is None:
            self._respond(200, 'application/json', b'{"polylines":[]}')
            return
        smooth_poly_data = _extract_polygon_coords(smooth_poly)
        smooth_blocks = _blocks_from_exact_polygon(smooth_poly_data)
        if len(smooth_blocks) < 3:
            self._respond(200, 'application/json', b'{"polylines":[]}')
            return

        # Run the full skeleton pipeline on the smoothed block set.
        island_id = island_dict.get('id', 0)
        try:
            skel_result = process_island(island_id, smooth_blocks)
        except Exception:
            self._respond(200, 'application/json', b'{"polylines":[]}')
            return

        min_xy, extent, padding, draw_size = norm
        polylines = _skeleton_result_to_svg_polylines(
            skel_result, min_xy, extent, padding, draw_size
        )
        data = json.dumps({'polylines': polylines}).encode('utf-8')
        self._respond(200, 'application/json', data)

    def _get_blocks(self, key: str, island_dict: dict) -> np.ndarray:
        """Return cached block array for key, computing it on first access."""
        cls = self.__class__
        if key not in cls._blocks_cache:
            poly_data = island_dict.get('simplified_polygon') or {}
            cls._blocks_cache[key] = _blocks_from_exact_polygon(poly_data)
        return cls._blocks_cache[key]

    def _respond(self, code: int, content_type: str, data: bytes) -> None:
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        pass  # suppress per-request access log noise


def run_review_server(
    entries: list[tuple[str, IslandProfile, dict]],
    overrides_path: Path,
    type_filter: Optional[str],
    port: int = 7890,
    maps_with_matches: Optional[set[str]] = None,
) -> None:
    """Start the profile review HTTP server and open a browser tab.

    Blocks until Ctrl+C.  The override file is updated in-place as the user
    makes selections in the browser.

    Parameters
    ----------
    entries:
        (map_slug, IslandProfile, representative_island_dict) triples to display.
    overrides_path:
        Path to island_profile_overrides.json (created/updated by the server).
    type_filter:
        If set, only show islands of this type.
    port:
        Local TCP port to bind (default: 7890).
    """
    import webbrowser

    # Pre-compute per-key SVG normalisation constants and island dict lookup.
    # Only the first occurrence of each canonical_key is used (consistent with
    # how _build_html deduplicates).
    seen: set[str] = set()
    svg_norm: dict[str, tuple] = {}
    island_dict_by_key: dict[str, dict] = {}
    for _, profile, island_dict in entries:
        key = profile.canonical_key
        if key in seen:
            continue
        seen.add(key)
        poly = island_dict.get('simplified_polygon') or {}
        exterior = poly.get('exterior') or []
        if len(exterior) >= 3:
            svg_norm[key] = _make_svg_normalizer(exterior, size=144)
        island_dict_by_key[key] = island_dict

    # Compute per-canonical-key match flag: True if the shape appears in at
    # least one map that has recorded match data.
    key_has_matches: dict[str, bool] = {}
    if maps_with_matches:
        for map_slug, profile, _ in entries:
            key = profile.canonical_key
            if key not in key_has_matches:
                key_has_matches[key] = False
            if map_slug in maps_with_matches:
                key_has_matches[key] = True

    # Build traffic heatmap overlays from position_events DB (if available).
    from ctw.common import PROJECT_ROOT
    db_path = PROJECT_ROOT / 'match_analysis' / 'metadata.db'
    traffic_svg_by_key: dict[str, str] = {}
    if db_path.exists():
        print('  Building traffic overlays from position data…')
        traffic_svg_by_key = _build_traffic_overlays(entries, svg_norm, db_path)
        print(f'  Traffic overlays built for {len(traffic_svg_by_key)} shapes.')

    _ReviewHandler.server_entries = entries
    _ReviewHandler.overrides_path = overrides_path
    _ReviewHandler.type_filter = type_filter
    _ReviewHandler.svg_norm = svg_norm
    _ReviewHandler.island_dict_by_key = island_dict_by_key
    _ReviewHandler._blocks_cache = {}
    _ReviewHandler.key_has_matches = key_has_matches
    _ReviewHandler.traffic_svg_by_key = traffic_svg_by_key

    server = HTTPServer(('localhost', port), _ReviewHandler)
    url = f'http://localhost:{port}/'
    n = len(seen)
    print(f'  Review server: {url}')
    print(f'  Showing {n} unique shapes | Override file: {overrides_path}')
    print(f'  Press Ctrl+C to stop.')
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n  Server stopped.')
    finally:
        server.server_close()
