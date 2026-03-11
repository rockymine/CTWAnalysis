#!/usr/bin/env python3
"""Create DuckDB metadata database with required tables."""

import duckdb
from pathlib import Path


def initialize_database() -> None:
    """Create DuckDB metadata database with required tables."""
    db_path = Path('match_analysis/metadata.db')
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))

    # Table 1: Maps metadata (must precede matches for FK)
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS seq_map_id START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS maps (
            map_id INTEGER PRIMARY KEY DEFAULT nextval('seq_map_id'),
            map_slug TEXT NOT NULL UNIQUE,
            map_name TEXT NOT NULL,
            max_build_height INTEGER,
            min_x FLOAT NOT NULL,
            max_x FLOAT NOT NULL,
            min_z FLOAT NOT NULL,
            max_z FLOAT NOT NULL,
            center_x FLOAT NOT NULL,
            center_z FLOAT NOT NULL,
            island_count INTEGER NOT NULL,
            team_count INTEGER,
            last_updated TIMESTAMP
        )
    """)

    # Table 2: Map spawns (spawn locations per map)
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS seq_map_spawn_id START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS map_spawns (
            spawn_id INTEGER PRIMARY KEY DEFAULT nextval('seq_map_spawn_id'),
            map_id INTEGER NOT NULL,
            x FLOAT NOT NULL,
            z FLOAT NOT NULL,
            min_x FLOAT NOT NULL,
            min_z FLOAT NOT NULL,
            max_x FLOAT NOT NULL,
            max_z FLOAT NOT NULL,
            team TEXT NOT NULL,
            team_color TEXT NOT NULL,
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)

    # Table 3: Match metadata
    conn.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            match_id INTEGER PRIMARY KEY,
            match_file TEXT NOT NULL UNIQUE,
            map_id INTEGER NOT NULL,
            match_start TIMESTAMP,
            match_duration FLOAT,
            player_count INTEGER,
            position_count INTEGER,
            processed BOOLEAN DEFAULT FALSE,
            processed_at TIMESTAMP,
            processing_time FLOAT,
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)

    # Table 4: Life segment summaries
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

    # Table 5: Combat events (kills + deaths)
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS seq_combat_id START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combat_events (
            combat_id INTEGER PRIMARY KEY DEFAULT nextval('seq_combat_id'),
            match_id INTEGER NOT NULL,
            timestamp INTEGER NOT NULL,
            event_type INTEGER NOT NULL,
            player_id INTEGER NOT NULL,
            victim_id INTEGER,
            x INTEGER,
            y INTEGER,
            z INTEGER,
            segment_idx INTEGER,
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        )
    """)

    # Table 6: Wool events (touch + capture)
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS seq_wool_event_id START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wool_events (
            wool_event_id INTEGER PRIMARY KEY DEFAULT nextval('seq_wool_event_id'),
            match_id INTEGER NOT NULL,
            timestamp INTEGER NOT NULL,
            event_type INTEGER NOT NULL,
            player_id INTEGER NOT NULL,
            wool_id INTEGER,
            x INTEGER,
            y INTEGER,
            z INTEGER,
            segment_idx INTEGER,
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        )
    """)

    # Table 7: Position events (type 5 only)
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS seq_position_id START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS position_events (
            position_id INTEGER PRIMARY KEY DEFAULT nextval('seq_position_id'),
            match_id INTEGER NOT NULL,
            timestamp INTEGER NOT NULL,
            player_id INTEGER NOT NULL,
            x INTEGER NOT NULL,
            y INTEGER NOT NULL,
            z INTEGER NOT NULL,
            segment_idx INTEGER,
            location_type TEXT,
            island_id INTEGER,
            nearest_node_1 INTEGER,
            nearest_node_2 INTEGER,
            nearest_island_1 INTEGER,
            nearest_island_2 INTEGER,
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        )
    """)

    # Table 7: Processing log
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

    # Table 8: Player team segments (team membership over time)
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS seq_team_segment_id START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS player_team_segments (
            team_segment_id INTEGER PRIMARY KEY DEFAULT nextval('seq_team_segment_id'),
            match_id INTEGER NOT NULL,
            player_id INTEGER NOT NULL,
            team TEXT NOT NULL,
            start_timestamp BIGINT NOT NULL,
            end_timestamp BIGINT,
            spawn_x FLOAT,
            spawn_z FLOAT,
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        )
    """)

    conn.close()
    print(f"Database initialized at {db_path}")


def migrate_log_interval_column() -> None:
    """Add log_interval column to matches and backfill from position_events.

    Migration functions in this file:

    | Function                          | What it adds                                                                  |
    |-----------------------------------|-------------------------------------------------------------------------------|
    | `migrate_log_interval_column()`   | `log_interval` to `matches` (2 or 5 — position sampling interval in seconds) |
    """
    db_path = Path('match_analysis/metadata.db')
    conn = duckdb.connect(str(db_path))

    conn.execute("""
        ALTER TABLE matches ADD COLUMN IF NOT EXISTS log_interval INTEGER
    """)

    conn.execute("""
        UPDATE matches
        SET log_interval = derived.log_interval
        FROM (
            WITH gaps AS (
                SELECT match_id,
                       timestamp - LAG(timestamp) OVER (
                           PARTITION BY match_id, player_id, segment_idx
                           ORDER BY timestamp
                       ) AS dt
                FROM position_events
            )
            SELECT match_id,
                   CASE WHEN MEDIAN(dt) >= 4 THEN 5 ELSE 2 END AS log_interval
            FROM gaps
            WHERE dt IS NOT NULL AND dt > 0
            GROUP BY match_id
        ) derived
        WHERE matches.match_id = derived.match_id
          AND matches.processed = TRUE
    """)

    conn.close()
    print("Migration complete: log_interval column added and backfilled")


if __name__ == "__main__":
    initialize_database()
