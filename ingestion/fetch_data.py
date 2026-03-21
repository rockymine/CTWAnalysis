import discord
import aiohttp
import asyncio
import re
import json
import unicodedata
import os
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# ─── Config ───────────────────────────────────────────────────────────────────
TOKEN      = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = int(os.environ["DISCORD_CHANNEL_ID"])
DOWNLOAD_DIR = Path("./parquet_downloads")
SYNC_STATE_FILE = Path("./last_sync.json")
KNOWN_MAPS_FILE = Path("./known_maps.json")
FIRST_RUN_SINCE = datetime(2026, 3, 6, tzinfo=timezone.utc)  # fallback for first run
# ──────────────────────────────────────────────────────────────────────────────

DOWNLOAD_DIR.mkdir(exist_ok=True)


# ─── State helpers ────────────────────────────────────────────────────────────
def load_last_sync() -> datetime:
    if SYNC_STATE_FILE.exists():
        ts = json.loads(SYNC_STATE_FILE.read_text())["last_sync"]
        return datetime.fromisoformat(ts)
    return FIRST_RUN_SINCE

def save_last_sync():
    SYNC_STATE_FILE.write_text(json.dumps({
        "last_sync": datetime.now(timezone.utc).isoformat()
    }))

def load_known_maps() -> set:
    if KNOWN_MAPS_FILE.exists():
        return set(json.loads(KNOWN_MAPS_FILE.read_text()))
    return set()

def save_known_maps(maps: set):
    KNOWN_MAPS_FILE.write_text(json.dumps(sorted(maps), indent=2))


# ─── Map name parsing & normalization ─────────────────────────────────────────
def parse_map_name(message_content: str) -> str | None:
    # Strip markdown bold (**) and inline code (`)
    cleaned = re.sub(r"[\*`]", "", message_content)
    match = re.match(r"#\d+\s*-\s*(.+?)\s*-\s*\d+m", cleaned)
    if match:
        return normalize_map_name(match.group(1))
    return None

def normalize_map_name(name: str) -> str:
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = name.lower()
    name = name.replace(" ", "_")
    name = re.sub(r"[^a-z0-9_]", "", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_")


# ─── Download ─────────────────────────────────────────────────────────────────
async def download_file(url: str, filename: str, map_slug: str | None, session: aiohttp.ClientSession):
    subfolder = DOWNLOAD_DIR / (map_slug if map_slug else "_unknown")
    subfolder.mkdir(parents=True, exist_ok=True)
    filepath = subfolder / filename
    if filepath.exists():
        print(f"  [SKIP] {filename}")
        return

    async with session.get(url, headers={"Authorization": f"Bot {TOKEN}"}) as resp:
        if resp.status == 200:
            filepath.write_bytes(await resp.read())
            print(f"  [OK]   {subfolder.name}/{filename}")
        else:
            print(f"  [FAIL] {filename} — HTTP {resp.status}")


# ─── Main sync ────────────────────────────────────────────────────────────────
async def sync():
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    async with client:
        await client.login(TOKEN)
        channel = await client.fetch_channel(CHANNEL_ID)

        since = load_last_sync()
        known_maps = load_known_maps()
        discovered_maps = set()

        print(f"Syncing #{channel.name} since {since.strftime('%Y-%m-%d %H:%M UTC')}...")

        async with aiohttp.ClientSession() as session:
            async for message in channel.history(after=since, limit=None, oldest_first=True):
                map_name = parse_map_name(message.content)
                if map_name:
                    discovered_maps.add(map_name)

                for attachment in message.attachments:
                    if attachment.filename.endswith(".parquet"):
                        await download_file(attachment.url, attachment.filename, map_name, session)

        # Summary
        new_maps = discovered_maps - known_maps
        print(f"\n─── Sync complete ───────────────────────")
        print(f"Maps seen this sync:  {len(discovered_maps)}")
        if new_maps:
            print(f"🆕 New maps found:")
            for m in sorted(new_maps):
                print(f"   - {m}")
        else:
            print("No new maps.")

        save_last_sync()
        save_known_maps(known_maps | discovered_maps)


asyncio.run(sync())