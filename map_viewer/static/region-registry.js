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

  /**
   * Update all internal maps when a region is renamed from oldId to newId.
   * node.id and node.label must already have been mutated by the caller.
   */
  renameNode(oldId, newId) {
    const entry = this.#entries.get(oldId);
    if (!entry) return;
    this.#entries.delete(oldId);
    this.#entries.set(newId, entry);

    // Update parent's childIds list
    if (entry.parentId) {
      const parentEntry = this.#entries.get(entry.parentId);
      if (parentEntry) {
        const idx = parentEntry.childIds.indexOf(oldId);
        if (idx !== -1) parentEntry.childIds[idx] = newId;
      }
    }

    // Update each child's parentId reference
    for (const childId of entry.childIds) {
      const childEntry = this.#entries.get(childId);
      if (childEntry) childEntry.parentId = newId;
    }

    // Update selection state
    if (this.#primaryId === oldId) this.#primaryId = newId;
    if (this.#selectedIds.has(oldId)) {
      this.#selectedIds.delete(oldId);
      this.#selectedIds.add(newId);
    }
  }

  /**
   * Walk up the ancestor chain from startId, recompute bounds for each
   * composite ancestor whose bounds can be derived from its children:
   *   union      → bounding box union of all children
   *   intersect  → bounding box intersection of all children
   * negative/complement are skipped (canvas renders them as map-bbox minus children).
   *
   * Mutates node.bounds in-place; returns an array of updated ancestor nodes
   * so the caller can refresh their canvas shapes.
   */
  recomputeAncestorBounds(startId) {
    const updated = [];
    let currentId = this.#entries.get(startId)?.parentId;
    while (currentId) {
      const entry = this.#entries.get(currentId);
      if (!entry) break;
      const { node } = entry;
      let newBounds = null;
      if (node.type === "union")     newBounds = this.#unionOfChildren(node);
      if (node.type === "intersect") newBounds = this.#intersectOfChildren(node);
      if (newBounds && node.bounds) {
        Object.assign(node.bounds, newBounds);
        updated.push(node);
      }
      currentId = entry.parentId;
    }
    return updated;
  }

  #unionOfChildren(node) {
    let minX = Infinity, minZ = Infinity, maxX = -Infinity, maxZ = -Infinity;
    let found = false;
    for (const child of (node.children || [])) {
      if (!child.bounds) continue;
      found = true;
      minX = Math.min(minX, child.bounds.min_x);
      minZ = Math.min(minZ, child.bounds.min_z);
      maxX = Math.max(maxX, child.bounds.max_x);
      maxZ = Math.max(maxZ, child.bounds.max_z);
    }
    return found ? { min_x: minX, min_z: minZ, max_x: maxX, max_z: maxZ } : null;
  }

  #intersectOfChildren(node) {
    let minX = -Infinity, minZ = -Infinity, maxX = Infinity, maxZ = Infinity;
    let found = false;
    for (const child of (node.children || [])) {
      if (!child.bounds) continue;
      found = true;
      minX = Math.max(minX, child.bounds.min_x);
      minZ = Math.max(minZ, child.bounds.min_z);
      maxX = Math.min(maxX, child.bounds.max_x);
      maxZ = Math.min(maxZ, child.bounds.max_z);
    }
    if (!found || minX >= maxX || minZ >= maxZ) return null;
    return { min_x: minX, min_z: minZ, max_x: maxX, max_z: maxZ };
  }

  #collectDescendants(id, out) {
    out.add(id);
    const info = this.#entries.get(id);
    if (!info) return;
    for (const childId of info.childIds) this.#collectDescendants(childId, out);
  }
}
