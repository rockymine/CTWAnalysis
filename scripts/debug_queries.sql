-- =============================================================================
-- CTW Analysis — Debug & Verification Queries
-- Run against match_analysis/metadata.db (DuckDB)
-- Usage: ctw db --list | ctw db --run <id> | ctw db --all
-- =============================================================================

-- =====================
-- 1. INVENTORY
-- =====================

-- 1a. All maps with match counts
SELECT mp.map_slug, mp.map_name, COUNT(mat.match_id) AS matches,
       SUM(mat.player_count) AS total_players,
       ROUND(AVG(mat.match_duration), 0) AS avg_duration_s
FROM maps mp
LEFT JOIN matches mat ON mp.map_id = mat.map_id
GROUP BY mp.map_slug, mp.map_name
ORDER BY matches DESC;

-- 1b. Full match listing
SELECT mat.match_id, mp.map_slug,
       ROUND(mat.match_duration, 0) AS duration_s,
       mat.player_count, mat.position_count, mat.processed
FROM matches mat
JOIN maps mp ON mat.map_id = mp.map_id
ORDER BY mat.match_id;

-- 1c. Processing status summary
SELECT processed, COUNT(*) AS matches
FROM matches
GROUP BY processed;

-- 1d. Unprocessed matches
SELECT mat.match_id, mp.map_slug, mat.match_file
FROM matches mat
JOIN maps mp ON mat.map_id = mp.map_id
WHERE mat.processed = FALSE
ORDER BY mat.match_id;

-- 1e. Row counts per table
SELECT 'maps' AS tbl, COUNT(*) AS rows FROM maps
UNION ALL SELECT 'map_spawns', COUNT(*) FROM map_spawns
UNION ALL SELECT 'matches', COUNT(*) FROM matches
UNION ALL SELECT 'life_segments', COUNT(*) FROM life_segments
UNION ALL SELECT 'combat_events', COUNT(*) FROM combat_events
UNION ALL SELECT 'position_events', COUNT(*) FROM position_events
UNION ALL SELECT 'player_team_segments', COUNT(*) FROM player_team_segments
UNION ALL SELECT 'processing_log', COUNT(*) FROM processing_log;

-- 1f. Map spawns overview
SELECT mp.map_slug, ms.team, ms.team_color,
       ROUND(ms.x, 1) AS x, ROUND(ms.z, 1) AS z
FROM map_spawns ms
JOIN maps mp ON ms.map_id = mp.map_id
ORDER BY mp.map_slug, ms.team;


-- =====================
-- 2. TEAM SEGMENTS
-- =====================

-- 2a. Maps with "unknown" team assignments
SELECT mp.map_slug, COUNT(*) AS unknown_segments,
       COUNT(DISTINCT pts.player_id) AS affected_players
FROM player_team_segments pts
JOIN matches mat ON mat.match_id = pts.match_id
JOIN maps mp ON mat.map_id = mp.map_id
WHERE pts.team = 'unknown'
GROUP BY mp.map_slug
ORDER BY unknown_segments DESC;

-- 2b. Team distribution per map
SELECT mp.map_slug, pts.team, COUNT(*) AS segments,
       COUNT(DISTINCT pts.player_id) AS players
FROM player_team_segments pts
JOIN matches mat ON mat.match_id = pts.match_id
JOIN maps mp ON mat.map_id = mp.map_id
GROUP BY mp.map_slug, pts.team
ORDER BY mp.map_slug, pts.team;

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
SELECT pts.match_id, mp.map_slug, pts.player_id,
       COUNT(*) AS team_segments,
       LIST(pts.team ORDER BY pts.start_timestamp) AS team_sequence
FROM player_team_segments pts
JOIN matches mat ON mat.match_id = pts.match_id
JOIN maps mp ON mat.map_id = mp.map_id
GROUP BY pts.match_id, mp.map_slug, pts.player_id
HAVING COUNT(DISTINCT pts.team) > 1
ORDER BY pts.match_id, pts.player_id;

-- 2e. Matches missing team segments entirely
SELECT mat.match_id, mp.map_slug, mat.player_count
FROM matches mat
JOIN maps mp ON mat.map_id = mp.map_id
LEFT JOIN player_team_segments pts ON mat.match_id = pts.match_id
WHERE mat.processed = TRUE AND pts.match_id IS NULL
ORDER BY mat.match_id;


-- =====================
-- 3. SPATIAL ANNOTATION
-- =====================

-- 3a. Annotation coverage per map
SELECT mp.map_slug,
       COUNT(*) AS total_positions,
       COUNT(pe.location_type) AS annotated,
       COUNT(*) - COUNT(pe.location_type) AS unannotated,
       ROUND(100.0 * COUNT(pe.location_type) / COUNT(*), 1) AS pct_annotated
FROM position_events pe
JOIN matches mat ON mat.match_id = pe.match_id
JOIN maps mp ON mat.map_id = mp.map_id
GROUP BY mp.map_slug
ORDER BY pct_annotated;

-- 3b. Location type distribution per map
SELECT mp.map_slug, pe.location_type, COUNT(*) AS positions
FROM position_events pe
JOIN matches mat ON mat.match_id = pe.match_id
JOIN maps mp ON mat.map_id = mp.map_id
WHERE pe.location_type IS NOT NULL
GROUP BY mp.map_slug, pe.location_type
ORDER BY mp.map_slug, positions DESC;

-- 3c. Positions classified as "void" (outside all islands)
SELECT mp.map_slug, mat.match_id, COUNT(*) AS void_positions
FROM position_events pe
JOIN matches mat ON mat.match_id = pe.match_id
JOIN maps mp ON mat.map_id = mp.map_id
WHERE pe.location_type = 'void'
GROUP BY mp.map_slug, mat.match_id
ORDER BY void_positions DESC;

-- 3d. Island usage — which islands see the most traffic
SELECT mp.map_slug, pe.island_id, pe.location_type, COUNT(*) AS visits
FROM position_events pe
JOIN matches mat ON mat.match_id = pe.match_id
JOIN maps mp ON mat.map_id = mp.map_id
WHERE pe.island_id IS NOT NULL
GROUP BY mp.map_slug, pe.island_id, pe.location_type
ORDER BY mp.map_slug, visits DESC;


-- =====================
-- 4. COMBAT & LIFE SEGMENTS
-- =====================

-- 4a. Life segment outcome distribution per map
SELECT mp.map_slug, ls.outcome, COUNT(*) AS segments
FROM life_segments ls
JOIN matches mat ON mat.match_id = ls.match_id
JOIN maps mp ON mat.map_id = mp.map_id
GROUP BY mp.map_slug, ls.outcome
ORDER BY mp.map_slug, segments DESC;

-- 4b. Combat events with team labels (sample)
SELECT ce.match_id, ce.player_id, ce.event_type, ce.timestamp,
       pts.team, ce.victim_id
FROM combat_events ce
LEFT JOIN player_team_segments pts
  ON ce.match_id = pts.match_id
  AND ce.player_id = pts.player_id
  AND ce.timestamp >= pts.start_timestamp
  AND (pts.end_timestamp IS NULL OR ce.timestamp < pts.end_timestamp)
ORDER BY ce.match_id, ce.timestamp
LIMIT 50;

-- 4c. Friendly fire — kills where killer and victim are on the same team
SELECT ce.match_id, mp.map_slug, ce.player_id AS killer, ce.victim_id AS victim,
       killer_team.team AS killer_team, victim_team.team AS victim_team, ce.timestamp
FROM combat_events ce
JOIN matches mat ON mat.match_id = ce.match_id
JOIN maps mp ON mat.map_id = mp.map_id
LEFT JOIN player_team_segments killer_team
  ON ce.match_id = killer_team.match_id
  AND ce.player_id = killer_team.player_id
  AND ce.timestamp >= killer_team.start_timestamp
  AND (killer_team.end_timestamp IS NULL OR ce.timestamp < killer_team.end_timestamp)
LEFT JOIN player_team_segments victim_team
  ON ce.match_id = victim_team.match_id
  AND ce.victim_id = victim_team.player_id
  AND ce.timestamp >= victim_team.start_timestamp
  AND (victim_team.end_timestamp IS NULL OR ce.timestamp < victim_team.end_timestamp)
WHERE ce.event_type = 3
  AND killer_team.team = victim_team.team
  AND killer_team.team != 'unknown'
ORDER BY ce.match_id, ce.timestamp;

-- 4d. Kill/death stats per team per map
SELECT mp.map_slug, pts.team,
       SUM(CASE WHEN ce.event_type = 3 THEN 1 ELSE 0 END) AS kills,
       SUM(CASE WHEN ce.event_type = 4 THEN 1 ELSE 0 END) AS deaths
FROM combat_events ce
JOIN matches mat ON mat.match_id = ce.match_id
JOIN maps mp ON mat.map_id = mp.map_id
LEFT JOIN player_team_segments pts
  ON ce.match_id = pts.match_id
  AND ce.player_id = pts.player_id
  AND ce.timestamp >= pts.start_timestamp
  AND (pts.end_timestamp IS NULL OR ce.timestamp < pts.end_timestamp)
GROUP BY mp.map_slug, pts.team
ORDER BY mp.map_slug, pts.team;


-- =====================
-- 5. DATA INTEGRITY
-- =====================

-- 5a. Matches with no life segments (should be 0 for processed matches)
SELECT mat.match_id, mp.map_slug, mat.processed
FROM matches mat
JOIN maps mp ON mat.map_id = mp.map_id
LEFT JOIN life_segments ls ON mat.match_id = ls.match_id
WHERE ls.match_id IS NULL AND mat.processed = TRUE
ORDER BY mat.match_id;

-- 5b. Matches with no position events (should be 0 for processed matches)
SELECT mat.match_id, mp.map_slug, mat.processed
FROM matches mat
JOIN maps mp ON mat.map_id = mp.map_id
LEFT JOIN position_events pe ON mat.match_id = pe.match_id
WHERE pe.match_id IS NULL AND mat.processed = TRUE
ORDER BY mat.match_id;

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

-- 5d. Processing log — failed steps
SELECT pl.match_id, mp.map_slug, pl.step, pl.status, pl.error_message
FROM processing_log pl
JOIN matches mat ON mat.match_id = pl.match_id
JOIN maps mp ON mat.map_id = mp.map_id
WHERE pl.status != 'success'
ORDER BY pl.match_id, pl.step;

-- 5e. Duplicate match files (should return 0 rows)
SELECT match_file, COUNT(*) AS dupes
FROM matches
GROUP BY match_file
HAVING COUNT(*) > 1;

-- 5f. Maps without spawns loaded
SELECT mp.map_slug, mp.map_name
FROM maps mp
LEFT JOIN map_spawns ms ON mp.map_id = ms.map_id
WHERE ms.spawn_id IS NULL
ORDER BY mp.map_slug;
