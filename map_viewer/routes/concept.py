"""Concept layout tool — compute polygons from sketched shapes."""
from __future__ import annotations

import math

from flask import Blueprint, jsonify, request

bp = Blueprint("concept", __name__)


@bp.route("/api/concept/compute", methods=["POST"])
def compute():
    """
    Compute island polygons from sketched shapes.

    Body:
        shapes:  list of { id, type, operation, ...coords }
        islands: list of { id, name, shape_ids }

    Returns:
        { islands: [ { id, name, polygon: {exterior, holes} | null } ] }
    """
    data = request.get_json(force=True)
    shapes  = data.get("shapes",  [])
    islands = data.get("islands", [])

    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union
    from shapely.validation import make_valid

    def shape_to_shapely(s):
        t = s.get("type")
        if t == "rectangle":
            return box(s["min_x"], s["min_z"], s["max_x"], s["max_z"])
        if t == "circle":
            cx, cz, r = s["center_x"], s["center_z"], s["radius"]
            pts = [
                (cx + r * math.cos(2 * math.pi * i / 64),
                 cz + r * math.sin(2 * math.pi * i / 64))
                for i in range(64)
            ]
            return Polygon(pts)
        if t == "polygon":
            verts = s.get("vertices", [])
            if len(verts) < 3:
                return None
            return Polygon([(v[0], v[1]) for v in verts])
        return None

    shape_map = {s["id"]: s for s in shapes}

    results = []
    for island in islands:
        add_geoms, sub_geoms = [], []
        for sid in island.get("shape_ids", []):
            s = shape_map.get(sid)
            if not s:
                continue
            g = shape_to_shapely(s)
            if g is None or g.is_empty:
                continue
            (sub_geoms if s.get("operation") == "subtract" else add_geoms).append(g)

        if not add_geoms:
            results.append({"id": island["id"], "name": island.get("name", ""), "polygon": None})
            continue

        combined = unary_union(add_geoms)
        if not combined.is_valid:
            combined = make_valid(combined)
        if sub_geoms:
            combined = combined.difference(unary_union(sub_geoms))
            if not combined.is_valid:
                combined = make_valid(combined)

        results.append({
            "id":      island["id"],
            "name":    island.get("name", ""),
            "polygon": _extract_polygon(combined),
        })

    return jsonify({"islands": results})


def _extract_polygon(geom):
    from shapely.geometry import Polygon
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "MultiPolygon":
        geom = max(geom.geoms, key=lambda g: g.area)
    if geom.geom_type != "Polygon":
        return None
    exterior = [[round(float(x), 1), round(float(z), 1)] for x, z in geom.exterior.coords]
    holes = [
        [[round(float(x), 1), round(float(z), 1)] for x, z in ring.coords]
        for ring in geom.interiors
    ]
    return {"exterior": exterior, "holes": holes}
