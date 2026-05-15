/** All server communication. */

export async function fetchMaps() {
  const r = await fetch("/api/maps");
  if (!r.ok) throw new Error("Failed to load map list");
  return r.json();
}

export async function fetchContext(mapName) {
  const r = await fetch(`/api/map/${mapName}/context`);
  if (!r.ok) throw new Error(`Failed to load context for ${mapName}`);
  return r.json();
}

export async function fetchRegions(mapName) {
  const r = await fetch(`/api/map/${mapName}/regions`);
  if (!r.ok) throw new Error(`Failed to load regions for ${mapName}`);
  return r.json();
}

export async function fetchRegionsXml(mapName) {
  const r = await fetch(`/api/map/${encodeURIComponent(mapName)}/export/xml`);
  if (!r.ok) throw new Error(`Export failed (${r.status})`);
  return r.text();
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
