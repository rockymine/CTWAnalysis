import duckdb

original  = 'match_analysis/metadata.db'
compacted = 'match_analysis/metadata_compacted.db'

conn = duckdb.connect()
conn.execute(f"ATTACH '{original}'  AS db1 (READ_ONLY)")
conn.execute(f"ATTACH '{compacted}' AS db2 (READ_ONLY)")

tables = [
    row[0] for row in
    conn.execute("SELECT table_name FROM duckdb_tables() WHERE database_name = 'db1' ORDER BY table_name").fetchall()
]

print(f"{'Table':<35} {'Orig rows':>12} {'Copy rows':>12} {'Match':>6}")
print("-" * 70)

all_ok = True
for table in tables:
    orig_count = conn.execute(f"SELECT COUNT(*) FROM db1.{table}").fetchone()[0]
    copy_count = conn.execute(f"SELECT COUNT(*) FROM db2.{table}").fetchone()[0]
    match = orig_count == copy_count
    if not match:
        all_ok = False
    flag = "OK" if match else "MISMATCH"
    print(f"{table:<35} {orig_count:>12,} {copy_count:>12,} {flag:>6}")

print("-" * 70)
if all_ok:
    print("All tables match. Compacted DB is consistent with original.")
else:
    print("VERIFICATION FAILED — some tables differ. Do not swap the databases.")

conn.close()
