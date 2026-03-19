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
            last_updated TIMESTAMP,
            traffic_graph_match_hash TEXT,
            traffic_graph_built_at TIMESTAMP
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
            spatial_classified BOOLEAN DEFAULT FALSE,
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

    # Table 10: Life segment traffic features (spatial classify step output)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS life_segment_traffic_features (
            segment_id     INTEGER PRIMARY KEY,
            snapped_sequence TEXT,
            max_attack_depth FLOAT,
            death_region   TEXT,
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

    # Table N+5: Layout layer statistics (block counts per map per layer)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS layout_layer_stats (
            map_id      INTEGER NOT NULL,
            layer       TEXT NOT NULL,
            block_count INTEGER NOT NULL,
            y_min       INTEGER,
            y_max       INTEGER,
            scanned_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (map_id, layer),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)

    # Table N+6: Layout block inventory (unique block IDs per map per layer)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS layout_block_inventory (
            map_id      INTEGER NOT NULL,
            layer       TEXT NOT NULL,
            block_id    INTEGER NOT NULL,
            block_count INTEGER NOT NULL,
            PRIMARY KEY (map_id, layer, block_id),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)

    # Table N+7: Map wool chest locations (verified from first-touch events)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS map_wool_locations (
            map_id            INTEGER NOT NULL,
            wool_id           INTEGER NOT NULL,
            wool_color        TEXT NOT NULL,
            team              TEXT,
            x                 FLOAT NOT NULL,
            z                 FLOAT NOT NULL,
            source            TEXT NOT NULL,
            first_touch_count INTEGER,
            x_std             FLOAT,
            z_std             FLOAT,
            PRIMARY KEY (map_id, wool_id),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)

    # Table: Map terrain height (surface_y and lowest_y per island cell per map)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS map_terrain_height (
            map_id    INTEGER NOT NULL,
            world_x   INTEGER NOT NULL,
            world_z   INTEGER NOT NULL,
            surface_y INTEGER NOT NULL,
            lowest_y  INTEGER,
            PRIMARY KEY (map_id, world_x, world_z),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)

    # Table N+8: Map wool monument positions (verified from capture events)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS map_wool_monuments (
            map_id         INTEGER NOT NULL,
            wool_id        INTEGER NOT NULL,
            wool_color     TEXT NOT NULL,
            monument_x     FLOAT NOT NULL,
            monument_z     FLOAT NOT NULL,
            capture_count  INTEGER NOT NULL DEFAULT 0,
            source         TEXT NOT NULL,
            PRIMARY KEY (map_id, wool_id, monument_x, monument_z),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)

    # Table: UUID → Minecraft name cache (reusable across features)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS uuid_name_cache (
            uuid       TEXT PRIMARY KEY,
            name       TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Table: Map authors and contributors
    conn.execute("""
        CREATE TABLE IF NOT EXISTS map_authors (
            map_id  INTEGER NOT NULL,
            uuid    TEXT NOT NULL,
            name    TEXT,
            role    TEXT NOT NULL CHECK(role IN ('author', 'contributor')),
            PRIMARY KEY (map_id, uuid),
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
    # life_segment_features view removed — skeleton tables dropped in migration


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


def _run_traffic_graph_migration(conn) -> None:
    """Execute all traffic-graph schema migration statements on an existing conn."""
    # Drop the old life_segment_features object. On a legacy DB it is a TABLE;
    # after migration it is a VIEW. DuckDB raises a type-mismatch error if the
    # wrong DROP variant is used, so check the catalog first.
    obj_type = conn.execute(
        "SELECT table_type FROM information_schema.tables "
        "WHERE table_name = 'life_segment_features'"
    ).fetchone()
    if obj_type is not None:
        if obj_type[0] == 'VIEW':
            conn.execute("DROP VIEW life_segment_features")
        else:
            conn.execute("DROP TABLE life_segment_features")

    # Create the three new tables
    conn.execute("""
        CREATE TABLE IF NOT EXISTS life_segment_summary (
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
            y_avg FLOAT,
            y_max INTEGER,
            frac_time_elevated FLOAT,
            cluster_id INTEGER,
            cluster_label TEXT,
            FOREIGN KEY (segment_id) REFERENCES life_segments(segment_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS life_segment_skeleton_features (
            segment_id INTEGER PRIMARY KEY,
            visited_junction BOOLEAN,
            frac_island_visits_with_junction FLOAT,
            max_node_degree_visited INTEGER,
            traversal_rate FLOAT,
            avg_nodes_per_island_visit FLOAT,
            died_at_endpoint BOOLEAN,
            n_unique_corridors INTEGER,
            position_entropy FLOAT,
            dominant_node_frac FLOAT,
            FOREIGN KEY (segment_id) REFERENCES life_segments(segment_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS life_segment_traffic_features (
            segment_id INTEGER PRIMARY KEY,
            snapped_sequence TEXT,
            unique_nodes INTEGER,
            min_enemy_wool_dist FLOAT,
            avg_home_wool_dist FLOAT,
            span_m FLOAT,
            tortuosity FLOAT,
            FOREIGN KEY (segment_id) REFERENCES life_segments(segment_id)
        )
    """)

    # Recreate the backward-compat view
    conn.execute("DROP VIEW IF EXISTS life_segment_features")
    conn.execute("""
        CREATE VIEW life_segment_features AS
        SELECT
            s.segment_id,
            s.n_islands_visited, s.n_build_regions_visited, s.n_transitions,
            s.frac_time_home_island, s.frac_time_enemy_island,
            s.frac_time_neutral_island, s.frac_time_build,
            s.max_attack_depth, s.target_wool_id,
            s.ended_on_enemy_island, s.ended_in_build,
            s.duration_s, s.time_to_first_departure_s,
            s.kills, s.deaths, s.kill_in_build, s.kill_on_enemy_island,
            s.wool_touches, s.wool_captures,
            s.y_avg, s.y_max, s.frac_time_elevated,
            s.cluster_id, s.cluster_label,
            sk.visited_junction, sk.frac_island_visits_with_junction,
            sk.max_node_degree_visited, sk.traversal_rate,
            sk.avg_nodes_per_island_visit, sk.died_at_endpoint,
            sk.n_unique_corridors, sk.position_entropy, sk.dominant_node_frac
        FROM life_segment_summary s
        LEFT JOIN life_segment_skeleton_features sk USING (segment_id)
    """)

    # Add new columns to maps table
    conn.execute(
        "ALTER TABLE maps ADD COLUMN IF NOT EXISTS traffic_graph_match_hash TEXT"
    )
    conn.execute(
        "ALTER TABLE maps ADD COLUMN IF NOT EXISTS traffic_graph_built_at TIMESTAMP"
    )


def migrate_traffic_graph_tables(
    db_path: str | None = None,
    conn=None,
) -> None:
    """Migrate database to the split life_segment_features schema.

    - Drops life_segment_features VIEW if it exists
    - Drops life_segment_features TABLE if it exists (old schema — wipes data,
      user must reprocess)
    - Creates life_segment_summary with CREATE TABLE IF NOT EXISTS
    - Creates life_segment_skeleton_features with CREATE TABLE IF NOT EXISTS
    - Creates life_segment_traffic_features with CREATE TABLE IF NOT EXISTS
    - Recreates the life_segment_features VIEW
    - Adds traffic_graph_match_hash and traffic_graph_built_at to maps table

    Safe to run repeatedly — IF NOT EXISTS guards prevent re-creation.

    Parameters
    ----------
    db_path:
        Path to the DuckDB file. Ignored if ``conn`` is provided.
    conn:
        Existing DuckDB connection to reuse. When provided, no new connection
        is opened — useful when called from within an active transaction to
        avoid DuckDB's single-writer lock.
    """
    _owns_conn = conn is None
    if _owns_conn:
        if db_path is None:
            db_path = str(Path('match_analysis/metadata.db'))
        conn = duckdb.connect(db_path)

    try:
        _run_traffic_graph_migration(conn)
    finally:
        if _owns_conn:
            conn.close()

    if _owns_conn:
        print(
            f"Traffic graph tables migrated in {db_path}. "
            "Re-run post-processing to repopulate life_segment_summary and "
            "life_segment_skeleton_features."
        )


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
        ("symmetry_confidence", "FLOAT"),
        ("has_intra_team_symmetry", "BOOLEAN"),
    ]:
        conn.execute(
            f"ALTER TABLE maps ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
        )
    conn.close()
    print(f"Map classification columns migrated in {db_path}")


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


def migrate_layout_audit_tables(db_path: str | None = None) -> None:
    """Create layout_layer_stats and layout_block_inventory tables if missing."""
    if db_path is None:
        db_path = str(Path('match_analysis/metadata.db'))
    conn = duckdb.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS layout_layer_stats (
            map_id      INTEGER NOT NULL,
            layer       TEXT NOT NULL,
            block_count INTEGER NOT NULL,
            y_min       INTEGER,
            y_max       INTEGER,
            scanned_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (map_id, layer),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS layout_block_inventory (
            map_id      INTEGER NOT NULL,
            layer       TEXT NOT NULL,
            block_id    INTEGER NOT NULL,
            block_count INTEGER NOT NULL,
            PRIMARY KEY (map_id, layer, block_id),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)
    conn.close()
    print(f"Layout audit tables created/verified in {db_path}")


def migrate_spatial_relations_tables(db_path: str | None = None) -> None:
    """Create map_wool_attack_relations and map_team_spatial tables if absent.

    Safe to run repeatedly — CREATE TABLE IF NOT EXISTS guards prevent re-creation.

    Parameters
    ----------
    db_path:
        Path to the DuckDB file. Defaults to 'match_analysis/metadata.db'.
    """
    if db_path is None:
        db_path = str(Path('match_analysis/metadata.db'))
    conn = duckdb.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS map_wool_attack_relations (
            map_id               INTEGER NOT NULL,
            attacking_team       TEXT    NOT NULL,
            wool_id              INTEGER NOT NULL,
            defending_team       TEXT,
            wool_color           TEXT    NOT NULL,
            wool_x               FLOAT   NOT NULL,
            wool_z               FLOAT   NOT NULL,
            spawn_x              FLOAT   NOT NULL,
            spawn_z              FLOAT   NOT NULL,
            cross_val            FLOAT   NOT NULL,
            dot_val              FLOAT   NOT NULL,
            distance             FLOAT   NOT NULL,
            angle_deg            FLOAT   NOT NULL,
            relative_side        TEXT    NOT NULL,
            relative_depth       TEXT    NOT NULL,
            defending_side       TEXT,
            defending_angle_deg  FLOAT,
            PRIMARY KEY (map_id, attacking_team, wool_id),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)
    # Migrate existing tables that predate defending_side/defending_angle_deg columns
    conn.execute("""
        ALTER TABLE map_wool_attack_relations
        ADD COLUMN IF NOT EXISTS defending_side TEXT
    """)
    conn.execute("""
        ALTER TABLE map_wool_attack_relations
        ADD COLUMN IF NOT EXISTS defending_angle_deg FLOAT
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS map_team_spatial (
            map_id          INTEGER NOT NULL,
            from_team       TEXT    NOT NULL,
            to_team         TEXT    NOT NULL,
            from_spawn_x    FLOAT   NOT NULL,
            from_spawn_z    FLOAT   NOT NULL,
            to_spawn_x      FLOAT   NOT NULL,
            to_spawn_z      FLOAT   NOT NULL,
            cross_val       FLOAT   NOT NULL,
            dot_val         FLOAT   NOT NULL,
            distance        FLOAT   NOT NULL,
            angle_deg       FLOAT   NOT NULL,
            relative_side   TEXT    NOT NULL,
            relative_depth  TEXT    NOT NULL,
            PRIMARY KEY (map_id, from_team, to_team),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)
    conn.close()


def migrate_wool_objectives_table(db_path: str | None = None) -> None:
    """Create map_wool_objectives table if it does not exist yet.

    Stores the many-to-many relationship between wools and the teams that
    must capture them — information that map_wool_locations cannot represent
    because its primary key only allows one team per wool.

    Safe to run repeatedly — CREATE TABLE IF NOT EXISTS guards prevent re-creation.

    Parameters
    ----------
    db_path:
        Path to the DuckDB file. Defaults to 'match_analysis/metadata.db'.
    """
    if db_path is None:
        db_path = str(Path('match_analysis/metadata.db'))
    conn = duckdb.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS map_wool_objectives (
            map_id      INTEGER NOT NULL,
            wool_id     INTEGER NOT NULL,
            wool_color  TEXT    NOT NULL,
            team        TEXT    NOT NULL,
            source      TEXT    NOT NULL,
            PRIMARY KEY (map_id, wool_id, team),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)
    conn.close()


def migrate_wool_location_tables(db_path: str | None = None) -> None:
    """Create map_wool_locations and map_wool_monuments tables if they do not exist yet.

    Safe to run repeatedly — CREATE TABLE IF NOT EXISTS guards prevent re-creation.

    Parameters
    ----------
    db_path:
        Path to the DuckDB file. Defaults to 'match_analysis/metadata.db'.
    """
    if db_path is None:
        db_path = str(Path('match_analysis/metadata.db'))
    conn = duckdb.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS map_wool_locations (
            map_id            INTEGER NOT NULL,
            wool_id           INTEGER NOT NULL,
            wool_color        TEXT NOT NULL,
            team              TEXT,
            x                 FLOAT NOT NULL,
            z                 FLOAT NOT NULL,
            source            TEXT NOT NULL,
            first_touch_count INTEGER,
            x_std             FLOAT,
            z_std             FLOAT,
            PRIMARY KEY (map_id, wool_id),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS map_wool_monuments (
            map_id         INTEGER NOT NULL,
            wool_id        INTEGER NOT NULL,
            wool_color     TEXT NOT NULL,
            monument_x     FLOAT NOT NULL,
            monument_z     FLOAT NOT NULL,
            capture_count  INTEGER NOT NULL DEFAULT 0,
            source         TEXT NOT NULL,
            PRIMARY KEY (map_id, wool_id, monument_x, monument_z),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)
    conn.close()


def migrate_authors_tables(db_path: str | None = None) -> None:
    """Create uuid_name_cache and map_authors tables if they do not exist yet."""
    if db_path is None:
        db_path = str(Path('match_analysis/metadata.db'))
    conn = duckdb.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS uuid_name_cache (
            uuid       TEXT PRIMARY KEY,
            name       TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS map_authors (
            map_id  INTEGER NOT NULL,
            uuid    TEXT NOT NULL,
            name    TEXT,
            role    TEXT NOT NULL CHECK(role IN ('author', 'contributor')),
            PRIMARY KEY (map_id, uuid),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)
    conn.close()
    print(f"Author tables created/verified in {db_path}")


def migrate_terrain_height_table(db_path: str | None = None) -> None:
    """Create map_terrain_height table if it does not exist yet.

    Safe to run repeatedly — CREATE TABLE IF NOT EXISTS prevents re-creation.

    Parameters
    ----------
    db_path:
        Path to the DuckDB file. Defaults to 'match_analysis/metadata.db'.
    """
    if db_path is None:
        db_path = str(Path('match_analysis/metadata.db'))
    conn = duckdb.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS map_terrain_height (
            map_id    INTEGER NOT NULL,
            world_x   INTEGER NOT NULL,
            world_z   INTEGER NOT NULL,
            surface_y INTEGER NOT NULL,
            lowest_y  INTEGER,
            PRIMARY KEY (map_id, world_x, world_z),
            FOREIGN KEY (map_id) REFERENCES maps(map_id)
        )
    """)
    conn.close()
    print(f"map_terrain_height table created/verified in {db_path}")


if __name__ == "__main__":
    initialize_database()
