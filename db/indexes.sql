-- =====================================================================
-- Secondary indexes (Stage 3: "describe what indexes you have and which
-- queries/reports they support"). Primary keys and UNIQUE constraints
-- already create indexes; the ones below are the extra ones we chose.
--
-- The loader creates these AFTER the bulk load (building an index once is
-- faster than updating it on every insert).
-- Prove each one with EXPLAIN (ANALYZE) before/after - see plan.md section 12.
-- =====================================================================

-- 1. Scouting Report (Requirement 2): filter by season range and phase.
--    Query: ... FROM mv_player_phase_stats WHERE season_year BETWEEN %s AND %s AND phase = ANY(%s)
--    The unique index (player_id, season_year, phase) starts with player_id, so it
--    cannot serve a season-range filter; this one can (Bitmap Index Scan, ~0.5 ms).
CREATE INDEX IF NOT EXISTS ix_mv_phase_season_phase
    ON mv_player_phase_stats (season_year, phase);

-- 2. Scouting Report season-level columns (matches, 50s, MVP points) by season range.
CREATE INDEX IF NOT EXISTS ix_mv_season_season
    ON mv_player_season_stats (season_year);

-- 3. "Current team" filter on the report, the team drop-down -> squad list,
--    and the salary join (contract for the latest season).
--    Query: SELECT ... FROM contract WHERE season_year = %s AND franchise_id = %s
CREATE INDEX IF NOT EXISTS ix_contract_season_franchise
    ON contract (season_year, franchise_id);

-- 4. Player profile page / pace-vs-spin drill-down for ONE player
--    (reads ~7k of 296k deliveries for a regular player instead of scanning all).
--    Query: SELECT ... FROM delivery WHERE batter_id = %s   /  WHERE bowler_id = %s
CREATE INDEX IF NOT EXISTS ix_delivery_batter ON delivery (batter_id);
CREATE INDEX IF NOT EXISTS ix_delivery_bowler ON delivery (bowler_id);

-- 5. Dismissals of one player (batting average on the profile page).
CREATE INDEX IF NOT EXISTS ix_dismissal_player_out ON dismissal (player_out_id);

-- 6. Team and venue pages filtered by season; match list by date.
CREATE INDEX IF NOT EXISTS ix_match_season_date ON match (season_year, match_date);
CREATE INDEX IF NOT EXISTS ix_match_venue       ON match (venue_id);

-- Considered and NOT added (talking points for the demo):
--  * draft_pick(board_id): already covered by UNIQUE (board_id, player_id), whose index
--    starts with board_id - used by the purse/slot check inside the "Buy" transaction.
--  * Trigram (pg_trgm GIN) index for the player search box (ILIKE '%kohli%'): tested,
--    and with only ~816 players the planner still chose a sequential scan (~0.5 ms),
--    so the index would only cost write time and space. Revisit above ~10k players.
--  * role, franchise, season, venue: tiny tables (<= 40 rows); a sequential scan is cheaper.
