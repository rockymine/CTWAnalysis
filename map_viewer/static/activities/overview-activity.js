import { OverviewPanel } from "../panels/overview-panel.js";

export class OverviewActivity {
  constructor({ onStatusChange } = {}) {
    this._el    = document.getElementById("overview-workspace");
    this._panel = new OverviewPanel(this._el, { onStatusChange });
  }

  activate({ mapName } = {}) {
    this._el.hidden = false;
    if (mapName) this._panel.load(mapName);
  }

  deactivate() {
    this._el.hidden = true;
  }

  resize() {
    this._panel._canvas?.resize();
  }
}
