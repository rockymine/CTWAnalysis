/**
 * coordGroup — builds a `div.detail-group-row` containing axis-prefixed number
 * inputs, using the `.detail-prefixed-field` / `.detail-prefix` /
 * `.detail-bounds-input` CSS classes that are shared across all inspector panels.
 *
 * Each axis descriptor is one of:
 *
 *   Read-only (disabled):
 *     { axis: "X", value: 49.5, disabled: true }
 *
 *   Editable:
 *     { axis: "X", value: 49.5, origValue: 49.5,
 *       onChange: (v) => { ... },   // called on each valid keystroke
 *       onSave:   (v) => { ... },   // called on blur / Enter with a valid value
 *       onRevert: ()  => { ... } }  // called on Escape or invalid-value blur
 *
 * `origValue` defaults to `value` when omitted.
 * When `disabled` is truthy all event wiring is skipped.
 *
 * Returns the `div.detail-group-row` element — append it wherever needed.
 *
 * @param {Array<{
 *   axis: string,
 *   value: number,
 *   disabled?: boolean,
 *   origValue?: number,
 *   onChange?: (v: number) => void,
 *   onSave?:   (v: number) => void,
 *   onRevert?: ()          => void,
 * }>} axes
 * @returns {HTMLDivElement}
 */
export function coordGroup(axes) {
  const row = document.createElement("div");
  row.className = "detail-group-row";

  for (const spec of axes) {
    const field = document.createElement("div");
    field.className = "detail-prefixed-field";

    const prefix = document.createElement("span");
    prefix.className  = "detail-prefix";
    prefix.textContent = spec.axis;

    const input = document.createElement("input");
    input.type      = "number";
    input.step      = "any";
    input.className = "detail-bounds-input";
    input.value     = spec.value ?? 0;

    if (spec.disabled) {
      input.disabled = true;
    } else {
      const orig = spec.origValue ?? spec.value ?? 0;

      if (spec.onChange) {
        input.addEventListener("input", () => {
          const v = parseFloat(input.value);
          if (!isNaN(v)) spec.onChange(v);
        });
      }

      input.addEventListener("blur", () => {
        const v = parseFloat(input.value);
        if (isNaN(v)) {
          input.value = orig;
          spec.onRevert?.();
        } else {
          input.value = v;
          spec.onSave?.(v);
        }
      });

      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter")  { e.preventDefault(); input.blur(); }
        if (e.key === "Escape") {
          e.preventDefault();
          input.value = orig;
          spec.onRevert?.();
          input.blur();
        }
      });
    }

    field.append(prefix, input);
    row.appendChild(field);
  }

  return row;
}
