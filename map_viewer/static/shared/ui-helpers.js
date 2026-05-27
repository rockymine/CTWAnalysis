/**
 * Shared UI helper utilities used across multiple activity/panel modules.
 */

/**
 * Returns true when the keyboard event target is an editable element.
 * Use as an early-return guard in keydown handlers to avoid stealing
 * keystrokes while the user is typing in an input.
 *
 * @param {KeyboardEvent} e
 * @returns {boolean}
 */
export function isEditableTarget(e) {
  const tag = e.target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || e.target.isContentEditable;
}

/**
 * Append an empty-state placeholder <div class="list-empty"> to listEl.
 *
 * @param {HTMLElement} listEl
 * @param {string}      msg
 */
export function renderEmptyPlaceholder(listEl, msg) {
  const el = document.createElement("div");
  el.className = "list-empty";
  el.textContent = msg;
  listEl.appendChild(el);
}
