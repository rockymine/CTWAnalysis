/**
 * RegionSidebar — owns the layers panel DOM tree.
 *
 * Renders category headers and per-region rows. No checkboxes; visibility
 * is driven entirely by selection. All layout/size styles live in viewer.css;
 * only data-driven colours are set inline.
 */

const TYPE_CLASS = {
  union: "type-union", negative: "type-negative", intersect: "type-intersect",
};
const CAT_COLOR = "#4a5568";

const EYE_OPEN   = `<svg width="14" height="9" viewBox="0 0 14 9" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M1 4.5C1 4.5 3 1 7 1s6 3.5 6 3.5S11 8 7 8 1 4.5 1 4.5z"/><circle cx="7" cy="4.5" r="1.5"/></svg>`;
const EYE_CLOSED = `<svg width="14" height="9" viewBox="0 0 14 9" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M1 2.5C3 5.5 5 7 7 7s4-1.5 6-4.5"/><line x1="4" y1="6.5" x2="3.5" y2="8.5"/><line x1="7" y1="7" x2="7" y2="9"/><line x1="10" y1="6.5" x2="10.5" y2="8.5"/></svg>`;

export class RegionSidebar {
  #listEl;
  #onSelect;
  #onVisibilityToggle;
  #rowMap    = new Map();   // id → rowEl
  #hiddenIds = new Set();   // ids the user has hidden

  /**
   * @param {HTMLElement} listEl
   * @param {object} [callbacks]
   * @param {function} [callbacks.onSelect]             Called with the node when a row is clicked.
   * @param {function} [callbacks.onVisibilityToggle]   Called with (id, hidden: boolean).
   */
  constructor(listEl, { onSelect, onVisibilityToggle } = {}) {
    this.#listEl              = listEl;
    this.#onSelect            = onSelect || null;
    this.#onVisibilityToggle  = onVisibilityToggle || null;
  }

  /** Rebuild the sidebar for a freshly loaded map. */
  build(groups) {
    this.#rowMap.clear();
    this.#hiddenIds.clear();
    this.#listEl.innerHTML = "";

    const hasRegions = groups.some(g => g.regions.length > 0);
    if (!hasRegions) {
      this.#listEl.innerHTML = '<div id="empty-msg">No named regions found</div>';
      return;
    }

    for (const group of groups) {
      this.#listEl.appendChild(this.#categoryHeader(group));
      this.#appendTree(group.regions, this.#listEl, 0, []);
    }
  }

  /**
   * Highlight the primary row in full blue and descendant rows in a lighter
   * tint. Passing null clears all highlights.
   *
   * @param {string|null} primaryId  The directly-selected node id.
   * @param {string[]}    allIds     All selected ids (primary + descendants).
   */
  setSelected(primaryId, allIds = []) {
    const descendantSet = new Set(allIds);
    for (const [id, rowEl] of this.#rowMap) {
      rowEl.classList.toggle("region-row--selected",       id === primaryId);
      rowEl.classList.toggle("region-row--selected-child", id !== primaryId && descendantSet.has(id));
    }
    if (primaryId) {
      const row = this.#rowMap.get(primaryId);
      if (row) row.scrollIntoView({ block: "nearest" });
    }
  }

  /** Programmatically set a region's hidden state (updates the eye icon). */
  setHidden(id, hidden) {
    if (hidden) this.#hiddenIds.add(id);
    else        this.#hiddenIds.delete(id);
    const row = this.#rowMap.get(id);
    if (!row) return;
    const btn = row.querySelector(".vis-btn");
    if (btn) {
      btn.innerHTML = hidden ? EYE_CLOSED : EYE_OPEN;
      btn.classList.toggle("vis-btn--hidden", hidden);
    }
  }

  /** Append a single new node row at the end of the list (for freshly-created regions). */
  appendRow(node) {
    // Remove the "no regions" placeholder if present
    const empty = this.#listEl.querySelector("#empty-msg");
    if (empty) empty.remove();
    this.#listEl.appendChild(this.#regionRow(node, 0, [], true));
  }

  /** Update the sidebar row when a region is renamed. */
  renameNode(oldId, newId) {
    const row = this.#rowMap.get(oldId);
    if (!row) return;
    this.#rowMap.delete(oldId);
    this.#rowMap.set(newId, row);
    row.dataset.regionId = newId;
    const labelEl = row.querySelector(".region-label");
    if (labelEl) { labelEl.textContent = newId; labelEl.title = newId; }
    if (this.#hiddenIds.has(oldId)) {
      this.#hiddenIds.delete(oldId);
      this.#hiddenIds.add(newId);
    }
    const btn = row.querySelector(".vis-btn");
    if (btn) btn.dataset.regionId = newId;
  }

  // ── private DOM builders ────────────────────────────────────────────────

  #categoryHeader(group) {
    const el = document.createElement("div");
    el.className = "cat-header";
    el.style.color = CAT_COLOR;
    const line = document.createElement("div");
    line.className = "cat-header-line";
    line.style.background = CAT_COLOR;
    el.appendChild(document.createTextNode(group.label));
    el.appendChild(line);
    return el;
  }

  #appendTree(nodes, container, depth, isLast) {
    for (let i = 0; i < nodes.length; i++) {
      const node = nodes[i];
      const isLastChild = i === nodes.length - 1;
      container.appendChild(this.#regionRow(node, depth, isLast, isLastChild));
      if ((node.children || []).length > 0) {
        this.#appendTree(node.children, container, depth + 1, [...isLast, isLastChild]);
      }
    }
  }

  #regionRow(node, depth, isLast, isLastChild) {
    const row = document.createElement("div");
    row.className = "region-row";
    row.dataset.regionId = node.id;

    row.appendChild(this.#treeIndent(depth, isLast, isLastChild));
    row.appendChild(this.#dot(node.color, node.synthetic_id));
    row.appendChild(this.#label(node));
    row.appendChild(this.#typeBadge(node.type));
    row.appendChild(this.#visBtn(node.id));

    row.addEventListener("click", () => {
      if (this.#onSelect) this.#onSelect(node);
    });

    this.#rowMap.set(node.id, row);
    return row;
  }

  #visBtn(id) {
    const btn = document.createElement("button");
    btn.className        = "vis-btn";
    btn.dataset.regionId = id;
    btn.innerHTML        = EYE_OPEN;
    btn.title            = "Toggle visibility";
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const nowHidden = !this.#hiddenIds.has(id);
      if (nowHidden) this.#hiddenIds.add(id);
      else           this.#hiddenIds.delete(id);
      btn.innerHTML = nowHidden ? EYE_CLOSED : EYE_OPEN;
      btn.classList.toggle("vis-btn--hidden", nowHidden);
      if (this.#onVisibilityToggle) this.#onVisibilityToggle(id, nowHidden);
    });
    return btn;
  }

  #treeIndent(depth, isLast, isLastChild) {
    const wrap = document.createElement("div");
    wrap.className = "region-indent";
    for (let d = 0; d < depth; d++) {
      const pipe = document.createElement("span");
      pipe.className = "indent-pipe";
      pipe.style.borderColor = isLast[d] ? "transparent" : "#2d4263";
      wrap.appendChild(pipe);
    }
    if (depth > 0) {
      const elbow = document.createElement("span");
      elbow.className = "indent-elbow";
      elbow.textContent = isLastChild ? "└" : "├";
      wrap.appendChild(elbow);
    }
    return wrap;
  }

  #dot(color, isSynthetic) {
    const el = document.createElement("div");
    el.className = isSynthetic ? "region-dot region-dot--synthetic" : "region-dot";
    if (isSynthetic) { el.style.borderColor = color; }
    else             { el.style.background  = color; }
    return el;
  }

  #label(node) {
    const el = document.createElement("span");
    el.className = node.synthetic_id
      ? "region-label region-label--synthetic"
      : "region-label";
    el.textContent = node.label;
    el.title = node.synthetic_id ? `${node.label}  (id: ${node.id})` : node.label;
    return el;
  }

  #typeBadge(type) {
    const el = document.createElement("span");
    el.className = "region-type-badge";
    const typeClass = TYPE_CLASS[type];
    if (typeClass) el.classList.add(typeClass);
    el.textContent = type;
    return el;
  }
}
