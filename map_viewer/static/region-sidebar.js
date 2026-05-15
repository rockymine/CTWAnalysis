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

function icon(iconData, size = 14) {
  return lucide.createElement(iconData, { width: size, height: size, "stroke-width": "1.5" });
}

export class RegionSidebar {
  #listEl;
  #onSelect;
  #onVisibilityToggle;
  #rowMap       = new Map();   // id → rowEl
  #hiddenIds    = new Set();   // ids the user has hidden
  #collapsedIds = new Set();   // ids whose children are collapsed in the sidebar
  #parentMap    = new Map();   // id → parentId (null for roots)

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
    this.#collapsedIds.clear();
    this.#parentMap.clear();
    this.#listEl.innerHTML = "";

    const hasRegions = groups.some(g => g.regions.length > 0);
    if (!hasRegions) {
      this.#listEl.innerHTML = '<div id="empty-msg">No named regions found</div>';
      return;
    }

    for (const group of groups) {
      this.#listEl.appendChild(this.#categoryHeader(group));
      this.#appendTree(group.regions, this.#listEl, 0, [], null);
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
      btn.replaceChildren(icon(hidden ? lucide.EyeOff : lucide.Eye));
      btn.classList.toggle("vis-btn--hidden", hidden);
    }
  }

  /** Remove a region's row from the sidebar (called on delete). */
  removeRow(id) {
    const row = this.#rowMap.get(id);
    if (row?.parentNode) row.parentNode.removeChild(row);
    this.#rowMap.delete(id);
    this.#hiddenIds.delete(id);
    this.#collapsedIds.delete(id);
    this.#parentMap.delete(id);
  }

  /** Highlight rows that are part of the pending multi-select group (green tint). */
  setMultiSelected(ids) {
    const multiSet = new Set(ids);
    for (const [id, rowEl] of this.#rowMap) {
      rowEl.classList.toggle("region-row--multi", multiSet.has(id));
    }
  }

  /** Append a single new node row at the end of the list (for freshly-created regions). */
  appendRow(node) {
    // Remove the "no regions" placeholder if present
    const empty = this.#listEl.querySelector("#empty-msg");
    if (empty) empty.remove();
    this.#parentMap.set(node.id, null);
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
    if (this.#collapsedIds.has(oldId)) {
      this.#collapsedIds.delete(oldId);
      this.#collapsedIds.add(newId);
    }
    // Update parentMap: rename key and any values that reference oldId
    const parent = this.#parentMap.get(oldId);
    this.#parentMap.delete(oldId);
    this.#parentMap.set(newId, parent);
    for (const [childId, parentId] of this.#parentMap) {
      if (parentId === oldId) this.#parentMap.set(childId, newId);
    }
    const visBtn = row.querySelector(".vis-btn");
    if (visBtn) visBtn.dataset.regionId = newId;
    const chevron = row.querySelector(".collapse-btn");
    if (chevron) chevron.dataset.regionId = newId;
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

  #appendTree(nodes, container, depth, isLast, parentId) {
    for (let i = 0; i < nodes.length; i++) {
      const node = nodes[i];
      const isLastChild = i === nodes.length - 1;
      this.#parentMap.set(node.id, parentId);
      container.appendChild(this.#regionRow(node, depth, isLast, isLastChild));
      if ((node.children || []).length > 0) {
        this.#appendTree(node.children, container, depth + 1, [...isLast, isLastChild], node.id);
      }
    }
  }

  #regionRow(node, depth, isLast, isLastChild) {
    const row = document.createElement("div");
    row.className = "region-row";
    row.dataset.regionId = node.id;

    row.appendChild(this.#treeIndent(depth, isLast, isLastChild));
    row.appendChild(this.#chevronBtn(node));
    row.appendChild(this.#dot(node.color, node.synthetic_id));
    row.appendChild(this.#label(node));
    row.appendChild(this.#typeBadge(node.type));
    row.appendChild(this.#visBtn(node.id));

    row.addEventListener("click", (e) => {
      if (this.#onSelect) this.#onSelect(node, e.ctrlKey);
    });

    this.#rowMap.set(node.id, row);
    return row;
  }

  #chevronBtn(node) {
    const btn = document.createElement("button");
    btn.className = "collapse-btn";
    btn.dataset.regionId = node.id;
    if (!(node.children?.length > 0)) {
      btn.style.visibility = "hidden";
      btn.appendChild(icon(lucide.ChevronDown, 12));
      return btn;
    }
    btn.appendChild(icon(this.#collapsedIds.has(node.id) ? lucide.ChevronRight : lucide.ChevronDown, 12));
    btn.title = "Collapse/expand";
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (this.#collapsedIds.has(node.id)) {
        this.#collapsedIds.delete(node.id);
        btn.replaceChildren(icon(lucide.ChevronDown, 12));
      } else {
        this.#collapsedIds.add(node.id);
        btn.replaceChildren(icon(lucide.ChevronRight, 12));
      }
      this.#refreshTreeVisibility();
    });
    return btn;
  }

  #visBtn(id) {
    const btn = document.createElement("button");
    btn.className        = "vis-btn";
    btn.dataset.regionId = id;
    btn.appendChild(icon(lucide.Eye));
    btn.title            = "Toggle visibility";
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const nowHidden = !this.#hiddenIds.has(id);
      if (nowHidden) this.#hiddenIds.add(id);
      else           this.#hiddenIds.delete(id);
      btn.replaceChildren(icon(nowHidden ? lucide.EyeOff : lucide.Eye));
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

  // ── collapse helpers ────────────────────────────────────────────────────

  /** Returns true if every ancestor of id is expanded. */
  #isRowVisible(id) {
    let current = this.#parentMap.get(id);
    while (current !== undefined && current !== null) {
      if (this.#collapsedIds.has(current)) return false;
      current = this.#parentMap.get(current);
    }
    return true;
  }

  /** Sync display:none/'' on every row based on collapsed ancestor state. */
  #refreshTreeVisibility() {
    for (const [id, rowEl] of this.#rowMap) {
      rowEl.style.display = this.#isRowVisible(id) ? "" : "none";
    }
  }
}
