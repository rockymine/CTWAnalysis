import duckdb

DB_PATH = 'match_analysis/metadata.db'

conn = duckdb.connect(DB_PATH)

before = conn.execute("SELECT COUNT(*) FROM matches WHERE match_start IS NULL").fetchone()[0]
print(f"Rows with NULL match_start before: {before:,}")

conn.execute("""
    UPDATE matches
    SET match_start = strptime(
        regexp_extract(match_file, '(\\d{4}-\\d{2}-\\d{2}_\\d{2}-\\d{2}-\\d{2})', 1),
        '%Y-%m-%d_%H-%M-%S'
    )
    WHERE match_start IS NULL
""")

after = conn.execute("SELECT COUNT(*) FROM matches WHERE match_start IS NULL").fetchone()[0]
filled = conn.execute("SELECT COUNT(*) FROM matches WHERE match_start IS NOT NULL").fetchone()[0]
print(f"Rows with NULL match_start after:  {after:,}")
print(f"Rows filled:                       {filled:,}")

conn.close()
