import { OverviewPanel } from "../panels/overview-panel.js";

export class OverviewActivity {
  #el    = null;
  #panel = null;

  constructor({ onStatusChange } = {}) {
    this.#el    = document.getElementById("overview-workspace");
    this.#panel = new OverviewPanel(this.#el, { onStatusChange });
  }

  activate({ mapName } = {}) {
    this.#el.hidden = false;
    if (mapName) this.#panel.load(mapName);
  }

  deactivate() {
    this.#el.hidden = true;
  }

  resize() {
    this.#panel.resize();
  }
}
