/** All server communication. */

// ── Dashboard / configuration API ─────────────────────────────────────────

export async function fetchConfig() {
  const r = await fetch("/api/config");
  if (!r.ok) throw new Error("Failed to load config");
  return r.json();
}

export async function saveConfig(config) {
  const r = await fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!r.ok) throw new Error(`Failed to save config (${r.status})`);
  return r.json();
}

export async function fetchSourceMaps() {
  const r = await fetch("/api/source-maps");
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.error || `Failed to load source maps (${r.status})`);
  }
  return r.json();
}

export async function validateSourceMap(name) {
  const r = await fetch(`/api/source-map/${encodeURIComponent(name)}/validate`);
  if (!r.ok) throw new Error(`Validation failed (${r.status})`);
  return r.json();
}

export async function fetchPipelineStatus(name) {
  const r = await fetch(`/api/source-map/${encodeURIComponent(name)}/pipeline-status`);
  if (!r.ok) throw new Error(`Failed to load pipeline status (${r.status})`);
  return r.json();
}

export async function fetchMaps() {
  const r = await fetch("/api/maps");
  if (!r.ok) throw new Error("Failed to load map list");
  return r.json();
}

export async function fetchMapData(mapName) {
  const r = await fetch(`/api/map/${encodeURIComponent(mapName)}/map-data`);
  if (!r.ok) throw new Error(`Failed to load map data for ${mapName}`);
  return r.json();
}

export async function saveMetadata(mapName, metadata) {
  const r = await fetch(`/api/map/${encodeURIComponent(mapName)}/metadata`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(metadata),
  });
  if (!r.ok) throw new Error(`Failed to save metadata (${r.status})`);
  return r.json();
}

export async function fetchContext(mapName) {
  const r = await fetch(`/api/map/${mapName}/context`);
  if (!r.ok) throw new Error(`Failed to load context for ${mapName}`);
  return r.json();
}

export async function fetchRegions(mapName) {
  const r = await fetch(`/api/map/${mapName}/regions`, { cache: "no-store" });
  if (!r.ok) throw new Error(`Failed to load regions for ${mapName}`);
  return r.json();
}

export async function fetchRegionsXml(mapName) {
  const r = await fetch(`/api/map/${encodeURIComponent(mapName)}/export/xml`);
  if (!r.ok) throw new Error(`Export failed (${r.status})`);
  return r.text();
}

export async function renameRegion(mapName, oldId, newId) {
  const r = await fetch(
    `/api/map/${encodeURIComponent(mapName)}/region/${encodeURIComponent(oldId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: newId }),
    },
  );
  if (!r.ok) throw new Error(`Rename failed (${r.status})`);
  return r.json();
}

export async function createRegion(mapName, { id, min_x, min_z, max_x, max_z }) {
  const r = await fetch(
    `/api/map/${encodeURIComponent(mapName)}/regions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: "rectangle", id, min_x, min_z, max_x, max_z }),
    },
  );
  if (!r.ok) throw new Error(`Create region failed (${r.status})`);
  return r.json();
}

export async function deleteRegion(mapName, regionId) {
  const r = await fetch(
    `/api/map/${encodeURIComponent(mapName)}/region/${encodeURIComponent(regionId)}`,
    { method: "DELETE" },
  );
  if (!r.ok) throw new Error(`Delete failed (${r.status})`);
  return r.json();  // { ok, snapshot }
}

export async function restoreRegion(mapName, snapshot) {
  const r = await fetch(
    `/api/map/${encodeURIComponent(mapName)}/regions/restore`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ snapshot }),
    },
  );
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.error || `Restore failed (${r.status})`);
  }
  return r.json();
}

export async function patchRegion(mapName, regionId, bounds) {
  const r = await fetch(
    `/api/map/${encodeURIComponent(mapName)}/region/${encodeURIComponent(regionId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bounds }),
    },
  );
  if (!r.ok) throw new Error(`Save failed (${r.status})`);
  return r.json();
}

export async function updateRegionCoords(mapName, regionId, coords) {
  const r = await fetch(
    `/api/map/${encodeURIComponent(mapName)}/region/${encodeURIComponent(regionId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ coords }),
    },
  );
  if (!r.ok) throw new Error(`Coord save failed (${r.status})`);
  return r.json();
}

export async function fetchTopSurface(mapName) {
  const r = await fetch(`/api/map/${encodeURIComponent(mapName)}/layers/top-surface`);
  if (!r.ok) throw new Error(`Failed to load top-surface layer (${r.status})`);
  return r.json();
}

export async function groupRegions(mapName, childIds, groupId = "") {
  const r = await fetch(
    `/api/map/${encodeURIComponent(mapName)}/regions/group`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ child_ids: childIds, id: groupId }),
    },
  );
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.error || `Group failed (${r.status})`);
  }
  return r.json();
}
