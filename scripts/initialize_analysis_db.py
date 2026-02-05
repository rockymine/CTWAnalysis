#!/usr/bin/env python3
"""Create DuckDB metadata database with required tables."""

import duckdb
from pathlib import Path


def initialize_database():
    """Create DuckDB metadata database with required tables."""
    db_path = Path('match_analysis/metadata.db')
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))

    # Table 1: Match metadata
    conn.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            match_id INTEGER PRIMARY KEY,
            match_file TEXT NOT NULL UNIQUE,
            map_name TEXT NOT NULL,
            match_start TIMESTAMP,
            match_duration FLOAT,
            player_count INTEGER,
            position_count INTEGER,
            processed BOOLEAN DEFAULT FALSE,
            processed_at TIMESTAMP,
            processing_time FLOAT
        )
    """)

    # Table 2: Life segment summaries
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS seq_segment_id START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS life_segments (
            segment_id INTEGER PRIMARY KEY DEFAULT nextval('seq_segment_id'),
            match_id INTEGER NOT NULL,
            player_id INTEGER NOT NULL,
            segment_idx INTEGER NOT NULL,
            start_timestamp BIGINT NOT NULL,
            end_timestamp BIGINT NOT NULL,
            duration FLOAT,
            outcome TEXT,
            spawn_x FLOAT,
            spawn_z FLOAT,
            position_count INTEGER,
            kill_count INTEGER,
            wool_touches INTEGER,
            wool_captures INTEGER,
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        )
    """)

    # Table 3: Processing log
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS seq_log_id START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS processing_log (
            log_id INTEGER PRIMARY KEY DEFAULT nextval('seq_log_id'),
            match_id INTEGER NOT NULL,
            step TEXT NOT NULL,
            status TEXT NOT NULL,
            duration FLOAT,
            error_message TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        )
    """)

    conn.close()
    print(f"Database initialized at {db_path}")


if __name__ == "__main__":
    initialize_database()
