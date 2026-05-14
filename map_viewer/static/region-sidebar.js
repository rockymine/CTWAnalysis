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

export class RegionSidebar {
  #listEl;
  #onSelect;
  #rowMap = new Map();  // id → rowEl

  /**
   * @param {HTMLElement} listEl
   * @param {object} [callbacks]
   * @param {function} [callbacks.onSelect]  Called with the node when a row is clicked.
   */
  constructor(listEl, { onSelect } = {}) {
    this.#listEl   = listEl;
    this.#onSelect = onSelect || null;
  }

  /** Rebuild the sidebar for a freshly loaded map. */
  build(groups) {
    this.#rowMap.clear();
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

    row.addEventListener("click", () => {
      if (this.#onSelect) this.#onSelect(node);
    });

    this.#rowMap.set(node.id, row);
    return row;
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
