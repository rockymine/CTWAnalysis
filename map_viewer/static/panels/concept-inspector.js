/**
 * ConceptInspector — right-panel detail view for a selected concept shape.
 *
 * Renders into a provided container element. Call show(shape) when a shape is
 * selected, update(shape) when it mutates (e.g. resize drag), and clear() when
 * the selection is removed.
 *
 * Reuses detail-* visual language from viewer.css / region-detail.js.
 */

import { polygonArea, visvalingamWhyatt } from "../simplify.js";

function licon(iconData, size = 14) {
  return lucide.createElement(iconData, { width: size, height: size, "stroke-width": "1.8" });
}

function fmt(v) {
  if (v == null) return "—";
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

const SHAPE_ICON  = { rectangle: lucide.RectangleHorizontal, circle: lucide.Circle, polygon: lucide.Pentagon };
const SHAPE_BADGE = { rectangle: "Rectangle", circle: "Circle", polygon: "Polygon" };

export class ConceptInspector {
  #el;
  #onSimplify;
  #currentId    = null;
  #currentShape = null;
  #tolerance    = 50;   // persists between selections

  constructor(el, { onSimplify } = {}) {
    this.#el         = el;
    this.#onSimplify = onSimplify ?? null;
    this.#renderEmpty();
  }

  show(shape) {
    this.#currentId    = shape.id;
    this.#currentShape = shape;
    this.#el.innerHTML = "";
    this.#el.appendChild(this.#buildHeader(shape));
    this.#el.appendChild(this.#buildOperationSection(shape));
    this.#el.appendChild(this.#buildGeometrySection(shape));
    if (shape.source === "lasso" && shape.type === "polygon") {
      this.#el.appendChild(this.#buildSimplifySection(shape));
    }
  }

  update(shape) {
    if (shape.id === this.#currentId) this.show(shape);
  }

  clear() {
    this.#currentId = null;
    this.#el.innerHTML = "";
    this.#renderEmpty();
  }

  // ── private ────────────────────────────────────────────────────────────────

  #renderEmpty() {
    const el = document.createElement("div");
    el.className = "detail-empty";
    el.textContent = "Select a shape to inspect.";
    this.#el.appendChild(el);
  }

  #buildHeader(shape) {
    const row = document.createElement("div");
    row.className = "detail-header";

    const iconWrap = document.createElement("div");
    iconWrap.className = "detail-type-icon";
    iconWrap.appendChild(licon(SHAPE_ICON[shape.type] ?? lucide.HelpCircle));
    row.appendChild(iconWrap);

    const label = document.createElement("span");
    label.className = "detail-label";
    label.textContent = shape.id;
    row.appendChild(label);

    const badge = document.createElement("span");
    badge.className = "detail-type-badge";
    badge.textContent = SHAPE_BADGE[shape.type] ?? shape.type;
    row.appendChild(badge);

    return row;
  }

  #buildOperationSection(shape) {
    const isAdd = shape.operation !== "subtract";
    const section = document.createElement("div");
    section.className = "detail-section";
    section.appendChild(this.#sectionHeader("OPERATION"));

    const badge = document.createElement("span");
    badge.className = `concept-op-badge concept-op-badge--${isAdd ? "add" : "sub"}`;
    badge.style.cssText = "font-size:11px; padding:2px 8px;";
    badge.textContent = isAdd ? "Add" : "Subtract";
    section.appendChild(badge);

    return section;
  }

  #buildGeometrySection(shape) {
    const section = document.createElement("div");
    section.className = "detail-section";
    section.appendChild(this.#sectionHeader("GEOMETRY"));

    if (shape.type === "rectangle") section.appendChild(this.#buildRectGeometry(shape));
    else if (shape.type === "circle")    section.appendChild(this.#buildCircleGeometry(shape));
    else if (shape.type === "polygon")   section.appendChild(this.#buildPolygonGeometry(shape));

    return section;
  }

  // ── geometry renderers ────────────────────────────────────────────────────

  #buildRectGeometry(shape) {
    const wrap = document.createElement("div");

    // Bounding box table
    const table = document.createElement("table");
    table.className = "detail-table";

    const thead = table.createTHead();
    const hrow  = thead.insertRow();
    for (const col of ["", "MIN", "MAX", "SIZE"]) {
      const th = document.createElement("th");
      th.textContent = col;
      hrow.appendChild(th);
    }

    const tbody = table.createTBody();
    for (const [axis, minF, maxF] of [["X", "min_x", "max_x"], ["Z", "min_z", "max_z"]]) {
      const row   = tbody.insertRow();
      const axisC = row.insertCell(); axisC.className = "detail-axis"; axisC.textContent = axis;
      const minC  = row.insertCell(); minC.className  = "detail-val";  minC.textContent  = fmt(shape[minF]);
      const maxC  = row.insertCell(); maxC.className  = "detail-val";  maxC.textContent  = fmt(shape[maxF]);
      const sizeC = row.insertCell(); sizeC.className = "detail-size"; sizeC.textContent = fmt(shape[maxF] - shape[minF]);
    }
    wrap.appendChild(table);
    return wrap;
  }

  #buildCircleGeometry(shape) {
    const wrap = document.createElement("div");
    wrap.appendChild(this.#buildXZGroup("CENTER", shape.center_x, shape.center_z));

    const radiusSection = document.createElement("div");
    radiusSection.className = "detail-geo-scalar";
    radiusSection.style.marginTop = "10px";
    radiusSection.appendChild(this.#sectionHeader("RADIUS", "blocks"));
    const val = document.createElement("span");
    val.className = "field-value";
    val.textContent = fmt(shape.radius);
    radiusSection.appendChild(val);
    wrap.appendChild(radiusSection);

    return wrap;
  }

  #buildPolygonGeometry(shape) {
    const wrap  = document.createElement("div");
    const verts = shape.vertices ?? [];

    wrap.appendChild(this.#sectionHeader("VERTICES", `${verts.length}`));

    const scroll = document.createElement("div");
    scroll.className = "concept-vertex-scroll";

    const table = document.createElement("table");
    table.className = "detail-table concept-vertex-table";

    const thead = table.createTHead();
    const hrow  = thead.insertRow();
    for (const col of ["#", "X", "Z"]) {
      const th = document.createElement("th");
      th.textContent = col;
      hrow.appendChild(th);
    }

    const tbody = table.createTBody();
    verts.forEach(([x, z], i) => {
      const row  = tbody.insertRow();
      const idxC = row.insertCell(); idxC.className = "detail-axis";  idxC.textContent = i + 1;
      const xC   = row.insertCell(); xC.className   = "detail-val";   xC.textContent   = fmt(x);
      const zC   = row.insertCell(); zC.className   = "detail-val";   zC.textContent   = fmt(z);
    });

    scroll.appendChild(table);
    wrap.appendChild(scroll);
    return wrap;
  }

  // ── Visvalingam–Whyatt simplify section ───────────────────────────────────

  #buildSimplifySection(shape) {
    const section = document.createElement("div");
    section.className = "detail-section";
    section.appendChild(this.#sectionHeader("SIMPLIFY"));

    const area = polygonArea(shape.vertices ?? []);

    // Area row
    const areaRow = document.createElement("div");
    areaRow.className = "concept-simplify-row";
    const areaLabel = document.createElement("span");
    areaLabel.className = "concept-simplify-label";
    areaLabel.textContent = "Area";
    const areaVal = document.createElement("span");
    areaVal.className = "concept-simplify-value";
    areaVal.textContent = `${Math.round(area).toLocaleString()} blk²`;
    areaRow.appendChild(areaLabel);
    areaRow.appendChild(areaVal);
    section.appendChild(areaRow);

    // Tolerance row
    const tolRow = document.createElement("div");
    tolRow.className = "concept-simplify-row";
    const tolLabel = document.createElement("span");
    tolLabel.className = "concept-simplify-label";
    tolLabel.textContent = "Tolerance";
    const tolWrap = document.createElement("div");
    tolWrap.className = "concept-simplify-input-wrap";
    const tolInput = document.createElement("input");
    tolInput.type      = "number";
    tolInput.min       = "1";
    tolInput.step      = "10";
    tolInput.value     = this.#tolerance;
    tolInput.className = "detail-bounds-input concept-simplify-input";
    const tolUnit = document.createElement("span");
    tolUnit.className   = "concept-simplify-unit";
    tolUnit.textContent = "blk²";
    tolInput.addEventListener("input", () => {
      const v = parseFloat(tolInput.value);
      if (!isNaN(v) && v > 0) this.#tolerance = v;
    });
    tolWrap.appendChild(tolInput);
    tolWrap.appendChild(tolUnit);
    tolRow.appendChild(tolLabel);
    tolRow.appendChild(tolWrap);
    section.appendChild(tolRow);

    // Generalize button
    const btn = document.createElement("button");
    btn.className   = "action-btn concept-simplify-btn";
    btn.textContent = "Generalize";
    btn.addEventListener("click", () => {
      const tol = parseFloat(tolInput.value);
      if (isNaN(tol) || tol <= 0 || !this.#onSimplify || !this.#currentShape) return;
      this.#tolerance = tol;
      this.#onSimplify(this.#currentShape, tol);
    });
    section.appendChild(btn);

    return section;
  }

  // ── shared builders ───────────────────────────────────────────────────────

  #buildXZGroup(label, x, z, hint = null) {
    const wrap = document.createElement("div");
    wrap.className = "detail-geo-group";
    wrap.appendChild(this.#sectionHeader(label, hint));

    const row = document.createElement("div");
    row.className = "detail-group-row";
    for (const [axis, val] of [["X", x], ["Z", z]]) {
      const field  = document.createElement("div");
      field.className = "detail-prefixed-field";
      const prefix = document.createElement("span");
      prefix.className = "detail-prefix";
      prefix.textContent = axis;
      const valEl  = document.createElement("span");
      valEl.className = "detail-group-static";
      valEl.textContent = fmt(val);
      field.appendChild(prefix);
      field.appendChild(valEl);
      row.appendChild(field);
    }
    wrap.appendChild(row);
    return wrap;
  }

  #sectionHeader(label, hint = null) {
    const el = document.createElement("div");
    el.className = "detail-section-header";
    const title = document.createElement("span");
    title.className = "section-title";
    title.textContent = label;
    el.appendChild(title);
    if (hint) {
      const hintEl = document.createElement("span");
      hintEl.className = "detail-section-hint";
      hintEl.textContent = hint;
      el.appendChild(hintEl);
    }
    return el;
  }
}
