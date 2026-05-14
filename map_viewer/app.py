"""Flask app for the CTW map viewer.

Routes
------
GET /                              Single-page HTML app
GET /api/maps                      List available maps (those with map_context.json)
GET /api/map/<name>/context        map_context.json payload
GET /api/map/<name>/regions        Named regions encoded for rendering
"""

from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, jsonify, abort

from map_viewer.region_encoder import encode_regions

OUTPUT_ROOT = Path(__file__).parent.parent / "output"

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>CTW Map Viewer</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: ui-monospace, monospace; font-size: 13px;
         background: #0f172a; color: #e2e8f0; display: flex;
         flex-direction: column; height: 100vh; overflow: hidden; }

  /* ── top bar ── */
  #topbar { display: flex; align-items: center; gap: 10px;
            padding: 8px 14px; background: #1e293b;
            border-bottom: 1px solid #334155; flex-shrink: 0; }
  #topbar h1 { font-size: 14px; font-weight: 600; color: #94a3b8;
               letter-spacing: .04em; }
  #map-select { background: #0f172a; color: #e2e8f0; border: 1px solid #475569;
                border-radius: 4px; padding: 4px 8px; font-size: 13px;
                font-family: inherit; cursor: pointer; }
  #status { margin-left: auto; color: #64748b; font-size: 11px; }

  /* ── main layout ── */
  #main { display: flex; flex: 1; overflow: hidden; }

  /* ── svg canvas ── */
  #canvas-wrap { flex: 1; display: flex; align-items: center;
                 justify-content: center; overflow: hidden; padding: 12px; }
  #map-svg { max-width: 100%; max-height: 100%; }

  /* ── sidebar ── */
  #sidebar { width: 260px; flex-shrink: 0; background: #1e293b;
             border-left: 1px solid #334155; display: flex;
             flex-direction: column; overflow: hidden; }
  #sidebar-header { padding: 10px 12px; border-bottom: 1px solid #334155;
                    font-weight: 600; color: #94a3b8; font-size: 12px;
                    letter-spacing: .05em; display: flex;
                    align-items: center; gap: 8px; }
  #toggle-all { cursor: pointer; accent-color: #60a5fa; }
  #region-list { flex: 1; overflow-y: auto; padding: 6px 0; }
  .region-row { display: flex; align-items: center; gap: 7px;
                padding: 4px 12px; cursor: pointer; }
  .region-row:hover { background: #0f172a; }
  .region-dot { width: 10px; height: 10px; border-radius: 2px;
                flex-shrink: 0; opacity: 0.85; }
  .region-label { flex: 1; white-space: nowrap; overflow: hidden;
                  text-overflow: ellipsis; font-size: 11px; color: #cbd5e1; }
  .region-type { font-size: 10px; color: #64748b; margin-left: auto;
                 flex-shrink: 0; }
  input[type=checkbox] { cursor: pointer; accent-color: #60a5fa; }
  #empty-msg { padding: 20px 12px; color: #475569; font-size: 11px; }
</style>
</head>
<body>

<div id="topbar">
  <h1>CTW Map Viewer</h1>
  <select id="map-select"><option value="">— select map —</option></select>
  <span id="status"></span>
</div>

<div id="main">
  <div id="canvas-wrap">
    <svg id="map-svg" xmlns="http://www.w3.org/2000/svg">
      <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle"
            fill="#334155" font-size="14">Select a map to begin</text>
    </svg>
  </div>
  <div id="sidebar">
    <div id="sidebar-header">
      <input type="checkbox" id="toggle-all" checked title="Toggle all regions"/>
      XML Regions
    </div>
    <div id="region-list">
      <div id="empty-msg">No map loaded</div>
    </div>
  </div>
</div>

<script>
// ── state ──────────────────────────────────────────────────────────────────
let _ctx = null;      // map_context.json
let _regions = [];    // encoded region list

// ── coordinate helpers ─────────────────────────────────────────────────────
const PAD = 20;
let _toSvg = null;    // (wx, wz) → {x, y}

function buildTransform(bbox, svgW, svgH) {
  // bbox = [min_x, max_x, min_z, max_z]
  const [minX, maxX, minZ, maxZ] = bbox;
  const worldW = maxX - minX;
  const worldH = maxZ - minZ;
  const drawW = svgW - 2 * PAD;
  const drawH = svgH - 2 * PAD;
  const scale = Math.min(drawW / worldW, drawH / worldH);
  const offX = PAD + (drawW - worldW * scale) / 2;
  const offY = PAD + (drawH - worldH * scale) / 2;
  return (wx, wz) => ({
    x: offX + (wx - minX) * scale,
    y: offY + (wz - minZ) * scale,
  });
}

// ── SVG helpers ────────────────────────────────────────────────────────────
function svgEl(tag, attrs = {}, children = []) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  for (const ch of children) el.appendChild(ch);
  return el;
}

function ringToPath(ring) {
  return ring.map(([x, z], i) => {
    const p = _toSvg(x, z);
    return (i === 0 ? "M" : "L") + `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
  }).join(" ") + " Z";
}

function polyToPath(poly) {
  let d = ringToPath(poly.exterior);
  for (const hole of (poly.holes || [])) d += " " + ringToPath(hole);
  return d;
}

// ── rendering ──────────────────────────────────────────────────────────────
const TEAM_FILL = { blue: "#3b82f6", red: "#ef4444" };
const TEAM_FILL_DEFAULT = "#6b7280";
const WOOL_COLORS = {
  orange:"#f97316", pink:"#ec4899", lime:"#84cc16", yellow:"#eab308",
  cyan:"#06b6d4", purple:"#a855f7", white:"#f1f5f9", light_blue:"#38bdf8",
  magenta:"#d946ef", gray:"#9ca3af", black:"#374151", brown:"#92400e",
  green:"#22c55e", red:"#ef4444", blue:"#3b82f6",
};

function renderMap(ctx, regions) {
  const svg = document.getElementById("map-svg");

  // Compute canvas size from element dimensions
  const wrap = document.getElementById("canvas-wrap");
  const svgW = wrap.clientWidth - 24;
  const svgH = wrap.clientHeight - 24;
  svg.setAttribute("width", svgW);
  svg.setAttribute("height", svgH);
  svg.setAttribute("viewBox", `0 0 ${svgW} ${svgH}`);

  _toSvg = buildTransform(ctx.bounding_box, svgW, svgH);

  // Clear
  while (svg.firstChild) svg.removeChild(svg.firstChild);

  // Layer 1: build region (green, semi-transparent)
  const buildGroup = svgEl("g", { id: "layer-build" });
  for (const poly of (ctx.build_region?.buildable_void || [])) {
    buildGroup.appendChild(svgEl("path", {
      d: polyToPath(poly),
      fill: "#22c55e", "fill-opacity": "0.10",
      stroke: "#22c55e", "stroke-width": "0.8", "stroke-opacity": "0.4",
      "fill-rule": "evenodd",
    }));
  }
  svg.appendChild(buildGroup);

  // Layer 2: island fills
  const islandGroup = svgEl("g", { id: "layer-islands" });
  for (const island of (ctx.islands || [])) {
    const poly = island.simplified_polygon;
    if (!poly?.exterior?.length) continue;
    const teamColor = TEAM_FILL[island.team] || TEAM_FILL_DEFAULT;
    islandGroup.appendChild(svgEl("path", {
      d: polyToPath(poly),
      fill: teamColor, "fill-opacity": "0.25",
      stroke: teamColor, "stroke-width": "1.2",
      "fill-rule": "evenodd",
    }));
  }
  svg.appendChild(islandGroup);

  // Layer 3: POIs
  const poiGroup = svgEl("g", { id: "layer-pois" });
  for (const spawn of (ctx.poi_assignments?.spawns || [])) {
    const p = _toSvg(spawn.x, spawn.z);
    const color = TEAM_FILL[spawn.team_color] || "#f1f5f9";
    const t = svgEl("text", {
      x: p.x, y: p.y,
      "text-anchor": "middle", "dominant-baseline": "middle",
      "font-size": "12", fill: color, "font-weight": "bold",
    });
    t.textContent = "★";
    poiGroup.appendChild(t);
  }
  for (const wool of (ctx.poi_assignments?.wools || [])) {
    const p = _toSvg(wool.x, wool.z);
    const color = WOOL_COLORS[wool.color] || "#f1c40f";
    const t = svgEl("text", {
      x: p.x, y: p.y,
      "text-anchor": "middle", "dominant-baseline": "middle",
      "font-size": "11", fill: color,
    });
    t.textContent = "◆";
    poiGroup.appendChild(t);
  }
  svg.appendChild(poiGroup);

  // Layer 4: XML regions (hidden by default, toggled per-region)
  const regionsGroup = svgEl("g", { id: "layer-regions" });
  for (const region of regions) {
    const { id, type, color, bounds } = region;
    const p1 = _toSvg(bounds.min_x, bounds.min_z);
    const p2 = _toSvg(bounds.max_x, bounds.max_z);
    const rx = Math.min(p1.x, p2.x), ry = Math.min(p1.y, p2.y);
    const rw = Math.abs(p2.x - p1.x), rh = Math.abs(p2.y - p1.y);
    const cx = (p1.x + p2.x) / 2, cy = (p1.y + p2.y) / 2;

    const g = svgEl("g", { id: `region-${id}`, style: "display:none" });
    const title = svgEl("title");
    title.textContent = `${id} (${type})`;
    g.appendChild(title);

    if (type === "cylinder" || type === "circle" || type === "sphere") {
      g.appendChild(svgEl("ellipse", {
        cx, cy, rx: rw / 2, ry: rh / 2,
        fill: color, "fill-opacity": "0.20",
        stroke: color, "stroke-width": "1.5", "stroke-dasharray": "4,2",
      }));
    } else {
      g.appendChild(svgEl("rect", {
        x: rx, y: ry, width: rw, height: rh,
        fill: color, "fill-opacity": "0.20",
        stroke: color, "stroke-width": "1.5", "stroke-dasharray": "4,2",
      }));
    }

    // Label (only when big enough)
    if (rw > 20 || rh > 20) {
      const lbl = svgEl("text", {
        x: cx, y: cy,
        "text-anchor": "middle", "dominant-baseline": "middle",
        "font-size": "9", fill: color, "fill-opacity": "0.9",
        "pointer-events": "none",
      });
      lbl.textContent = id.length > 24 ? id.slice(0, 22) + "…" : id;
      g.appendChild(lbl);
    }

    regionsGroup.appendChild(g);
  }
  svg.appendChild(regionsGroup);
}

// ── sidebar ────────────────────────────────────────────────────────────────
function buildSidebar(regions) {
  const list = document.getElementById("region-list");
  list.innerHTML = "";

  if (!regions.length) {
    list.innerHTML = '<div id="empty-msg">No named regions found</div>';
    return;
  }

  for (const region of regions) {
    const row = document.createElement("div");
    row.className = "region-row";

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.dataset.regionId = region.id;
    cb.addEventListener("change", () => {
      const g = document.getElementById(`region-${region.id}`);
      if (g) g.style.display = cb.checked ? "" : "none";
      syncToggleAll();
    });

    const dot = document.createElement("div");
    dot.className = "region-dot";
    dot.style.background = region.color;

    const label = document.createElement("span");
    label.className = "region-label";
    label.textContent = region.label;
    label.title = region.label;

    const type = document.createElement("span");
    type.className = "region-type";
    type.textContent = region.type;

    row.appendChild(cb);
    row.appendChild(dot);
    row.appendChild(label);
    row.appendChild(type);
    row.addEventListener("click", (e) => {
      if (e.target !== cb) cb.click();
    });

    list.appendChild(row);
  }
}

function syncToggleAll() {
  const cbs = [...document.querySelectorAll("#region-list input[type=checkbox]")];
  const allChecked = cbs.every(cb => cb.checked);
  const noneChecked = cbs.every(cb => !cb.checked);
  const ta = document.getElementById("toggle-all");
  ta.indeterminate = !allChecked && !noneChecked;
  ta.checked = allChecked;
}

document.getElementById("toggle-all").addEventListener("change", (e) => {
  const checked = e.target.checked;
  document.querySelectorAll("#region-list input[type=checkbox]").forEach(cb => {
    if (cb.checked !== checked) cb.click();
  });
});

// ── data loading ───────────────────────────────────────────────────────────
function setStatus(msg) {
  document.getElementById("status").textContent = msg;
}

async function loadMaps() {
  const resp = await fetch("/api/maps");
  const maps = await resp.json();
  const sel = document.getElementById("map-select");
  for (const m of maps) {
    const opt = document.createElement("option");
    opt.value = m.name;
    opt.textContent = m.display_name;
    sel.appendChild(opt);
  }
}

async function loadMap(name) {
  setStatus("Loading…");
  const [ctxResp, regResp] = await Promise.all([
    fetch(`/api/map/${name}/context`),
    fetch(`/api/map/${name}/regions`),
  ]);
  if (!ctxResp.ok) { setStatus("Error loading map"); return; }
  _ctx = await ctxResp.json();
  _regions = regResp.ok ? await regResp.json() : [];
  renderMap(_ctx, _regions);
  buildSidebar(_regions);
  setStatus(`${_ctx.map_name} v${_ctx.map_version || "?"} · ${_ctx.island_count} island(s) · ${_regions.length} region(s)`);
}

document.getElementById("map-select").addEventListener("change", (e) => {
  if (e.target.value) loadMap(e.target.value);
});

window.addEventListener("resize", () => {
  if (_ctx) renderMap(_ctx, _regions);
});

loadMaps();
</script>
</body>
</html>
"""


def create_app() -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def index():
        from flask import Response
        return Response(_HTML, mimetype="text/html")

    @app.route("/api/maps")
    def list_maps():
        maps = []
        for path in sorted(OUTPUT_ROOT.iterdir()):
            if (path / "map_context.json").exists():
                display = path.name.replace("_", " ").title()
                maps.append({"name": path.name, "display_name": display})
        return jsonify(maps)

    @app.route("/api/map/<name>/context")
    def map_context(name: str):
        ctx_path = OUTPUT_ROOT / name / "map_context.json"
        if not ctx_path.exists():
            abort(404)
        return jsonify(json.loads(ctx_path.read_text(encoding="utf-8")))

    @app.route("/api/map/<name>/regions")
    def map_regions(name: str):
        data_path = OUTPUT_ROOT / name / "map_data.json"
        if not data_path.exists():
            abort(404)
        data = json.loads(data_path.read_text(encoding="utf-8"))
        regions = encode_regions(data.get("regions", {}))
        return jsonify(regions)

    return app
