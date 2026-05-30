import duckdb
from pathlib import Path

LOGS_DIR = Path("C:/Users/Michael/source/repos/PGMLoggerResults/logs")
DB_PATH  = Path("match_analysis/metadata.db")

log_slugs = {p.name for p in LOGS_DIR.iterdir() if p.is_dir()}

conn = duckdb.connect(str(DB_PATH), read_only=True)
db_slugs = {row[0] for row in conn.execute("SELECT map_slug FROM maps").fetchall()}
conn.close()

missing = sorted(log_slugs - db_slugs)

print(f"Log folders:   {len(log_slugs)}")
print(f"In DB:         {len(db_slugs)}")
print(f"Missing:       {len(missing)}\n")
for slug in missing:
    print(f"  {slug}")
