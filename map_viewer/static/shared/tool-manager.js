/**
 * ToolManager — centralizes tool-button state management for activity toolbars.
 *
 * Eliminates the near-identical `_setTool` / `#setToolActive` pattern duplicated
 * across RegionsActivity, TeamsActivity, and ObjectiveActivity.
 *
 * @param {object} canvas     — MapCanvas instance (must have setActiveTool(tool))
 * @param {object} buttonMap  — plain object { toolName: btnEl }
 *                              Use "select" as key for the null/select-mode tool.
 */
export class ToolManager {
  #canvas;
  #buttons;      // Map<toolKey, btnEl>  where toolKey is null for "select"
  #activeTool = null;

  constructor(canvas, buttonMap) {
    this.#canvas = canvas;
    this.#buttons = new Map(
      Object.entries(buttonMap).map(([name, btn]) => [name === "select" ? null : name, btn]),
    );
  }

  get activeTool() { return this.#activeTool; }

  setTool(tool) {
    this.#activeTool = tool;
    this.#canvas.setActiveTool(tool);
    for (const [key, btn] of this.#buttons) {
      btn.classList.toggle("draw-tool-btn--active", tool === key);
    }
  }

  setEnabled(enabled) {
    for (const btn of this.#buttons.values()) btn.disabled = !enabled;
  }
}
