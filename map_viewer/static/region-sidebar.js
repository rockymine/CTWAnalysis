/**
 * RegionSidebar — owns the sidebar DOM tree.
 *
 * Renders the category headers and per-region rows. All layout/size styles
 * live in viewer.css (classes); only data-driven colours are set inline.
 * Delegates all checkbox cascade logic to RegionRegistry.
 */

const TYPE_CLASS = {
  union: "type-union", negative: "type-negative", intersect: "type-intersect",
};
const CAT_COLORS = {
  spawn: "#60a5fa", wool: "#f1c40f", monument: "#a78bfa",
  build: "#34d399", other: "#94a3b8",
};

export class RegionSidebar {
  #listEl;
  #registry;
  #onSelect;
  #selectedRowEl = null;

  /**
   * @param {HTMLElement} listEl      The #region-list container.
   * @param {RegionRegistry} registry Shared registry for cascade + visibility.
   * @param {object} [callbacks]
   * @param {function} [callbacks.onSelect]  Called with the node when a row is clicked.
   */
  constructor(listEl, registry, { onSelect } = {}) {
    this.#listEl    = listEl;
    this.#registry  = registry;
    this.#onSelect  = onSelect || null;
  }

  /** Rebuild the sidebar for a freshly loaded map. */
  build(groups) {
    this.#selectedRowEl = null;
    this.#listEl.innerHTML = "";

    const hasRegions = groups.some(g => g.regions.length > 0);
    if (!hasRegions) {
      this.#listEl.innerHTML = '<div id="empty-msg">No named regions found</div>';
      return;
    }

    // Register all nodes in the registry before building DOM
    // (registry needs the full tree before checkboxes are attached)
    for (const group of groups) {
      for (const root of group.regions) this.#registry.register(root, null);
    }

    for (const group of groups) {
      this.#listEl.appendChild(this.#categoryHeader(group));
      this.#appendTree(group.regions, this.#listEl, 0, []);
    }
  }

  // ── private DOM builders ────────────────────────────────────────────────

  #categoryHeader(group) {
    const color = CAT_COLORS[group.name] || "#64748b";
    const el = document.createElement("div");
    el.className = "cat-header";
    el.style.color = color;

    const line = document.createElement("div");
    line.className = "cat-header-line";
    line.style.background = color;

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
    const cb = this.#checkbox(node);
    row.appendChild(cb.wrap);
    row.appendChild(this.#dot(node.color, node.synthetic_id));
    row.appendChild(this.#label(node));
    row.appendChild(this.#typeBadge(node.type));

    row.addEventListener("click", (e) => {
      // Any click within the checkbox wrapper is for visibility only — not selection.
      if (cb.wrap.contains(e.target)) return;
      if (this.#selectedRowEl && this.#selectedRowEl !== row)
        this.#selectedRowEl.classList.remove("region-row--selected");
      this.#selectedRowEl = row;
      row.classList.add("region-row--selected");
      if (this.#onSelect) this.#onSelect(node);
    });
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

  #checkbox(node) {
    const wrap = document.createElement("div");
    wrap.className = "checkbox-wrap";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = false;
    input.addEventListener("change", () => {
      this.#registry.setVisible(node.id, input.checked);
    });
    this.#registry.attachCheckbox(node.id, input);
    wrap.appendChild(input);
    return { wrap, input };
  }

  #dot(color, isSynthetic) {
    const el = document.createElement("div");
    el.className = isSynthetic ? "region-dot region-dot--synthetic" : "region-dot";
    if (isSynthetic) {
      el.style.borderColor = color;
    } else {
      el.style.background = color;
    }
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
