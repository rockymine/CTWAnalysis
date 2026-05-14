/** All server communication. One place to add save/update endpoints later. */

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
