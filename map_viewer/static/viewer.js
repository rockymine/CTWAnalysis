// ── state ──────────────────────────────────────────────────────────────────
let _ctx = null;
let _regionGroups = [];   // [{name, label, regions: [tree node, ...]}, ...]

// Registry: id → { parentId, directChildIds, el (checkbox) }
const _reg = new Map();

// ── coordinate transform ───────────────────────────────────────────────────
const PAD = 20;
let _toSvg = null;

function buildTransform(bbox, svgW, svgH) {
  const [minX, maxX, minZ, maxZ] = bbox;
  const worldW = maxX - minX, worldH = maxZ - minZ;
  const drawW = svgW - 2 * PAD, drawH = svgH - 2 * PAD;
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

function boundsToRingPath(bounds) {
  const { min_x, min_z, max_x, max_z } = bounds;
  const corners = [[min_x, min_z], [max_x, min_z], [max_x, max_z], [min_x, max_z]];
  return corners.map(([wx, wz], i) => {
    const p = _toSvg(wx, wz);
    return (i === 0 ? "M" : "L") + `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
  }).join(" ") + " Z";
}

// ── flatten groups/tree → named+bounded nodes ──────────────────────────────
function flattenNamed(groupsOrNodes, out = []) {
  for (const item of groupsOrNodes) {
    if (item.regions) {
      flattenNamed(item.regions, out);
    } else {
      if (item.id && (item.bounds || item.is_negative)) out.push(item);
      flattenNamed(item.children || [], out);
    }
  }
  return out;
}

// ── map rendering ──────────────────────────────────────────────────────────
const TEAM_FILL = { blue: "#3b82f6", red: "#ef4444" };
const TEAM_FILL_DEFAULT = "#6b7280";
const WOOL_COLORS = {
  orange: "#f97316", pink: "#ec4899", lime: "#84cc16", yellow: "#eab308",
  cyan: "#06b6d4", purple: "#a855f7", white: "#f1f5f9", light_blue: "#38bdf8",
  magenta: "#d946ef", gray: "#9ca3af", black: "#374151", brown: "#92400e",
  green: "#22c55e", red: "#ef4444", blue: "#3b82f6",
};

function renderMap(ctx, groups) {
  const svg = document.getElementById("map-svg");
  const wrap = document.getElementById("canvas-wrap");
  const svgW = wrap.clientWidth - 24, svgH = wrap.clientHeight - 24;
  svg.setAttribute("width", svgW);
  svg.setAttribute("height", svgH);
  svg.setAttribute("viewBox", `0 0 ${svgW} ${svgH}`);
  _toSvg = buildTransform(ctx.bounding_box, svgW, svgH);
  while (svg.firstChild) svg.removeChild(svg.firstChild);

  _renderBuildRegion(svg, ctx);
  _renderIslands(svg, ctx);
  _renderPois(svg, ctx);
  _renderXmlRegions(svg, ctx, groups);
}

function _renderBuildRegion(svg, ctx) {
  const g = svgEl("g", { id: "layer-build" });
  for (const poly of (ctx.build_region?.buildable_void || [])) {
    g.appendChild(svgEl("path", {
      d: polyToPath(poly),
      fill: "#22c55e", "fill-opacity": "0.10",
      stroke: "#22c55e", "stroke-width": "0.8", "stroke-opacity": "0.4",
      "fill-rule": "evenodd",
    }));
  }
  svg.appendChild(g);
}

function _renderIslands(svg, ctx) {
  const g = svgEl("g", { id: "layer-islands" });
  for (const island of (ctx.islands || [])) {
    const poly = island.simplified_polygon;
    if (!poly?.exterior?.length) continue;
    const color = TEAM_FILL[island.team] || TEAM_FILL_DEFAULT;
    g.appendChild(svgEl("path", {
      d: polyToPath(poly),
      fill: color, "fill-opacity": "0.25",
      stroke: color, "stroke-width": "1.2",
      "fill-rule": "evenodd",
    }));
  }
  svg.appendChild(g);
}

function _renderPois(svg, ctx) {
  const g = svgEl("g", { id: "layer-pois" });
  for (const spawn of (ctx.poi_assignments?.spawns || [])) {
    const p = _toSvg(spawn.x, spawn.z);
    const t = svgEl("text", {
      x: p.x, y: p.y,
      "text-anchor": "middle", "dominant-baseline": "middle",
      "font-size": "12", fill: TEAM_FILL[spawn.team_color] || "#f1f5f9",
      "font-weight": "bold",
    });
    t.textContent = "★";
    g.appendChild(t);
  }
  for (const wool of (ctx.poi_assignments?.wools || [])) {
    const p = _toSvg(wool.x, wool.z);
    const t = svgEl("text", {
      x: p.x, y: p.y,
      "text-anchor": "middle", "dominant-baseline": "middle",
      "font-size": "11", fill: WOOL_COLORS[wool.color] || "#f1c40f",
    });
    t.textContent = "◆";
    g.appendChild(t);
  }
  svg.appendChild(g);
}

function _renderXmlRegions(svg, ctx, groups) {
  const g = svgEl("g", { id: "layer-regions" });
  for (const region of flattenNamed(groups)) {
    g.appendChild(_regionSvgGroup(region, ctx));
  }
  svg.appendChild(g);
}

function _regionSvgGroup(region, ctx) {
  const { id, type, color, bounds } = region;
  const p1 = bounds ? _toSvg(bounds.min_x, bounds.min_z) : null;
  const p2 = bounds ? _toSvg(bounds.max_x, bounds.max_z) : null;
  const rx = p1 ? Math.min(p1.x, p2.x) : 0, ry = p1 ? Math.min(p1.y, p2.y) : 0;
  const rw = p1 ? Math.abs(p2.x - p1.x) : 0, rh = p1 ? Math.abs(p2.y - p1.y) : 0;
  const cx = p1 ? (p1.x + p2.x) / 2 : 0, cy = p1 ? (p1.y + p2.y) / 2 : 0;

  const g = svgEl("g", { id: `region-${id}`, style: "display:none" });
  const title = svgEl("title");
  title.textContent = `${id} (${type})`;
  g.appendChild(title);

  if (region.is_negative) {
    g.appendChild(_negativeShape(region, ctx, color));
    g.appendChild(_label(id, _mapCenter(ctx), color, "0.75"));
  } else if (type === "cylinder" || type === "circle" || type === "sphere") {
    g.appendChild(svgEl("ellipse", {
      cx, cy, rx: rw / 2, ry: rh / 2,
      fill: color, "fill-opacity": "0.20",
      stroke: color, "stroke-width": "1.5", "stroke-dasharray": "4,2",
    }));
    if (rw > 20 || rh > 20) g.appendChild(_label(id, { x: cx, y: cy }, color));
  } else {
    g.appendChild(svgEl("rect", {
      x: rx, y: ry, width: rw, height: rh,
      fill: color, "fill-opacity": "0.20",
      stroke: color, "stroke-width": "1.5", "stroke-dasharray": "4,2",
    }));
    if (rw > 20 || rh > 20) g.appendChild(_label(id, { x: cx, y: cy }, color));
  }
  return g;
}

function _negativeShape(region, ctx, color) {
  const [mapMinX, mapMaxX, mapMinZ, mapMaxZ] = ctx.bounding_box;
  let d = boundsToRingPath({ min_x: mapMinX, min_z: mapMinZ, max_x: mapMaxX, max_z: mapMaxZ });
  for (const child of (region.children || [])) {
    if (child.bounds) d += " " + boundsToRingPath(child.bounds);
  }
  return svgEl("path", {
    d,
    fill: color, "fill-opacity": "0.12",
    stroke: color, "stroke-width": "1.5", "stroke-dasharray": "6,3",
    "fill-rule": "evenodd",
  });
}

function _mapCenter(ctx) {
  const [minX, maxX, minZ, maxZ] = ctx.bounding_box;
  const a = _toSvg(minX, minZ), b = _toSvg(maxX, maxZ);
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

function _label(id, pos, color, opacity = "0.9") {
  const el = svgEl("text", {
    x: pos.x, y: pos.y,
    "text-anchor": "middle", "dominant-baseline": "middle",
    "font-size": "9", fill: color, "fill-opacity": opacity,
    "pointer-events": "none",
  });
  el.textContent = id.length > 24 ? id.slice(0, 22) + "…" : id;
  return el;
}

// ── checkbox cascade ───────────────────────────────────────────────────────
function toggleSvg(id, visible) {
  const g = document.getElementById(`region-${id}`);
  if (g) g.style.display = visible ? "" : "none";
}

function cascadeDown(id, checked) {
  const info = _reg.get(id);
  if (!info) return;
  if (info.el) {
    info.el.checked = checked;
    info.el.indeterminate = false;
    toggleSvg(id, checked);
  }
  for (const childId of info.directChildIds) cascadeDown(childId, checked);
}

function updateAncestors(id) {
  const info = _reg.get(id);
  if (!info || !info.parentId) return;
  const parentInfo = _reg.get(info.parentId);
  if (!parentInfo) { updateAncestors(info.parentId); return; }
  if (parentInfo.el) {
    const childStates = parentInfo.directChildIds.map(cid => {
      const c = _reg.get(cid);
      return c?.el ? c.el.checked && !c.el.indeterminate : true;
    });
    const allChecked = childStates.every(Boolean);
    const anyChecked = childStates.some(Boolean);
    parentInfo.el.indeterminate = anyChecked && !allChecked;
    if (!parentInfo.el.indeterminate) parentInfo.el.checked = allChecked;
  }
  updateAncestors(info.parentId);
}

function syncToggleAll() {
  const allEls = [..._reg.values()].filter(i => i.el).map(i => i.el);
  const allChecked = allEls.every(el => el.checked && !el.indeterminate);
  const anyChecked = allEls.some(el => el.checked || el.indeterminate);
  const ta = document.getElementById("toggle-all");
  ta.indeterminate = anyChecked && !allChecked;
  ta.checked = allChecked;
}

// ── sidebar ────────────────────────────────────────────────────────────────
const TYPE_CLASS = { union: "type-union", negative: "type-negative", intersect: "type-intersect" };
const CAT_COLORS = {
  spawn: "#60a5fa", wool: "#f1c40f", monument: "#a78bfa",
  build: "#34d399", other: "#94a3b8",
};

function buildRegistryEntry(node, parentId) {
  const directChildIds = (node.children || []).filter(c => c.id).map(c => c.id);
  _reg.set(node.id, { parentId, directChildIds, el: null });
  for (const child of (node.children || [])) buildRegistryEntry(child, node.id);
}

function buildSidebar(groups) {
  _reg.clear();
  const list = document.getElementById("region-list");
  list.innerHTML = "";

  if (!flattenNamed(groups).length) {
    list.innerHTML = '<div id="empty-msg">No named regions found</div>';
    return;
  }

  for (const group of groups) {
    for (const root of group.regions) buildRegistryEntry(root, null);
  }

  for (const group of groups) {
    list.appendChild(_categoryHeader(group));
    buildSidebarTree(group.regions, list, 0, []);
  }
}

function _categoryHeader(group) {
  const color = CAT_COLORS[group.name] || "#64748b";
  const header = document.createElement("div");
  header.style.cssText = `
    display:flex; align-items:center; gap:6px; padding:8px 10px 4px 10px;
    font-size:10px; font-weight:700; letter-spacing:.07em;
    color:${color}; text-transform:uppercase; user-select:none;
  `;
  const line = document.createElement("div");
  line.style.cssText = `flex:1; height:1px; background:${color}; opacity:0.25;`;
  header.appendChild(document.createTextNode(group.label));
  header.appendChild(line);
  return header;
}

function buildSidebarTree(nodes, container, depth, isLast = []) {
  for (let i = 0; i < nodes.length; i++) {
    const node = nodes[i];
    const isLastChild = i === nodes.length - 1;
    container.appendChild(_regionRow(node, depth, isLast, isLastChild));
    if ((node.children || []).length > 0) {
      buildSidebarTree(node.children, container, depth + 1, [...isLast, isLastChild]);
    }
  }
}

function _regionRow(node, depth, isLast, isLastChild) {
  const isSynthetic = !!node.synthetic_id;
  const row = document.createElement("div");
  row.className = "region-row";
  row.appendChild(_treeIndent(depth, isLast, isLastChild));
  row.appendChild(_checkbox(node));
  row.appendChild(_dot(node.color, isSynthetic));
  row.appendChild(_regionLabel(node, isSynthetic));
  row.appendChild(_typeBadge(node.type));
  row.addEventListener("click", (e) => {
    const cb = row.querySelector("input[type=checkbox]");
    if (cb && e.target !== cb) cb.click();
  });
  return row;
}

function _treeIndent(depth, isLast, isLastChild) {
  const wrap = document.createElement("div");
  wrap.className = "region-indent";
  wrap.style.paddingLeft = "8px";
  for (let d = 0; d < depth; d++) {
    const line = document.createElement("span");
    line.style.cssText = `
      display:inline-block; width:14px; flex-shrink:0;
      border-left:1px solid ${isLast[d] ? "transparent" : "#2d4263"};
    `;
    wrap.appendChild(line);
  }
  if (depth > 0) {
    const elbow = document.createElement("span");
    elbow.style.cssText = "display:inline-block; width:14px; flex-shrink:0; font-size:9px; color:#334155; line-height:22px;";
    elbow.textContent = isLastChild ? "└" : "├";
    wrap.appendChild(elbow);
  }
  return wrap;
}

function _checkbox(node) {
  const wrap = document.createElement("div");
  wrap.style.cssText = "width:17px; flex-shrink:0; display:flex; justify-content:center;";
  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.checked = false;
  const info = _reg.get(node.id);
  if (info) info.el = cb;
  cb.addEventListener("change", () => {
    toggleSvg(node.id, cb.checked);
    for (const childId of (info?.directChildIds || [])) cascadeDown(childId, cb.checked);
    updateAncestors(node.id);
    syncToggleAll();
  });
  wrap.appendChild(cb);
  return wrap;
}

function _dot(color, isSynthetic) {
  const dot = document.createElement("div");
  dot.style.cssText = isSynthetic
    ? `width:9px; height:9px; border-radius:2px; flex-shrink:0; opacity:0.5; background:transparent; border:1px dashed ${color};`
    : `width:9px; height:9px; border-radius:2px; flex-shrink:0; opacity:0.85; background:${color};`;
  return dot;
}

function _regionLabel(node, isSynthetic) {
  const el = document.createElement("span");
  el.style.cssText = `
    flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-size:11px;
    ${isSynthetic ? "font-style:italic; color:#64748b;" : "color:#cbd5e1;"}
  `;
  el.textContent = node.label;
  el.title = isSynthetic ? `${node.label}  (id: ${node.id})` : node.label;
  return el;
}

function _typeBadge(type) {
  const el = document.createElement("span");
  const cls = TYPE_CLASS[type];
  el.style.cssText = `font-size:9px; background:#0f172a; padding:1px 4px; border-radius:3px; flex-shrink:0;`;
  if (cls) { el.className = cls; } else { el.style.color = "#475569"; }
  el.textContent = type;
  return el;
}

// ── data loading ───────────────────────────────────────────────────────────
function countNamed(groupsOrNodes) {
  let n = 0;
  for (const item of groupsOrNodes) {
    if (item.regions) { n += countNamed(item.regions); }
    else { if (item.id) n++; n += countNamed(item.children || []); }
  }
  return n;
}

async function loadMaps() {
  const maps = await fetch("/api/maps").then(r => r.json());
  const sel = document.getElementById("map-select");
  for (const m of maps) {
    const opt = document.createElement("option");
    opt.value = m.name;
    opt.textContent = m.display_name;
    sel.appendChild(opt);
  }
}

async function loadMap(name) {
  document.getElementById("status").textContent = "Loading…";
  const [ctxResp, regResp] = await Promise.all([
    fetch(`/api/map/${name}/context`),
    fetch(`/api/map/${name}/regions`),
  ]);
  if (!ctxResp.ok) { document.getElementById("status").textContent = "Error loading map"; return; }
  _ctx = await ctxResp.json();
  _regionGroups = regResp.ok ? await regResp.json() : [];
  renderMap(_ctx, _regionGroups);
  buildSidebar(_regionGroups);
  document.getElementById("status").textContent =
    `${_ctx.map_name} v${_ctx.map_version || "?"} · ` +
    `${_ctx.island_count} island(s) · ${countNamed(_regionGroups)} region(s)`;
}

// ── event wiring ───────────────────────────────────────────────────────────
document.getElementById("toggle-all").addEventListener("change", (e) => {
  const checked = e.target.checked;
  for (const [id, info] of _reg.entries()) {
    if (!info.parentId) cascadeDown(id, checked);
  }
  syncToggleAll();
});

document.getElementById("map-select").addEventListener("change", (e) => {
  if (e.target.value) loadMap(e.target.value);
});

window.addEventListener("resize", () => {
  if (_ctx) renderMap(_ctx, _regionGroups);
});

loadMaps();
