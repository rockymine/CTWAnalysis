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
            held_item INTEGER,
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
            nearest_graph_node INTEGER,
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

    # Table 9: Wool spawn baselines (post-processing)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wool_spawn_baselines (
            map_id INTEGER NOT NULL,
            team TEXT NOT NULL,
            wool_id INTEGER NOT NULL,
            spawn_x FLOAT NOT NULL,
            spawn_z FLOAT NOT NULL,
            wool_x FLOAT NOT NULL,
            wool_z FLOAT NOT NULL,
            baseline_distance FLOAT NOT NULL,
            PRIMARY KEY (map_id, team, wool_id),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)

    # Table 10: Life segment region visits (post-processing)
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS seq_visit_id START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS life_segment_region_visits (
            visit_id INTEGER PRIMARY KEY DEFAULT nextval('seq_visit_id'),
            segment_id INTEGER NOT NULL,
            match_id INTEGER NOT NULL,
            player_id INTEGER NOT NULL,
            visit_idx INTEGER NOT NULL,
            location_type TEXT NOT NULL,
            island_id INTEGER,
            bridge_island_1 INTEGER,
            bridge_island_2 INTEGER,
            entry_timestamp BIGINT NOT NULL,
            exit_timestamp BIGINT NOT NULL,
            duration_s FLOAT NOT NULL,
            is_home_island BOOLEAN,
            is_enemy_island BOOLEAN,
            kill_count INTEGER NOT NULL DEFAULT 0,
            was_death BOOLEAN NOT NULL DEFAULT FALSE,
            entry_node INTEGER,
            exit_node INTEGER,
            bridge_node_1 INTEGER,
            bridge_node_2 INTEGER,
            node_path TEXT,
            FOREIGN KEY (segment_id) REFERENCES life_segments(segment_id),
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        )
    """)

    # Table 11: Life segment features (post-processing)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS life_segment_features (
            segment_id INTEGER PRIMARY KEY,
            n_islands_visited INTEGER,
            n_build_regions_visited INTEGER,
            n_transitions INTEGER,
            frac_time_home_island FLOAT,
            frac_time_enemy_island FLOAT,
            frac_time_neutral_island FLOAT,
            frac_time_build FLOAT,
            max_attack_depth FLOAT,
            target_wool_id INTEGER,
            ended_on_enemy_island BOOLEAN,
            ended_in_build BOOLEAN,
            duration_s FLOAT,
            time_to_first_departure_s FLOAT,
            kills INTEGER,
            deaths INTEGER,
            kill_in_build INTEGER,
            kill_on_enemy_island INTEGER,
            wool_touches INTEGER,
            wool_captures INTEGER,
            -- Node-path metrics (require life_segment_region_visits.node_path)
            visited_junction BOOLEAN,
            frac_island_visits_with_junction FLOAT,
            max_node_degree_visited INTEGER,
            traversal_rate FLOAT,
            avg_nodes_per_island_visit FLOAT,
            died_at_endpoint BOOLEAN,
            n_unique_corridors INTEGER,
            position_entropy FLOAT,
            dominant_node_frac FLOAT,
            cluster_id INTEGER,
            cluster_label TEXT,
            FOREIGN KEY (segment_id) REFERENCES life_segments(segment_id)
        )
    """)

    # Table N: Map resource blocks (iron/gold/diamond blocks, classified by zone)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS map_resource_blocks (
            map_id        INTEGER NOT NULL,
            world_x       INTEGER NOT NULL,
            world_z       INTEGER NOT NULL,
            y             INTEGER NOT NULL,
            resource_type TEXT NOT NULL,
            zone          TEXT NOT NULL,
            team          TEXT,
            PRIMARY KEY (map_id, world_x, world_z, y),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)

    # Table N+1: Map chests (located and zone-classified)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS map_chests (
            map_id         INTEGER NOT NULL,
            world_x        INTEGER NOT NULL,
            world_z        INTEGER NOT NULL,
            y              INTEGER NOT NULL,
            chest_type     TEXT NOT NULL,
            zone           TEXT NOT NULL,
            team           TEXT,
            is_double      BOOLEAN NOT NULL DEFAULT FALSE,
            chest_group_id INTEGER,
            PRIMARY KEY (map_id, world_x, world_z, y),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)

    # Table N+2: Map chest contents (inventory items per chest)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS map_chest_contents (
            map_id      INTEGER NOT NULL,
            world_x     INTEGER NOT NULL,
            world_z     INTEGER NOT NULL,
            y           INTEGER NOT NULL,
            slot        INTEGER NOT NULL,
            item_id     TEXT NOT NULL,
            item_damage INTEGER NOT NULL DEFAULT 0,
            count       INTEGER NOT NULL,
            PRIMARY KEY (map_id, world_x, world_z, y, slot),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)

    # Table N+3: Map kit items (inventory slots from spawn kit)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS map_kit_items (
            map_id       INTEGER NOT NULL,
            kit_id       TEXT NOT NULL,
            team         TEXT NOT NULL DEFAULT '',
            slot         INTEGER NOT NULL,
            material     TEXT NOT NULL,
            amount       INTEGER NOT NULL DEFAULT 1,
            item_damage  INTEGER NOT NULL DEFAULT 0,
            unbreakable  BOOLEAN NOT NULL DEFAULT FALSE,
            team_color   BOOLEAN NOT NULL DEFAULT FALSE,
            enchantments TEXT,
            PRIMARY KEY (map_id, kit_id, team, slot),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)

    # Table N+4: Map kit armor (armor slots from spawn kit)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS map_kit_armor (
            map_id       INTEGER NOT NULL,
            kit_id       TEXT NOT NULL,
            team         TEXT NOT NULL DEFAULT '',
            slot_name    TEXT NOT NULL,
            material     TEXT NOT NULL,
            unbreakable  BOOLEAN NOT NULL DEFAULT FALSE,
            team_color   BOOLEAN NOT NULL DEFAULT FALSE,
            enchantments TEXT,
            PRIMARY KEY (map_id, kit_id, team, slot_name),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)

    _create_views(conn)

    conn.close()
    print(f"Database initialized at {db_path}")


def _create_views(conn) -> None:
    """Create or replace derived views."""
    conn.execute("DROP VIEW IF EXISTS map_size_buckets")
    conn.execute("""
        CREATE VIEW map_size_buckets AS
        WITH ranked AS (
            SELECT
                map_id,
                map_slug,
                total_blocks,
                NTILE(5) OVER (ORDER BY total_blocks) AS bucket_rank
            FROM maps
            WHERE wools_per_team > 0
              AND total_blocks IS NOT NULL
              AND total_blocks > 0
        )
        SELECT
            map_id,
            map_slug,
            total_blocks,
            bucket_rank,
            CASE bucket_rank
                WHEN 1 THEN 'tiny'
                WHEN 2 THEN 'small'
                WHEN 3 THEN 'medium'
                WHEN 4 THEN 'large'
                WHEN 5 THEN 'huge'
            END AS map_size_bucket
        FROM ranked
    """)


def _ensure_wool_carry_chains_table(conn) -> None:
    """Create wool_carry_chains table if it does not exist yet."""
    conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_chain_id START 1")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wool_carry_chains (
            chain_id    INTEGER PRIMARY KEY DEFAULT nextval('seq_chain_id'),
            match_id    INTEGER NOT NULL,
            wool_id     INTEGER NOT NULL,
            wave_idx    INTEGER NOT NULL,
            attacking_team TEXT,
            n_carriers  INTEGER NOT NULL DEFAULT 1,
            n_handoffs  INTEGER NOT NULL DEFAULT 0,
            start_timestamp BIGINT NOT NULL,
            end_timestamp   BIGINT,
            duration_s  FLOAT,
            outcome     TEXT,
            first_x     INTEGER, first_y INTEGER, first_z INTEGER,
            final_x     INTEGER, final_y INTEGER, final_z INTEGER,
            max_y_before_touch INTEGER,
            approach_type TEXT,
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        )
    """)


def migrate_y_columns(db_path: str | None = None) -> None:
    """Add Y-level feature columns to life_segment_features and create
    wool_carry_chains table if missing."""
    if db_path is None:
        db_path = str(Path('match_analysis/metadata.db'))
    conn = duckdb.connect(db_path)
    for col_name, col_type in [
        ("y_avg", "FLOAT"),
        ("y_max", "INTEGER"),
        ("frac_time_elevated", "FLOAT"),
    ]:
        conn.execute(
            f"ALTER TABLE life_segment_features "
            f"ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
        )
    _ensure_wool_carry_chains_table(conn)
    conn.close()
    print(f"Y-level columns and wool_carry_chains migrated in {db_path}")


def migrate_views(db_path: str | None = None) -> None:
    """Create or replace all derived views in an existing database."""
    if db_path is None:
        db_path = str(Path('match_analysis/metadata.db'))
    conn = duckdb.connect(db_path)
    _create_views(conn)
    conn.close()
    print(f"Views created/replaced in {db_path}")


def migrate_map_classification_columns(db_path: str | None = None) -> None:
    """Add map classification columns to the maps table.

    Safe to run on an already-migrated database — DuckDB silently skips
    ADD COLUMN for columns that already exist when using IF NOT EXISTS.
    """
    if db_path is None:
        db_path = str(Path('match_analysis/metadata.db'))
    conn = duckdb.connect(db_path)
    for col_name, col_type in [
        ("wools_per_team", "INTEGER"),
        ("max_players_per_team", "INTEGER"),
        ("total_blocks", "INTEGER"),
        ("size_tier", "VARCHAR"),
        ("symmetry_type", "VARCHAR"),
        ("has_intra_team_symmetry", "BOOLEAN"),
    ]:
        conn.execute(
            f"ALTER TABLE maps ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
        )
    conn.close()
    print(f"Map classification columns migrated in {db_path}")


def migrate_node_path_columns(db_path: str | None = None) -> None:
    """Add node-path feature columns to an existing life_segment_features table.

    Safe to run on an already-migrated database — DuckDB silently skips
    ADD COLUMN for columns that already exist when using IF NOT EXISTS.
    """
    if db_path is None:
        db_path = str(Path('match_analysis/metadata.db'))
    conn = duckdb.connect(db_path)
    new_columns = [
        ("visited_junction", "BOOLEAN"),
        ("frac_island_visits_with_junction", "FLOAT"),
        ("max_node_degree_visited", "INTEGER"),
        ("traversal_rate", "FLOAT"),
        ("avg_nodes_per_island_visit", "FLOAT"),
        ("died_at_endpoint", "BOOLEAN"),
        ("n_unique_corridors", "INTEGER"),
        ("position_entropy", "FLOAT"),
        ("dominant_node_frac", "FLOAT"),
    ]
    for col_name, col_type in new_columns:
        conn.execute(
            f"ALTER TABLE life_segment_features "
            f"ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
        )
    conn.close()
    print(f"Node-path columns migrated in {db_path}")


def migrate_log_interval_column(db_path: str | None = None) -> None:
    """Add log_interval column to matches and backfill from position_events.

    Safe to run on an already-migrated database — DuckDB silently skips
    ADD COLUMN for columns that already exist when using IF NOT EXISTS.
    """
    if db_path is None:
        db_path = str(Path('match_analysis/metadata.db'))
    conn = duckdb.connect(db_path)

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
    print(f"log_interval column added and backfilled in {db_path}")


def migrate_resource_tables(db_path: str | None = None) -> None:
    """Create map_resource_blocks, map_chests, and map_chest_contents if missing."""
    if db_path is None:
        db_path = str(Path('match_analysis/metadata.db'))
    conn = duckdb.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS map_resource_blocks (
            map_id        INTEGER NOT NULL,
            world_x       INTEGER NOT NULL,
            world_z       INTEGER NOT NULL,
            y             INTEGER NOT NULL,
            resource_type TEXT NOT NULL,
            zone          TEXT NOT NULL,
            team          TEXT,
            PRIMARY KEY (map_id, world_x, world_z, y),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS map_chests (
            map_id         INTEGER NOT NULL,
            world_x        INTEGER NOT NULL,
            world_z        INTEGER NOT NULL,
            y              INTEGER NOT NULL,
            chest_type     TEXT NOT NULL,
            zone           TEXT NOT NULL,
            team           TEXT,
            is_double      BOOLEAN NOT NULL DEFAULT FALSE,
            chest_group_id INTEGER,
            PRIMARY KEY (map_id, world_x, world_z, y),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS map_chest_contents (
            map_id      INTEGER NOT NULL,
            world_x     INTEGER NOT NULL,
            world_z     INTEGER NOT NULL,
            y           INTEGER NOT NULL,
            slot        INTEGER NOT NULL,
            item_id     TEXT NOT NULL,
            item_damage INTEGER NOT NULL DEFAULT 0,
            count       INTEGER NOT NULL,
            PRIMARY KEY (map_id, world_x, world_z, y, slot),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)
    conn.close()
    print(f"Resource tables created in {db_path}")


def migrate_kit_tables(db_path: str | None = None) -> None:
    """Create map_kit_items and map_kit_armor tables if they do not exist yet."""
    if db_path is None:
        db_path = str(Path('match_analysis/metadata.db'))
    conn = duckdb.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS map_kit_items (
            map_id       INTEGER NOT NULL,
            kit_id       TEXT NOT NULL,
            team         TEXT NOT NULL DEFAULT '',
            slot         INTEGER NOT NULL,
            material     TEXT NOT NULL,
            amount       INTEGER NOT NULL DEFAULT 1,
            item_damage  INTEGER NOT NULL DEFAULT 0,
            unbreakable  BOOLEAN NOT NULL DEFAULT FALSE,
            team_color   BOOLEAN NOT NULL DEFAULT FALSE,
            enchantments TEXT,
            PRIMARY KEY (map_id, kit_id, team, slot),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS map_kit_armor (
            map_id       INTEGER NOT NULL,
            kit_id       TEXT NOT NULL,
            team         TEXT NOT NULL DEFAULT '',
            slot_name    TEXT NOT NULL,
            material     TEXT NOT NULL,
            unbreakable  BOOLEAN NOT NULL DEFAULT FALSE,
            team_color   BOOLEAN NOT NULL DEFAULT FALSE,
            enchantments TEXT,
            PRIMARY KEY (map_id, kit_id, team, slot_name),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)
    conn.close()
    print(f"Kit tables created in {db_path}")


if __name__ == "__main__":
    initialize_database()
