#!/usr/bin/env python3
"""Test script for database setup and match processing."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from match_analysis.database.schema import initialize_database
from match_analysis.database.indexer import index_match_files
from match_analysis.processing.processor import process_match
import duckdb


def main():
    print("=" * 70)
    print("MATCH ANALYSIS DATABASE SETUP TEST")
    print("=" * 70)

    # Step 1: Initialize database
    print("\n[1/5] Initializing database...")
    initialize_database()

    # Step 2: Index all match files
    print("\n[2/5] Indexing match files...")
    indexed, skipped = index_match_files('match_logs')

    # Step 3: Show summary
    print("\n[3/5] Database summary:")
    conn = duckdb.connect('match_analysis/metadata.db')

    result = conn.execute("""
        SELECT
            COUNT(*) as total_matches,
            COUNT(DISTINCT map_name) as unique_maps,
            SUM(player_count) as total_player_records,
            SUM(position_count) as total_positions,
            AVG(match_duration) as avg_duration
        FROM matches
    """).fetchone()

    print(f"   Total matches: {result[0]}")
    print(f"   Unique maps: {result[1]}")
    print(f"   Total player records: {result[2]}")
    print(f"   Total positions: {result[3]}")
    print(f"   Average match duration: {result[4]:.1f}s")

    # Step 4: Show matches
    print("\n[4/5] Match details:")
    results = conn.execute("""
        SELECT match_id, match_file, player_count, match_duration
        FROM matches
        ORDER BY match_id
    """).fetchall()

    for match_id, match_file, players, duration in results:
        filename = Path(match_file).name
        print(f"   Match {match_id}: {filename} ({players} players, {duration:.0f}s)")

    # Step 5: Process first match
    if results:
        first_match_id = results[0][0]
        print(f"\n[5/5] Processing first match (ID {first_match_id})...")
        conn.close()

        process_match(first_match_id)

        # Verify results
        conn = duckdb.connect('match_analysis/metadata.db')
        result = conn.execute("""
            SELECT processed, processing_time
            FROM matches
            WHERE match_id = ?
        """, [first_match_id]).fetchone()

        if result[0]:
            print(f"\n   Match processed successfully in {result[1]:.2f}s")

            output_file = f'match_analysis/trajectories/{first_match_id}.parquet'
            if Path(output_file).exists():
                import pandas as pd
                df = pd.read_parquet(output_file)
                print(f"   Life segments saved: {len(df)} segments")
        else:
            print("\n   Match processing failed")

    conn.close()

    print("\n" + "=" * 70)
    print("Setup complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
