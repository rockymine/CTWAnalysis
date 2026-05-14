/**
 * RegionDetail — owns the inspector panel below the sidebar tree.
 *
 * Shows all fields of the selected region node: id, type, flags, bounds,
 * and children list. Each coordinate row is a plain <span> for now; they
 * will become <input> elements when the editor is wired up.
 */

export class RegionDetail {
  #el;

  /** @param {HTMLElement} el  The #region-detail container. */
  constructor(el) {
    this.#el = el;
    this.#renderEmpty();
  }

  /** Show details for the given encoded region node. */
  show(node) {
    this.#el.innerHTML = "";
    this.#el.appendChild(this.#buildHeader(node));
    this.#el.appendChild(this.#buildFields(node));
    if (node.bounds) this.#el.appendChild(this.#buildBounds(node.bounds));
    if ((node.children || []).length > 0) this.#el.appendChild(this.#buildChildren(node.children));
  }

  /** Reset to the idle placeholder. */
  clear() {
    this.#el.innerHTML = "";
    this.#renderEmpty();
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

    const dot = document.createElement("div");
    dot.className = "detail-dot";
    dot.style.cssText = node.synthetic_id
      ? `background:transparent; border:1px dashed ${node.color};`
      : `background:${node.color};`;

    const label = document.createElement("span");
    label.className = "detail-label";
    label.textContent = node.label;

    const badge = document.createElement("span");
    badge.className = "detail-type-badge";
    badge.textContent = node.type;

    row.appendChild(dot);
    row.appendChild(label);
    row.appendChild(badge);
    return row;
  }

  #buildFields(node) {
    const section = document.createElement("div");
    section.className = "detail-section";

    const rows = [
      ["id", node.id],
      ["label", node.label !== node.id ? node.label : null],
      ["synthetic", node.synthetic_id ? "yes" : null],
      ["negative", node.is_negative ? "yes" : null],
    ].filter(([, v]) => v !== null);

    for (const [key, val] of rows) {
      section.appendChild(this.#fieldRow(key, val));
    }
    return section;
  }

  #buildBounds(bounds) {
    const section = document.createElement("div");
    section.className = "detail-section";

    const heading = document.createElement("div");
    heading.className = "detail-section-label";
    heading.textContent = "bounds";
    section.appendChild(heading);

    const table = document.createElement("table");
    table.className = "detail-table";

    const thead = table.createTHead();
    const hr = thead.insertRow();
    for (const text of ["", "min", "max", "size"]) {
      const th = document.createElement("th");
      th.textContent = text;
      hr.appendChild(th);
    }

    const tbody = table.createTBody();
    for (const [axis, minVal, maxVal] of [
      ["X", bounds.min_x, bounds.max_x],
      ["Z", bounds.min_z, bounds.max_z],
    ]) {
      const size = +(maxVal - minVal).toFixed(4);
      const tr = tbody.insertRow();
      const axisCell = tr.insertCell(); axisCell.className = "detail-axis"; axisCell.textContent = axis;
      const minCell  = tr.insertCell(); minCell.className  = "detail-val";  minCell.textContent  = minVal;
      const maxCell  = tr.insertCell(); maxCell.className  = "detail-val";  maxCell.textContent  = maxVal;
      const sizeCell = tr.insertCell(); sizeCell.className = "detail-size"; sizeCell.textContent = size;
    }

    section.appendChild(table);
    return section;
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

      const dot = document.createElement("span");
      dot.className = "detail-child-dot";
      dot.style.cssText = child.synthetic_id
        ? `background:transparent; border:1px dashed ${child.color};`
        : `background:${child.color};`;

      const nameEl = document.createElement("span");
      nameEl.className = "detail-child-name";
      nameEl.textContent = child.label;

      const typeEl = document.createElement("span");
      typeEl.className = "detail-child-type";
      typeEl.textContent = child.type;

      const boundsEl = document.createElement("span");
      boundsEl.className = "detail-child-bounds";
      if (child.bounds) {
        const { min_x, min_z, max_x, max_z } = child.bounds;
        boundsEl.textContent = `${min_x},${min_z} → ${max_x},${max_z}`;
      } else {
        boundsEl.textContent = "—";
      }

      row.appendChild(dot);
      row.appendChild(nameEl);
      row.appendChild(typeEl);
      row.appendChild(boundsEl);
      section.appendChild(row);
    }

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
