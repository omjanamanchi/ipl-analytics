-- =====================================================================
-- IPL Auction War Room - PostgreSQL 16 schema
-- Run with:  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/schema.sql
-- Re-running this file DROPS and recreates every table (data is lost).
-- =====================================================================

DROP MATERIALIZED VIEW IF EXISTS mv_player_phase_stats  CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mv_player_season_stats CASCADE;
DROP TABLE IF EXISTS draft_pick, draft_board, scout,
                     season_award, award,
                     dismissal_fielder, dismissal, delivery, innings,
                     match_player, match, contract, player,
                     franchise_name, franchise, season,
                     venue_alias, venue, role CASCADE;

-- ---------------------------------------------------------------------
-- 1. Reference / lookup tables
-- ---------------------------------------------------------------------

-- Player roles. Also feeds the role check-boxes in the UI (built from the DB).
CREATE TABLE role (
    role_code   VARCHAR(4)  PRIMARY KEY CHECK (role_code IN ('BAT','WK','AR','BOWL')),
    description TEXT        NOT NULL,
    sort_order  SMALLINT    NOT NULL
);

CREATE TABLE venue (
    venue_id  SERIAL PRIMARY KEY,
    name      TEXT NOT NULL UNIQUE,
    city      TEXT NOT NULL,
    country   TEXT NOT NULL DEFAULT 'India'
);

-- Cricsheet spells the same ground many ways ("Eden Gardens", "Eden Gardens, Kolkata").
-- Every raw spelling maps to exactly one canonical venue.
CREATE TABLE venue_alias (
    alias     TEXT    PRIMARY KEY,
    venue_id  INTEGER NOT NULL REFERENCES venue(venue_id)
);

CREATE TABLE franchise (
    franchise_id   SMALLSERIAL PRIMARY KEY,
    short_code     VARCHAR(5) NOT NULL UNIQUE,      -- CSK, MI, RCB ...
    current_name   TEXT       NOT NULL UNIQUE,
    city           TEXT       NOT NULL,
    owner_group    TEXT,
    home_venue_id  INTEGER    REFERENCES venue(venue_id),
    founded_season SMALLINT   NOT NULL,
    is_active      BOOLEAN    NOT NULL DEFAULT TRUE
);

-- Name history: "Delhi Daredevils" (2008-2018) and "Delhi Capitals" (2019-) are one franchise.
CREATE TABLE franchise_name (
    name         TEXT     PRIMARY KEY,
    franchise_id SMALLINT NOT NULL REFERENCES franchise(franchise_id),
    from_season  SMALLINT NOT NULL,
    to_season    SMALLINT,
    CHECK (to_season IS NULL OR to_season >= from_season)
);

-- One row per IPL season, including the season we are drafting for (2027).
-- Auction rules live here so the draft board can enforce them.
CREATE TABLE season (
    season_year      SMALLINT PRIMARY KEY CHECK (season_year BETWEEN 2008 AND 2100),
    start_date       DATE,
    end_date         DATE,
    purse_cr         NUMERIC(6,2),          -- auction purse in Rs crore
    min_squad        SMALLINT,
    max_squad        SMALLINT,
    max_overseas     SMALLINT,
    overseas_cap_cr  NUMERIC(6,2),          -- max fee an overseas player can earn
    champion_id      SMALLINT REFERENCES franchise(franchise_id),
    runner_up_id     SMALLINT REFERENCES franchise(franchise_id),
    CHECK (champion_id IS NULL OR champion_id <> runner_up_id),
    CHECK (end_date IS NULL OR end_date >= start_date)
);

-- ---------------------------------------------------------------------
-- 2. Players and contracts
-- ---------------------------------------------------------------------

CREATE TABLE player (
    player_id       SERIAL       PRIMARY KEY,
    cricsheet_id    CHAR(8)      NOT NULL UNIQUE,   -- stable id from the Cricsheet register
    cricsheet_name  TEXT         NOT NULL,          -- "V Kohli" (NOT unique: two "Harmeet Singh"s exist)
    full_name       TEXT,                            -- legal name, e.g. "Samuel Matthew Curran"
    display_name    TEXT         NOT NULL,           -- common name shown in the UI, e.g. "Sam Curran"
    cricinfo_id     INTEGER,
    dob             DATE,
    country         TEXT,
    is_overseas     BOOLEAN GENERATED ALWAYS AS (country IS NOT NULL AND country <> 'India') STORED,
    batting_hand    VARCHAR(5)   CHECK (batting_hand IN ('Right','Left')),
    bowling_arm     VARCHAR(5)   CHECK (bowling_arm  IN ('Right','Left')),
    bowling_style   TEXT,                            -- e.g. "Right arm Fast medium", "Legbreak Googly"
    bowling_type    VARCHAR(4)   CHECK (bowling_type IN ('Pace','Spin')),
    role_code       VARCHAR(4)   REFERENCES role(role_code),
    meta_source     TEXT         NOT NULL DEFAULT 'none'  -- where bio data came from
);

-- Which franchise a player belonged to in a season and what he was paid.
-- Seeded from playing XIs; price_cr filled from auction data where known.
CREATE TABLE contract (
    player_id     INTEGER     NOT NULL REFERENCES player(player_id),
    season_year   SMALLINT    NOT NULL REFERENCES season(season_year),
    franchise_id  SMALLINT    NOT NULL REFERENCES franchise(franchise_id),
    price_cr      NUMERIC(5,2) CHECK (price_cr IS NULL OR price_cr >= 0),
    acquisition   VARCHAR(12) CHECK (acquisition IN ('Auction','Retained','RTM','Trade','Replacement','Unknown')),
    is_captain    BOOLEAN     NOT NULL DEFAULT FALSE,
    PRIMARY KEY (player_id, season_year)             -- one team per player per season
);

-- ---------------------------------------------------------------------
-- 3. Match facts (loaded from Cricsheet, read-only for the app)
-- ---------------------------------------------------------------------

CREATE TABLE match (
    match_id        INTEGER     PRIMARY KEY,         -- Cricsheet match id
    season_year     SMALLINT    NOT NULL REFERENCES season(season_year),
    match_number    SMALLINT,
    match_date      DATE        NOT NULL,
    stage           TEXT        NOT NULL DEFAULT 'League',
    venue_id        INTEGER     NOT NULL REFERENCES venue(venue_id),
    team1_id        SMALLINT    NOT NULL REFERENCES franchise(franchise_id),
    team2_id        SMALLINT    NOT NULL REFERENCES franchise(franchise_id),
    toss_winner_id  SMALLINT    NOT NULL REFERENCES franchise(franchise_id),
    toss_decision   VARCHAR(5)  NOT NULL CHECK (toss_decision IN ('bat','field')),
    result          VARCHAR(9)  NOT NULL CHECK (result IN ('win','tie','no result')),
    winner_id       SMALLINT    REFERENCES franchise(franchise_id),   -- includes super-over winner of a tie
    win_by_runs     SMALLINT,
    win_by_wickets  SMALLINT,
    method          VARCHAR(5),                                       -- 'D/L' for rain-affected results
    potm_player_id  INTEGER     REFERENCES player(player_id),
    CHECK (team1_id <> team2_id),
    CHECK (toss_winner_id IN (team1_id, team2_id)),
    CHECK (winner_id IS NULL OR winner_id IN (team1_id, team2_id)),
    CHECK (result <> 'no result' OR winner_id IS NULL)
);

-- Playing XI (plus impact substitute from 2023) for each side.
CREATE TABLE match_player (
    match_id      INTEGER  NOT NULL REFERENCES match(match_id) ON DELETE CASCADE,
    player_id     INTEGER  NOT NULL REFERENCES player(player_id),
    franchise_id  SMALLINT NOT NULL REFERENCES franchise(franchise_id),
    PRIMARY KEY (match_id, player_id)
);

-- Weak entity of match. innings_no 3+ are super overs.
CREATE TABLE innings (
    match_id         INTEGER  NOT NULL REFERENCES match(match_id) ON DELETE CASCADE,
    innings_no       SMALLINT NOT NULL CHECK (innings_no >= 1),
    batting_team_id  SMALLINT NOT NULL REFERENCES franchise(franchise_id),
    bowling_team_id  SMALLINT NOT NULL REFERENCES franchise(franchise_id),
    is_super_over    BOOLEAN  NOT NULL DEFAULT FALSE,
    target_runs      SMALLINT,
    target_overs     NUMERIC(4,1),
    PRIMARY KEY (match_id, innings_no),
    CHECK (batting_team_id <> bowling_team_id)
);

-- Ball-by-ball facts (~296k rows). Weak entity of innings; seq orders every ball,
-- including wides/no-balls that repeat a ball number.
CREATE TABLE delivery (
    match_id        INTEGER  NOT NULL,
    innings_no      SMALLINT NOT NULL,
    seq             SMALLINT NOT NULL,
    over_no         SMALLINT NOT NULL CHECK (over_no BETWEEN 0 AND 19),  -- 0-based like Cricsheet
    ball_in_over    SMALLINT NOT NULL,
    batter_id       INTEGER  NOT NULL REFERENCES player(player_id),
    non_striker_id  INTEGER  NOT NULL REFERENCES player(player_id),
    bowler_id       INTEGER  NOT NULL REFERENCES player(player_id),
    batter_runs     SMALLINT NOT NULL DEFAULT 0 CHECK (batter_runs >= 0),
    wides           SMALLINT NOT NULL DEFAULT 0,
    noballs         SMALLINT NOT NULL DEFAULT 0,
    byes            SMALLINT NOT NULL DEFAULT 0,
    legbyes         SMALLINT NOT NULL DEFAULT 0,
    penalty         SMALLINT NOT NULL DEFAULT 0,
    -- Derived columns: computed by PostgreSQL, so they can never disagree with the raw data.
    extra_runs      SMALLINT GENERATED ALWAYS AS (wides + noballs + byes + legbyes + penalty) STORED,
    total_runs      SMALLINT GENERATED ALWAYS AS (batter_runs + wides + noballs + byes + legbyes + penalty) STORED,
    is_legal_ball   BOOLEAN  GENERATED ALWAYS AS (wides = 0 AND noballs = 0) STORED,      -- counts toward the over
    is_ball_faced   BOOLEAN  GENERATED ALWAYS AS (wides = 0) STORED,                      -- counts toward batter's balls
    bowler_runs     SMALLINT GENERATED ALWAYS AS (batter_runs + wides + noballs) STORED,  -- byes/leg-byes not charged
    phase           VARCHAR(9) GENERATED ALWAYS AS (
                        CASE WHEN over_no < 6  THEN 'Powerplay'
                             WHEN over_no < 15 THEN 'Middle'
                             ELSE 'Death' END) STORED,
    PRIMARY KEY (match_id, innings_no, seq),
    FOREIGN KEY (match_id, innings_no) REFERENCES innings(match_id, innings_no) ON DELETE CASCADE
);

-- A dismissal happens on a delivery. Separate table because most balls have none
-- and the dismissed player may be the non-striker (run out).
CREATE TABLE dismissal (
    match_id       INTEGER  NOT NULL,
    innings_no     SMALLINT NOT NULL,
    seq            SMALLINT NOT NULL,
    player_out_id  INTEGER  NOT NULL REFERENCES player(player_id),
    kind           VARCHAR(25) NOT NULL CHECK (kind IN (
                       'caught','bowled','run out','lbw','caught and bowled','stumped',
                       'hit wicket','retired hurt','retired out','obstructing the field')),
    bowler_credit  BOOLEAN GENERATED ALWAYS AS (kind IN
                       ('caught','bowled','lbw','caught and bowled','stumped','hit wicket')) STORED,
    PRIMARY KEY (match_id, innings_no, seq, player_out_id),
    FOREIGN KEY (match_id, innings_no, seq) REFERENCES delivery(match_id, innings_no, seq) ON DELETE CASCADE
);

-- Fielders involved in a dismissal (catches, stumpings, run outs - possibly several).
CREATE TABLE dismissal_fielder (
    match_id       INTEGER  NOT NULL,
    innings_no     SMALLINT NOT NULL,
    seq            SMALLINT NOT NULL,
    player_out_id  INTEGER  NOT NULL,
    fielder_id     INTEGER  NOT NULL REFERENCES player(player_id),
    is_substitute  BOOLEAN  NOT NULL DEFAULT FALSE,
    PRIMARY KEY (match_id, innings_no, seq, player_out_id, fielder_id),
    FOREIGN KEY (match_id, innings_no, seq, player_out_id)
        REFERENCES dismissal(match_id, innings_no, seq, player_out_id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------
-- 4. Awards
-- ---------------------------------------------------------------------

CREATE TABLE award (
    award_id    SMALLSERIAL PRIMARY KEY,
    award_name  TEXT NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE season_award (
    season_year  SMALLINT NOT NULL REFERENCES season(season_year),
    award_id     SMALLINT NOT NULL REFERENCES award(award_id),
    player_id    INTEGER  NOT NULL REFERENCES player(player_id),
    stat_value   NUMERIC(8,2),
    PRIMARY KEY (season_year, award_id)
);

-- ---------------------------------------------------------------------
-- 5. Application tables (the only tables the web app writes to)
-- ---------------------------------------------------------------------

CREATE TABLE scout (
    scout_id     SERIAL PRIMARY KEY,
    username     VARCHAR(40) NOT NULL UNIQUE,
    display_name TEXT        NOT NULL
);

-- A franchise's plan for an upcoming auction. Rules copied from the season row
-- at creation so the board keeps working even if the season row changes.
CREATE TABLE draft_board (
    board_id         SERIAL PRIMARY KEY,
    name             TEXT         NOT NULL,
    franchise_id     SMALLINT     NOT NULL REFERENCES franchise(franchise_id),
    target_season    SMALLINT     NOT NULL REFERENCES season(season_year),
    purse_cr         NUMERIC(6,2) NOT NULL CHECK (purse_cr > 0),
    max_squad        SMALLINT     NOT NULL CHECK (max_squad > 0),
    max_overseas     SMALLINT     NOT NULL CHECK (max_overseas >= 0),
    overseas_cap_cr  NUMERIC(6,2),
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (franchise_id, target_season, name)
);

-- MAIN TABLE for Requirement 1 (add / edit / delete).
CREATE TABLE draft_pick (
    pick_id        SERIAL PRIMARY KEY,
    board_id       INTEGER      NOT NULL REFERENCES draft_board(board_id) ON DELETE CASCADE,
    player_id      INTEGER      NOT NULL REFERENCES player(player_id),
    role_slot      VARCHAR(4)   NOT NULL REFERENCES role(role_code),
    priority       SMALLINT     NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    max_bid_cr     NUMERIC(5,2) NOT NULL CHECK (max_bid_cr > 0),
    status         VARCHAR(6)   NOT NULL DEFAULT 'Target' CHECK (status IN ('Target','Bought','Lost')),
    price_paid_cr  NUMERIC(5,2) CHECK (price_paid_cr IS NULL OR price_paid_cr > 0),
    notes          TEXT,
    updated_by     INTEGER      REFERENCES scout(scout_id),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    version        INTEGER      NOT NULL DEFAULT 1,      -- optimistic concurrency control
    UNIQUE (board_id, player_id),                         -- a player appears once per board
    CHECK ((status = 'Bought') = (price_paid_cr IS NOT NULL))
);
