/**
 * ConceptActivity — layout concepting and sketching tool.
 *
 * Islands are topology-driven: adding/removing shapes triggers an automatic
 * boolean recompute (union of add shapes − union of subtract shapes).  Each
 * connected component of the result becomes a separate island.
 */

import { ConceptCanvas }                              from "../canvas/concept-canvas.js";
import { ToolManager }                                from "../shared/tool-manager.js";
import { computeIslands, assignShapesToIslands }      from "../concept-geometry.js";
import * as api                                       from "../api.js";

export class ConceptActivity {
  // ── state ──────────────────────────────────────────────────────────────────
  #shapes   = new Map();   // id → shape object
  #shapeSeq = 0;

  #computedIslands  = [];   // [{ id, name, color, exterior, holes, shapeIds }]
  #prevIslandCount  = 0;    // used to detect newly disconnected islands
  #primitivesVisible = false;

  #canvas = null;
  #tools  = null;

  #meta = {
    name:     "",
    version:  "0.1.0",
    authors:  [],
    bboxMinX: -256,
    bboxMaxX:  256,
    bboxMinZ: -256,
    bboxMaxZ:  256,
    centerX:   0,
    centerZ:   0,
  };
  #centerIsAutomatic = true;

  #activeActivity = "overview";

  constructor() {
    this.#initCanvas();
    this.#initToolbar();
    this.#initSidebars();
    this.#initMetaPanel();
    this.#initActivityRail();
    this.#switchActivity("overview");
    window.addEventListener("resize", () => this.#canvas.resize());
  }

  // ── canvas setup ───────────────────────────────────────────────────────────

  #initCanvas() {
    const svg  = document.getElementById("concept-svg");
    const wrap = document.getElementById("concept-svg-area");

    this.#canvas = new ConceptCanvas(svg, wrap, {
      onCoords: (x, z) => this.#updateCoords(x, z),
      onZoom:   (scale) => {
        const el = document.getElementById("ct-zoom-level");
        if (el) el.textContent = `${Math.round(scale * 100)}%`;
      },
      onShapeCreated:  (partial) => this.#addShape(partial),
      onShapeUpdated:  (shape)   => this.#onShapeUpdated(shape),
      onShapeSelected: (id)      => this.#selectShape(id),
      onShapeDeleted:  (id)      => this.#deleteShape(id),
    });
  }

  // ── activity rail ──────────────────────────────────────────────────────────

  #initActivityRail() {
    document.getElementById("ct-activity-overview").addEventListener("click",
      () => this.#switchActivity("overview"));
    document.getElementById("ct-activity-layout").addEventListener("click",
      () => this.#switchActivity("layout"));
  }

  #switchActivity(id) {
    this.#activeActivity = id;
    const isOverview = id === "overview";

    document.getElementById("ct-activity-overview").classList.toggle("active", isOverview);
    document.getElementById("ct-activity-layout").classList.toggle("active", !isOverview);

    document.getElementById("concept-overview-left").hidden = !isOverview;
    document.getElementById("concept-layout-left").hidden   = isOverview;
    document.getElementById("concept-right-area").hidden    = isOverview;
    document.getElementById("concept-right-handle").hidden  = isOverview;

    if (isOverview) this.#selectShape(null);
    this.#setToolbarMode(isOverview ? "overview" : "layout");

    // Resize after DOM layout changes (right panel appears/disappears),
    // otherwise the SVG keeps stale dimensions and coordinate mapping drifts.
    requestAnimationFrame(() => this.#canvas.resize());
  }

  #setToolbarMode(mode) {
    const isOverview = mode === "overview";
    const drawIds = [
      "ct-tool-select", "ct-tool-rect", "ct-tool-circ",
      "ct-tool-poly", "ct-tool-lasso",
      "ct-draw-toolbar-sep", "ct-op-add", "ct-op-sub",
    ];
    for (const id of drawIds) {
      const el = document.getElementById(id);
      if (el) el.hidden = isOverview;
    }
    if (isOverview) this.#tools.setTool("move");
  }

  // ── toolbar ────────────────────────────────────────────────────────────────

  #initToolbar() {
    const btnMove   = document.getElementById("ct-tool-move");
    const btnSelect = document.getElementById("ct-tool-select");
    const btnRect   = document.getElementById("ct-tool-rect");
    const btnCirc   = document.getElementById("ct-tool-circ");
    const btnPoly   = document.getElementById("ct-tool-poly");
    const btnLasso  = document.getElementById("ct-tool-lasso");

    this.#tools = new ToolManager(this.#canvas, {
      move:      btnMove,
      select:    btnSelect,
      rectangle: btnRect,
      circle:    btnCirc,
      polygon:   btnPoly,
      lasso:     btnLasso,
    });

    const setOrToggle = (tool) =>
      this.#tools.setTool(this.#tools.activeTool === tool ? null : tool);
    btnMove.addEventListener("click",   () => this.#tools.setTool("move"));
    btnSelect.addEventListener("click", () => this.#tools.setTool(null));
    btnRect.addEventListener("click",   () => setOrToggle("rectangle"));
    btnCirc.addEventListener("click",   () => setOrToggle("circle"));
    btnPoly.addEventListener("click",   () => setOrToggle("polygon"));
    btnLasso.addEventListener("click",  () => setOrToggle("lasso"));

    document.addEventListener("keydown", (e) => {
      if (["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
      if (e.key === "m" || e.key === "M") this.#tools.setTool("move");
      if (this.#activeActivity === "overview") return;
      if (e.key === "s" || e.key === "S") this.#tools.setTool(null);
      if (e.key === "r" || e.key === "R") this.#tools.setTool("rectangle");
      if (e.key === "o" || e.key === "O") this.#tools.setTool("circle");
      if (e.key === "p" || e.key === "P") this.#tools.setTool("polygon");
      if (e.key === "l" || e.key === "L") this.#tools.setTool("lasso");
    });

    this.#tools.setTool(null);

    const btnAdd = document.getElementById("ct-op-add");
    const btnSub = document.getElementById("ct-op-sub");
    const setOp = (op) => {
      this.#canvas.setOperation(op);
      btnAdd.classList.toggle("draw-tool-btn--active", op === "add");
      btnSub.classList.toggle("draw-tool-btn--active", op === "subtract");
    };
    btnAdd.addEventListener("click", () => setOp("add"));
    btnSub.addEventListener("click", () => setOp("subtract"));
    setOp("add");
  }

  // ── meta panel (Overview left) ─────────────────────────────────────────────

  #initMetaPanel() {
    const nameEl    = document.getElementById("ct-map-name");
    const versionEl = document.getElementById("ct-map-version");
    const bboxMinX  = document.getElementById("ct-bbox-minx");
    const bboxMaxX  = document.getElementById("ct-bbox-maxx");
    const bboxMinZ  = document.getElementById("ct-bbox-minz");
    const bboxMaxZ  = document.getElementById("ct-bbox-maxz");
    const sizeXEl   = document.getElementById("ct-bbox-size-x");
    const sizeZEl   = document.getElementById("ct-bbox-size-z");
    const centerXEl = document.getElementById("ct-center-x");
    const centerZEl = document.getElementById("ct-center-z");

    nameEl.addEventListener("input",    () => { this.#meta.name    = nameEl.value; });
    versionEl.addEventListener("input", () => { this.#meta.version = versionEl.value; });

    const refreshSizes = () => {
      const minX = parseInt(bboxMinX.value, 10), maxX = parseInt(bboxMaxX.value, 10);
      const minZ = parseInt(bboxMinZ.value, 10), maxZ = parseInt(bboxMaxZ.value, 10);
      if (!isNaN(minX) && !isNaN(maxX)) sizeXEl.textContent = String(maxX - minX);
      if (!isNaN(minZ) && !isNaN(maxZ)) sizeZEl.textContent = String(maxZ - minZ);
    };

    const applyBBox = () => {
      const minX = parseInt(bboxMinX.value, 10), maxX = parseInt(bboxMaxX.value, 10);
      const minZ = parseInt(bboxMinZ.value, 10), maxZ = parseInt(bboxMaxZ.value, 10);
      if ([minX, maxX, minZ, maxZ].some(isNaN)) return;
      if (minX >= maxX || minZ >= maxZ) return;
      this.#meta.bboxMinX = minX; this.#meta.bboxMaxX = maxX;
      this.#meta.bboxMinZ = minZ; this.#meta.bboxMaxZ = maxZ;
      this.#canvas.setBBox(minX, maxX, minZ, maxZ);
      if (this.#centerIsAutomatic) this.#resetCenter();
    };

    const applyCenter = () => {
      const cx = parseFloat(centerXEl.value), cz = parseFloat(centerZEl.value);
      if (isNaN(cx) || isNaN(cz)) return;
      this.#meta.centerX = cx; this.#meta.centerZ = cz;
      this.#canvas.setCenter(cx, cz);
    };

    for (const el of [bboxMinX, bboxMaxX, bboxMinZ, bboxMaxZ]) {
      el.addEventListener("input", refreshSizes);
      el.addEventListener("blur", applyBBox);
      el.addEventListener("keydown", (e) => { if (e.key === "Enter") applyBBox(); });
    }
    for (const el of [centerXEl, centerZEl]) {
      el.addEventListener("blur",    () => { this.#centerIsAutomatic = false; applyCenter(); });
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { this.#centerIsAutomatic = false; applyCenter(); }
      });
    }

    document.getElementById("ct-add-author").addEventListener("click", () => {
      this.#meta.authors.push({ name: "", uuid: "", contribution: "" });
      this.#renderAuthors();
    });

    this.#canvas.setCenter(this.#meta.centerX, this.#meta.centerZ);
  }

  #resetCenter() {
    const cx = (this.#meta.bboxMinX + this.#meta.bboxMaxX) / 2;
    const cz = (this.#meta.bboxMinZ + this.#meta.bboxMaxZ) / 2;
    this.#meta.centerX = cx; this.#meta.centerZ = cz;
    document.getElementById("ct-center-x").value = cx;
    document.getElementById("ct-center-z").value = cz;
    this.#canvas.setCenter(cx, cz);
  }

  #renderAuthors() {
    const list = document.getElementById("ct-authors-list");
    list.innerHTML = "";
    this.#meta.authors.forEach((author, idx) => {
      const row = document.createElement("div");
      row.className = "author-row";
      row.dataset.uuid = author.uuid ?? "";

      const avatarSrc = author.uuid ? _avatarUrl(author.uuid) : _AVATAR_EMPTY;
      row.innerHTML = `
        <img class="author-avatar" src="${_esc(avatarSrc)}" width="16" height="16" alt=""/>
        <input class="field-input author-name" type="text"
               placeholder="Minecraft username" value="${_esc(author.name ?? "")}"/>
        <input class="field-input author-contribution" type="text"
               placeholder="Contribution (optional)" value="${_esc(author.contribution ?? "")}"/>
        <button class="btn-remove" title="Remove">×</button>
      `;

      const avatarImg    = row.querySelector(".author-avatar");
      const nameInput    = row.querySelector(".author-name");
      const contribInput = row.querySelector(".author-contribution");

      nameInput.addEventListener("input",    (e) => { author.name         = e.target.value; });
      contribInput.addEventListener("input", (e) => { author.contribution = e.target.value; });

      nameInput.addEventListener("blur", async () => {
        const val = nameInput.value.trim();
        if (!val || val === author.uuid) return;
        try {
          const player    = await api.fetchMinecraftPlayer(val);
          author.uuid     = player.uuid;
          author.name     = player.name;
          row.dataset.uuid     = player.uuid;
          nameInput.value      = player.name;
          nameInput.title      = player.uuid;
          avatarImg.src        = _avatarUrl(player.uuid);
          nameInput.classList.remove("author-name--error");
        } catch {
          author.uuid   = "";
          avatarImg.src = _AVATAR_EMPTY;
          nameInput.classList.add("author-name--error");
          nameInput.title = "Player not found";
        }
      });

      row.querySelector(".btn-remove").addEventListener("click", () => {
        this.#meta.authors.splice(idx, 1);
        this.#renderAuthors();
      });
      list.appendChild(row);
    });
  }

  // ── right panel sidebars (Layout activity) ─────────────────────────────────

  #initSidebars() {
    // Primitives visibility toggle
    document.getElementById("ct-primitives-toggle").addEventListener("change", (e) => {
      this.#primitivesVisible = e.target.checked;
      this.#canvas.setShapesVisible(this.#primitivesVisible);
    });

    document.getElementById("ct-export").addEventListener("click", () => this.#exportJSON());
  }

  // ── island recomputation ───────────────────────────────────────────────────

  #recompute(addedShapeId = null) {
    const shapes = [...this.#shapes.values()];
    const { islands, addUnion, overrideAddUnion, newIslandCount } = computeIslands(shapes);

    assignShapesToIslands(shapes, islands, addUnion, overrideAddUnion);

    // Warn if a new add shape caused a new disconnected island
    if (addedShapeId) {
      const shape = this.#shapes.get(addedShapeId);
      if (shape?.operation !== "subtract" && newIslandCount > this.#prevIslandCount) {
        this.#showToast("New disconnected mass — created a separate island");
      }
    }
    this.#prevIslandCount = newIslandCount;

    // Preserve user-assigned names across recomputes by matching by color index
    for (let i = 0; i < islands.length; i++) {
      const prev = this.#computedIslands[i];
      if (prev?.name && prev.name !== `Island ${i + 1}`) {
        islands[i].name = prev.name;
      }
    }
    this.#computedIslands = islands;

    this.#canvas.setResultPolygons(
      islands.map(isl => ({ exterior: isl.exterior, holes: isl.holes }))
    );
    this.#renderLayoutSidebar();
  }

  // ── sidebar rendering (Layout activity) ───────────────────────────────────

  #renderLayoutSidebar() {
    const list = document.getElementById("ct-shape-list");
    list.innerHTML = "";

    if (this.#computedIslands.length === 0) {
      list.innerHTML = '<div class="concept-empty">Draw shapes to create islands.</div>';
      return;
    }

    // Shapes not assigned to any island (e.g. floating subtract shapes)
    const assignedIds = new Set(this.#computedIslands.flatMap(isl => isl.shapeIds));
    const unassigned  = [...this.#shapes.values()].filter(s => !assignedIds.has(s.id));

    for (const island of this.#computedIslands) {
      list.appendChild(this.#buildIslandGroup(island));
    }

    if (unassigned.length > 0) {
      const section = document.createElement("div");
      section.className = "concept-island-group concept-island-group--unassigned";
      section.innerHTML = `
        <div class="concept-island-header">
          <span class="concept-island-label">Unassigned shapes</span>
        </div>
      `;
      const children = document.createElement("div");
      children.className = "concept-island-children";
      for (const shape of unassigned) {
        children.appendChild(this.#buildShapeChild(shape));
      }
      section.appendChild(children);
      list.appendChild(section);
    }

    lucide.createIcons({ nodes: [list], attrs: { "stroke-width": "1.5", width: "11", height: "11" } });
  }

  #buildIslandGroup(island) {
    const group = document.createElement("div");
    group.className = "concept-island-group";
    group.dataset.islandId = island.id;

    const header = document.createElement("div");
    header.className = "concept-island-header";
    header.innerHTML = `
      <span class="concept-island-dot" style="background:${island.color}"></span>
      <input class="concept-island-name field-input" value="${_esc(island.name)}" spellcheck="false"/>
      <span class="concept-island-count">${island.shapeIds.length} shape${island.shapeIds.length !== 1 ? "s" : ""}</span>
    `;
    header.querySelector(".concept-island-name").addEventListener("change", (e) => {
      island.name = e.target.value.trim() || island.name;
    });

    const children = document.createElement("div");
    children.className = "concept-island-children";
    for (const shapeId of island.shapeIds) {
      const shape = this.#shapes.get(shapeId);
      if (shape) children.appendChild(this.#buildShapeChild(shape));
    }

    group.appendChild(header);
    group.appendChild(children);
    return group;
  }

  #buildShapeChild(shape) {
    const isAdd = shape.operation !== "subtract";
    const row = document.createElement("div");
    row.className = "concept-shape-child";
    row.dataset.shapeId = shape.id;
    row.innerHTML = `
      <button class="concept-op-badge concept-op-badge--${isAdd ? "add" : "sub"}" title="Toggle add/subtract">${isAdd ? "add" : "sub"}</button>
      <span class="concept-shape-icon">${_typeIcon(shape.type)}</span>
      <span class="concept-shape-label">${this.#shapeLabel(shape)}</span>
      <button class="concept-override-btn${shape.override ? ` concept-override-btn--active concept-override-btn--active-${isAdd ? "add" : "sub"}` : ""}"
              title="${isAdd ? "Override subtract — fills area even inside subtract zones" : "Override add — cuts through override add shapes"}"
      ><i data-lucide="shield"></i></button>
      <button class="btn-remove" title="Delete shape">×</button>
    `;
    row.addEventListener("click", (e) => {
      if (e.target.closest(".btn-remove, .concept-override-btn, .concept-op-badge")) return;
      this.#selectShape(shape.id);
    });
    row.querySelector(".concept-op-badge").addEventListener("click", (e) => {
      e.stopPropagation();
      this.#toggleShapeOperation(shape.id);
    });
    row.querySelector(".concept-override-btn").addEventListener("click", (e) => {
      e.stopPropagation();
      this.#toggleShapeOverride(shape.id);
    });
    row.querySelector(".btn-remove").addEventListener("click", (e) => {
      e.stopPropagation();
      this.#deleteShape(shape.id);
    });
    return row;
  }

  #toggleShapeOperation(id) {
    const shape = this.#shapes.get(id);
    if (!shape) return;
    shape.operation = shape.operation === "subtract" ? "add" : "subtract";
    this.#canvas.updateShape(shape);
    this.#recompute();
  }

  #toggleShapeOverride(id) {
    const shape = this.#shapes.get(id);
    if (!shape) return;
    shape.override = !shape.override;
    this.#recompute();
  }

  // ── shape management ───────────────────────────────────────────────────────

  #addShape(partial) {
    const id = `s${++this.#shapeSeq}`;
    const shape = { ...partial, id, override: false };
    this.#shapes.set(id, shape);

    if (this.#primitivesVisible) {
      this.#canvas.addShape(shape);
    } else {
      // Store in canvas state but keep shapes layer hidden
      this.#canvas.addShape(shape);
    }

    this.#tools.setTool(null);
    this.#recompute(id);
    this.#selectShape(id);
  }

  #onShapeUpdated(shape) {
    this.#shapes.set(shape.id, shape);
    this.#recompute();
  }

  #selectShape(id) {
    this.#canvas.selectShape(id);
    document.querySelectorAll(".concept-shape-child").forEach(r => {
      r.classList.toggle("list-row--selected", r.dataset.shapeId === id);
    });
  }

  #deleteShape(id) {
    this.#shapes.delete(id);
    this.#canvas.removeShape(id);
    this.#recompute();
  }

  #shapeLabel(shape) {
    if (shape.type === "rectangle") {
      const w = shape.max_x - shape.min_x, h = shape.max_z - shape.min_z;
      return `rect ${w}×${h}`;
    }
    if (shape.type === "circle")  return `circle r=${shape.radius}`;
    if (shape.type === "polygon") return `poly ${shape.vertices.length}v`;
    return shape.type;
  }

  // ── toast notifications ────────────────────────────────────────────────────

  #showToast(message) {
    const toast = document.createElement("div");
    toast.className = "concept-toast";
    toast.textContent = message;
    document.body.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add("concept-toast--visible"));
    setTimeout(() => {
      toast.classList.remove("concept-toast--visible");
      toast.addEventListener("transitionend", () => toast.remove(), { once: true });
    }, 3000);
  }

  // ── export ─────────────────────────────────────────────────────────────────

  #exportJSON() {
    const payload = {
      map_name:     this.#meta.name    || "Unnamed Map",
      map_version:  this.#meta.version || "0.1.0",
      authors:      this.#meta.authors
                      .filter(a => a.name?.trim())
                      .map(a => ({
                        name:         a.name,
                        ...(a.uuid         && { uuid:         a.uuid }),
                        ...(a.contribution && { contribution: a.contribution }),
                      })),
      bounding_box: [
        this.#meta.bboxMinX, this.#meta.bboxMaxX,
        this.#meta.bboxMinZ, this.#meta.bboxMaxZ,
      ],
      map_center: [this.#meta.centerX, this.#meta.centerZ],
      islands:    this.#computedIslands.map(isl => ({
        name:     isl.name,
        exterior: isl.exterior,
        holes:    isl.holes,
        shapes:   isl.shapeIds.map(id => {
          const s = this.#shapes.get(id);
          return s ? { type: s.type, operation: s.operation, ...s } : null;
        }).filter(Boolean),
      })),
    };
    const json = JSON.stringify(payload, null, 2);
    const a    = document.createElement("a");
    a.href     = `data:application/json,${encodeURIComponent(json)}`;
    a.download = "concept-layout.json";
    a.click();
  }

  // ── utils ──────────────────────────────────────────────────────────────────

  #updateCoords(x, z) {
    const el = document.getElementById("ct-cursor-coords");
    if (!el) return;
    el.textContent = (x === null) ? "" : `X ${x}  Z ${z}`;
  }
}

function _esc(str) {
  return String(str).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

const _AVATAR_EMPTY = "data:image/gif;base64,R0lGODlhEAAQAAAAACwAAAAAEAAQAAABEIQBADs=";
function _avatarUrl(uuid) {
  return `https://mc-heads.net/avatar/${encodeURIComponent(uuid)}/16`;
}

function _typeIcon(type) {
  if (type === "rectangle") return "▭";
  if (type === "circle")    return "◯";
  if (type === "polygon")   return "⬡";
  return "?";
}
