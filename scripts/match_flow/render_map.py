#!/usr/bin/env python3
"""Render a top-down SVG of one match: detected structures, or the sky network.

Two modes:

  structures   the walls and staircases from structures.py, each drawn as its
               real cell footprint and labelled with who stands on it
  sky          cells occupied at the build ceiling plus the entry points where
               players climb onto them

The SVG uses CSS custom properties (var(--cap) and friends) so it inherits the
palette of whatever page it is embedded in; standalone it falls back to the
inline :root block written at the top.

Usage
-----
    python scripts/match_flow/render_map.py --map sanctum_wasser --match 2174 --mode structures
    python scripts/match_flow/render_map.py --map outback_outback_edition --match 1862 --mode sky
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
import skynetwork
import structures

WOOL_COLOUR = {'orange': '#C8752A', 'yellow': '#B39B2E', 'pink': '#B85C86', 'purple': '#7A5AA8',
               'lime': '#7FA33A', 'cyan': '#3E8E9C', 'magenta': '#B2559B',
               'light_blue': '#5C8FC0', 'red': '#B0473E', 'blue': '#3B6796',
               'green': '#5A8A46', 'white': '#9AA0A6', 'black': '#5A5F66'}
# team names are map-specific, so colour them from the wool palette where possible
TEAM_COLOUR = dict(WOOL_COLOUR)

FALLBACK_STYLE = (':root{--rule:#D2D6D3;--stone:#5A6672;--mute:#7C8794;'
                  '--cap:#B8842B;--hold:#3C7A62;}')


def _land(con, map_id: int, step: int = 4):
    cells = con.execute('select world_x, world_z from map_terrain_height where map_id = ?',
                        [map_id]).fetchall()
    return sorted({(x // step * step, z // step * step) for x, z in cells})


def render(con, map_slug: str, match_id: int, mode: str, scale: float = 2.4,
           pad: int = 10) -> str:
    ctx = common.load_match(con, map_slug, match_id)
    if ctx is None:
        raise SystemExit('no terrain reference for that map')
    land = _land(con, ctx['map_id'])
    if not land:
        raise SystemExit('no terrain rows')

    items: list = []
    if mode == 'structures':
        items = structures.describe(ctx, structures.ramp_runs(ctx))
        xs = [c[0] for c in land]
        zs = [c[1] for c in land]
    else:
        sky = skynetwork.network(ctx)
        climbs = skynetwork.climbs(ctx)
        entries = skynetwork.entry_points(ctx, climbs)
        items = (sky, entries)
        xs = [c[0] for c in land] + list(sky.gx)
        zs = [c[1] for c in land] + list(sky.gz)
    for rect in ctx['rooms'].values():
        xs += [rect[0], rect[2]]
        zs += [rect[1], rect[3]]

    x0, z0, x1, z1 = min(xs), min(zs), max(xs) + 4, max(zs) + 4
    width = (x1 - x0 + 2 * pad) * scale
    height = (z1 - z0 + 2 * pad) * scale
    px = lambda v: (v - x0 + pad) * scale
    pz = lambda v: (v - z0 + pad) * scale
    mono = 'ui-monospace,Menlo,monospace'
    out = [f'<svg viewBox="0 0 {width:.0f} {height:.0f}" xmlns="http://www.w3.org/2000/svg" '
           f'role="img" aria-label="{map_slug} {mode}">', f'<style>{FALLBACK_STYLE}</style>']

    rows: dict[int, list[int]] = defaultdict(list)
    for gx, gz in land:
        rows[gz].append(gx)
    out.append('<g fill="var(--rule)" opacity="0.5">')
    for gz, gxs in sorted(rows.items()):
        gxs = sorted(gxs)
        start = prev = gxs[0]
        for gx in gxs[1:] + [None]:
            if gx == prev + 4:
                prev = gx
                continue
            out.append(f'<rect x="{px(start):.1f}" y="{pz(gz):.1f}" '
                       f'width="{(prev - start + 4) * scale:.1f}" height="{4 * scale:.1f}"/>')
            if gx is None:
                break
            start = prev = gx
    out.append('</g>')

    if mode == 'sky':
        sky, entries = items
        peak = sky.n.max() if len(sky) else 1
        out.append('<g fill="var(--cap)">')
        for r in sky.itertuples():
            opacity = 0.16 + 0.72 * min(1.0, (r.n / peak) ** 0.42)
            out.append(f'<rect x="{px(r.gx):.1f}" y="{pz(r.gz):.1f}" width="{4 * scale:.1f}" '
                       f'height="{4 * scale:.1f}" fill-opacity="{opacity:.2f}"/>')
        out.append('</g>')

    for wool_id, rect in ctx['rooms'].items():
        colour = WOOL_COLOUR.get(ctx['wool_colour'].get(wool_id, ''), 'var(--stone)')
        a, b, c, e = rect
        captured = ctx['captures'].get(wool_id)
        note = ('never fell' if captured is None
                else f'fell {captured / 60:.0f} min' if captured > 600
                else f'fell {captured / 60:.1f} min')
        out.append(f'<rect x="{px(a):.1f}" y="{pz(b):.1f}" width="{(c - a) * scale:.1f}" '
                   f'height="{(e - b) * scale:.1f}" fill="{colour}" fill-opacity="0.13" '
                   f'stroke="{colour}" stroke-width="1.5"/>')
        out.append(f'<text x="{px((a + c) / 2):.1f}" y="{pz(b) - 5:.1f}" text-anchor="middle" '
                   f'font-size="10" fill="{colour}" font-family="{mono}">'
                   f'{ctx["wool_colour"].get(wool_id, wool_id)} &#183; {note}</text>')

    if mode == 'structures':
        middle = (z0 + z1) / 2
        for item in items:
            colour = 'var(--cap)' if item['kind'] == 'stair' else 'var(--hold)'
            out.append(f'<g fill="{colour}" fill-opacity="0.92">')
            for cx, cz in item['cells']:
                out.append(f'<rect x="{px(cx):.1f}" y="{pz(cz):.1f}" '
                           f'width="{ctx["cell"] * scale:.1f}" height="{ctx["cell"] * scale:.1f}"/>')
            out.append('</g>')
            dy = -14 if item['cz'] > middle else 22
            head = (f"staircase &#183; {item['owner']} {100 * item['owner_share']:.0f}%"
                    if item['kind'] == 'stair'
                    else f"wall &#183; {item['owner']} {100 * item['owner_share']:.0f}% ({item['role']})")
            sub = (f"climbs {item['rise']:.0f}, gradient {item['g_long']:.2f}, "
                   f"{item['spawn_distance']:.0f} from spawn" if item['kind'] == 'stair'
                   else f"flat, {item['room_distance']:.0f} off the room, "
                        f"bow {100 * item['bow']:.0f}%")
            out.append(f'<text x="{px(item["cx"]):.1f}" y="{pz(item["cz"]) + dy:.1f}" '
                       f'text-anchor="middle" font-size="10.5" font-weight="600" fill="{colour}" '
                       f'font-family="{mono}">{head}</text>')
            out.append(f'<text x="{px(item["cx"]):.1f}" y="{pz(item["cz"]) + dy + 12:.1f}" '
                       f'text-anchor="middle" font-size="9.5" fill="var(--mute)" '
                       f'font-family="{mono}">{sub}</text>')
    else:
        _sky, entries = items
        peak = entries.n.max() if len(entries) else 1
        for r in entries.itertuples():
            colour = TEAM_COLOUR.get(r.team, 'var(--stone)')
            radius = 3 + 11 * (r.n / peak) ** 0.5
            out.append(f'<circle cx="{px(r.gx + 2):.1f}" cy="{pz(r.gz + 2):.1f}" r="{radius:.1f}" '
                       f'fill="{colour}" fill-opacity="0.8" stroke="{colour}" stroke-width="0.8"/>')

    for team, rect in ctx['spawns'].items():
        colour = TEAM_COLOUR.get(team, 'var(--stone)')
        cx, cz = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
        out.append(f'<circle cx="{px(cx):.1f}" cy="{pz(cz):.1f}" r="5.5" fill="none" '
                   f'stroke="{colour}" stroke-width="2.2"/>')
        out.append(f'<text x="{px(cx):.1f}" y="{pz(cz) + 22:.1f}" text-anchor="middle" '
                   f'font-size="10.5" fill="{colour}" font-family="{mono}">{team} spawn</text>')

    out.append(f'<text x="14" y="{height - 12:.0f}" font-size="10" fill="var(--mute)" '
               f'font-family="{mono}">x {x0}&#8230;{x1}, z {z0}&#8230;{z1} '
               f'&#8212; north is up, east is right</text>')
    out.append('</svg>')
    return '\n'.join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--map', required=True)
    parser.add_argument('--match', type=int, required=True)
    parser.add_argument('--mode', choices=('structures', 'sky'), default='structures')
    parser.add_argument('--out')
    args = parser.parse_args()
    con = common.connect()
    svg = render(con, args.map, args.match, args.mode)
    path = Path(args.out) if args.out else Path(f'{args.map}_{args.match}_{args.mode}.svg')
    path.write_text(svg)
    print(f'wrote {path} ({len(svg):,} bytes)')


if __name__ == '__main__':
    main()
