/**
 * RegionRegistry — tracks the region tree and selection state.
 *
 * Selection is single-primary: clicking a node selects it and all its
 * descendants. The onSelectionChange callback receives the primary node
 * object and the full array of selected ids (primary + all descendants).
 */
export class RegionRegistry {
  #entries = new Map();   // id → { parentId, childIds, node }
  #onSelectionChange;     // (primaryNode | null, selectedIds: string[]) => void
  #selectedIds = new Set();
  #primaryId = null;

  constructor({ onSelectionChange } = {}) {
    this.#onSelectionChange = onSelectionChange || null;
  }

  clear() {
    this.#entries.clear();
    this.#selectedIds.clear();
    this.#primaryId = null;
  }

  /** Recursively register a tree node and all its descendants. */
  register(node, parentId = null) {
    const childIds = (node.children || []).map(c => c.id).filter(Boolean);
    this.#entries.set(node.id, { parentId, childIds, node });
    for (const child of (node.children || [])) this.register(child, node.id);
  }

  /** Select a node by id; fires onSelectionChange with the node + all descendants. */
  select(id) {
    const info = this.#entries.get(id);
    if (!info) return;
    this.#primaryId = id;
    this.#selectedIds.clear();
    this.#collectDescendants(id, this.#selectedIds);
    if (this.#onSelectionChange) this.#onSelectionChange(info.node, [...this.#selectedIds]);
  }

  /** Clear selection; fires onSelectionChange with null and an empty array. */
  deselect() {
    this.#primaryId = null;
    this.#selectedIds.clear();
    if (this.#onSelectionChange) this.#onSelectionChange(null, []);
  }

  /** Return the stored node object for a given id, or null. */
  getNode(id) {
    return this.#entries.get(id)?.node ?? null;
  }

  #collectDescendants(id, out) {
    out.add(id);
    const info = this.#entries.get(id);
    if (!info) return;
    for (const childId of info.childIds) this.#collectDescendants(childId, out);
  }
}
