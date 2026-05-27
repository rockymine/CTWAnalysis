def spawn_region_id(spawn: dict) -> str:
    """Return the region id for a spawn entry (handles both embedded and ref forms)."""
    region = spawn.get("region")
    if isinstance(region, dict):
        return region.get("id", "")
    if isinstance(region, str):
        return region
    return ""
