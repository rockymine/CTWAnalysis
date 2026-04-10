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
# SVG renderer
# ---------------------------------------------------------------------------


def _island_svg(island_dict: dict, color: str, size: int = 110) -> str:
    """Render island polygon as a self-contained SVG element.

    Normalizes the polygon to fill the viewport with padding so all shapes
    are displayed at comparable scale.  Uses SVG path fill-rule=evenodd so
    holes render correctly.
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

    pts = np.asarray(exterior, dtype=float)
    min_xy = pts.min(axis=0)
    max_xy = pts.max(axis=0)
    extent = max(float((max_xy - min_xy).max()), 1.0)
    padding = 5
    draw_size = size - 2 * padding

    def to_svg_coords(coords: list | np.ndarray) -> np.ndarray:
        arr = np.asarray(coords, dtype=float)
        return (arr - min_xy) / extent * draw_size + padding

    def ring_to_path_segment(ring_pts: np.ndarray) -> str:
        pairs = ' '.join(f'{x:.1f},{y:.1f}' for x, y in ring_pts)
        return f'M {pairs} Z'

    path_d = ring_to_path_segment(to_svg_coords(pts))
    for hole in holes:
        if len(hole) >= 3:
            path_d += ' ' + ring_to_path_segment(to_svg_coords(hole))

    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
        f'xmlns="http://www.w3.org/2000/svg" style="display:block">'
        f'<path d="{path_d}" fill="{color}" fill-opacity="0.65" '
        f'stroke="#333" stroke-width="0.8" fill-rule="evenodd"/></svg>'
    )


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------


def _build_html(
    entries: list[tuple[str, IslandProfile, dict]],
    override_data: dict[str, dict[str, str]],
    type_filter: Optional[str] = None,
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
    """
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
    entry_keys = {profile.canonical_key for _, profile, _ in entries}
    active_override_count = sum(
        1 for key, entry in override_data.items()
        if key in entry_keys and entry.get('profile')
    )

    all_options_html = '\n'.join(
        f'<option value="{t}">{t}</option>' for t in _ALL_TYPES
    )

    sections_html = _build_sections(by_type, override_data, key_maps, all_options_html)

    nav_links = ' | '.join(
        f'<a href="#{t}">{t} ({len(by_type[t])})</a>'
        for t in _ALL_TYPES
        if t in by_type
    )

    filter_note = f' — filtered to <b>{type_filter}</b>' if type_filter else ''

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Island Profile Review</title>
<style>
* {{ box-sizing: border-box; }}
body {{ font-family: monospace; font-size: 12px; background: #e8e8e8; margin: 0; padding: 16px; }}
header {{ background: #222; color: #eee; padding: 10px 16px; margin: -16px -16px 16px; position: sticky; top: 0; z-index: 10; }}
header h1 {{ font-size: 14px; margin: 0 0 4px; }}
header .summary {{ font-size: 11px; color: #aaa; }}
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
.metrics {{ font-size: 9px; color: #aaa; line-height: 1.5; }}
select.reclassify {{ font-size: 10px; width: 100%; margin-top: 5px; padding: 2px; }}
textarea.note-input {{ font-size: 9px; width: 100%; margin-top: 4px; padding: 2px; resize: vertical; min-height: 36px; border: 1px solid #ddd; border-radius: 2px; font-family: monospace; color: #555; background: #fafafa; }}
textarea.note-input:focus {{ border-color: #7ec8e3; outline: none; background: #fff; }}
textarea.note-input.has-note {{ background: #fffef0; border-color: #f0c040; }}
.flash {{ outline: 2px solid #27ae60; outline-offset: 1px; }}
</style>
</head>
<body>
<header>
  <h1>Island Profile Review{filter_note}</h1>
  <div class="summary">{total_shapes} unique shapes &nbsp;|&nbsp; {active_override_count} active overrides &nbsp;|&nbsp; <a style="color:#7ec8e3" href="/overrides.json">overrides.json</a></div>
  <div class="nav">{nav_links}</div>
</header>
{sections_html}
<script>
async function postReclassify(payload) {{
  const resp = await fetch('/reclassify', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload)
  }});
  if (!resp.ok) throw new Error('HTTP ' + resp.status);
}}

document.querySelectorAll('select.reclassify').forEach(sel => {{
  sel.addEventListener('change', async function() {{
    const key = this.dataset.key;
    const profile = this.value;
    const autoProfile = this.dataset.auto;
    const cell = this.closest('.cell');
    try {{
      await postReclassify({{key, profile}});
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
      await postReclassify({{key, note}});
      this.classList.toggle('has-note', note.trim().length > 0);
      cell.classList.add('flash');
      setTimeout(() => cell.classList.remove('flash'), 400);
    }} catch(e) {{
      alert('Note save failed: ' + e.message);
    }}
  }});
}});
</script>
</body>
</html>'''


def _build_sections(
    by_type: dict[str, list[tuple[str, IslandProfile, dict]]],
    override_data: dict[str, dict[str, str]],
    key_maps: dict[str, list[str]],
    all_options_html: str,
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

            svg = _island_svg(island_dict, color, size=144)

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
            cells_html += f'''
<div class="{cell_class}">
  {svg}
  <code class="key">{key[:8]}</code>
  <div class="meta">{map_label}</div>
  {badge_html}
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

    # Set by run_review_server before the server starts
    server_entries: list[tuple[str, IslandProfile, dict]]
    overrides_path: Path
    type_filter: Optional[str]

    def do_GET(self) -> None:
        if self.path in ('/', '/index.html'):
            override_data = load_override_data(self.__class__.overrides_path)
            html = _build_html(
                self.__class__.server_entries,
                override_data,
                self.__class__.type_filter,
            )
            self._respond(200, 'text/html; charset=utf-8', html.encode('utf-8'))

        elif self.path == '/overrides.json':
            override_data = load_override_data(self.__class__.overrides_path)
            data = json.dumps(override_data, indent=2).encode('utf-8')
            self._respond(200, 'application/json', data)

        else:
            self._respond(404, 'text/plain', b'Not found')

    def do_POST(self) -> None:
        if self.path == '/reclassify':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length))
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
        else:
            self._respond(404, 'text/plain', b'Not found')

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

    _ReviewHandler.server_entries = entries
    _ReviewHandler.overrides_path = overrides_path
    _ReviewHandler.type_filter = type_filter

    server = HTTPServer(('localhost', port), _ReviewHandler)
    url = f'http://localhost:{port}/'
    n = len({profile.canonical_key for _, profile, _ in entries})
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
