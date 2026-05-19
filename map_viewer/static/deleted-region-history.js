/**
 * Undo/redo history for region deletion only.
 *
 * Snapshots are opaque blobs returned by the server's delete endpoint and
 * sent verbatim to the restore endpoint. No live node references are stored.
 */
export class DeletedRegionHistory {
  #undoStack = [];  // snapshots that can be restored (Ctrl+Z)
  #redoStack = [];  // snapshots that can be re-deleted (Ctrl+Y)
  #busy      = false;
  #limit     = 20;
  #onChange  = null;

  constructor({ onChange } = {}) {
    this.#onChange = onChange || null;
  }

  get canUndo() { return !this.#busy && this.#undoStack.length > 0; }
  get canRedo()  { return !this.#busy && this.#redoStack.length > 0; }

  /**
   * Returns a plain snapshot of both stacks for display purposes.
   * undoStack[last] = most recently deleted; redoStack[last] = most recently restored.
   */
  getState() {
    return {
      undoStack: this.#undoStack.map(s => s.root_id),
      redoStack: this.#redoStack.map(s => s.root_id),
    };
  }

  /** Called after a successful server delete. Clears the redo stack. */
  pushDelete(snapshot) {
    this.#undoStack.push(snapshot);
    if (this.#undoStack.length > this.#limit) this.#undoStack.shift();
    this.#redoStack = [];
    this.#onChange?.();
  }

  /**
   * Called after any successful non-delete mutation (bounds save, coords save,
   * rename, create). Invalidates redo so a stale snapshot cannot restore old data
   * over a modified region.
   */
  clearRedo() {
    if (this.#redoStack.length === 0) return;
    this.#redoStack = [];
    this.#onChange?.();
  }

  /** Called on map load to discard history from a previous map. */
  clear() {
    this.#undoStack = [];
    this.#redoStack = [];
    this.#onChange?.();
  }

  /**
   * Ctrl+Z: restore the most recently deleted region.
   * restoreFn(snapshot) must call the server and re-render; throws on failure.
   * Snapshot is only moved to redo stack after success; stacks unchanged on failure.
   */
  async undo(restoreFn, onError) {
    if (this.#busy || this.#undoStack.length === 0) return;
    const snapshot = this.#undoStack[this.#undoStack.length - 1];
    this.#busy = true;
    try {
      await restoreFn(snapshot);
      this.#undoStack.pop();
      this.#redoStack.push(snapshot);
      this.#onChange?.();
    } catch (err) {
      onError(err);
    } finally {
      this.#busy = false;
    }
  }

  /**
   * Ctrl+Y: re-delete the most recently restored region.
   * redeleteFn(snapshot) must call the server and re-render; throws on failure.
   * Snapshot is only moved to undo stack after success; stacks unchanged on failure.
   */
  async redo(redeleteFn, onError) {
    if (this.#busy || this.#redoStack.length === 0) return;
    const snapshot = this.#redoStack[this.#redoStack.length - 1];
    this.#busy = true;
    try {
      await redeleteFn(snapshot);
      this.#redoStack.pop();
      this.#undoStack.push(snapshot);
      this.#onChange?.();
    } catch (err) {
      onError(err);
    } finally {
      this.#busy = false;
    }
  }
}
