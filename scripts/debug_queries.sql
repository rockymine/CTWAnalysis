-- =============================================================================
-- CTW Analysis — Debug & Verification Queries
-- Run against match_analysis/metadata.db (DuckDB)
-- Usage: ctw db --list | ctw db --run <id> | ctw db --all
-- =============================================================================

-- 0a. All maps with matches

SELECT mp.map_slug
FROM maps mp
ORDER BY mp.map_slug ASC

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

-- 1b. Matches for a specific map (sorted by most positions)
SELECT mat.match_id, mp.map_slug, mat.player_count AS players,
       ROUND(mat.match_duration, 0) AS duration_s,
       mat.position_count AS positions, mat.processed,
       ROUND(gaps.median_gap, 1) AS interval_s
FROM matches mat
JOIN maps mp ON mat.map_id = mp.map_id
LEFT JOIN (
    SELECT match_id, MEDIAN(gap) AS median_gap
    FROM (
        SELECT match_id,
               timestamp - LAG(timestamp) OVER (
                   PARTITION BY match_id, player_id ORDER BY timestamp
               ) AS gap
        FROM position_events
    )
    WHERE gap > 0 AND gap < 30
    GROUP BY match_id
) gaps ON gaps.match_id = mat.match_id
WHERE mp.map_slug = 'expedition'
ORDER BY mat.position_count DESC;

-- 1c. Full match listing (all maps)
SELECT mat.match_id, mp.map_slug,
       ROUND(mat.match_duration, 0) AS duration_s,
       mat.player_count, mat.position_count, mat.processed
FROM matches mat
JOIN maps mp ON mat.map_id = mp.map_id
ORDER BY mat.match_id;

-- 1d. Processing status summary
SELECT processed, COUNT(*) AS matches
FROM matches
GROUP BY processed;

-- 1e. Unprocessed matches
SELECT mat.match_id, mp.map_slug, mat.match_file
FROM matches mat
JOIN maps mp ON mat.map_id = mp.map_id
WHERE mat.processed = FALSE
ORDER BY mat.match_id;

-- 1f. Row counts per table
SELECT 'maps' AS tbl, COUNT(*) AS rows FROM maps
UNION ALL SELECT 'map_spawns', COUNT(*) FROM map_spawns
UNION ALL SELECT 'matches', COUNT(*) FROM matches
UNION ALL SELECT 'life_segments', COUNT(*) FROM life_segments
UNION ALL SELECT 'combat_events', COUNT(*) FROM combat_events
UNION ALL SELECT 'position_events', COUNT(*) FROM position_events
UNION ALL SELECT 'player_team_segments', COUNT(*) FROM player_team_segments
UNION ALL SELECT 'processing_log', COUNT(*) FROM processing_log;

-- 1g. Map spawns overview
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

-- 5e. Stub maps — maps indexed from file structure but never run through ctw run
SELECT mp.map_slug, COUNT(mat.match_id) AS match_count
FROM maps mp
LEFT JOIN matches mat ON mp.map_id = mat.map_id
WHERE mp.stub = TRUE
GROUP BY mp.map_slug
ORDER BY match_count DESC;

-- 5f. Duplicate match files (should return 0 rows)
SELECT match_file, COUNT(*) AS dupes
FROM matches
GROUP BY match_file
HAVING COUNT(*) > 1;

-- 5g. Maps without spawns loaded
SELECT mp.map_slug, mp.map_name
FROM maps mp
LEFT JOIN map_spawns ms ON mp.map_id = ms.map_id
WHERE ms.spawn_id IS NULL
ORDER BY mp.map_slug;

-- 6a. Maps with block 36 in y0 layer
SELECT m.map_slug, m.map_name,
        SUM(CASE WHEN inv.block_id = 36 THEN inv.block_count ELSE 0 END) as block36,
        ls.block_count as total,
        ROUND(100.0 * SUM(CASE WHEN inv.block_id = 36 THEN inv.block_count ELSE 0 END) / ls.block_count, 1) as pct
FROM layout_block_inventory inv
JOIN maps m ON inv.map_id = m.map_id
JOIN layout_layer_stats ls ON inv.map_id = ls.map_id AND ls.layer = 'y0'
WHERE inv.layer = 'y0'
GROUP BY m.map_slug, m.map_name, ls.block_count
HAVING block36 > 0
ORDER BY m.map_slug ASC

-- 7a. flag suspiciously long gaps between subsequent ctw matches
WITH gap_calc AS (
    SELECT
        maps.map_slug,
        m.match_start,
        m.match_duration,
        m.match_start + (m.match_duration || ' seconds')::interval AS expected_end,
        LEAD(m.match_start) OVER (ORDER BY m.match_start) AS next_match_start,
        LEAD(maps.map_slug)  OVER (ORDER BY m.match_start) AS next_map_slug
    FROM matches m
    JOIN maps ON m.map_id = maps.map_id
    WHERE m.match_start >= '2026-01-24 10:00:00'
),
gap_sized AS (
    SELECT
        map_slug,
        match_start,
        match_duration,
        next_map_slug,
        date_diff('second', expected_end, next_match_start) AS gap_seconds
    FROM gap_calc
    WHERE date_diff('minute', expected_end, next_match_start) >= 100
)
SELECT
    map_slug AS map_before_gap,
    (CASE WHEN match_duration >= 3600 THEN floor(match_duration / 3600)::int || 'h ' ELSE '' END ||
     CASE WHEN (match_duration % 3600) >= 60 THEN floor((match_duration % 3600) / 60)::int || 'm ' ELSE '' END ||
     floor(match_duration % 60)::int || 's') AS duration,
    next_map_slug AS map_after_gap,
    (CASE WHEN gap_seconds >= 3600 THEN floor(gap_seconds / 3600)::int || 'h ' ELSE '' END ||
     CASE WHEN (gap_seconds % 3600) >= 60 THEN floor((gap_seconds % 3600) / 60)::int || 'm ' ELSE '' END ||
     (gap_seconds % 60)::int || 's') AS gap_duration
FROM gap_sized
ORDER BY match_start;

-- 8a. validate if a map has matches in the db
SELECT
    m.match_id,
    m.match_start,
    m.match_duration, -- This is in seconds
    maps.map_slug,
    m.match_file
FROM matches m
JOIN maps ON m.map_id = maps.map_id

-- =====================
-- 9. CHEST ANALYSIS
-- =====================

-- 9a. Zone × content_category cross-tab (pct of chests in each zone by category)
-- Shows how well spatial zones align with chest content semantics
WITH zone_cat AS (
    SELECT
        mc.zone,
        mc.content_category,
        COUNT(*) AS chest_count
    FROM map_chests mc
    WHERE mc.zone IS NOT NULL
      AND mc.content_category IS NOT NULL
    GROUP BY mc.zone, mc.content_category
),
zone_totals AS (
    SELECT zone, SUM(chest_count) AS zone_total
    FROM zone_cat
    GROUP BY zone
)
SELECT
    zc.zone,
    zc.content_category,
    zc.chest_count,
    zt.zone_total,
    ROUND(100.0 * zc.chest_count / zt.zone_total, 1) AS pct_of_zone
FROM zone_cat zc
JOIN zone_totals zt ON zc.zone = zt.zone
ORDER BY zc.zone, pct_of_zone DESC;

-- 9b. Defense chest material composition per map (top items by total count)
-- Useful for spotting outlier maps with unusual defense supply loadouts
SELECT
    mp.map_slug,
    mcc.item_id,
    SUM(mcc.count) AS total_items
FROM map_chests mc
JOIN maps mp ON mc.map_id = mp.map_id
JOIN map_chest_contents mcc ON mc.chest_id = mcc.chest_id
WHERE mc.content_category = 'defense'
GROUP BY mp.map_slug, mcc.item_id
ORDER BY mp.map_slug, total_items DESC;

-- 9c. Defense chest count and total items per map, sorted by intensity
-- density = defense items per wool chest (proxy for how heavily defended each wool is)
WITH defense_stats AS (
    SELECT
        mc.map_id,
        COUNT(DISTINCT mc.chest_id) AS defense_chests,
        SUM(mcc.count) AS defense_items
    FROM map_chests mc
    JOIN map_chest_contents mcc ON mc.chest_id = mcc.chest_id
    WHERE mc.content_category = 'defense'
    GROUP BY mc.map_id
),
wool_counts AS (
    SELECT map_id, COUNT(*) AS wool_count
    FROM map_chests
    WHERE content_category = 'wool'
    GROUP BY map_id
)
SELECT
    mp.map_slug,
    COALESCE(ds.defense_chests, 0) AS defense_chests,
    COALESCE(ds.defense_items, 0) AS defense_items,
    COALESCE(wc.wool_count, 0) AS wool_chests,
    CASE WHEN COALESCE(wc.wool_count, 0) > 0
         THEN ROUND(ds.defense_items::DOUBLE / wc.wool_count, 0)
         ELSE NULL END AS defense_items_per_wool
FROM maps mp
LEFT JOIN defense_stats ds ON mp.map_id = ds.map_id
LEFT JOIN wool_counts wc ON mp.map_id = wc.map_id
ORDER BY defense_items DESC NULLS LAST;

-- 9d. Content category summary across all maps
-- Quick count of how many chests fall into each category
SELECT
    content_category,
    COUNT(*) AS chest_count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM map_chests
WHERE content_category IS NOT NULL
GROUP BY content_category
ORDER BY chest_count DESC;

-- 9e. Maps with no defense chests (may rely on kit-based defense instead)
SELECT mp.map_slug, mp.map_name, COUNT(mc.chest_id) AS total_chests
FROM maps mp
LEFT JOIN map_chests mc ON mp.map_id = mc.map_id
WHERE mp.map_id NOT IN (
    SELECT DISTINCT map_id FROM map_chests WHERE content_category = 'defense'
)
GROUP BY mp.map_slug, mp.map_name
ORDER BY total_chests DESC;
WHERE maps.map_slug = 'tumbleweed'

-- 9f. Armor combination breakdown — per combat chest (what pieces are in the same chest?)
-- Shows 13 distinct combinations with chest count and map count.
SELECT
    MAX(CASE WHEN item_id LIKE '%helmet%'     THEN 1 ELSE 0 END) AS has_helmet,
    MAX(CASE WHEN item_id LIKE '%chestplate%' THEN 1 ELSE 0 END) AS has_chestplate,
    MAX(CASE WHEN item_id LIKE '%leggings%'   THEN 1 ELSE 0 END) AS has_leggings,
    MAX(CASE WHEN item_id LIKE '%boots%'      THEN 1 ELSE 0 END) AS has_boots,
    COUNT(DISTINCT (mcc.map_id, mcc.world_x, mcc.world_z, mcc.y)) AS chest_count,
    COUNT(DISTINCT mcc.map_id)                                      AS map_count,
    ROUND(100.0 * COUNT(DISTINCT (mcc.map_id, mcc.world_x, mcc.world_z, mcc.y))
          / SUM(COUNT(DISTINCT (mcc.map_id, mcc.world_x, mcc.world_z, mcc.y))) OVER (), 1) AS pct_chests
FROM map_chest_contents mcc
JOIN map_chests mc
    ON mc.map_id = mcc.map_id AND mc.world_x = mcc.world_x
    AND mc.world_z = mcc.world_z AND mc.y = mcc.y
WHERE mc.content_category = 'combat'
GROUP BY mcc.map_id, mcc.world_x, mcc.world_z, mcc.y
-- Outer aggregation: collapse to unique combinations
;
-- NOTE: the above groups per chest then needs a second aggregation. Use the CTE version:

WITH chest_armor AS (
    SELECT
        mcc.map_id, mcc.world_x, mcc.world_z, mcc.y,
        MAX(CASE WHEN item_id LIKE '%helmet%'     THEN 1 ELSE 0 END) AS has_helmet,
        MAX(CASE WHEN item_id LIKE '%chestplate%' THEN 1 ELSE 0 END) AS has_chestplate,
        MAX(CASE WHEN item_id LIKE '%leggings%'   THEN 1 ELSE 0 END) AS has_leggings,
        MAX(CASE WHEN item_id LIKE '%boots%'      THEN 1 ELSE 0 END) AS has_boots
    FROM map_chest_contents mcc
    JOIN map_chests mc
        ON mc.map_id = mcc.map_id AND mc.world_x = mcc.world_x
        AND mc.world_z = mcc.world_z AND mc.y = mcc.y
    WHERE mc.content_category = 'combat'
    GROUP BY mcc.map_id, mcc.world_x, mcc.world_z, mcc.y
)
SELECT
    has_helmet, has_chestplate, has_leggings, has_boots,
    COUNT(*)                                           AS chest_count,
    COUNT(DISTINCT map_id)                             AS map_count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_chests
FROM chest_armor
GROUP BY has_helmet, has_chestplate, has_leggings, has_boots
ORDER BY chest_count DESC;

-- 9g. Armor coverage per map — which pieces appear across all of a map's combat chests?
-- Each row = one map; flags show whether that piece appears in ANY combat chest.
WITH chest_armor AS (
    SELECT
        mcc.map_id, mcc.world_x, mcc.world_z, mcc.y,
        MAX(CASE WHEN item_id LIKE '%helmet%'     THEN 1 ELSE 0 END) AS has_helmet,
        MAX(CASE WHEN item_id LIKE '%chestplate%' THEN 1 ELSE 0 END) AS has_chestplate,
        MAX(CASE WHEN item_id LIKE '%leggings%'   THEN 1 ELSE 0 END) AS has_leggings,
        MAX(CASE WHEN item_id LIKE '%boots%'      THEN 1 ELSE 0 END) AS has_boots
    FROM map_chest_contents mcc
    JOIN map_chests mc
        ON mc.map_id = mcc.map_id AND mc.world_x = mcc.world_x
        AND mc.world_z = mcc.world_z AND mc.y = mcc.y
    WHERE mc.content_category = 'combat'
    GROUP BY mcc.map_id, mcc.world_x, mcc.world_z, mcc.y
),
map_armor AS (
    SELECT map_id,
           MAX(has_helmet)     AS uses_helmet,
           MAX(has_chestplate) AS uses_chestplate,
           MAX(has_leggings)   AS uses_leggings,
           MAX(has_boots)      AS uses_boots,
           COUNT(*)            AS combat_chests
    FROM chest_armor
    GROUP BY map_id
)
SELECT
    uses_helmet, uses_chestplate, uses_leggings, uses_boots,
    COUNT(*)                     AS map_count,
    ROUND(AVG(combat_chests), 1) AS avg_combat_chests,
    MIN(combat_chests)           AS min_chests,
    MAX(combat_chests)           AS max_chests
FROM map_armor
GROUP BY uses_helmet, uses_chestplate, uses_leggings, uses_boots
ORDER BY map_count DESC;
