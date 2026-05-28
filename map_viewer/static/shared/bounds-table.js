/**
 * boundsTable — builds a BOUNDS section (header + MIN/MAX/SIZE table) matching
 * the region editor's inspector style.
 *
 * Usage:
 *   const bt = boundsTable(["X", "Z"], { onInput: () => markDirty() });
 *   container.appendChild(bt.el);
 *   bt.setValues({ X: { min: -100, max: 100 }, Z: { min: -80, max: 80 } });
 *   const vals = bt.getValues(); // { X: { min, max }, Z: { min, max } }
 *
 * @param {string[]} axisLabels   e.g. ["X", "Z"] or ["X", "Y", "Z"]
 * @param {{ onInput?: () => void }} opts
 * @returns {{ el: HTMLElement,
 *             getValues: () => Record<string, { min: number|null, max: number|null }>,
 *             setValues: (vals: Record<string, { min?: number, max?: number }>) => void,
 *             hasValues: () => boolean }}
 */
export function boundsTable(axisLabels, { onInput } = {}) {
  const section = document.createElement("div");
  section.className = "detail-section";

  const header   = document.createElement("div");
  header.className = "detail-section-header";
  const titleEl  = document.createElement("span");
  titleEl.className   = "section-title";
  titleEl.textContent = "BOUNDS";
  header.appendChild(titleEl);
  section.appendChild(header);

  const table = document.createElement("table");
  table.className = "detail-table";
  section.appendChild(table);

  const thead = table.createTHead();
  const hrow  = thead.insertRow();
  for (const col of ["", "MIN", "MAX", "SIZE"]) {
    const th = document.createElement("th");
    th.textContent = col;
    hrow.appendChild(th);
  }

  const tbody  = table.createTBody();
  const inputs = /** @type {Record<string, { min: HTMLInputElement, max: HTMLInputElement, refreshSize: () => void }>} */ ({});

  for (const axis of axisLabels) {
    const row   = tbody.insertRow();
    const axisC = row.insertCell(); axisC.className = "detail-axis"; axisC.textContent = axis;
    const minC  = row.insertCell(); minC.className  = "detail-val";
    const maxC  = row.insertCell(); maxC.className  = "detail-val";
    const sizeC = row.insertCell(); sizeC.className = "detail-size";

    const minInput = _makeInput();
    const maxInput = _makeInput();
    minC.appendChild(minInput);
    maxC.appendChild(maxInput);

    const refreshSize = () => {
      const mn = parseFloat(minInput.value);
      const mx = parseFloat(maxInput.value);
      if (!isNaN(mn) && !isNaN(mx)) {
        const sz = mx - mn;
        sizeC.textContent = Number.isInteger(sz) ? String(sz) : sz.toFixed(1);
      } else {
        sizeC.textContent = "";
      }
    };

    const handleInput = () => { refreshSize(); onInput?.(); };
    minInput.addEventListener("input", handleInput);
    maxInput.addEventListener("input", handleInput);

    inputs[axis] = { min: minInput, max: maxInput, refreshSize };
  }

  return {
    el: section,

    getValues() {
      const result = {};
      for (const [axis, { min, max }] of Object.entries(inputs)) {
        const mn = parseFloat(min.value);
        const mx = parseFloat(max.value);
        result[axis] = { min: isNaN(mn) ? null : mn, max: isNaN(mx) ? null : mx };
      }
      return result;
    },

    setValues(vals) {
      for (const [axis, pair] of Object.entries(vals)) {
        if (!inputs[axis]) continue;
        if (pair.min !== null && pair.min !== undefined) inputs[axis].min.value = pair.min;
        if (pair.max !== null && pair.max !== undefined) inputs[axis].max.value = pair.max;
        inputs[axis].refreshSize();
      }
    },

    hasValues() {
      return Object.values(inputs).every(
        ({ min, max }) => min.value.trim() !== "" && max.value.trim() !== "",
      );
    },
  };
}

function _makeInput() {
  const input = document.createElement("input");
  input.type      = "number";
  input.step      = "any";
  input.className = "detail-bounds-input";
  return input;
}
