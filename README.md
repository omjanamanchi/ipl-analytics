# IPL Analytics

**An auction-planning and scouting platform for Indian Premier League franchises, built on every IPL ball bowled from 2008 to 2026.**

IPL Analytics lets a franchise's analysts scout players using real ball-by-ball statistics and
build an auction plan for the **2027 season**. The database enforces the real auction rules:
a ₹125 crore purse, at most 25 players, at most 8 overseas players, and a ₹18 crore cap on
overseas fees.

| | |
|---|---|
| **Course** | CS348 Information Systems, Purdue University, Fall 2026 (semester project) |
| **Stack** | Python 3.12 · Flask 3 · PostgreSQL 16 · psycopg 3 · Jinja2 · Docker |
| **Hosting** | Google App Engine (Standard) + Cloud SQL for PostgreSQL |
| **Live app** | _add URL after deployment_ |
| **Design document** | [plan.md](plan.md) |

---

## Contents
1. [Features](#1-features)
2. [Architecture](#2-architecture)
3. [Getting started](#3-getting-started)
4. [Configuration](#4-configuration)
5. [Database design](#5-database-design)
6. [Statistics and metrics](#6-statistics-and-metrics)
7. [Security](#7-security)
8. [Transactions and concurrency](#8-transactions-and-concurrency)
9. [Indexes](#9-indexes)
10. [Testing](#10-testing)
11. [Deployment](#11-deployment)
12. [Project structure](#12-project-structure)
13. [Course requirements map](#13-course-requirements-map)
14. [Known limitations](#14-known-limitations)
15. [Data sources and licences](#15-data-sources-and-licences)
16. [AI usage](#16-ai-usage)

---

## 1. Features

| Page | URL | Description | Access |
|---|---|---|---|
| **Home** | `/` | Database summary (matches, deliveries, players, seasons), 2026 season leaders, recent finals. | Everyone |
| **Sign up / Log in** | `/signup`, `/login` | Create an account with username, email and password. Log in with username **or** email. Accounts lock for 15 minutes after 5 failed attempts. | Everyone |
| **Guest mode** | `/guest` | Browse without an account. Read-only. | Everyone |
| **Draft Board** (Requirement 1) | `/draft` | Add, edit and delete target players. Mark them **Bought** or **Lost**. Live purse, squad, overseas and role-balance totals. The database enforces the auction rules. | View: everyone. Edit: board owner or editor |
| **My Boards** | `/draft/boards` | List the boards you own or that are shared with you. Share a board with another user as **editor** or **viewer**. | Logged-in users |
| **New Board** | `/draft/create` | Create a draft board for any franchise and target season. Auction rules are copied from the season. | Logged-in users |
| **Scouting Report** (Requirement 2) | `/report` | Filter all players by season range, phase, role, team, nationality, bowling type, age, salary and sample size. Sortable metrics, summary cards and live board status. | Everyone |
| **Player Search** | `/players` | Search all 816 players by name. | Everyone |
| **Player Profile** | `/players/<id>` | Bio, 2026 contract, board status, career totals, phase splits, season-by-season statistics. | Everyone |
| **Health check** | `/healthz` | Returns `{"status": "ok"}` when the database is reachable. | Monitoring |

---

## 2. Architecture

```
Browser ──HTTPS──▶ Flask (gunicorn)                      PostgreSQL 16
                    ├─ app/routes.py   home, /healthz      ├─ reference tables
                    ├─ app/auth.py     accounts, guests    ├─ match facts (296k balls)
                    ├─ app/draft.py    Requirement 1  ───▶ ├─ application tables
                    ├─ app/report.py   Requirement 2       ├─ views + materialized views
                    ├─ app/players.py  search, profiles    └─ indexes, constraints, grants
                    └─ app/db.py       pool + transactions
                                                          ▲
 etl/download_data.py ─▶ Cricsheet JSON ─▶ etl/load_cricsheet.py (one transaction per match)
```

- **No ORM.** All SQL is written by hand and run through psycopg 3 with parameters, so every query can be shown and explained.
- **Server-rendered HTML** (Jinja2) with small amounts of vanilla JavaScript for the player autocomplete and the light/dark theme.
- **Statistics are computed in the database.** Python never recalculates a metric.

---

## 3. Getting started

### Prerequisites
- Python 3.12
- Docker Desktop, for a local PostgreSQL 16 database. A native PostgreSQL 16 install also works.
- Git

### Windows (PowerShell)
```powershell
git clone https://github.com/omjanamanchi/ipl-analytics.git
cd ipl-analytics
copy .env.example .env                                   # then edit .env (section 4)
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
docker compose up -d db                                  # PostgreSQL on localhost:5433
.\.venv\Scripts\python -m etl.download_data              # ~1,243 JSON match files
.\.venv\Scripts\python -m etl.load_cricsheet --reset     # build schema + load (~4-5 min on Windows)
.\.venv\Scripts\python -m pytest -q                      # 52 tests
.\.venv\Scripts\flask --app main run --debug --port 8080 # http://localhost:8080
```

### macOS / Linux
```bash
cp .env.example .env
make setup && make db-up && make data && make load && make test && make run
```

### Logging in locally
The loader creates a demo account, **`om`** (email `om@ipl.local`), which owns the seeded
"2027 Auction Plan" board. Its password is whatever you set as `DEMO_USER_PASSWORD` in `.env`.
You can also sign up a new account, or continue as a guest.

---

## 4. Configuration

All settings are environment variables, read from `.env` locally. `.env` is git-ignored.

| Variable | Used by | Purpose |
|---|---|---|
| `DATABASE_URL` | app, ETL, tests | Local connection string. Default: `postgresql://ipl:ipl_local_dev@localhost:5433/ipl` |
| `FLASK_SECRET_KEY` | app | Signs session cookies. Use a long random value. |
| `DEMO_USER_PASSWORD` | ETL | Password given to the seeded demo users. **Set your own.** |
| `BOARD_FRANCHISE` | ETL | Franchise of the seeded demo board (default `RCB`). |
| `INSTANCE_CONNECTION_NAME`, `DB_USER`, `DB_NAME`, `DB_PASS_SECRET`, `FLASK_SECRET_SECRET` | app (cloud) | Cloud SQL connection and Secret Manager names; set by `deploy/app.yaml.template`. |

---

## 5. Database design

The schema has **20 tables in four groups**, plus views and materialized views for analytics.
The full definitions are in [`db/schema.sql`](db/schema.sql), and the design rationale is in
[plan.md section 6](plan.md).

### 5.1 Entity-relationship overview

```mermaid
erDiagram
    FRANCHISE ||--o{ FRANCHISE_NAME : "known as"
    VENUE ||--o{ VENUE_ALIAS : "spelled as"
    VENUE ||--o{ FRANCHISE : "home ground"
    ROLE ||--o{ PLAYER : "plays as"
    PLAYER ||--o{ CONTRACT : signs
    FRANCHISE ||--o{ CONTRACT : employs
    SEASON ||--o{ CONTRACT : "valid for"
    SEASON ||--o{ MATCH : contains
    VENUE ||--o{ MATCH : hosts
    FRANCHISE ||--o{ MATCH : "plays (team1/team2/toss/winner)"
    MATCH ||--o{ MATCH_PLAYER : "playing XI"
    PLAYER ||--o{ MATCH_PLAYER : "selected in"
    MATCH ||--|{ INNINGS : has
    INNINGS ||--|{ DELIVERY : has
    PLAYER ||--o{ DELIVERY : "bats / bowls"
    DELIVERY ||--o| DISMISSAL : "may cause"
    DISMISSAL ||--o{ DISMISSAL_FIELDER : involves
    AWARD ||--o{ SEASON_AWARD : "given as"
    SEASON ||--o{ SEASON_AWARD : "awarded in"
    APP_USER ||--o{ DRAFT_BOARD : owns
    APP_USER ||--o{ BOARD_MEMBER : "member of"
    DRAFT_BOARD ||--o{ BOARD_MEMBER : "shared with"
    FRANCHISE ||--o{ DRAFT_BOARD : "plans for"
    DRAFT_BOARD ||--o{ DRAFT_PICK : contains
    PLAYER ||--o{ DRAFT_PICK : "targeted by"
    ROLE ||--o{ DRAFT_PICK : "slot"
    APP_USER ||--o{ DRAFT_PICK : "last edited"

    PLAYER {
        int player_id PK
        char cricsheet_id UK
        text display_name
        text country
        bool is_overseas "generated"
        text bowling_type
        text role_code FK
    }
    DELIVERY {
        int match_id PK
        smallint innings_no PK
        smallint seq PK
        int batter_id FK
        int bowler_id FK
        smallint batter_runs
        text phase "generated"
    }
    DRAFT_PICK {
        int pick_id PK
        int board_id FK
        int player_id FK
        text status
        numeric price_paid_cr
        int version
    }
```

### 5.2 Table reference

**Reference data:**

| Table | Primary key | Foreign keys | Notes |
|---|---|---|---|
| `role` | `role_code` | — | BAT, WK, AR, BOWL. Feeds the role dropdowns and checkboxes. |
| `venue` | `venue_id` | — | 36 grounds; `name` unique. |
| `venue_alias` | `alias` | `venue_id` → venue | Maps 60 raw Cricsheet spellings, including renamed grounds (Feroz Shah Kotla → Arun Jaitley Stadium). |
| `franchise` | `franchise_id` | `home_venue_id` → venue | 10 active and 5 defunct franchises; owner group; `is_active`. |
| `franchise_name` | `name` | `franchise_id` → franchise | Name history, e.g. Delhi Daredevils (2008–18) → Delhi Capitals. |
| `season` | `season_year` | `champion_id`, `runner_up_id` → franchise | 2008–2027, with auction rules per season: purse, squad limits, overseas limit, overseas fee cap. |
| `award`, `season_award` | `award_id`; (`season_year`, `award_id`) | → season, award, player | Orange Cap, Purple Cap, MVP and Most Sixes, computed from the data. |

**Players and contracts:**

| Table | Primary key | Foreign keys | Notes |
|---|---|---|---|
| `player` | `player_id` | `role_code` → role | 816 players. `cricsheet_id` is a unique natural key, while names are not unique (two different players are called "Harmeet Singh"). `is_overseas` is a **generated column**. |
| `contract` | (`player_id`, `season_year`) | → player, season, franchise | One team per player per season. `price_cr` holds 2026 salaries for 226 players. |

**Match facts** (loaded from Cricsheet; read-only for the app):

| Table | Primary key | Foreign keys | Notes |
|---|---|---|---|
| `match` | `match_id` | season, venue, team1/team2/toss winner/winner → franchise, `potm_player_id` → player | 1,243 matches. CHECKs: team1 ≠ team2; toss winner and winner must be one of the two teams; a no-result has no winner. |
| `match_player` | (`match_id`, `player_id`) | → match, player, franchise | Playing XI (plus the Impact Player from 2023). |
| `innings` | (`match_id`, `innings_no`) | → match, batting/bowling team | **Weak entity** of match; super overs flagged with `is_super_over`. |
| `delivery` | (`match_id`, `innings_no`, `seq`) | → innings; batter, non-striker, bowler → player | **Weak entity** of innings; 295,732 rows. **Generated columns:** `extra_runs`, `total_runs`, `is_legal_ball`, `is_ball_faced`, `bowler_runs`, `phase`. |
| `dismissal` | delivery key + `player_out_id` | → delivery, player | 14,705 wickets. `bowler_credit` is generated (run-outs are not credited to the bowler). |
| `dismissal_fielder` | dismissal key + `fielder_id` | → dismissal, player | Catches, stumpings and run-out participants. |

**Application data** (the only tables the web app writes):

| Table | Primary key | Foreign keys | Notes |
|---|---|---|---|
| `app_user` | `user_id` | — | Username and email unique, case-insensitively (`LOWER()` unique indexes). Hashed password, `failed_logins`, `locked_until`, `is_active`. |
| `draft_board` | `board_id` | `franchise_id`, `target_season`, `owner_id` → app_user | Auction rules copied from the season when the board is created. UNIQUE (franchise, season, name). |
| `board_member` | (`board_id`, `user_id`) | → draft_board, app_user | `role` ∈ {owner, editor, viewer}; controls who can change a board. |
| **`draft_pick`** | `pick_id` | `board_id`, `player_id`, `role_slot`, `updated_by` | **Main table for Requirement 1.** UNIQUE (board_id, player_id); priority 1–5; max bid > 0; `status` ∈ {Target, Bought, Lost}; `price_paid_cr` is set if and only if Bought; `version` for optimistic locking. |

### 5.3 Views

| View | Type | Purpose |
|---|---|---|
| `mv_player_phase_stats` | Materialized | Player × season × phase: batting, bowling and pace/spin splits (8,868 rows). |
| `mv_player_season_stats` | Materialized | Player × season: matches, 50s/100s, best figures, fielding, MVP points (3,354 rows). |
| `v_innings_summary` | View | Totals per innings (runs, legal balls, wickets, phase runs). |
| `v_team_season_stats` | View | Team results, net run rate (official league-stage rules), powerplay run rate, death economy. |
| `v_venue_stats` | View | Average first-innings score, chase win %, spin wicket share per ground. |
| `v_draft_board_summary` | View | Live purse spent and remaining, squad and overseas counts, role balance per board. |

### 5.4 Design decisions
- **Normalized to 3NF.** Each fact is stored once; for example, team names are reached through `franchise_id`.
- **Weak entities.** A delivery is identified by its innings, and an innings by its match.
- **Derived values are never typed in.** Strike rate, economy, age and "overseas" are calculated, and generated columns keep the ball-level values consistent automatically.
- **One deliberate denormalization.** `innings.bowling_team_id` could be derived, but nearly every bowling query needs it.
- **Materialized views** pre-aggregate the 296k deliveries. The data is historical and only changes on reload.

### 5.5 Inspecting the database
```powershell
docker compose exec db psql -U ipl ipl
```
```sql
\dt                -- tables          \dv  -- views          \dm  -- materialized views
\d draft_pick      -- columns, keys and constraints of one table
SELECT p.display_name, s.runs FROM mv_player_season_stats s JOIN player p USING (player_id)
WHERE s.season_year = 2026 ORDER BY s.runs DESC LIMIT 10;
```
GUI option: the PostgreSQL extension for VS Code, pgAdmin or DBeaver, connecting to
`localhost:5433`, database `ipl`, user `ipl`, password `ipl_local_dev`.

---

## 6. Statistics and metrics

Phases: **Powerplay** = overs 1–6 · **Middle** = overs 7–15 · **Death** = overs 16–20.
Super-over innings are excluded from every statistic.

| Metric | Definition |
|---|---|
| Strike rate | 100 × runs ÷ balls faced (wides are not balls faced) |
| Batting average | runs ÷ dismissals (retired hurt is not out) |
| Boundary % / Dot % | (4s + 6s) ÷ balls faced; dot balls ÷ balls faced |
| SR vs pace / spin | Strike rate split by the bowler's `bowling_type` |
| Economy | 6 × runs conceded ÷ legal balls (byes and leg-byes are not charged to the bowler) |
| Bowling average / SR | runs conceded ÷ wickets; legal balls ÷ wickets |
| Wickets | Dismissals credited to the bowler (excludes run-outs and retirements) |
| **MVP points** | Official IPL formula: 3.5 × sixes + 2.5 × fours + 3.5 × wickets + 1 × dot balls + 2.5 × (catches + stumpings) |
| **MVP per crore** | (MVP points ÷ seasons) ÷ 2026 salary. Value for money; higher is better. |
| Net run rate | runs for ÷ overs faced − runs against ÷ overs bowled; a side bowled out is charged its full quota of overs; league stage only |

**Validated against published results** (`tests/test_data.py`):
- the 2024–2026 Orange and Purple Caps
- the 2025 MVP (Suryakumar Yadav, 320.5 points)
- net run rates (KKR 2024 +1.428, SRH 2024 +0.414, PBKS 2025 +0.372)
- every season's champion

---

## 7. Security

| Measure | Implementation |
|---|---|
| **SQL injection** | Every query passes values as psycopg parameters (`%s` / `%(name)s`). The only SQL text built in Python is the report's ORDER BY, which is looked up from a fixed whitelist (`SORT_COLUMNS`). `LIKE` patterns escape `%` and `_`. Optional filters use `(param IS NULL OR column = param)` instead of building SQL. |
| **Input validation** | Numbers are parsed and range-checked. Dropdown values are checked against values loaded from the database. Bad input returns a flash message or HTTP 400. |
| **Database constraints** | CHECK, UNIQUE and foreign-key constraints reject invalid data even if application code has a bug. |
| **Passwords** | Hashed with `werkzeug.security`; never stored or logged in plain text. Accounts lock after 5 failed logins (`locked_until`). |
| **Authorization** | Every write checks `board_member` in SQL: owners and editors may change a board, viewers and guests may not. Only the owner may share a board. |
| **CSRF** | Flask-WTF `CSRFProtect` on every POST form. |
| **XSS** | Jinja2 autoescaping; no user input is marked `|safe`. |
| **Least-privilege DB user** | In production the app connects as `ipl_app` (`db/grants.sql`): SELECT on everything, but INSERT/UPDATE/DELETE only on the application tables. |
| **Secrets** | Kept in `.env` locally (git-ignored) and in Secret Manager in the cloud. |

---

## 8. Transactions and concurrency

| Operation | Isolation level | Mechanism | Prevents |
|---|---|---|---|
| Load one match (ETL) | READ COMMITTED | One transaction per match file | Half-loaded matches |
| Add / edit / delete a pick | READ COMMITTED | `version` column (optimistic locking) | **Lost updates** when two users edit the same pick |
| **Buy a player** | READ COMMITTED | `SELECT … FOR UPDATE` on the board row, then purse, squad, overseas and fee-cap checks | **Write skew**: two concurrent buys that each fit the purse alone but not together |
| Scouting Report + board panel | REPEATABLE READ, read-only | One snapshot | The table and the purse panel disagreeing |
| Failed-login counter | READ COMMITTED | Single atomic `UPDATE … SET failed_logins = failed_logins + 1` | Lost increments |

**Why not SERIALIZABLE for Buy?** It would also prevent write skew, but the losing
transaction would fail and need retry logic. Locking a single board row is simpler and
explicit, and only buys on the same board ever wait for each other.

---

## 9. Indexes

Primary keys and UNIQUE constraints create indexes automatically. The additional indexes are
in [`db/indexes.sql`](db/indexes.sql) and [`db/views.sql`](db/views.sql):

| Index | Supports |
|---|---|
| `mv_player_phase_stats (season_year, phase)` | Scouting Report season-range and phase filter (bitmap index scan, about 0.5 ms) |
| `mv_player_season_stats (season_year)` | Season-level report columns |
| `mv_*` unique `(player_id, season_year[, phase])` | `REFRESH MATERIALIZED VIEW CONCURRENTLY`; player profile lookups |
| `contract (season_year, franchise_id)` | "Current team" filter and salary join |
| `delivery (batter_id)`, `delivery (bowler_id)` | Single-player ball-level queries: 2.7 ms with the index vs 17 ms sequential scan |
| `dismissal (player_out_id)` | A player's dismissals |
| `match (season_year, match_date)`, `match (venue_id)` | Season and venue queries |
| `app_user (LOWER(username))`, `app_user (LOWER(email))` | Case-insensitive login lookup and uniqueness |

**Considered and rejected:** a trigram (pg_trgm) index for name search. With 816 players the
planner still preferred a sequential scan.

---

## 10. Testing

### Automated tests
```powershell
.\.venv\Scripts\python -m pytest -q        # 52 tests
```

| File | Tests | Covers |
|---|---|---|
| `tests/test_data.py` | 15 | Row counts; Orange and Purple Caps, MVP, net run rate and champions against official figures; view consistency; salaries within purse; home page |
| `tests/test_draft.py` | 8 | Add, edit, delete; duplicate player; purse limit; ninth overseas player; overseas fee cap; version conflict |
| `tests/test_report.py` | 18 | Default report; each filter; all sort keys; unknown sort key; SQL-injection strings in filters, team id and sort key; hide-on-board; before/after purchase |
| `tests/test_auth.py` | 11 | Sign-up; duplicate username and email; invalid email; short password; login by username and by email; wrong password; lockout; guest mode |

> **Note:** the test configuration (`TESTING = True`) bypasses `login_required` and the
> board-permission checks, so viewer and guest restrictions are verified manually (below).

### Manual test checklist
Run these in order on a freshly loaded database (`etl.load_cricsheet --reset`), using one normal browser window and one private window for the second user:

| # | Feature | Steps | Expected result |
|---|---|---|---|
| 1 | Guest | Log in page → **Continue as guest** → open Report, Players, Draft Board → try to add a pick | Pages load; any change asks you to sign in |
| 2 | Sign up | `/signup` with a new username, email and an 8+ character password | "Welcome, …! Your account has been created." |
| 3 | Duplicate | Sign up again with the same email in different capitals | "That username or email is already taken" |
| 4 | Log in by email | Log in with `om@ipl.local` | Logged in as Om Janamanchi |
| 5 | Add target | Draft Board → add Virat Kohli, BAT, bid 20 | Appears in the list; purse **stays** ₹125.00 |
| 6 | Duplicate pick | Add Kohli again | "That player is already on the board" |
| 7 | Buy | Add Pathirana → Edit → Bought, ₹14 | Purse ₹111.00; overseas 1/8 |
| 8 | Purse limit | Edit Kohli → Bought, ₹200 | "Not enough purse left (₹111.00 cr remaining…)" |
| 9 | Version conflict | Open one pick's Edit page in two tabs; save in both | Second save: "Someone else changed this pick" |
| 10 | Report before/after | Report: Death, Overseas, Pace, 2024–26 → Pathirana shows **Bought**; tick *Hide board players* | Purse ₹111.00 in the panel; Pathirana disappears when hidden |
| 11 | Share | My Boards → share with your test user as **viewer** | "Shared with … as viewer" |
| 12 | Viewer blocked | Log in as the viewer → try to add a pick | "You need editor or owner access to modify this board" |
| 13 | Lockout | Enter a wrong password 5 times for a test account, then the right one | "Account locked … Try again in 15 minutes." |
| 14 | New board | **+ New Board** → name, franchise, 2027 | New board is active, purse ₹125.00 |
| 15 | Player profile | Players → search "bumrah" → open profile | Bio, contract, phase splits, season table |

Reset demo data: `docker compose exec db psql -U ipl ipl -c "DELETE FROM draft_pick;"`

---

## 11. Deployment

The app is deployed to **Google App Engine Standard** with **Cloud SQL for PostgreSQL 16**.
It's paid for with the CS348 Google Cloud education coupon. Full instructions are in
[plan.md section 14](plan.md).

```bash
cp deploy/gcp.env.example deploy/gcp.env   # set PROJECT_ID and BILLING_ACCOUNT
bash deploy/gcp_setup.sh                    # APIs, Cloud SQL, users, secrets, IAM, App Engine
bash deploy/push_db.sh                      # copy the loaded local database to Cloud SQL
bash deploy/deploy_app.sh                   # deploy; prints the public URL
bash deploy/teardown.sh                     # after 12/23/2026: delete everything
```

**Security posture:**
- Cloud SQL has no authorized networks; the app connects only through App Engine's built-in Cloud SQL socket.
- Encrypted connections only.
- Random passwords kept in Secret Manager.
- Least-privilege `ipl_app` database user.
- HTTPS only.
- At most 2 App Engine instances.
- A $20 budget alert.

---

## 12. Project structure

```
app/
  __init__.py          application factory, blueprints, CSRF, template context
  config.py            local vs Cloud SQL / Secret Manager configuration
  db.py                connection pool, query helpers, transaction(isolation=…)
  routes.py            home page, /healthz
  auth.py              sign-up, login, lockout, guest mode, logout
  draft.py             Draft Board, My Boards, sharing, Buy transaction   (Requirement 1)
  report.py            Scouting Report                                    (Requirement 2)
  players.py           player search and profiles
  queries/scouting_report.sql
  templates/  static/
db/        schema.sql · seed_reference.sql · views.sql · indexes.sql · grants.sql
etl/       download_data.py · load_cricsheet.py · build_contract_prices.py
data/      venue aliases, player metadata, 2026 salaries (sources/ipl_2026_squads.csv)
deploy/    gcp_setup.sh · push_db.sh · deploy_app.sh · teardown.sh · app.yaml.template
tests/     test_data.py · test_draft.py · test_report.py · test_auth.py
plan.md    design document and build plan        CLAUDE.md   coding rules for Claude Code
```

---

## 13. Course requirements map

| Stage | Requirement | Where |
|---|---|---|
| 2 | Database design: tables, primary keys, foreign keys | Section 5, `db/schema.sql` |
| 2 | Requirement 1: insert, update, delete on a main table | Draft Board (`draft_pick`), `app/draft.py` |
| 2 | Requirement 2: filtered report with statistics, before and after a data change | Scouting Report, `app/report.py`, `app/queries/scouting_report.sql` |
| 2 | UI built from the database | Role, season, team, bowling-type, franchise and board dropdowns; player autocomplete |
| 3 | SQL injection protection | Section 7 |
| 3 | Indexes | Section 9 |
| 3 | Transactions and isolation levels | Section 8 |
| 3 | AI usage | Section 16 |
| Extra credit | Cloud deployment | Section 11 |

---

## 14. Known limitations
- Matches abandoned without a ball are not in Cricsheet, so some teams show fewer matches than the official table.
- The 27 players who debuted in 2025–26 have their country assumed to be India, no bowling style, and a role inferred from how they played.
- 2027 auction rules are assumed to equal 2026's until announced.
- The computed MVP total differs slightly from published figures in some seasons (e.g. 2026). Runs, fours and sixes match exactly.
- Read-only users (guests and viewers) still see the add and edit controls; the server rejects their changes.
- Automated tests bypass authentication; permission checks are covered by the manual checklist.

---

## 15. Data sources and licences
- **Ball-by-ball data:** [Cricsheet](https://cricsheet.org), [Open Data Commons Attribution License](https://cricsheet.org/licensing/). Fallback mirror: [ritesh-ojha/IPL-DATASET](https://github.com/ritesh-ojha/IPL-DATASET).
- **Player metadata:** `player_meta` from the [cricketdata](https://github.com/robjhyndman/cricketdata) R package (GPL-3), sourced from ESPNcricinfo.
- **2026 squads and salaries:** compiled from Wikipedia, *List of 2026 Indian Premier League personnel changes* (CC BY-SA).
- **Team names and logos** belong to their respective franchises and are used for educational purposes only.

---

## 16. AI usage
_Required by the course AI policy and discussed in the Stage 3 demo._

**Tools used:**
- Claude (claude.ai): planning, research, the initial database, ETL and deployment setup, and this README.
- Claude Code: building features from `plan.md`.

**What AI assisted with:**
- Researching IPL data sources and the 2026 auction rules.
- Designing the schema.
- Writing the Cricsheet loader, SQL views and deployment scripts.
- Drafting `plan.md`.
- Building the Draft Board, Scouting Report and player pages.
- Building the user accounts system:
  - replaced the `scout` table with `app_user`
  - added `board_member` and `draft_board.owner_id`
  - sign-up, login by username or email, lockout and guest mode
  - `_require_editor` permission checks
  - My Boards and board sharing
  - 11 tests in `tests/test_auth.py`

**How the output was verified or modified:**
- The loaded data is tested against published figures (`tests/test_data.py`).
- Indexes were checked with `EXPLAIN ANALYZE`; a trigram index was rejected because the planner did not use it.
- The 2026 salary-to-player matching was reviewed by hand; about 10 wrong automatic matches were fixed with explicit overrides, and a duplicate-id guard was added.
- Every feature was tested manually in the browser with multiple user accounts (section 10).
- Cloud setup choices were checked against the Google Cloud documentation.
- _(add what you personally reviewed, changed or rewrote)_

### AI usage log
| Date | Tool | Task | How I verified / what I changed |
|---|---|---|---|
| 2026-11-09 | Claude | Schema, loader, views, indexes, deploy scripts, plan.md | Ran the loader and 15 tests against official stats; reviewed the schema |
| 2026-11-09 | Claude Code | Added .gitattributes (LF for .sh/.sql), python-dotenv, renamed app title to IPL Analytics | Ran 15 tests (all passed); verified the app starts on port 8080 |
| 2026-11-09 | Claude Code | Built the Draft Board blueprint (Phase 2): all CRUD routes, buy transaction, Flask-WTF CSRF, autocomplete, 8 new tests | Ran 23 tests (all passed); walked through every SQL statement |
| 2026-11-10 | Claude Code | Built the Scouting Report blueprint (Phase 3): all filters from DB, SORT_COLUMNS whitelist, REPEATABLE READ snapshot, before/after demo, 18 new tests | Ran 41 tests (all passed); performed the before/after demo manually |
| 2026-11-10 | Claude Code | UI redesign, player search and profiles, user accounts (sign-up, email login, lockout, guest mode, shared boards), 11 new tests | Ran 52 tests (all passed); tested sign-up, guest, sharing and lockout in the browser |
| 2026-11-10 | Claude | Rewrote README.md (structure, schema reference, testing checklist) | Checked the schema section against the live database (`information_schema`) and ran every checklist step |
