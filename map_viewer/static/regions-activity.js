export class RegionsActivity {
  constructor() {
    this._el = document.getElementById("regions-workspace");
  }

  activate(_context) {
    this._el.hidden = false;
  }

  deactivate() {
    this._el.hidden = true;
  }
}
