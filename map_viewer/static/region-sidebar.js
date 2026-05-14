/**
 * RegionSidebar — owns the sidebar DOM tree.
 *
 * Renders the category headers and per-region rows. Delegates all checkbox
 * cascade logic to RegionRegistry. Designed to grow a coordinate detail
 * panel below the tree for the editor.
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

  /**
   * @param {HTMLElement} listEl      The #region-list container.
   * @param {RegionRegistry} registry Shared registry for cascade + visibility.
   */
  constructor(listEl, registry) {
    this.#listEl    = listEl;
    this.#registry  = registry;
  }

  /** Rebuild the sidebar for a freshly loaded map. */
  build(groups) {
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
    el.style.cssText = `
      display:flex; align-items:center; gap:6px; padding:8px 10px 4px 10px;
      font-size:10px; font-weight:700; letter-spacing:.07em;
      color:${color}; text-transform:uppercase; user-select:none;
    `;
    const line = document.createElement("div");
    line.style.cssText = `flex:1; height:1px; background:${color}; opacity:0.25;`;
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
    const isSynthetic = !!node.synthetic_id;
    const row = document.createElement("div");
    row.className = "region-row";
    row.dataset.regionId = node.id;

    row.appendChild(this.#treeIndent(depth, isLast, isLastChild));
    const cb = this.#checkbox(node);
    row.appendChild(cb.wrap);
    row.appendChild(this.#dot(node.color, isSynthetic));
    row.appendChild(this.#label(node, isSynthetic));
    row.appendChild(this.#typeBadge(node.type));

    row.addEventListener("click", (e) => {
      if (e.target !== cb.input) cb.input.click();
    });
    return row;
  }

  #treeIndent(depth, isLast, isLastChild) {
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

  #checkbox(node) {
    const wrap = document.createElement("div");
    wrap.style.cssText = "width:17px; flex-shrink:0; display:flex; justify-content:center;";
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
    el.style.cssText = isSynthetic
      ? `width:9px; height:9px; border-radius:2px; flex-shrink:0; opacity:0.5; background:transparent; border:1px dashed ${color};`
      : `width:9px; height:9px; border-radius:2px; flex-shrink:0; opacity:0.85; background:${color};`;
    return el;
  }

  #label(node, isSynthetic) {
    const el = document.createElement("span");
    el.style.cssText = `
      flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-size:11px;
      ${isSynthetic ? "font-style:italic; color:#64748b;" : "color:#cbd5e1;"}
    `;
    el.textContent = node.label;
    el.title = isSynthetic ? `${node.label}  (id: ${node.id})` : node.label;
    return el;
  }

  #typeBadge(type) {
    const el = document.createElement("span");
    const cls = TYPE_CLASS[type];
    el.style.cssText = "font-size:9px; background:#0f172a; padding:1px 4px; border-radius:3px; flex-shrink:0;";
    if (cls) { el.className = cls; } else { el.style.color = "#475569"; }
    el.textContent = type;
    return el;
  }
}
