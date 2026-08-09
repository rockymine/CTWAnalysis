#!/usr/bin/env python3
"""Land, build regions, classified voids and every successful approach, in one SVG.

The view that shows why an offered route goes unused: the playable surface, the
declared build regions dashed over it, every enclosed void filled and labelled
with its class, and the path of every life that reached a wool drawn on top.

Usage
-----
    python scripts/match_flow/render_design.py --map outback_outback_edition
"""

from __future__ import annotations

import argparse, json, math, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from collections import defaultdict
import approaches as approach_mod
import common
import voidmap
con = common.connect()
WOOL = {'orange': '#C8752A', 'yellow': '#B39B2E', 'pink': '#B85C86', 'purple': '#7A5AA8',
        'lime': '#7FA33A', 'cyan': '#3E8E9C', 'magenta': '#B2559B', 'light_blue': '#5C8FC0',
        'red': '#B0473E', 'blue': '#3B6796', 'green': '#5A8A46'}
VOIDCOL = {'middle': 'var(--against)', 'encased': 'var(--hold)',
           'frontline': 'var(--cap)', 'gap': 'var(--blue)'}


def render(slug, scale=2.0, pad=12):
    map_id = con.execute('select map_id from maps where map_slug=?', [slug]).fetchone()[0]
    land = sorted({(x // 3 * 3, z // 3 * 3) for x, z in con.execute(
        'select world_x, world_z from map_terrain_height where map_id=?', [map_id]).fetchall()})
    polys = (json.loads((common.OUTPUT_DIR / slug / 'map_context.json').read_text())
             .get('build_region') or {}).get('polygons') or []
    labelled = voidmap.label_voids(con, slug)
    appr = approach_mod.extract(con, slug)
    rooms = {k[1]: v for k, v in common.load_wool_rooms().items() if k[0] == slug}
    colours = dict(con.execute('select wool_id, wool_color from map_wool_locations where map_id=?',
                               [map_id]).fetchall())
    spawns = {t: (a, b, c, d) for t, a, b, c, d in con.execute(
        'select team, min_x, min_z, max_x, max_z from map_spawns where map_id=?', [map_id]).fetchall()}

    xs = [c[0] for c in land] + [c[0] for p in polys for c in p['exterior']]
    zs = [c[1] for c in land] + [c[1] for p in polys for c in p['exterior']]
    for a in appr:
        xs += [q[0] for q in a['path']]; zs += [q[1] for q in a['path']]
    x0, z0, x1, z1 = min(xs), min(zs), max(xs) + 3, max(zs) + 3
    W, H = (x1 - x0 + 2 * pad) * scale, (z1 - z0 + 2 * pad) * scale
    px = lambda v: (v - x0 + pad) * scale
    pz = lambda v: (v - z0 + pad) * scale
    mono = 'ui-monospace,Menlo,monospace'
    o = [f'<svg class="spark" viewBox="0 0 {W:.0f} {H:.0f}" role="img" '
         f'aria-label="{slug}: land, build regions, classified voids and every successful approach">']
    rows = defaultdict(list)
    for gx, gz in land: rows[gz].append(gx)
    o.append('<g fill="var(--rule)" opacity="0.6">')
    for gz, gxs in sorted(rows.items()):
        gxs = sorted(gxs); s = p = gxs[0]
        for x in gxs[1:] + [None]:
            if x == p + 3: p = x; continue
            o.append(f'<rect x="{px(s):.1f}" y="{pz(gz):.1f}" width="{(p-s+3)*scale:.1f}" '
                     f'height="{3*scale:.1f}"/>')
            if x is None: break
            s = p = x
    o.append('</g>')
    for i, poly in enumerate(polys):
        pts = ' '.join(f'{px(c[0]):.1f},{pz(c[1]):.1f}' for c in poly['exterior'])
        o.append(f'<polygon points="{pts}" fill="var(--stone)" fill-opacity="0.10" '
                 f'stroke="var(--stone)" stroke-width="1.2" stroke-dasharray="4 3"/>')
    for v in labelled:
        a, b, c, d = v['span']
        col = VOIDCOL.get(v['cls'], 'var(--mute)')
        o.append(f'<rect x="{px(a):.1f}" y="{pz(c):.1f}" width="{(b-a+1)*scale:.1f}" '
                 f'height="{(d-c+1)*scale:.1f}" fill="{col}" fill-opacity="0.16" '
                 f'stroke="{col}" stroke-width="1.1"/>')
        o.append(f'<text x="{px((a+b)/2):.1f}" y="{pz((c+d)/2)+3:.1f}" text-anchor="middle" '
                 f'font-size="9" fill="{col}" font-family="{mono}">{v["cls"]}</text>')
    for a in appr:
        if len(a['path']) < 3: continue
        col = WOOL.get(colours.get(a['wool_id'], ''), 'var(--ink)')
        pts = ' '.join(f'{px(x):.1f},{pz(z):.1f}' for x, z in a['path'])
        o.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="0.9" '
                 f'stroke-opacity="0.42" stroke-linejoin="round"/>')
    for wid, rect in rooms.items():
        col = WOOL.get(colours.get(wid, ''), 'var(--stone)')
        a, b, c, d = rect
        o.append(f'<rect x="{px(a):.1f}" y="{pz(b):.1f}" width="{(c-a)*scale:.1f}" '
                 f'height="{(d-b)*scale:.1f}" fill="none" stroke="{col}" stroke-width="1.8"/>')
        o.append(f'<text x="{px((a+c)/2):.1f}" y="{pz(b)-4:.1f}" text-anchor="middle" font-size="9.5" '
                 f'fill="{col}" font-family="{mono}">{colours.get(wid, wid)}</text>')
    for team, rect in spawns.items():
        col = WOOL.get(team, 'var(--ink)')
        cx, cz = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
        o.append(f'<circle cx="{px(cx):.1f}" cy="{pz(cz):.1f}" r="5" fill="none" stroke="{col}" '
                 f'stroke-width="2"/>')
        o.append(f'<text x="{px(cx):.1f}" y="{pz(cz)+19:.1f}" text-anchor="middle" font-size="9.5" '
                 f'fill="{col}" font-family="{mono}">{team}</text>')
    o.append(f'<text x="12" y="{H-10:.0f}" font-size="9.5" fill="var(--mute)" font-family="{mono}">'
             f'dashed = declared build region &middot; filled + labelled = enclosed void &middot; '
             f'thin lines = every approach that reached a wool</text>')
    o.append('</svg>')
    return '\n'.join(o)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--map', action='append', required=True)
    parser.add_argument('--out-dir', default='.')
    args = parser.parse_args()
    for slug in args.map:
        svg = render(slug)
        path = Path(args.out_dir) / f'design_{slug}.svg'
        path.write_text(svg)
        print(f'wrote {path} ({len(svg):,} bytes)')


if __name__ == '__main__':
    main()
