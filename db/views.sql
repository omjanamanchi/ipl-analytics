-- =====================================================================
-- Analytics layer: every metric is DERIVED from delivery/dismissal rows.
-- Materialized views are refreshed by the loader after each data load:
--   REFRESH MATERIALIZED VIEW CONCURRENTLY mv_player_phase_stats;
--   REFRESH MATERIALIZED VIEW CONCURRENTLY mv_player_season_stats;
-- Super-over innings are excluded from all player and team statistics.
-- Phases: Powerplay = overs 1-6, Middle = 7-15, Death = 16-20.
-- =====================================================================

DROP VIEW IF EXISTS v_draft_board_summary, v_venue_stats, v_team_season_stats,
                    v_innings_summary, v_player_report_base CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mv_player_phase_stats, mv_player_season_stats CASCADE;

-- ---------------------------------------------------------------------
-- Innings totals (used for team run rates, NRR, venue averages)
-- ---------------------------------------------------------------------
CREATE VIEW v_innings_summary AS
SELECT i.match_id, i.innings_no, i.batting_team_id, i.bowling_team_id, m.season_year, m.venue_id,
       COALESCE(SUM(d.total_runs), 0)                          AS runs,
       COUNT(*) FILTER (WHERE d.is_legal_ball)                 AS legal_balls,
       (SELECT COUNT(*) FROM dismissal x
         WHERE x.match_id = i.match_id AND x.innings_no = i.innings_no
           AND x.kind <> 'retired hurt')                       AS wickets,
       COALESCE(i.target_overs, 20)                            AS quota_overs,
       COALESCE(SUM(d.total_runs) FILTER (WHERE d.phase = 'Powerplay'), 0) AS pp_runs,
       COUNT(*) FILTER (WHERE d.phase = 'Powerplay' AND d.is_legal_ball)   AS pp_balls,
       COALESCE(SUM(d.total_runs) FILTER (WHERE d.phase = 'Death'), 0)     AS death_runs,
       COUNT(*) FILTER (WHERE d.phase = 'Death' AND d.is_legal_ball)       AS death_balls
FROM innings i
JOIN match m      ON m.match_id = i.match_id
LEFT JOIN delivery d ON d.match_id = i.match_id AND d.innings_no = i.innings_no
WHERE NOT i.is_super_over
GROUP BY i.match_id, i.innings_no, i.batting_team_id, i.bowling_team_id, m.season_year, m.venue_id, i.target_overs;

-- ---------------------------------------------------------------------
-- Player x season x phase: rate stats (additive counts only)
-- ---------------------------------------------------------------------
CREATE MATERIALIZED VIEW mv_player_phase_stats AS
WITH d AS (
    SELECT d.*, m.season_year, bp.bowling_type AS bowler_type
    FROM delivery d
    JOIN innings i ON i.match_id = d.match_id AND i.innings_no = d.innings_no AND NOT i.is_super_over
    JOIN match m   ON m.match_id = d.match_id
    JOIN player bp ON bp.player_id = d.bowler_id
),
bat AS (
    SELECT batter_id AS player_id, season_year, phase,
           SUM(batter_runs)                                            AS runs,
           COUNT(*) FILTER (WHERE is_ball_faced)                       AS balls_faced,
           COUNT(*) FILTER (WHERE batter_runs = 4)                     AS fours,
           COUNT(*) FILTER (WHERE batter_runs = 6)                     AS sixes,
           COUNT(*) FILTER (WHERE is_ball_faced AND batter_runs = 0)   AS dots_faced,
           SUM(batter_runs) FILTER (WHERE bowler_type = 'Pace')        AS runs_vs_pace,
           COUNT(*) FILTER (WHERE is_ball_faced AND bowler_type = 'Pace') AS balls_vs_pace,
           SUM(batter_runs) FILTER (WHERE bowler_type = 'Spin')        AS runs_vs_spin,
           COUNT(*) FILTER (WHERE is_ball_faced AND bowler_type = 'Spin') AS balls_vs_spin
    FROM d GROUP BY 1, 2, 3
),
outs AS (
    SELECT x.player_out_id AS player_id, d.season_year, d.phase,
           COUNT(*)                                          AS outs,
           COUNT(*) FILTER (WHERE d.bowler_type = 'Pace')    AS outs_vs_pace,
           COUNT(*) FILTER (WHERE d.bowler_type = 'Spin')    AS outs_vs_spin
    FROM dismissal x
    JOIN d ON d.match_id = x.match_id AND d.innings_no = x.innings_no AND d.seq = x.seq
    WHERE x.kind <> 'retired hurt'
    GROUP BY 1, 2, 3
),
bowl AS (
    SELECT bowler_id AS player_id, season_year, phase,
           COUNT(*) FILTER (WHERE is_legal_ball)                       AS legal_balls_bowled,
           SUM(bowler_runs)                                            AS runs_conceded,
           COUNT(*) FILTER (WHERE is_legal_ball AND bowler_runs = 0)   AS dots_bowled,
           COUNT(*) FILTER (WHERE batter_runs = 4)                     AS fours_conceded,
           COUNT(*) FILTER (WHERE batter_runs = 6)                     AS sixes_conceded,
           COUNT(*) FILTER (WHERE wides > 0)                           AS wides,
           COUNT(*) FILTER (WHERE noballs > 0)                         AS noballs
    FROM d GROUP BY 1, 2, 3
),
wkts AS (
    SELECT d.bowler_id AS player_id, d.season_year, d.phase, COUNT(*) AS wickets
    FROM dismissal x
    JOIN d ON d.match_id = x.match_id AND d.innings_no = x.innings_no AND d.seq = x.seq
    WHERE x.bowler_credit
    GROUP BY 1, 2, 3
),
keys AS (
    SELECT player_id, season_year, phase FROM bat
    UNION SELECT player_id, season_year, phase FROM bowl
    UNION SELECT player_id, season_year, phase FROM outs
)
SELECT k.player_id, k.season_year, k.phase::VARCHAR(9) AS phase,
       COALESCE(b.runs, 0)               AS runs,
       COALESCE(b.balls_faced, 0)        AS balls_faced,
       COALESCE(b.fours, 0)              AS fours,
       COALESCE(b.sixes, 0)              AS sixes,
       COALESCE(b.dots_faced, 0)         AS dots_faced,
       COALESCE(o.outs, 0)               AS outs,
       COALESCE(b.runs_vs_pace, 0)       AS runs_vs_pace,
       COALESCE(b.balls_vs_pace, 0)      AS balls_vs_pace,
       COALESCE(o.outs_vs_pace, 0)       AS outs_vs_pace,
       COALESCE(b.runs_vs_spin, 0)       AS runs_vs_spin,
       COALESCE(b.balls_vs_spin, 0)      AS balls_vs_spin,
       COALESCE(o.outs_vs_spin, 0)       AS outs_vs_spin,
       COALESCE(w.legal_balls_bowled, 0) AS legal_balls_bowled,
       COALESCE(w.runs_conceded, 0)      AS runs_conceded,
       COALESCE(w.dots_bowled, 0)        AS dots_bowled,
       COALESCE(w.fours_conceded, 0)     AS fours_conceded,
       COALESCE(w.sixes_conceded, 0)     AS sixes_conceded,
       COALESCE(w.wides, 0)              AS wides,
       COALESCE(w.noballs, 0)            AS noballs,
       COALESCE(wk.wickets, 0)           AS wickets
FROM keys k
LEFT JOIN bat  b  USING (player_id, season_year, phase)
LEFT JOIN outs o  USING (player_id, season_year, phase)
LEFT JOIN bowl w  USING (player_id, season_year, phase)
LEFT JOIN wkts wk USING (player_id, season_year, phase);

-- Required for REFRESH ... CONCURRENTLY, and serves single-player lookups.
CREATE UNIQUE INDEX ux_mv_phase_player_season_phase
    ON mv_player_phase_stats (player_id, season_year, phase);

-- ---------------------------------------------------------------------
-- Player x season: per-innings milestones, fielding, MVP points
-- ---------------------------------------------------------------------
CREATE MATERIALIZED VIEW mv_player_season_stats AS
WITH reg AS (   -- regular (non super-over) deliveries
    SELECT d.*, m.season_year
    FROM delivery d
    JOIN innings i ON i.match_id = d.match_id AND i.innings_no = d.innings_no AND NOT i.is_super_over
    JOIN match m   ON m.match_id = d.match_id
),
bat_inn AS (    -- one row per batting innings (anyone who faced a ball or stood at the other end)
    SELECT p.player_id, p.match_id, p.innings_no, p.season_year,
           SUM(p.runs) AS runs,
           BOOL_OR(o.player_out_id IS NOT NULL) AS was_out
    FROM (SELECT batter_id AS player_id, match_id, innings_no, season_year, batter_runs AS runs FROM reg
          UNION ALL
          SELECT non_striker_id, match_id, innings_no, season_year, 0 FROM reg) p
    LEFT JOIN (SELECT DISTINCT match_id, innings_no, player_out_id FROM dismissal
                WHERE kind <> 'retired hurt') o
           ON o.match_id = p.match_id AND o.innings_no = p.innings_no AND o.player_out_id = p.player_id
    GROUP BY p.player_id, p.match_id, p.innings_no, p.season_year
),
inn_wkts AS (   -- wickets per bowler per innings
    SELECT r.bowler_id, r.match_id, r.innings_no, COUNT(*) AS wickets
    FROM dismissal x JOIN reg r USING (match_id, innings_no, seq)
    WHERE x.bowler_credit
    GROUP BY 1, 2, 3
),
bowl_inn AS (   -- one row per bowling innings
    SELECT r.bowler_id AS player_id, r.match_id, r.innings_no, r.season_year,
           SUM(r.bowler_runs) AS runs,
           COALESCE(MAX(w.wickets), 0) AS wickets
    FROM reg r
    LEFT JOIN inn_wkts w ON w.bowler_id = r.bowler_id AND w.match_id = r.match_id AND w.innings_no = r.innings_no
    GROUP BY r.bowler_id, r.match_id, r.innings_no, r.season_year
),
fielding AS (
    SELECT f.fielder_id AS player_id, m.season_year,
           COUNT(*) FILTER (WHERE x.kind = 'caught')   AS catches,
           COUNT(*) FILTER (WHERE x.kind = 'stumped')  AS stumpings,
           COUNT(*) FILTER (WHERE x.kind = 'run out')  AS run_outs
    FROM dismissal_fielder f
    JOIN dismissal x USING (match_id, innings_no, seq, player_out_id)
    JOIN innings i   ON i.match_id = x.match_id AND i.innings_no = x.innings_no AND NOT i.is_super_over
    JOIN match m     ON m.match_id = x.match_id
    GROUP BY 1, 2
),
cab AS (        -- caught & bowled counts as a catch for the bowler
    SELECT r.bowler_id AS player_id, r.season_year, COUNT(*) AS catches
    FROM dismissal x JOIN reg r USING (match_id, innings_no, seq)
    WHERE x.kind = 'caught and bowled' GROUP BY 1, 2
),
apps AS (
    SELECT mp.player_id, m.season_year, COUNT(*) AS matches
    FROM match_player mp JOIN match m USING (match_id) GROUP BY 1, 2
),
potm AS (
    SELECT potm_player_id AS player_id, season_year, COUNT(*) AS potm_awards
    FROM match WHERE potm_player_id IS NOT NULL GROUP BY 1, 2
),
bat AS (
    SELECT player_id, season_year,
           COUNT(*)                                     AS bat_innings,
           COUNT(*) FILTER (WHERE NOT was_out)          AS not_outs,
           MAX(runs)                                    AS highest_score,
           COUNT(*) FILTER (WHERE runs BETWEEN 30 AND 49) AS thirties,
           COUNT(*) FILTER (WHERE runs BETWEEN 50 AND 99) AS fifties,
           COUNT(*) FILTER (WHERE runs >= 100)          AS hundreds,
           COUNT(*) FILTER (WHERE runs = 0 AND was_out) AS ducks
    FROM bat_inn GROUP BY 1, 2
),
bowl AS (
    SELECT player_id, season_year,
           COUNT(*)                                   AS bowl_innings,
           COUNT(*) FILTER (WHERE wickets = 3)        AS three_wkt_hauls,
           COUNT(*) FILTER (WHERE wickets = 4)        AS four_wkt_hauls,
           COUNT(*) FILTER (WHERE wickets >= 5)       AS five_wkt_hauls,
           (ARRAY_AGG(wickets || '/' || runs ORDER BY wickets DESC, runs ASC))[1] AS best_figures
    FROM bowl_inn GROUP BY 1, 2
),
totals AS (     -- additive totals come from the phase view so the two views always agree
    SELECT player_id, season_year,
           SUM(runs) AS runs, SUM(balls_faced) AS balls_faced, SUM(fours) AS fours, SUM(sixes) AS sixes,
           SUM(outs) AS outs, SUM(legal_balls_bowled) AS legal_balls_bowled,
           SUM(runs_conceded) AS runs_conceded, SUM(wickets) AS wickets, SUM(dots_bowled) AS dots_bowled
    FROM mv_player_phase_stats GROUP BY 1, 2
)
SELECT a.player_id, a.season_year,
       a.matches,
       COALESCE(t.runs, 0)                AS runs,
       COALESCE(t.balls_faced, 0)         AS balls_faced,
       COALESCE(t.fours, 0)               AS fours,
       COALESCE(t.sixes, 0)               AS sixes,
       COALESCE(t.outs, 0)                AS outs,
       COALESCE(b.bat_innings, 0)         AS bat_innings,
       COALESCE(b.not_outs, 0)            AS not_outs,
       b.highest_score,
       COALESCE(b.thirties, 0)            AS thirties,
       COALESCE(b.fifties, 0)             AS fifties,
       COALESCE(b.hundreds, 0)            AS hundreds,
       COALESCE(b.ducks, 0)               AS ducks,
       COALESCE(w.bowl_innings, 0)        AS bowl_innings,
       COALESCE(t.legal_balls_bowled, 0)  AS legal_balls_bowled,
       COALESCE(t.runs_conceded, 0)       AS runs_conceded,
       COALESCE(t.wickets, 0)             AS wickets,
       COALESCE(t.dots_bowled, 0)         AS dots_bowled,
       COALESCE(w.three_wkt_hauls, 0)     AS three_wkt_hauls,
       COALESCE(w.four_wkt_hauls, 0)      AS four_wkt_hauls,
       COALESCE(w.five_wkt_hauls, 0)      AS five_wkt_hauls,
       w.best_figures,
       COALESCE(f.catches, 0) + COALESCE(c.catches, 0) AS catches,
       COALESCE(f.stumpings, 0)           AS stumpings,
       COALESCE(f.run_outs, 0)            AS run_outs,
       COALESCE(p.potm_awards, 0)         AS potm_awards,
       -- Official IPL Most Valuable Player formula
       ( 3.5 * COALESCE(t.sixes, 0) + 2.5 * COALESCE(t.fours, 0)
       + 3.5 * COALESCE(t.wickets, 0) + 1.0 * COALESCE(t.dots_bowled, 0)
       + 2.5 * (COALESCE(f.catches, 0) + COALESCE(c.catches, 0) + COALESCE(f.stumpings, 0))
       )::NUMERIC(7,1)                    AS mvp_points
FROM apps a
LEFT JOIN totals   t USING (player_id, season_year)
LEFT JOIN bat      b USING (player_id, season_year)
LEFT JOIN bowl     w USING (player_id, season_year)
LEFT JOIN fielding f USING (player_id, season_year)
LEFT JOIN cab      c USING (player_id, season_year)
LEFT JOIN potm     p USING (player_id, season_year);

CREATE UNIQUE INDEX ux_mv_season_player_season
    ON mv_player_season_stats (player_id, season_year);

-- ---------------------------------------------------------------------
-- Team x season: results, net run rate, phase run rates
-- ---------------------------------------------------------------------
CREATE VIEW v_team_season_stats AS
WITH team_match AS (
    SELECT m.season_year, m.match_id, t.team_id, m.result, m.winner_id,
           (SELECT batting_team_id FROM innings
             WHERE match_id = m.match_id AND innings_no = 1) = t.team_id AS batted_first
    FROM match m
    CROSS JOIN LATERAL (VALUES (m.team1_id), (m.team2_id)) AS t(team_id)
),
inn AS (
    SELECT s.*,
           -- NRR rule: a side that is bowled out is charged its full quota of overs
           CASE WHEN s.wickets >= 10 THEN s.quota_overs ELSE s.legal_balls / 6.0 END AS overs_for_nrr
    FROM v_innings_summary s
    -- Official NRR uses league-stage matches only, and ignores no-results.
    JOIN match m ON m.match_id = s.match_id AND m.result <> 'no result' AND m.stage = 'League'
),
bat AS (
    SELECT season_year, batting_team_id AS team_id,
           SUM(runs) AS runs_for, SUM(overs_for_nrr) AS overs_faced,
           SUM(pp_runs) AS pp_runs, SUM(pp_balls) AS pp_balls
    FROM inn GROUP BY 1, 2
),
bowl AS (
    SELECT season_year, bowling_team_id AS team_id,
           SUM(runs) AS runs_against, SUM(overs_for_nrr) AS overs_bowled,
           SUM(death_runs) AS death_runs_conceded, SUM(death_balls) AS death_balls_bowled
    FROM inn GROUP BY 1, 2
)
SELECT tm.season_year, tm.team_id AS franchise_id, f.short_code, f.current_name,
       COUNT(*)                                                         AS matches,
       COUNT(*) FILTER (WHERE tm.winner_id = tm.team_id)                AS wins,
       COUNT(*) FILTER (WHERE tm.result <> 'no result' AND tm.winner_id IS DISTINCT FROM tm.team_id) AS losses,
       COUNT(*) FILTER (WHERE tm.result = 'no result')                  AS no_results,
       ROUND(100.0 * COUNT(*) FILTER (WHERE tm.winner_id = tm.team_id)
             / NULLIF(COUNT(*) FILTER (WHERE tm.result <> 'no result'), 0), 1) AS win_pct,
       COUNT(*) FILTER (WHERE tm.winner_id = tm.team_id AND tm.batted_first)     AS wins_batting_first,
       COUNT(*) FILTER (WHERE tm.winner_id = tm.team_id AND NOT tm.batted_first) AS wins_chasing,
       ROUND(MAX(b.runs_for) / NULLIF(MAX(b.overs_faced), 0)
           - MAX(w.runs_against) / NULLIF(MAX(w.overs_bowled), 0), 3)   AS net_run_rate,
       ROUND(6.0 * MAX(b.pp_runs) / NULLIF(MAX(b.pp_balls), 0), 2)      AS powerplay_run_rate,
       ROUND(6.0 * MAX(w.death_runs_conceded) / NULLIF(MAX(w.death_balls_bowled), 0), 2) AS death_economy
FROM team_match tm
JOIN franchise f ON f.franchise_id = tm.team_id
LEFT JOIN bat  b ON b.season_year = tm.season_year AND b.team_id = tm.team_id
LEFT JOIN bowl w ON w.season_year = tm.season_year AND w.team_id = tm.team_id
GROUP BY tm.season_year, tm.team_id, f.short_code, f.current_name;

-- ---------------------------------------------------------------------
-- Venue profile: scoring level, chasing success, pace vs spin wickets
-- ---------------------------------------------------------------------
CREATE VIEW v_venue_stats AS
SELECT v.venue_id, v.name, v.city,
       COUNT(DISTINCT m.match_id)                                         AS matches,
       ROUND(AVG(s.runs) FILTER (WHERE s.innings_no = 1), 1)              AS avg_first_innings_score,
       ROUND(100.0 * COUNT(DISTINCT m.match_id) FILTER (
                 WHERE m.winner_id = (SELECT batting_team_id FROM innings
                                       WHERE match_id = m.match_id AND innings_no = 2))
             / NULLIF(COUNT(DISTINCT m.match_id) FILTER (WHERE m.result = 'win'), 0), 1) AS chase_win_pct,
       (SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE bp.bowling_type = 'Spin') / NULLIF(COUNT(*), 0), 1)
          FROM dismissal x
          JOIN delivery d USING (match_id, innings_no, seq)
          JOIN match mm   ON mm.match_id = d.match_id
          JOIN player bp  ON bp.player_id = d.bowler_id
         WHERE mm.venue_id = v.venue_id AND x.bowler_credit)               AS spin_wicket_pct
FROM venue v
JOIN match m ON m.venue_id = v.venue_id
LEFT JOIN v_innings_summary s ON s.match_id = m.match_id
GROUP BY v.venue_id, v.name, v.city;

-- ---------------------------------------------------------------------
-- Draft board status (purse, slots, role balance) - live, not materialized
-- ---------------------------------------------------------------------
CREATE VIEW v_draft_board_summary AS
SELECT b.board_id, b.name, b.franchise_id, b.target_season, b.purse_cr, b.max_squad, b.max_overseas,
       COALESCE(SUM(dp.price_paid_cr) FILTER (WHERE dp.status = 'Bought'), 0)               AS spent_cr,
       b.purse_cr - COALESCE(SUM(dp.price_paid_cr) FILTER (WHERE dp.status = 'Bought'), 0)  AS remaining_cr,
       COUNT(*) FILTER (WHERE dp.status = 'Bought')                                         AS squad_count,
       COUNT(*) FILTER (WHERE dp.status = 'Bought' AND p.is_overseas)                       AS overseas_count,
       COUNT(*) FILTER (WHERE dp.status = 'Target')                                         AS targets,
       COUNT(*) FILTER (WHERE dp.status = 'Bought' AND dp.role_slot = 'BAT')                AS bat_count,
       COUNT(*) FILTER (WHERE dp.status = 'Bought' AND dp.role_slot = 'WK')                 AS wk_count,
       COUNT(*) FILTER (WHERE dp.status = 'Bought' AND dp.role_slot = 'AR')                 AS ar_count,
       COUNT(*) FILTER (WHERE dp.status = 'Bought' AND dp.role_slot = 'BOWL')               AS bowl_count
FROM draft_board b
LEFT JOIN draft_pick dp ON dp.board_id = b.board_id
LEFT JOIN player p      ON p.player_id = dp.player_id
GROUP BY b.board_id;
