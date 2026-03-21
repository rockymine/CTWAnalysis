"""Layout audit: populate layout_layer_stats and layout_block_inventory in the DB.

Public entry point:
- run(args): scan output parquet files for each map and upsert audit tables
"""

import sys
from pathlib import Path


_AUDIT_LAYERS: list[tuple[str, str]] = [
    ('y0',           'layout_y0.parquet'),
    ('bedrock',      'layout_bedrock.parquet'),
    ('top_surface',  'layout_top_surface.parquet'),
    ('lowest_solid', 'layout_lowest_solid.parquet'),
]


def run(args: object) -> None:
    """Populate layout_layer_stats and layout_block_inventory in the database."""
    import duckdb
    import pandas as pd

    from ctw.common import ensure_match_db
    from match_analysis.database.schema import migrate_layout_audit_tables

    ensure_match_db()
    migrate_layout_audit_tables()

    output_root = Path(args.dir)
    if not output_root.is_dir():
        print(f"Error: directory not found: {output_root}", file=sys.stderr)
        sys.exit(1)

    if args.all_maps:
        map_slugs = [d.name for d in sorted(output_root.iterdir()) if d.is_dir()]
    else:
        map_slugs = [m.strip() for m in args.map.split(',') if m.strip()]

    conn = duckdb.connect('match_analysis/metadata.db')

    n_processed = 0
    n_skipped = 0

    for map_slug in map_slugs:
        map_dir = output_root / map_slug
        if not map_dir.is_dir():
            print(f"  Warning: output dir not found for '{map_slug}', skipping")
            n_skipped += 1
            continue

        row = conn.execute(
            "SELECT map_id FROM maps WHERE map_slug = ?", [map_slug]
        ).fetchone()
        if row is None:
            print(f"  Warning: '{map_slug}' not in maps table, skipping")
            n_skipped += 1
            continue

        map_id: int = row[0]

        for layer_name, filename in _AUDIT_LAYERS:
            parquet_path = map_dir / filename
            if not parquet_path.exists():
                continue

            try:
                df = pd.read_parquet(parquet_path)
            except Exception as e:
                print(f"  Warning: failed to read {parquet_path}: {e}")
                continue

            if df.empty:
                continue

            block_count = len(df)
            y_min: int | None = None
            y_max: int | None = None
            if 'y' in df.columns:
                y_min = int(df['y'].min())
                y_max = int(df['y'].max())

            conn.execute(
                "DELETE FROM layout_layer_stats WHERE map_id = ? AND layer = ?",
                [map_id, layer_name],
            )
            conn.execute(
                """
                INSERT INTO layout_layer_stats (map_id, layer, block_count, y_min, y_max, scanned_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [map_id, layer_name, block_count, y_min, y_max],
            )

            conn.execute(
                "DELETE FROM layout_block_inventory WHERE map_id = ? AND layer = ?",
                [map_id, layer_name],
            )
            if 'block_id' in df.columns:
                counts = (
                    df.groupby('block_id', sort=False)
                    .size()
                    .reset_index(name='cnt')
                )
                conn.executemany(
                    "INSERT INTO layout_block_inventory VALUES (?, ?, ?, ?)",
                    [
                        (map_id, layer_name, int(r['block_id']), int(r['cnt']))
                        for _, r in counts.iterrows()
                    ],
                )

        n_processed += 1
        if n_processed % 50 == 0:
            print(f"  {n_processed}/{len(map_slugs)} maps processed...")

    conn.close()
    print(f"\nAudit complete: {n_processed} maps processed, {n_skipped} skipped")
