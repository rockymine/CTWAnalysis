import { typeIcon } from "./region-types.js";

// ── helpers ───────────────────────────────────────────────────────────────────

function fmt(v) {
  if (v == null) return "?";
  return (typeof v === "number" && !Number.isInteger(v)) ? v.toFixed(2) : String(v);
}

// ── geometry schema ───────────────────────────────────────────────────────────

const Y = { min: 0, max: 256 };
const R = { min: 0 };
const H = { min: 0 };

// Each entry is either:
//   { type: "group",  label, note?, axes: [{ axis, key, display?, min?, max? }] }
//   { type: "scalar", label, key, display?, unit?, min?, max? }
// key=null → read-only; display(node) required for that axis/field.
// rectangle and cuboid are NOT in this schema — their coords are in #buildBounds.
const GEOMETRY_SCHEMA = {
  cylinder: [
    { type: "group",  label: "BASE POINT", axes: [
      { axis: "X", key: "base_x" },
      { axis: "Y", key: "base_y", ...Y },
      { axis: "Z", key: "base_z" },
    ]},
    { type: "scalar-pair", entries: [
      { label: "RADIUS", key: "radius", unit: "blocks", ...R },
      { label: "HEIGHT", key: "height", unit: "blocks", ...H },
    ]},
  ],
  circle: [
    { type: "group",  label: "CENTER", axes: [
      { axis: "X", key: "center_x" },
      { axis: "Z", key: "center_z" },
    ]},
    { type: "scalar", label: "RADIUS", key: "radius", unit: "blocks", ...R },
  ],
  sphere: [
    { type: "group",  label: "ORIGIN", axes: [
      { axis: "X", key: "origin_x" },
      { axis: "Y", key: "origin_y", ...Y },
      { axis: "Z", key: "origin_z" },
    ]},
    { type: "scalar", label: "RADIUS", key: "radius", unit: "blocks", ...R },
  ],
  block: [
    { type: "group", label: "POSITION", note: "single block", axes: [
      { axis: "X", key: "x" },
      { axis: "Y", key: "y", ...Y },
      { axis: "Z", key: "z" },
    ]},
  ],
  point: [
    { type: "group", label: "POSITION", axes: [
      { axis: "X", key: "x" },
      { axis: "Y", key: "y", ...Y },
      { axis: "Z", key: "z" },
    ]},
  ],
  reference: [
    { type: "scalar", label: "REF", key: null, display: n => n.coords?.ref_id ?? "?" },
  ],
  mirror: [
    { type: "group", label: "ORIGIN", axes: [
      { axis: "X", key: null, display: n => fmt(n.coords?.origin_x) },
      { axis: "Y", key: null, display: n => fmt(n.coords?.origin_y) },
      { axis: "Z", key: null, display: n => fmt(n.coords?.origin_z) },
    ]},
    { type: "group", label: "NORMAL", axes: [
      { axis: "X", key: null, display: n => fmt(n.coords?.normal_x) },
      { axis: "Y", key: null, display: n => fmt(n.coords?.normal_y) },
      { axis: "Z", key: null, display: n => fmt(n.coords?.normal_z) },
    ]},
  ],
  translate: [
    { type: "group", label: "OFFSET", axes: [
      { axis: "X", key: null, display: n => fmt(n.coords?.offset_x) },
      { axis: "Y", key: null, display: n => fmt(n.coords?.offset_y) },
      { axis: "Z", key: null, display: n => fmt(n.coords?.offset_z) },
    ]},
  ],
  above: [
    { type: "scalar", label: "Y", key: "y", ...Y },
  ],
};

// ── XML reconstruction ────────────────────────────────────────────────────────

function nodeToXml(node, depth = 0) {
  const indent = "  ".repeat(depth);
  const id     = node.synthetic_id ? "" : ` id="${node.label}"`;
  const t      = node.type;
  const b      = node.bounds  ?? {};
  const c      = node.coords  ?? {};

  let attr = "";

  if (t === "rectangle") {
    attr = ` min="${b.min_x},${b.min_z}" max="${b.max_x},${b.max_z}"`;
  } else if (t === "cuboid") {
    const minY = c.min_y ?? "?";
    const maxY = c.max_y ?? "?";
    attr = ` min="${b.min_x},${minY},${b.min_z}" max="${b.max_x},${maxY},${b.max_z}"`;
  } else if (t === "cylinder") {
    const by = c.base_y ?? "?";
    attr = ` base="${b.min_x + (b.max_x - b.min_x) / 2},${by},${b.min_z + (b.max_z - b.min_z) / 2}"` +
           ` radius="${c.radius ?? "?"}" height="${c.height ?? "?"}"`;
  } else if (t === "circle") {
    attr = ` center="${b.min_x + (b.max_x - b.min_x) / 2},${b.min_z + (b.max_z - b.min_z) / 2}"` +
           ` radius="${c.radius ?? "?"}"`;
  } else if (t === "sphere") {
    const oy = c.origin_y ?? "?";
    attr = ` origin="${b.min_x + (b.max_x - b.min_x) / 2},${oy},${b.min_z + (b.max_z - b.min_z) / 2}"` +
           ` radius="${c.radius ?? "?"}"`;
  }

  const composite = ["union", "negative", "intersect", "complement"].includes(t);
  if (composite) {
    const inner = (node.children || [])
      .map(ch => nodeToXml(ch, depth + 1))
      .join("\n");
    return inner
      ? `${indent}<${t}${id}>\n${inner}\n${indent}</${t}>`
      : `${indent}<${t}${id}/>`;
  }

  if (t === "block" || t === "point") {
    const x = c.x ?? "?", y = c.y ?? "?", z = c.z ?? "?";
    return `${indent}<${t}${id}>${x},${y},${z}</${t}>`;
  }

  if (t === "reference") {
    return `${indent}<region id="${c.ref_id ?? "?"}"/>`;
  }

  return attr
    ? `${indent}<${t}${id}${attr}/>`
    : `${indent}<${t}${id}/>`;
}

// ── RegionDetail ──────────────────────────────────────────────────────────────

export class RegionDetail {
  #el;
  #callbacks;
  #xmlCodeEl     = null;
  #headerLabelEl = null;

  constructor(el, callbacks = {}) {
    this.#el        = el;
    this.#callbacks = callbacks;
    this.#renderEmpty();
  }

  static #COMPOSITE_TYPES = new Set(["union", "negative", "intersect", "complement"]);

  show(node) {
    this.#el.innerHTML = "";
    this.#xmlCodeEl     = null;
    this.#headerLabelEl = null;
    this.#el.appendChild(this.#buildHeader(node));

    const hint = document.createElement("div");
    hint.className = "detail-save-hint";
    hint.textContent = "enter or click outside to save · esc to revert";
    this.#el.appendChild(hint);

    this.#el.appendChild(this.#buildFields(node));

    if (node.type === "rectangle" && node.bounds) {
      this.#el.appendChild(this.#buildBounds(node, false));
    } else if (node.type === "cuboid") {
      // Y is integrated into the bounds table — no separate geometry section needed
      if (node.bounds) this.#el.appendChild(this.#buildBounds(node, true));
    } else if (node.type === "everywhere") {
      this.#el.appendChild(this.#buildNote("Matches every location — no geometry to display."));
    } else if (GEOMETRY_SCHEMA[node.type]) {
      this.#el.appendChild(this.#buildGeometry(node));
    }

    if ((node.children || []).length > 0) this.#el.appendChild(this.#buildChildren(node.children));
    this.#el.appendChild(this.#buildXmlPreview(node));
  }

  clear() {
    this.#el.innerHTML = "";
    this.#xmlCodeEl     = null;
    this.#headerLabelEl = null;
    this.#renderEmpty();
  }

  updateXmlPreview(node) {
    if (this.#xmlCodeEl) this.#xmlCodeEl.textContent = nodeToXml(node);
  }

  // ── private ─────────────────────────────────────────────────────────────────

  #renderEmpty() {
    const el = document.createElement("div");
    el.className = "detail-empty";
    el.textContent = "Click a region to inspect";
    this.#el.appendChild(el);
  }

  #buildHeader(node) {
    const row = document.createElement("div");
    row.className = "detail-header";

    const label = document.createElement("span");
    label.className = "detail-label";
    label.textContent = node.label;
    this.#headerLabelEl = label;

    const badge = document.createElement("span");
    badge.className = "detail-type-badge";
    badge.textContent = node.type ? node.type.charAt(0).toUpperCase() + node.type.slice(1) : "";

    row.appendChild(typeIcon(node.type, node.synthetic_id, "detail-type-icon"));
    row.appendChild(label);
    row.appendChild(badge);
    return row;
  }

  #buildFields(node) {
    const section = document.createElement("div");
    section.className = "detail-section";

    if (node.synthetic_id) {
      section.appendChild(this.#fieldRow("id", node.id));
    } else {
      section.appendChild(this.#makeIdRow(node));
    }

    const extras = [
      ["label",    node.label !== node.id ? node.label : null],
      ["synthetic", node.synthetic_id ? "yes" : null],
      ["negative",  node.is_negative  ? "yes" : null],
    ].filter(([, v]) => v !== null);

    for (const [key, val] of extras) section.appendChild(this.#fieldRow(key, val));
    return section;
  }

  // Vertical: label div above input
  #makeIdRow(node) {
    const wrap = document.createElement("div");
    wrap.className = "detail-field-row";

    const keyEl = document.createElement("div");
    keyEl.className = "detail-field-key";
    keyEl.textContent = "ID";

    const input = document.createElement("input");
    input.type      = "text";
    input.value     = node.id;
    input.className = "detail-id-input";

    input.addEventListener("blur", () => {
      const newId = input.value.trim();
      if (!newId || newId === node.id) { input.value = node.id; return; }
      const oldId = node.id;
      node.id    = newId;
      node.label = newId;
      if (this.#headerLabelEl) this.#headerLabelEl.textContent = newId;
      this.updateXmlPreview(node);
      if (this.#callbacks.onIdChange) this.#callbacks.onIdChange(node, oldId, newId);
    });

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter")  { e.preventDefault(); input.blur(); }
      if (e.key === "Escape") { e.preventDefault(); input.value = node.id; input.blur(); }
    });

    wrap.appendChild(keyEl);
    wrap.appendChild(input);
    return wrap;
  }

  // ── bounds table (rectangle: X/Z; cuboid: X/Y/Z) ─────────────────────────

  #buildBounds(node, includeY) {
    const origBounds = { ...node.bounds };
    const origCoords = includeY ? { ...node.coords } : null;

    const section = document.createElement("div");
    section.className = "detail-section";
    section.appendChild(this.#sectionHeader("BOUNDS"));

    const table = document.createElement("table");
    table.className = "detail-table";
    section.appendChild(table);

    const thead = table.createTHead();
    const hrow  = thead.insertRow();
    for (const col of ["", "MIN", "MAX", "SIZE"]) {
      const th = document.createElement("th");
      th.textContent = col;
      hrow.appendChild(th);
    }

    const tbody        = table.createTBody();
    const sizeUpdaters = [];

    const axes = includeY
      ? [["X", "min_x", "max_x", "bounds"], ["Y", "min_y", "max_y", "coords"], ["Z", "min_z", "max_z", "bounds"]]
      : [["X", "min_x", "max_x", "bounds"], ["Z", "min_z", "max_z", "bounds"]];

    for (const [axis, minF, maxF, source] of axes) {
      const row   = tbody.insertRow();
      const axisC = row.insertCell(); axisC.className = "detail-axis"; axisC.textContent = axis;
      const minC  = row.insertCell(); minC.className  = "detail-val";
      const maxC  = row.insertCell(); maxC.className  = "detail-val";
      const sizeC = row.insertCell(); sizeC.className = "detail-size";

      const getVal = (key) => source === "bounds" ? node.bounds[key] : (node.coords?.[key] ?? 0);

      const refreshSize = () => {
        const sz = getVal(maxF) - getVal(minF);
        sizeC.textContent = Number.isInteger(sz) ? String(sz) : sz.toFixed(1);
      };
      refreshSize();
      sizeUpdaters.push(refreshSize);

      if (source === "bounds") {
        minC.appendChild(this.#makeBoundInput(minF, node, origBounds, sizeUpdaters));
        maxC.appendChild(this.#makeBoundInput(maxF, node, origBounds, sizeUpdaters));
      } else {
        // Y row for cuboid uses coord inputs (onCoordsChange/Save callbacks)
        const opts = { min: 0, max: 256, sizeUpdaters };
        minC.appendChild(this.#makeCoordInput(minF, node, origCoords, opts));
        maxC.appendChild(this.#makeCoordInput(maxF, node, origCoords, opts));
      }
    }

    return section;
  }

  #makeBoundInput(field, node, origBounds, sizeUpdaters) {
    const input = document.createElement("input");
    input.type      = "number";
    input.step      = "any";
    input.value     = node.bounds[field];
    input.className = "detail-bounds-input";

    const notify = () => {
      sizeUpdaters.forEach(fn => fn());
      if (this.#callbacks.onBoundsChange) this.#callbacks.onBoundsChange(node, node.bounds);
    };

    input.addEventListener("input", () => {
      const val = parseFloat(input.value);
      if (!isNaN(val)) { node.bounds[field] = val; notify(); }
    });

    input.addEventListener("blur", () => {
      const val = parseFloat(input.value);
      if (isNaN(val)) {
        input.value = node.bounds[field];
      } else {
        if (this.#callbacks.onBoundsSave) this.#callbacks.onBoundsSave(node, node.bounds);
      }
    });

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); input.blur(); }
      if (e.key === "Escape") {
        e.preventDefault();
        node.bounds[field] = origBounds[field];
        input.value = origBounds[field];
        notify();
      }
    });

    return input;
  }

  // ── geometry sections (non-rectangle/cuboid types) ────────────────────────

  #buildGeometry(node) {
    const schema     = GEOMETRY_SCHEMA[node.type];
    const origCoords = { ...node.coords };

    const section = document.createElement("div");
    section.className = "detail-section";

    for (const entry of schema) {
      if (entry.type === "group") {
        section.appendChild(this.#buildGroupEntry(entry, node, origCoords));
      } else if (entry.type === "scalar-pair") {
        section.appendChild(this.#buildScalarPairEntry(entry, node, origCoords));
      } else {
        section.appendChild(this.#buildScalarEntry(entry, node, origCoords));
      }
    }

    return section;
  }

  // Inline XYZ (or XZ) row: each field is a bordered box with axis prefix inside
  #buildGroupEntry(entry, node, origCoords) {
    const wrap = document.createElement("div");
    wrap.className = "detail-geo-group";

    const header = document.createElement("div");
    header.className = "detail-section-header";
    const labelEl = document.createElement("span");
    labelEl.className = "detail-section-label";
    labelEl.textContent = entry.label;
    header.appendChild(labelEl);
    if (entry.note) {
      const noteEl = document.createElement("span");
      noteEl.className = "detail-section-hint";
      noteEl.textContent = entry.note;
      header.appendChild(noteEl);
    }
    wrap.appendChild(header);

    const row = document.createElement("div");
    row.className = "detail-group-row";

    for (const axisEntry of entry.axes) {
      const field = document.createElement("div");
      field.className = "detail-prefixed-field";

      const prefix = document.createElement("span");
      prefix.className = "detail-prefix";
      prefix.textContent = axisEntry.axis;
      field.appendChild(prefix);

      if (axisEntry.key != null) {
        const input = this.#makeCoordInput(axisEntry.key, node, origCoords, {
          min: axisEntry.min, max: axisEntry.max,
        });
        field.appendChild(input);
      } else {
        const valEl = document.createElement("span");
        valEl.className = "detail-group-static";
        valEl.textContent = axisEntry.display(node);
        field.appendChild(valEl);
      }

      row.appendChild(field);
    }
    wrap.appendChild(row);
    return wrap;
  }

  // DIMENSIONS header + two prefixed fields (R/H) side by side
  #buildScalarPairEntry(entry, node, origCoords) {
    const wrap = document.createElement("div");
    wrap.className = "detail-geo-scalar-pair";

    wrap.appendChild(this.#sectionHeader("DIMENSIONS"));

    const row = document.createElement("div");
    row.className = "detail-pair-row";

    for (const scalar of entry.entries) {
      const field = document.createElement("div");
      field.className = "detail-prefixed-field";

      const prefix = document.createElement("span");
      prefix.className = "detail-prefix";
      prefix.textContent = scalar.label[0];
      field.appendChild(prefix);

      if (scalar.key != null) {
        const input = this.#makeCoordInput(scalar.key, node, origCoords, {
          min: scalar.min, max: scalar.max,
        });
        field.appendChild(input);
      } else {
        const valEl = document.createElement("span");
        valEl.className = "detail-group-static";
        valEl.textContent = scalar.display(node);
        field.appendChild(valEl);
      }

      row.appendChild(field);
    }

    wrap.appendChild(row);
    return wrap;
  }

  // Stacked: label above, full-width input below
  #buildScalarEntry(entry, node, origCoords) {
    const wrap = document.createElement("div");
    wrap.className = "detail-geo-scalar";

    const header = document.createElement("div");
    header.className = "detail-section-header";
    const labelEl = document.createElement("span");
    labelEl.className = "detail-section-label";
    labelEl.textContent = entry.label;
    header.appendChild(labelEl);
    if (entry.unit) {
      const unitEl = document.createElement("span");
      unitEl.className = "detail-section-hint";
      unitEl.textContent = entry.unit;
      header.appendChild(unitEl);
    }
    wrap.appendChild(header);

    if (entry.key != null) {
      const input = this.#makeCoordInput(entry.key, node, origCoords, {
        min: entry.min, max: entry.max,
      });
      input.classList.add("detail-scalar-input");
      wrap.appendChild(input);
    } else {
      const valEl = document.createElement("span");
      valEl.className = "detail-field-val";
      valEl.textContent = entry.display(node);
      wrap.appendChild(valEl);
    }

    return wrap;
  }

  // Shared coord input — handles both geometry-section fields and the Y row in the bounds table.
  // sizeUpdaters (optional): array of refresh fns to call when value changes (for table size column).
  #makeCoordInput(coordKey, node, origCoords, { min, max, sizeUpdaters } = {}) {
    const clamp = (v) => {
      if (min != null && v < min) return min;
      if (max != null && v > max) return max;
      return v;
    };

    const input = document.createElement("input");
    input.type      = "number";
    input.step      = "any";
    input.value     = node.coords[coordKey] ?? "";
    input.className = "detail-bounds-input";
    if (min != null) input.min = min;
    if (max != null) input.max = max;

    input.addEventListener("input", () => {
      let val = parseFloat(input.value);
      if (!isNaN(val)) {
        val = clamp(val);
        node.coords[coordKey] = val;
        sizeUpdaters?.forEach(fn => fn());
        this.updateXmlPreview(node);
        if (this.#callbacks.onCoordsChange) this.#callbacks.onCoordsChange(node, node.coords);
      }
    });

    input.addEventListener("blur", () => {
      let val = parseFloat(input.value);
      if (isNaN(val)) {
        input.value = node.coords[coordKey] ?? "";
      } else {
        val = clamp(val);
        input.value = val;
        node.coords[coordKey] = val;
        if (this.#callbacks.onCoordsSave) this.#callbacks.onCoordsSave(node, node.coords);
      }
    });

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); input.blur(); }
      if (e.key === "Escape") {
        e.preventDefault();
        node.coords[coordKey] = origCoords[coordKey];
        input.value = origCoords[coordKey] ?? "";
        sizeUpdaters?.forEach(fn => fn());
        this.updateXmlPreview(node);
        if (this.#callbacks.onCoordsChange) this.#callbacks.onCoordsChange(node, node.coords);
      }
    });

    return input;
  }

  // ── section header with optional right-side hint ──────────────────────────

  #sectionHeader(label, hint = null) {
    const header = document.createElement("div");
    header.className = "detail-section-header";
    const labelEl = document.createElement("span");
    labelEl.className = "detail-section-label";
    labelEl.textContent = label;
    header.appendChild(labelEl);
    if (hint) {
      const hintEl = document.createElement("span");
      hintEl.className = "detail-section-hint";
      hintEl.textContent = hint;
      header.appendChild(hintEl);
    }
    return header;
  }

  // ── misc ──────────────────────────────────────────────────────────────────

  #buildNote(text) {
    const el = document.createElement("div");
    el.className = "detail-empty";
    el.style.marginBottom = "10px";
    el.textContent = text;
    return el;
  }

  #buildChildren(children) {
    const section = document.createElement("div");
    section.className = "detail-section";

    const heading = document.createElement("div");
    heading.className = "detail-section-label";
    heading.textContent = `children (${children.length})`;
    section.appendChild(heading);

    for (const child of children) {
      const row = document.createElement("div");
      row.className = "detail-child-row";

      const nameEl = document.createElement("span");
      nameEl.className = "detail-child-name";
      nameEl.textContent = child.label;

      const typeEl = document.createElement("span");
      typeEl.className = "detail-child-type";
      typeEl.textContent = child.type ? child.type.charAt(0).toUpperCase() + child.type.slice(1) : "";

      const boundsEl = document.createElement("span");
      boundsEl.className = "detail-child-bounds";
      if (child.bounds) {
        const { min_x, min_z, max_x, max_z } = child.bounds;
        boundsEl.textContent = `${min_x},${min_z} → ${max_x},${max_z}`;
      } else {
        boundsEl.textContent = "—";
      }

      row.appendChild(typeIcon(child.type, child.synthetic_id, "detail-type-icon"));
      row.appendChild(nameEl);
      row.appendChild(typeEl);
      row.appendChild(boundsEl);
      section.appendChild(row);
    }
    return section;
  }

  #buildXmlPreview(node) {
    const section = document.createElement("div");
    section.className = "detail-section";

    const heading = document.createElement("div");
    heading.className = "detail-section-label";
    heading.textContent = "XML";
    section.appendChild(heading);

    const pre = document.createElement("pre");
    pre.className = "detail-xml-pre";
    pre.textContent = nodeToXml(node);
    section.appendChild(pre);

    this.#xmlCodeEl = pre;
    return section;
  }

  // Vertical field: label div above static value span
  #fieldRow(key, value) {
    const row = document.createElement("div");
    row.className = "detail-field-row";
    const keyEl = document.createElement("div");
    keyEl.className = "detail-field-key";
    keyEl.textContent = key.toUpperCase();
    const valEl = document.createElement("span");
    valEl.className = "detail-field-val";
    valEl.textContent = value;
    row.appendChild(keyEl);
    row.appendChild(valEl);
    return row;
  }
}
