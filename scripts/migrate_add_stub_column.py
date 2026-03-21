"""Add stub BOOLEAN column to maps table.

Marks rows that were auto-created by 'matches index' for log-file slugs that
have no processed map data yet. Existing rows are set to FALSE (fully loaded).
"""

import duckdb

conn = duckdb.connect('match_analysis/metadata.db')
try:
    conn.execute("ALTER TABLE maps ADD COLUMN stub BOOLEAN DEFAULT FALSE")
    print("Added 'stub' column to maps table (all existing rows set to FALSE).")
except Exception as error:
    print(f"Migration skipped: {error}")
finally:
    conn.close()
