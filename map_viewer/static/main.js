/**
 * Application bootstrap — wires activities together and manages map loading.
 *
 * This module is intentionally thin.  All Regions-specific logic lives in
 * RegionsActivity; Teams logic lives in TeamsActivity; Overview in
 * OverviewActivity.  main.js only handles:
 *   - Reading the ?map= URL param and calling loadMap()
 *   - Activity switching (deactivate / activate / resize)
 *   - The Export button
 *   - Shared UI: breadcrumb, status bar, window resize
 */

import { OverviewActivity }   from "./activities/overview-activity.js";
import { RegionsActivity }    from "./activities/regions-activity.js";
import { TeamsActivity }      from "./activities/teams-activity.js";
import { ObjectiveActivity }  from "./activities/objective-activity.js";
import * as api               from "./api.js";

lucide.createIcons({ attrs: { "stroke-width": "1.5", width: "15", height: "15" } });

// ── Shared helpers ────────────────────────────────────────────────────────────

function setStatus(msg) {
  document.getElementById("status").textContent = msg;
}

function setBreadcrumb(name, version) {
  const nameEl = document.getElementById("topbar-map-name");
  const verEl  = document.getElementById("topbar-version");
  if (nameEl) nameEl.textContent = name ?? "";
  if (verEl)  verEl.textContent  = version ? `v${version}` : "";
}

// ── Activity setup ────────────────────────────────────────────────────────────

const activityBtns  = document.querySelectorAll(".activity-btn");
const overviewBtn   = document.getElementById("activity-overview");
const teamsBtn      = document.getElementById("activity-teams");
const objectiveBtn  = document.getElementById("activity-objective");

const ACTIVITIES = {
  "activity-overview": new OverviewActivity({
    onStatusChange: (dotStatus) => { overviewBtn.dataset.status = dotStatus ?? ""; },
  }),
  "activity-teams": new TeamsActivity({
    onStatusChange: (dotStatus) => { teamsBtn.dataset.status = dotStatus ?? ""; },
  }),
  "activity-objective": new ObjectiveActivity(),
  "activity-regions": new RegionsActivity({ setStatus }),
};

let currentActivityId = "activity-overview";
let currentMap        = null;

function switchActivity(id) {
  ACTIVITIES[currentActivityId].deactivate();
  currentActivityId = id;
  activityBtns.forEach(btn => btn.classList.toggle("active", btn.id === id));
  ACTIVITIES[id].activate({ mapName: currentMap });
  requestAnimationFrame(() => ACTIVITIES[id].resize());
}

overviewBtn.addEventListener("click",   () => { if (!overviewBtn.disabled)  switchActivity("activity-overview"); });
teamsBtn.addEventListener("click",     () => { if (!teamsBtn.disabled)     switchActivity("activity-teams"); });
objectiveBtn.addEventListener("click", () => { if (!objectiveBtn.disabled) switchActivity("activity-objective"); });
document.getElementById("activity-regions").addEventListener("click", () => switchActivity("activity-regions"));

// ── Export button ─────────────────────────────────────────────────────────────

const exportBtn = document.getElementById("export-xml-btn");
exportBtn.addEventListener("click", async () => {
  if (!currentMap) return;
  try {
    const xml  = await api.fetchRegionsXml(currentMap);
    const blob = new Blob([xml], { type: "application/xml" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = `${currentMap}_regions.xml`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    setStatus(`Export failed: ${err.message}`);
  }
});

// ── Map loading ────────────────────────────────────────────────────────────────

async function loadMap(name) {
  currentMap = name;
  exportBtn.disabled    = true;
  overviewBtn.disabled  = true;
  teamsBtn.disabled     = true;
  objectiveBtn.disabled = true;
  setStatus("Loading…");
  try {
    const ctx = await api.fetchContext(name);
    setBreadcrumb(ctx.map_name || name.replace(/_/g, " "), ctx.map_version);
    exportBtn.disabled    = false;
    overviewBtn.disabled  = false;
    teamsBtn.disabled     = false;
    objectiveBtn.disabled = false;
    setStatus("");
    // Activate the current activity now that the map name is known.
    // Each activity handles its own data fetching internally.
    ACTIVITIES[currentActivityId].activate({ mapName: name });
    requestAnimationFrame(() => ACTIVITIES[currentActivityId].resize());
  } catch (err) {
    setStatus(`Error: ${err.message}`);
  }
}

// ── Window resize ─────────────────────────────────────────────────────────────

window.addEventListener("resize", () => ACTIVITIES[currentActivityId].resize());

// ── Boot: read map from URL query param ───────────────────────────────────────

const urlParams = new URLSearchParams(window.location.search);
const mapParam  = urlParams.get("map");

if (!mapParam) {
  window.location.replace("/");
} else {
  setBreadcrumb(mapParam.replace(/_/g, " "), null);
  loadMap(mapParam);
}
