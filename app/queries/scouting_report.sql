-- Scouting Report (Requirement 2). One fixed SQL text; every filter is a parameter.
-- Optional filters use the pattern  (<param> IS NULL OR column = <param>)  so no SQL is ever
-- assembled from user input. The ONLY dynamic part is ORDER BY, which the Python code
-- picks from a fixed whitelist (see SORT_COLUMNS in plan.md) and appends to this text.
--
-- Parameters:
--   season_from, season_to   int        required (season range)
--   phases                   text[]     required, subset of {Powerplay,Middle,Death}
--   roles                    text[]     required, subset of role.role_code
--   team_id                  int|null   current (latest contract season) franchise
--   nationality              text|null  'Indian' | 'Overseas'
--   bowling_type             text|null  'Pace' | 'Spin'
--   age_min, age_max         int|null
--   price_min, price_max     numeric|null  (Rs crore, latest contract)
--   min_balls                int        balls faced OR bowled in the selected phases
--   board_id                 int        draft board whose status column is shown
--   hide_on_board            bool       true = exclude players already on the board
--   contract_season          int        season whose salary is "current" (2026)
WITH ph AS (
    SELECT player_id,
           SUM(runs) AS runs, SUM(balls_faced) AS balls, SUM(fours) AS fours, SUM(sixes) AS sixes,
           SUM(dots_faced) AS dots_faced, SUM(outs) AS outs,
           SUM(runs_vs_pace) AS runs_vs_pace, SUM(balls_vs_pace) AS balls_vs_pace,
           SUM(runs_vs_spin) AS runs_vs_spin, SUM(balls_vs_spin) AS balls_vs_spin,
           SUM(legal_balls_bowled) AS balls_bowled, SUM(runs_conceded) AS runs_conceded,
           SUM(wickets) AS wickets, SUM(dots_bowled) AS dots_bowled
    FROM mv_player_phase_stats
    WHERE season_year BETWEEN %(season_from)s AND %(season_to)s
      AND phase = ANY(%(phases)s)
    GROUP BY player_id
),
se AS (
    SELECT player_id, SUM(matches) AS matches, COUNT(*) AS seasons,
           SUM(fifties) AS fifties, SUM(hundreds) AS hundreds, MAX(highest_score) AS highest_score,
           SUM(catches) AS catches, SUM(stumpings) AS stumpings, SUM(mvp_points) AS mvp_points
    FROM mv_player_season_stats
    WHERE season_year BETWEEN %(season_from)s AND %(season_to)s
    GROUP BY player_id
),
rows AS (
    SELECT p.player_id,
           p.display_name                                             AS player,
           p.cricsheet_name, p.role_code, p.country, p.is_overseas, p.bowling_type,
           EXTRACT(YEAR FROM age(p.dob))::int                         AS age,
           f.short_code                                               AS team,
           c.price_cr,
           se.matches, se.seasons, se.fifties, se.hundreds, se.highest_score,
           ph.runs, ph.balls,
           ROUND(100.0 * ph.runs / NULLIF(ph.balls, 0), 1)            AS strike_rate,
           ROUND(ph.runs::numeric / NULLIF(ph.outs, 0), 1)            AS batting_avg,
           ROUND(100.0 * (ph.fours + ph.sixes) / NULLIF(ph.balls, 0), 1) AS boundary_pct,
           ROUND(100.0 * ph.dots_faced / NULLIF(ph.balls, 0), 1)      AS dot_pct_faced,
           ROUND(100.0 * ph.runs_vs_pace / NULLIF(ph.balls_vs_pace, 0), 1) AS sr_vs_pace,
           ROUND(100.0 * ph.runs_vs_spin / NULLIF(ph.balls_vs_spin, 0), 1) AS sr_vs_spin,
           ph.wickets,
           ROUND(ph.balls_bowled / 6.0, 1)                            AS overs,
           ROUND(6.0 * ph.runs_conceded / NULLIF(ph.balls_bowled, 0), 2) AS economy,
           ROUND(ph.runs_conceded::numeric / NULLIF(ph.wickets, 0), 1) AS bowling_avg,
           ROUND(ph.balls_bowled::numeric / NULLIF(ph.wickets, 0), 1)  AS bowling_sr,
           ROUND(100.0 * ph.dots_bowled / NULLIF(ph.balls_bowled, 0), 1) AS dot_pct_bowled,
           se.catches + se.stumpings                                  AS dismissals_fielding,
           se.mvp_points,
           ROUND(se.mvp_points / NULLIF(se.matches, 0), 1)            AS mvp_per_match,
           -- Value: MVP points per season for every Rs 1 crore of salary (higher = better value)
           ROUND((se.mvp_points / se.seasons) / NULLIF(c.price_cr, 0), 1) AS mvp_per_crore,
           dp.pick_id, dp.status AS board_status
    FROM player p
    JOIN ph ON ph.player_id = p.player_id
    JOIN se ON se.player_id = p.player_id
    LEFT JOIN contract c   ON c.player_id = p.player_id AND c.season_year = %(contract_season)s
    LEFT JOIN franchise f  ON f.franchise_id = c.franchise_id
    LEFT JOIN draft_pick dp ON dp.player_id = p.player_id AND dp.board_id = %(board_id)s
    WHERE p.role_code = ANY(%(roles)s)
      AND (ph.balls >= %(min_balls)s OR ph.balls_bowled >= %(min_balls)s)
      AND (%(team_id)s::int       IS NULL OR c.franchise_id = %(team_id)s)
      AND (%(nationality)s::text  IS NULL OR p.is_overseas = (%(nationality)s = 'Overseas'))
      AND (%(bowling_type)s::text IS NULL OR p.bowling_type = %(bowling_type)s)
      AND (%(age_min)s::int       IS NULL OR age(p.dob) >= make_interval(years => %(age_min)s))
      AND (%(age_max)s::int       IS NULL OR age(p.dob) <  make_interval(years => %(age_max)s + 1))
      AND (%(price_min)s::numeric IS NULL OR c.price_cr >= %(price_min)s)
      AND (%(price_max)s::numeric IS NULL OR c.price_cr <= %(price_max)s)
      AND (NOT %(hide_on_board)s OR dp.pick_id IS NULL)
)
SELECT * FROM rows
