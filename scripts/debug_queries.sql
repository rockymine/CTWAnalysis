-- =============================================================================
-- CTW Analysis — Debug & Verification Queries
-- Run against match_analysis/metadata.db (DuckDB)
-- =============================================================================

-- =====================
-- 1. INVENTORY
-- =====================

-- 1a. All maps with match counts
SELECT map_name, COUNT(*) AS matches,
       SUM(player_count) AS total_players,
       ROUND(AVG(match_duration), 0) AS avg_duration_s
FROM matches
GROUP BY map_name
ORDER BY matches DESC;

-- 1b. Full match listing
SELECT match_id, map_name, match_start,
       ROUND(match_duration, 0) AS duration_s,
       player_count, position_count, processed
FROM matches
ORDER BY match_id;

-- 1c. Processing status summary
SELECT processed, COUNT(*) AS matches
FROM matches
GROUP BY processed;

-- 1d. Unprocessed matches
SELECT match_id, map_name, match_file
FROM matches
WHERE processed = FALSE
ORDER BY match_id;


-- =====================
-- 2. TEAM SEGMENTS
-- =====================

-- 2a. Maps with "unknown" team assignments
SELECT m.map_name, COUNT(*) AS unknown_segments,
       COUNT(DISTINCT pts.player_id) AS affected_players
FROM player_team_segments pts
JOIN matches m ON m.match_id = pts.match_id
WHERE pts.team = 'unknown'
GROUP BY m.map_name
ORDER BY unknown_segments DESC;

-- 2b. Team distribution per map
SELECT m.map_name, pts.team, COUNT(*) AS segments,
       COUNT(DISTINCT pts.player_id) AS players
FROM player_team_segments pts
JOIN matches m ON m.match_id = pts.match_id
GROUP BY m.map_name, pts.team
ORDER BY m.map_name, pts.team;

-- 2c. Overlapping team segments (should return 0 rows)
SELECT a.match_id, a.player_id,
       a.team_segment_id AS seg_a, a.team AS team_a,
       b.team_segment_id AS seg_b, b.team AS team_b
FROM player_team_segments a
JOIN player_team_segments b
  ON a.match_id = b.match_id
  AND a.player_id = b.player_id
  AND a.team_segment_id < b.team_segment_id
  AND a.start_timestamp < COALESCE(b.end_timestamp, 9999999999)
  AND b.start_timestamp < COALESCE(a.end_timestamp, 9999999999);

-- 2d. Players who switched teams mid-match
SELECT pts.match_id, m.map_name, pts.player_id,
       COUNT(*) AS team_segments,
       LIST(pts.team ORDER BY pts.start_timestamp) AS team_sequence
FROM player_team_segments pts
JOIN matches m ON m.match_id = pts.match_id
GROUP BY pts.match_id, m.map_name, pts.player_id
HAVING COUNT(DISTINCT pts.team) > 1
ORDER BY pts.match_id, pts.player_id;

-- 2e. Matches missing team segments entirely
SELECT m.match_id, m.map_name, m.player_count
FROM matches m
LEFT JOIN player_team_segments pts ON m.match_id = pts.match_id
WHERE m.processed = TRUE AND pts.match_id IS NULL
ORDER BY m.match_id;


-- =====================
-- 3. SPATIAL ANNOTATION
-- =====================

-- 3a. Annotation coverage per map
SELECT m.map_name,
       COUNT(*) AS total_positions,
       COUNT(pe.location_type) AS annotated,
       COUNT(*) - COUNT(pe.location_type) AS unannotated,
       ROUND(100.0 * COUNT(pe.location_type) / COUNT(*), 1) AS pct_annotated
FROM position_events pe
JOIN matches m ON m.match_id = pe.match_id
GROUP BY m.map_name
ORDER BY pct_annotated;

-- 3b. Location type distribution per map
SELECT m.map_name, pe.location_type, COUNT(*) AS positions
FROM position_events pe
JOIN matches m ON m.match_id = pe.match_id
WHERE pe.location_type IS NOT NULL
GROUP BY m.map_name, pe.location_type
ORDER BY m.map_name, positions DESC;

-- 3c. Positions classified as "void" (outside all islands)
SELECT m.map_name, m.match_id, COUNT(*) AS void_positions
FROM position_events pe
JOIN matches m ON m.match_id = pe.match_id
WHERE pe.location_type = 'void'
GROUP BY m.map_name, m.match_id
ORDER BY void_positions DESC;

-- 3d. Island usage — which islands see the most traffic
SELECT m.map_name, pe.island_id, pe.location_type, COUNT(*) AS visits
FROM position_events pe
JOIN matches m ON m.match_id = pe.match_id
WHERE pe.island_id IS NOT NULL
GROUP BY m.map_name, pe.island_id, pe.location_type
ORDER BY m.map_name, visits DESC;


-- =====================
-- 4. COMBAT & LIFE SEGMENTS
-- =====================

-- 4a. Life segment outcome distribution per map
SELECT m.map_name, ls.outcome, COUNT(*) AS segments
FROM life_segments ls
JOIN matches m ON m.match_id = ls.match_id
GROUP BY m.map_name, ls.outcome
ORDER BY m.map_name, segments DESC;

-- 4b. Combat events with team labels
SELECT ce.match_id, ce.player_id, ce.event_type, ce.timestamp,
       pts.team, ce.other_player_id
FROM combat_events ce
LEFT JOIN player_team_segments pts
  ON ce.match_id = pts.match_id
  AND ce.player_id = pts.player_id
  AND ce.timestamp >= pts.start_timestamp
  AND (pts.end_timestamp IS NULL OR ce.timestamp < pts.end_timestamp)
ORDER BY ce.match_id, ce.timestamp
LIMIT 50;

-- 4c. Friendly fire — kills where killer and victim are on the same team
SELECT ce.match_id, m.map_name, ce.player_id AS killer, ce.other_player_id AS victim,
       killer_team.team AS killer_team, victim_team.team AS victim_team, ce.timestamp
FROM combat_events ce
JOIN matches m ON m.match_id = ce.match_id
LEFT JOIN player_team_segments killer_team
  ON ce.match_id = killer_team.match_id
  AND ce.player_id = killer_team.player_id
  AND ce.timestamp >= killer_team.start_timestamp
  AND (killer_team.end_timestamp IS NULL OR ce.timestamp < killer_team.end_timestamp)
LEFT JOIN player_team_segments victim_team
  ON ce.match_id = victim_team.match_id
  AND ce.other_player_id = victim_team.player_id
  AND ce.timestamp >= victim_team.start_timestamp
  AND (victim_team.end_timestamp IS NULL OR ce.timestamp < victim_team.end_timestamp)
WHERE ce.event_type = 'KILL'
  AND killer_team.team = victim_team.team
  AND killer_team.team != 'unknown'
ORDER BY ce.match_id, ce.timestamp;

-- 4d. Kill/death stats per team per map
SELECT m.map_name, pts.team,
       SUM(CASE WHEN ce.event_type = 'KILL' THEN 1 ELSE 0 END) AS kills,
       SUM(CASE WHEN ce.event_type = 'DEATH' THEN 1 ELSE 0 END) AS deaths
FROM combat_events ce
JOIN matches m ON m.match_id = ce.match_id
LEFT JOIN player_team_segments pts
  ON ce.match_id = pts.match_id
  AND ce.player_id = pts.player_id
  AND ce.timestamp >= pts.start_timestamp
  AND (pts.end_timestamp IS NULL OR ce.timestamp < pts.end_timestamp)
GROUP BY m.map_name, pts.team
ORDER BY m.map_name, pts.team;


-- =====================
-- 5. DATA INTEGRITY
-- =====================

-- 5a. Matches with no life segments (should be 0 for processed matches)
SELECT m.match_id, m.map_name, m.processed
FROM matches m
LEFT JOIN life_segments ls ON m.match_id = ls.match_id
WHERE ls.match_id IS NULL AND m.processed = TRUE
ORDER BY m.match_id;

-- 5b. Matches with no position events (should be 0 for processed matches)
SELECT m.match_id, m.map_name, m.processed
FROM matches m
LEFT JOIN position_events pe ON m.match_id = pe.match_id
WHERE pe.match_id IS NULL AND m.processed = TRUE
ORDER BY m.match_id;

-- 5c. Orphaned records — events referencing non-existent matches
SELECT 'life_segments' AS tbl, COUNT(*) AS orphans
FROM life_segments ls LEFT JOIN matches m ON ls.match_id = m.match_id WHERE m.match_id IS NULL
UNION ALL
SELECT 'combat_events', COUNT(*)
FROM combat_events ce LEFT JOIN matches m ON ce.match_id = m.match_id WHERE m.match_id IS NULL
UNION ALL
SELECT 'position_events', COUNT(*)
FROM position_events pe LEFT JOIN matches m ON pe.match_id = m.match_id WHERE m.match_id IS NULL
UNION ALL
SELECT 'player_team_segments', COUNT(*)
FROM player_team_segments pts LEFT JOIN matches m ON pts.match_id = m.match_id WHERE m.match_id IS NULL;

-- 5d. Row counts per table
SELECT 'matches' AS tbl, COUNT(*) AS rows FROM matches
UNION ALL SELECT 'life_segments', COUNT(*) FROM life_segments
UNION ALL SELECT 'combat_events', COUNT(*) FROM combat_events
UNION ALL SELECT 'position_events', COUNT(*) FROM position_events
UNION ALL SELECT 'player_team_segments', COUNT(*) FROM player_team_segments
UNION ALL SELECT 'processing_log', COUNT(*) FROM processing_log;

-- 5e. Processing log — failed steps
SELECT pl.match_id, m.map_name, pl.step, pl.status, pl.message
FROM processing_log pl
JOIN matches m ON m.match_id = pl.match_id
WHERE pl.status != 'success'
ORDER BY pl.match_id, pl.step;

-- 5f. Duplicate match files (should return 0 rows)
SELECT match_file, COUNT(*) AS dupes
FROM matches
GROUP BY match_file
HAVING COUNT(*) > 1;

-- 5g. Map name casing check — should all be lowercase
SELECT DISTINCT map_name
FROM matches
WHERE map_name != LOWER(map_name);
