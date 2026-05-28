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

export async function fetchSymmetry(mapName) {
  const r = await fetch(`/api/map/${encodeURIComponent(mapName)}/symmetry`);
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`Failed to load symmetry for ${mapName}`);
  return r.json();
}

export async function fetchContext(mapName) {
  const r = await fetch(`/api/map/${encodeURIComponent(mapName)}/context`);
  if (!r.ok) throw new Error(`Failed to load context for ${mapName}`);
  return r.json();
}

export async function fetchRegions(mapName) {
  const r = await fetch(`/api/map/${encodeURIComponent(mapName)}/regions`, { cache: "no-store" });
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

export async function createRegion(mapName, payload) {
  const r = await fetch(
    `/api/map/${encodeURIComponent(mapName)}/regions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
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

export async function fetchMinecraftPlayer(nameOrUuid) {
  const isUuid = nameOrUuid.includes("-") && nameOrUuid.length > 30;
  const param  = isUuid
    ? `uuid=${encodeURIComponent(nameOrUuid)}`
    : `name=${encodeURIComponent(nameOrUuid)}`;
  const r = await fetch(`/api/minecraft/player?${param}`);
  if (!r.ok) throw new Error(`Player not found: ${nameOrUuid}`);
  return r.json();  // { uuid, name }
}

export async function fetchTopSurface(mapName) {
  const r = await fetch(`/api/map/${encodeURIComponent(mapName)}/layers/top-surface`);
  if (!r.ok) throw new Error(`Failed to load top-surface layer (${r.status})`);
  return r.json();
}

// ── Configure page API ─────────────────────────────────────────────────────

export async function fetchLayoutConfig(mapName) {
  const r = await fetch(`/api/layout-config/${encodeURIComponent(mapName)}`);
  if (!r.ok) throw new Error(`Failed to load layout config (${r.status})`);
  return r.json();
}

export async function patchLayoutConfig(mapName, payload) {
  const r = await fetch(`/api/layout-config/${encodeURIComponent(mapName)}`, {
    method:  "PATCH",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(payload),
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.error || `Failed to save layout config (${r.status})`);
  }
  return r.json();
}

export async function fetchLayoutLayers(mapName) {
  const r = await fetch(`/api/source-map/${encodeURIComponent(mapName)}/layout-layers`);
  if (!r.ok) throw new Error(`Failed to load layout layers (${r.status})`);
  return r.json();
}

export async function fetchObserverIslandHint(mapName) {
  const r = await fetch(`/api/source-map/${encodeURIComponent(mapName)}/observer-island-hint`);
  if (!r.ok) throw new Error(`Failed to load observer island hint (${r.status})`);
  return r.json();
}

// ── Team CRUD ──────────────────────────────────────────────────────────────

export async function addTeam(mapName, team) {
  const r = await fetch(`/api/map/${encodeURIComponent(mapName)}/teams`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(team),
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.error || `Add team failed (${r.status})`);
  }
  return r.json();
}

export async function updateTeam(mapName, teamId, fields) {
  const r = await fetch(
    `/api/map/${encodeURIComponent(mapName)}/teams/${encodeURIComponent(teamId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    },
  );
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.error || `Update team failed (${r.status})`);
  }
  return r.json();
}

export async function deleteTeam(mapName, teamId) {
  const r = await fetch(
    `/api/map/${encodeURIComponent(mapName)}/teams/${encodeURIComponent(teamId)}`,
    { method: "DELETE" },
  );
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.error || `Delete team failed (${r.status})`);
  }
  return r.json();
}

// ── Spawn link CRUD ────────────────────────────────────────────────────────

export async function addSpawn(mapName, spawn) {
  const r = await fetch(`/api/map/${encodeURIComponent(mapName)}/spawns`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(spawn),
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.error || `Add spawn failed (${r.status})`);
  }
  return r.json();
}

export async function updateSpawn(mapName, regionId, fields) {
  const r = await fetch(
    `/api/map/${encodeURIComponent(mapName)}/spawn/${encodeURIComponent(regionId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    },
  );
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.error || `Update spawn failed (${r.status})`);
  }
  return r.json();
}

export async function deleteSpawn(mapName, regionId) {
  const r = await fetch(
    `/api/map/${encodeURIComponent(mapName)}/spawn/${encodeURIComponent(regionId)}`,
    { method: "DELETE" },
  );
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.error || `Delete spawn failed (${r.status})`);
  }
  return r.json();
}

// ── Wool CRUD ──────────────────────────────────────────────────────────────

export async function addWool(mapName, wool) {
  const r = await fetch(`/api/map/${encodeURIComponent(mapName)}/wools`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(wool),
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.error || `Add wool failed (${r.status})`);
  }
  return r.json();
}

export async function updateWool(mapName, teamId, color, fields) {
  const r = await fetch(
    `/api/map/${encodeURIComponent(mapName)}/wool/${encodeURIComponent(teamId)}/${encodeURIComponent(color)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    },
  );
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.error || `Update wool failed (${r.status})`);
  }
  return r.json();
}

export async function deleteWool(mapName, teamId, color) {
  const r = await fetch(
    `/api/map/${encodeURIComponent(mapName)}/wool/${encodeURIComponent(teamId)}/${encodeURIComponent(color)}`,
    { method: "DELETE" },
  );
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.error || `Delete wool failed (${r.status})`);
  }
  return r.json();
}

export async function fetchWoolRoomStatus(mapName, teamId, color) {
  const r = await fetch(
    `/api/map/${encodeURIComponent(mapName)}/wool/${encodeURIComponent(teamId)}/${encodeURIComponent(color)}/room-status`,
  );
  if (!r.ok) return null;
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
