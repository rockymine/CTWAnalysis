/**
 * RegionRegistry — owns the checkbox cascade and selection state.
 *
 * Knows nothing about the DOM beyond checkboxes; talks to the canvas and
 * sidebar via callbacks injected at construction time.
 */
export class RegionRegistry {
  // id → { parentId, directChildIds, el: HTMLInputElement|null }
  #entries = new Map();
  #onVisibilityChange;  // (id, visible) => void  — wired to canvas
  #toggleAllEl = null;

  constructor({ onVisibilityChange }) {
    this.#onVisibilityChange = onVisibilityChange;
  }

  setToggleAllEl(el) {
    this.#toggleAllEl = el;
  }

  clear() {
    this.#entries.clear();
  }

  /** Recursively register a tree node and all its descendants. */
  register(node, parentId = null) {
    const directChildIds = (node.children || []).filter(c => c.id).map(c => c.id);
    this.#entries.set(node.id, { parentId, directChildIds, el: null });
    for (const child of (node.children || [])) this.register(child, node.id);
  }

  /** Called by the sidebar after it creates a checkbox element. */
  attachCheckbox(id, el) {
    const info = this.#entries.get(id);
    if (info) info.el = el;
  }

  /** Toggle a region and cascade to all descendants. */
  setVisible(id, checked) {
    this.#cascade(id, checked);
    this.#updateAncestors(id);
    this.#syncToggleAll();
  }

  /** Cascade down without ancestor update — used by setVisible internally. */
  #cascade(id, checked) {
    const info = this.#entries.get(id);
    if (!info) return;
    if (info.el) {
      info.el.checked = checked;
      info.el.indeterminate = false;
    }
    this.#onVisibilityChange(id, checked);
    for (const childId of info.directChildIds) this.#cascade(childId, checked);
  }

  #updateAncestors(id) {
    const info = this.#entries.get(id);
    if (!info?.parentId) return;
    const parent = this.#entries.get(info.parentId);
    if (!parent) { this.#updateAncestors(info.parentId); return; }
    if (parent.el) {
      const states = parent.directChildIds.map(cid => {
        const c = this.#entries.get(cid);
        return c?.el ? c.el.checked && !c.el.indeterminate : true;
      });
      const allChecked = states.every(Boolean);
      const anyChecked = states.some(Boolean);
      parent.el.indeterminate = anyChecked && !allChecked;
      if (!parent.el.indeterminate) parent.el.checked = allChecked;
    }
    this.#updateAncestors(info.parentId);
  }

  #syncToggleAll() {
    if (!this.#toggleAllEl) return;
    const els = [...this.#entries.values()].filter(i => i.el).map(i => i.el);
    const allChecked = els.every(el => el.checked && !el.indeterminate);
    const anyChecked = els.some(el => el.checked || el.indeterminate);
    this.#toggleAllEl.indeterminate = anyChecked && !allChecked;
    this.#toggleAllEl.checked = allChecked;
  }

  /** Set all regions on or off (called by the toggle-all checkbox). */
  setAllVisible(checked) {
    for (const [id, info] of this.#entries) {
      if (!info.parentId) this.#cascade(id, checked);
    }
    this.#syncToggleAll();
  }

  rootIds() {
    return [...this.#entries.entries()]
      .filter(([, i]) => !i.parentId)
      .map(([id]) => id);
  }
}
