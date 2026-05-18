import { typeIcon } from "./region-types.js";

/**
 * RegionDetail — owns the inspector panel.
 *
 * Shows all fields of the selected region node. Bound values are editable
 * inputs for named regions; synthetic regions are read-only.
 *
 * Callbacks injected at construction:
 *   onBoundsChange(node, bounds)  — fired on every keystroke for live canvas preview
 *   onBoundsSave(node, bounds)    — fired on blur / Enter to persist to server
 */

/**
 * Reconstruct the XML element for a region node.
 * 2D coordinate fields come from node.bounds (kept in sync with edits).
 * Type-specific non-2D fields (y, radius, height) come from node.coords.
 */
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

export class RegionDetail {
  #el;
  #callbacks;
  #xmlCodeEl    = null;
  #headerLabelEl = null;

  constructor(el, callbacks = {}) {
    this.#el        = el;
    this.#callbacks = callbacks;
    this.#renderEmpty();
  }

  // Composite region types carry no own coordinates — their bounds are
  // purely derived from children and have no XML representation.
  static #COMPOSITE_TYPES = new Set(["union", "negative", "intersect", "complement"]);

  show(node) {
    this.#el.innerHTML = "";
    this.#xmlCodeEl     = null;
    this.#headerLabelEl = null;
    this.#el.appendChild(this.#buildHeader(node));
    this.#el.appendChild(this.#buildFields(node));
    const isComposite = RegionDetail.#COMPOSITE_TYPES.has(node.type);
    if (node.bounds && !isComposite) this.#el.appendChild(this.#buildBounds(node));
    if ((node.children || []).length > 0) this.#el.appendChild(this.#buildChildren(node.children));
    this.#el.appendChild(this.#buildXmlPreview(node));
  }

  clear() {
    this.#el.innerHTML = "";
    this.#xmlCodeEl     = null;
    this.#headerLabelEl = null;
    this.#renderEmpty();
  }

  /** Refresh XML preview after bounds have been edited live. */
  updateXmlPreview(node) {
    if (this.#xmlCodeEl) this.#xmlCodeEl.textContent = nodeToXml(node);
  }

  // ── private ─────────────────────────────────────────────────────────────

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

    // id row: editable for named regions, static for synthetic ones
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

  #makeIdRow(node) {
    const row = document.createElement("div");
    row.className = "detail-field-row";

    const keyEl = document.createElement("span");
    keyEl.className = "detail-field-key";
    keyEl.textContent = "id";

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

    row.appendChild(keyEl);
    row.appendChild(input);
    return row;
  }

  #buildBounds(node) {
    // Snapshot the bounds at show-time so Escape can revert correctly.
    const origBounds = { ...node.bounds };
    const editable   = true;

    const section = document.createElement("div");
    section.className = "detail-section";

    const heading = document.createElement("div");
    heading.className = "detail-section-label";
    heading.textContent = editable ? "bounds  (enter to save · esc to revert)" : "bounds";
    section.appendChild(heading);

    const table = document.createElement("table");
    table.className = "detail-table";
    section.appendChild(table);

    const thead = table.createTHead();
    const hrow  = thead.insertRow();
    for (const col of ["", "min", "max", "size"]) {
      const th = document.createElement("th");
      th.textContent = col;
      hrow.appendChild(th);
    }

    const tbody        = table.createTBody();
    const sizeUpdaters = [];

    for (const [axis, minF, maxF] of [["X", "min_x", "max_x"], ["Z", "min_z", "max_z"]]) {
      const row   = tbody.insertRow();
      const axisC = row.insertCell(); axisC.className = "detail-axis"; axisC.textContent = axis;
      const minC  = row.insertCell(); minC.className  = "detail-val";
      const maxC  = row.insertCell(); maxC.className  = "detail-val";
      const sizeC = row.insertCell(); sizeC.className = "detail-size";

      const refreshSize = () => {
        const sz = node.bounds[maxF] - node.bounds[minF];
        sizeC.textContent = Number.isInteger(sz) ? String(sz) : sz.toFixed(1);
      };
      refreshSize();
      sizeUpdaters.push(refreshSize);

      if (editable) {
        minC.appendChild(this.#makeBoundInput(minF, node, origBounds, sizeUpdaters));
        maxC.appendChild(this.#makeBoundInput(maxF, node, origBounds, sizeUpdaters));
      } else {
        minC.appendChild(this.#staticVal(node.bounds[minF]));
        maxC.appendChild(this.#staticVal(node.bounds[maxF]));
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
        // Revert invalid text to last valid bound value
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

  #staticVal(value) {
    const el = document.createElement("span");
    el.className = "detail-val";
    el.textContent = value;
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
    heading.textContent = "xml";
    section.appendChild(heading);

    const pre = document.createElement("pre");
    pre.className = "detail-xml-pre";
    pre.textContent = nodeToXml(node);
    section.appendChild(pre);

    this.#xmlCodeEl = pre;
    return section;
  }

  #fieldRow(key, value) {
    const row = document.createElement("div");
    row.className = "detail-field-row";
    const keyEl = document.createElement("span");
    keyEl.className = "detail-field-key";
    keyEl.textContent = key;
    const valEl = document.createElement("span");
    valEl.className = "detail-field-val";
    valEl.textContent = value;
    row.appendChild(keyEl);
    row.appendChild(valEl);
    return row;
  }
}
