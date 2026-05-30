import duckdb
import os
import shutil
import tempfile

original = 'match_analysis/metadata.db'
compacted = 'match_analysis/metadata_compacted.db'

if os.path.exists(compacted):
    os.remove(compacted)

tmpdir = tempfile.mkdtemp(prefix='duckdb_compact_')
try:
    # Export schema + data to a temp directory.
    # DuckDB writes schema.sql in topological FK order, so IMPORT handles
    # constraint ordering automatically. Parquet preserves types exactly.
    print("Exporting...")
    conn = duckdb.connect(original, read_only=True)
    conn.execute(f"EXPORT DATABASE '{tmpdir}' (FORMAT PARQUET)")
    conn.close()

    print("Importing...")
    conn = duckdb.connect(compacted)
    conn.execute(f"IMPORT DATABASE '{tmpdir}'")
    conn.close()
finally:
    shutil.rmtree(tmpdir)

original_size = os.path.getsize(original)
compacted_size = os.path.getsize(compacted)
print(f"Original:  {original_size  / 1024 / 1024:.2f} MB")
print(f"Compacted: {compacted_size / 1024 / 1024:.2f} MB")
print(f"Saved:     {(original_size - compacted_size) / 1024 / 1024:.2f} MB")

# Rename original → .old, then promote compacted → original
archived = original.replace('.db', '_old.db')
os.rename(original, archived)
os.rename(compacted, original)
print(f"Archived original as: {archived}")
print(f"Compacted DB is now:  {original}")