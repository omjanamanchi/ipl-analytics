# IPL Auction War Room — Build Plan

CS348 semester project (Fall 2026). This file is the single source of truth for building
the app with Claude Code. Work through the phases in order. Each phase ends with a
checklist and a suggested Claude Code prompt.

> **Deadlines:** Stage 2 due **Wed 11/11/2026** · Stage 3 due **Fri 12/11/2026** ·
> Extra-credit URL must stay live **12/11 11:59 pm → 12/23 11:59 pm**, then tear down.

---

## 0. How to use this plan with Claude Code

1. Open the repo in Claude Code. It reads `CLAUDE.md` automatically (house rules).
2. Start each phase with the prompt given at the end of that phase, e.g.
   *"Read plan.md section 8 and build Phase 2 (Draft Board). Follow CLAUDE.md."*
3. After each phase: run `make test`, click through the feature, commit.
4. **AI policy:** you must be able to explain every line on camera. After Claude Code writes
   something, ask it *"walk me through this code and the SQL"* and edit anything you
   don't understand. Keep notes for the README "AI Usage" section as you go
   (tool, task, how you verified/changed it).

---

## 1. What we're building

A franchise analyst's tool for the **IPL 2027 auction**:

- **Scouting Report:** filter every IPL player by season range, game phase, role, team,
  nationality, bowling type, age and salary, and rank them on real metrics (strike rate,
  economy, phase splits, pace-vs-spin, MVP points, value per crore).
- **Draft Board:** build a 2027 squad. Add targets, set max bids, mark players bought, and
  let the database enforce the real auction rules: ₹125 cr purse, 25 players max, 8 overseas
  max, overseas fee capped at ₹18 cr.

### Rubric map

| Stage | Item | Weight | Where it is satisfied |
|---|---|---|---|
| 1 | Hello-world page + 1–2 min demo | — | `/` home page (already works) |
| 2 | Database design (tables, PKs, FKs) | 10% | `db/schema.sql`, section 6 |
| 2 | Req 1: insert / update / delete + code walkthrough | 25% | Draft Board, section 8 |
| 2 | Req 2: filter + report, before/after a data change + code | 25% | Scouting Report, section 9 |
| 2 | UI built from DB (dropdowns/checkboxes) | 5% | section 10 |
| 3 | SQL injection protection | 7% | section 11 |
| 3 | Indexes and the queries they serve | 6% | section 12, `db/indexes.sql` |
| 3 | Transactions, concurrency, isolation levels | 6% | section 13 |
| 3 | AI usage discussion | 6% | README "AI Usage" + demo |
| EC | Live on a cloud provider, TA can edit data and see the report change | +1% course | section 14 |

### Status

| Part | Status |
|---|---|
| Schema, reference data, views, indexes, grants | ✅ done (`db/`) |
| Cricsheet loader (1,243 matches, 295,732 balls, 2008–2026) | ✅ done, tested |
| Player bios (789 players) + 2026 salaries (226 players) | ✅ done |
| Flask skeleton, DB pool, transaction helper, home page, `/healthz` | ✅ done |
| Scouting Report SQL (`app/queries/scouting_report.sql`) | ✅ written + tested |
| Google Cloud scripts (`deploy/`) | ✅ written; run them yourself (section 14) |
| Draft Board UI + routes (Req 1) | ⬜ Phase 2 |
| Scouting Report UI + routes (Req 2) | ⬜ Phase 3 |
| Concurrency demo, EXPLAIN demo | ⬜ Phase 4 |
| Deployment | ⬜ Phase 5 |

---

## 2. Architecture

```
Browser ──HTTPS──> App Engine Standard (Python 3.12, Flask, gunicorn)
                        │  psycopg 3 + connection pool
                        │  Unix socket /cloudsql/<project:region:instance>
                        ▼
                   Cloud SQL for PostgreSQL 16 (db-f1-micro, no authorized networks)
                        ▲
   laptop: etl/load_cricsheet.py → local Postgres → pg_dump → GCS → gcloud sql import
```

- **No ORM.** Raw SQL via psycopg 3 is easier to show and explain in the demos.
- **Server-rendered HTML** (Jinja templates) with a few lines of vanilla JS. No React.
- **Why PostgreSQL:**
  - The data is relational.
  - The analytics need window and aggregate functions, `FILTER`, generated columns and
    materialized views.
  - Postgres has real isolation levels (true `SERIALIZABLE`), row locks and `EXPLAIN ANALYZE`.
  - Cloud SQL supports it natively.

### Repo layout

```
app/
  __init__.py          create_app(), registers blueprints
  config.py            local DATABASE_URL vs Cloud SQL + Secret Manager
  db.py                pool, query(), query_one(), transaction(isolation=...)
  routes.py            home page, /healthz
  draft.py             ⬜ Phase 2 - Draft Board blueprint
  report.py            ⬜ Phase 3 - Scouting Report blueprint
  queries/scouting_report.sql   ✅ the report query
  templates/  static/
db/
  schema.sql           tables, keys, constraints (DROPS everything first)
  seed_reference.sql   roles, franchises, name history, seasons + auction rules, awards
  views.sql            metric views + materialized views
  indexes.sql          secondary indexes with justification
  grants.sql           least-privilege app user
etl/
  download_data.py     fetch Cricsheet JSON
  load_cricsheet.py    load everything (one transaction per match)
  build_contract_prices.py   match 2026 salary list to player ids
data/
  venue_aliases.csv, player_meta_ipl.csv, player_meta_supplement.csv,
  contracts_prices.csv, sources/ipl_2026_squads.csv
deploy/                gcp_setup.sh, push_db.sh, deploy_app.sh, teardown.sh, app.yaml.template
tests/                 pytest: data checks against official results + app tests
```

---

## 3. Local setup (Phase 0, ~15 min)

Prereqs: Python 3.12+, Docker Desktop (or a native PostgreSQL 16), git.

```bash
cp .env.example .env
make setup          # virtualenv + packages
make db-up          # PostgreSQL 16 in Docker on localhost:5432
make data           # download Cricsheet IPL JSON (~4 MB zip)
make load           # build schema + load everything (~15 s)
make test           # 15 tests: awards, NRR, champions match official results
make run            # http://localhost:8080
```

Native Postgres instead of Docker (macOS): `brew install postgresql@16 && brew services start postgresql@16 && createdb ipl`,
then set `DATABASE_URL=postgresql://localhost/ipl` in `.env`.

To test the app as the restricted user, as in production:
```sql
CREATE ROLE ipl_app LOGIN PASSWORD 'devpass';   -- then: psql $DATABASE_URL -f db/grants.sql
```
Then use `DATABASE_URL=postgresql://ipl_app:devpass@localhost:5432/ipl`.

**Phase 0 checklist:** `make test` is green; the home page shows 1,243 matches and the 2026 leaders.

---

## 4. Data sources and licensing

| Data | Source | License | Notes |
|---|---|---|---|
| Ball-by-ball, XIs, toss, results, POTM (2008–2026) | [Cricsheet](https://cricsheet.org) IPL JSON | ODC-BY (credit required: footer + README) | 1,243 matches; wash-outs with no balls are not in the data |
| Player DOB, country, batting/bowling style, role | `cricketdata` R package `player_meta` (from ESPNcricinfo) | GPL-3 | 789 of 816 players; 27 recent debutants in `player_meta_supplement.csv` (country assumed India; **verify**) |
| 2026 salaries (173 retained/traded + 77 auction buys) | Wikipedia "List of 2026 IPL personnel changes" → `data/sources/ipl_2026_squads.csv` | CC BY-SA | 226 matched to Cricsheet ids; 24 unmatched have never played an IPL game |
| Owners, home grounds, auction rules | `db/seed_reference.sql` | — | Rules: 2025 ₹120 cr; 2026/27 ₹125 cr, 8 overseas, 25 max squad, ₹18 cr overseas cap |

**Cleaning the loader does** (good Stage 2 talking points):
- **Venue names:** 60 spellings map to 36 real grounds through `venue_alias`. Renamed grounds
  are merged: Feroz Shah Kotla is now Arun Jaitley, and Motera is now Narendra Modi.
- **Team renames map to one franchise** through `franchise_name`: Delhi Daredevils → DC,
  Kings XI Punjab → PBKS, RCB "Bangalore" → "Bengaluru".
- **Season labels:** Cricsheet labels like "2007/08" and "2020/21" are replaced by the year of
  the first match.
- **Player keys:** players are keyed by Cricsheet registry id, never by name. Two different
  players are both called "Harmeet Singh".
- **Super overs** are stored with `is_super_over = TRUE` and excluded from every statistic.
- **Missing roles:** a player with no role in the bio data gets one inferred from how he
  played (stumpings → WK, bowls and bats → AR, and so on).

**Data checks (`tests/test_data.py`), all matching official figures:**
- 2024–2026 Orange and Purple Caps.
- 2025 MVP: Suryakumar Yadav, 320.5 points.
- League net run rate: KKR 2024 +1.428, SRH 2024 +0.414, PBKS 2025 +0.372.
- Champions for every season, and every team's 2026 salaries within the ₹125 cr purse.

**Known gap:** our MVP total for some seasons differs a little from the published figure. For
2026 we have Sooryavanshi on 414.5 against 436.5 in the published table. Runs, fours and sixes
match exactly, so the gap is probably in how fielding or dot balls are counted. Mention it as a
known limitation; the FAQ encourages acknowledging minor issues.

---

## 5. ERD (paste into the course ERD generator)

```
entity Franchise { franchise_id key, short_code, current_name, city, owner_group, founded_season, is_active }
entity weak FranchiseName { name key, from_season, to_season }
entity Venue { venue_id key, name, city, country }
entity weak VenueAlias { alias key }
entity Season { season_year key, start_date, end_date, purse_cr, min_squad, max_squad, max_overseas, overseas_cap_cr }
entity Role { role_code key, description, sort_order }
entity Player { player_id key, cricsheet_id, cricsheet_name, display_name, full_name, dob, country, batting_hand, bowling_arm, bowling_style, bowling_type }
entity Match { match_id key, match_number, match_date, stage, toss_decision, result, win_by_runs, win_by_wickets, method }
entity weak Innings { innings_no key, is_super_over, target_runs, target_overs }
entity weak Delivery { seq key, over_no, ball_in_over, batter_runs, wides, noballs, byes, legbyes, penalty }
entity Award { award_id key, award_name, description }
entity Scout { scout_id key, username, display_name }
entity DraftBoard { board_id key, name, purse_cr, max_squad, max_overseas, overseas_cap_cr, created_at }
entity DraftPick { pick_id key, priority, max_bid_cr, status, price_paid_cr, notes, updated_at, version }

relation identifying Known_as(Franchise 1..N!, FranchiseName 1..1!)
relation identifying Spelled_as(Venue 1..N!, VenueAlias 1..1!)
relation Home_ground(Franchise 0..1, Venue 0..N)
relation Plays_role(Player 0..1, Role 0..N)
relation Contract(Player 0..N, Franchise 0..N, Season 0..N) { price_cr, acquisition, is_captain }
relation In_season(Season 0..N, Match 1..1!)
relation Hosted_at(Venue 0..N, Match 1..1!)
relation Contested_by(Franchise 0..N, Franchise 0..N, Match 1..1!)
relation Toss_won_by(Franchise 0..N, Match 1..1!)
relation Won_by(Franchise 0..N, Match 0..1)
relation Player_of_match(Player 0..N, Match 0..1)
relation Match_squad(Player 0..N, Match 1..N!, Franchise 0..N)
relation identifying Has_innings(Match 0..N, Innings 1..1!)
relation Batting_side(Franchise 0..N, Innings 1..1!)
relation identifying Has_ball(Innings 0..N, Delivery 1..1!)
relation Faced_by(Player 0..N, Delivery 1..1!)
relation Bowled_by(Player 0..N, Delivery 1..1!)
relation Non_striker(Player 0..N, Delivery 1..1!)
relation Dismissal(Player 0..N, Delivery 0..1) { kind }
relation Fielded_by(Player 0..N, Delivery 0..N) { is_substitute }
relation Champion(Franchise 0..N, Season 0..1)
relation Runner_up(Franchise 0..N, Season 0..1)
relation Won_award(Player 0..N, Award 0..N, Season 0..N) { stat_value }
relation Plans_for(Franchise 0..N, DraftBoard 1..1!)
relation Targets_season(Season 0..N, DraftBoard 1..1!)
relation On_board(DraftBoard 0..N, DraftPick 1..1!)
relation Targets(Player 0..N, DraftPick 1..1!)
relation Slot_role(Role 0..N, DraftPick 1..1!)
relation Last_edited_by(Scout 0..N, DraftPick 0..1)
```

---

## 6. Database design walkthrough (Stage 2: 10%)

### 6.1 Tables, keys and why

| Table | PK | Foreign keys | Key constraints / design notes |
|---|---|---|---|
| `role` | `role_code` | — | CHECK in (BAT, WK, AR, BOWL). Lookup table, so the role checkboxes come from the DB. |
| `venue` | `venue_id` (serial) | — | `name` UNIQUE |
| `venue_alias` | `alias` | → venue | Many spellings → one ground |
| `franchise` | `franchise_id` | `home_venue_id` → venue | `short_code`, `current_name` UNIQUE; `is_active` marks defunct teams |
| `franchise_name` | `name` | → franchise | Name history with `from_season`/`to_season` (CHECK to ≥ from) |
| `season` | `season_year` | `champion_id`, `runner_up_id` → franchise | Auction rules stored per season, so the app never hard-codes ₹125 cr |
| `player` | `player_id` (serial) | `role_code` → role | `cricsheet_id` UNIQUE (natural key); **`is_overseas` is a generated column** (`country <> 'India'`) so it can never be wrong |
| `contract` | (`player_id`, `season_year`) | → player, season, franchise | The composite PK enforces one team per player per season; `price_cr` ≥ 0 |
| `match` | `match_id` (Cricsheet id) | season, venue, team1/team2/toss winner/winner → franchise, POTM → player | CHECKs: team1 ≠ team2; toss winner and winner ∈ {team1, team2}; no-result ⇒ no winner |
| `match_player` | (`match_id`, `player_id`) | → match (CASCADE), player, franchise | Playing XI (plus the impact substitute from 2023) |
| `innings` | (`match_id`, `innings_no`) | → match (CASCADE), batting/bowling team | **Weak entity** of match |
| `delivery` | (`match_id`, `innings_no`, `seq`) | → innings (CASCADE), batter/non-striker/bowler → player | **Weak entity** of innings. Raw facts only; `extra_runs`, `total_runs`, `is_legal_ball`, `is_ball_faced`, `bowler_runs`, `phase` are **generated columns** |
| `dismissal` | (`match_id`, `innings_no`, `seq`, `player_out_id`) | → delivery | Separate table because about 95% of balls have no wicket, and the batter out may be the non-striker. `bowler_credit` is generated (run outs don't count for the bowler) |
| `dismissal_fielder` | dismissal key + `fielder_id` | → dismissal, player | A run-out can involve several fielders |
| `award`, `season_award` | `award_id`; (`season_year`, `award_id`) | → season, award, player | Filled from the data by the loader |
| `scout` | `scout_id` | — | `username` UNIQUE. Who made a change, used in the concurrency demo. |
| `draft_board` | `board_id` | → franchise, season | Rules copied from `season` when the board is created; UNIQUE (franchise, season, name) |
| **`draft_pick`** (Req 1 main table) | `pick_id` | → board (CASCADE), player, role, scout | UNIQUE (board_id, player_id); CHECKs: priority 1–5, max_bid > 0, `status = 'Bought'` ⇔ `price_paid_cr` is set; `version` for optimistic locking |

### 6.2 Normalization decisions to talk about

- **3NF:** facts live once. For example, a franchise's name is not stored on every match; it
  comes through `franchise_id`.
- **Weak entities:** a delivery is identified by its innings, and an innings by its match.
  This matches the ERD's identifying relationships.
- **Derived values are never typed in by hand:**
  - Strike rate, economy, age and "overseas" are calculated.
  - The generated columns are computed by Postgres, so they can never disagree with the raw data.
- **Deliberate denormalization:**
  - `innings.bowling_team_id` could be worked out from `match`, but nearly every bowling query
    needs it. It is kept consistent by a CHECK and by the loader.
  - The two **materialized views** are pre-aggregated copies of `delivery`. They are refreshed
    after each load (the data is historical and only changes when we reload).
- **The app writes only `draft_board`, `draft_pick` and `scout`.** Match data is read-only to
  the app user (`db/grants.sql`).

---

## 7. Metrics dictionary

Phases: **Powerplay** = overs 1–6, **Middle** = 7–15, **Death** = 16–20 (`delivery.phase`).

| Metric | Formula (SQL) | Why scouts care |
|---|---|---|
| Strike rate | `100 * runs / balls_faced` (wides not faced) | Scoring speed, the key T20 batting stat |
| Batting average | `runs / outs` (retired hurt is not out) | Consistency |
| Boundary % | `100 * (4s + 6s) / balls_faced` | Power-hitting |
| Dot % (batting) | `100 * dots_faced / balls_faced` | Pressure absorbed; lower is better |
| SR vs pace / vs spin | runs and balls split by the bowler's `bowling_type` | Matchups (e.g. weak vs spin → avoid at Chepauk) |
| Economy | `6 * bowler_runs / legal_balls` (byes and leg-byes not charged) | Run control, especially at the death |
| Bowling average / SR | `runs_conceded / wickets`, `legal_balls / wickets` | Wicket-taking |
| Dot % (bowling) | `100 * dots_bowled / legal_balls` | Pressure created |
| Wickets | dismissals with `bowler_credit` (not run out or retired) | Purple Cap rules |
| 30s / 50s / 100s, highest score | per-innings totals | Big-innings ability |
| 3W / 4W / 5W hauls, best figures | per-innings wickets | Match-winning spells |
| Catches / stumpings / run outs | `dismissal_fielder` (+ caught & bowled to the bowler) | Fielding value |
| **MVP points** (official IPL formula) | `3.5·6s + 2.5·4s + 3.5·wkts + 1·dot balls + 2.5·(catches + stumpings)` | One all-round impact number |
| **MVP per crore** | `(mvp_points / seasons) / price_cr` | **Value for money**; higher is better |
| Net run rate | `runs_for / overs_faced − runs_against / overs_bowled`; all out ⇒ full quota; league only | Table tiebreaker |
| Powerplay run rate / death economy (team) | from `v_innings_summary` | Team phase strength |
| Venue profile | avg 1st-innings score, chase win %, spin wicket % | Fit the squad to the home ground |

Views: `mv_player_phase_stats` (player × season × phase), `mv_player_season_stats`
(player × season), `v_team_season_stats`, `v_venue_stats`, `v_innings_summary`,
`v_draft_board_summary` (purse, slots and role balance, always current).

---

## 8. Phase 2: Requirement 1, Draft Board (main table `draft_pick`)

### 8.1 User stories
1. As a scout, I pick **who I am** (dropdown from `scout`) so changes are attributed to me.
2. I see my board: purse left, squad count / 25, overseas count / 8, role balance, and the
   list of picks.
3. I **add** a player: search by name, pick a role slot (dropdown from `role`), priority 1–5,
   max bid (₹ cr), notes.
4. I **edit** a pick: change bid, priority, role slot, notes; **mark Bought** with a price
   paid, or **Lost**.
5. I **delete** a pick.
6. The app refuses anything that breaks the auction rules and tells me why.

### 8.2 Routes (`app/draft.py`, blueprint `draft`, url_prefix `/draft`)

| Method | Path | Does |
|---|---|---|
| GET | `/draft` | Board page (endpoint name **`board`**, so the nav link appears) |
| GET | `/draft/players/search?q=` | JSON: up to 15 players matching `q`, for the add form's search box |
| POST | `/draft/picks` | Add a pick |
| GET | `/draft/picks/<pick_id>/edit` | Edit form |
| POST | `/draft/picks/<pick_id>` | Update a pick (including Bought or Lost) |
| POST | `/draft/picks/<pick_id>/delete` | Delete a pick |
| POST | `/draft/scout` | Set `session["scout_id"]` |

Use POST-redirect-GET and `flash()` for success and error messages. Use `request.form` and
convert types explicitly; reject bad input with a 400 or a flash message.

### 8.3 SQL (all parameterized)

```sql
-- board header (view keeps purse/slots live)
SELECT * FROM v_draft_board_summary WHERE board_id = %(board_id)s;

-- board list
SELECT dp.*, p.display_name, p.is_overseas, p.country, r.description AS role_name,
       c.price_cr AS last_salary, f.short_code AS last_team, s.display_name AS updated_by_name
FROM draft_pick dp
JOIN player p USING (player_id)
JOIN role r ON r.role_code = dp.role_slot
LEFT JOIN contract c ON c.player_id = dp.player_id AND c.season_year = 2026
LEFT JOIN franchise f ON f.franchise_id = c.franchise_id
LEFT JOIN scout s ON s.scout_id = dp.updated_by
WHERE dp.board_id = %(board_id)s
ORDER BY dp.status, dp.priority, p.display_name;

-- player search (escape % and _ in the user's text before adding the wildcards)
SELECT player_id, display_name, role_code, country
FROM player
WHERE display_name ILIKE %(pattern)s OR cricsheet_name ILIKE %(pattern)s
ORDER BY display_name LIMIT 15;

-- add
INSERT INTO draft_pick (board_id, player_id, role_slot, priority, max_bid_cr, notes, updated_by)
VALUES (%(board_id)s, %(player_id)s, %(role_slot)s, %(priority)s, %(max_bid_cr)s, %(notes)s, %(scout_id)s)
RETURNING pick_id;
-- UniqueViolation on (board_id, player_id) → flash "already on the board"

-- delete
DELETE FROM draft_pick WHERE pick_id = %(pick_id)s AND board_id = %(board_id)s;
```

### 8.4 The "Buy" transaction (also the Stage 3 transactions story)

Marking a pick **Bought** must check the purse, squad size, overseas count and overseas cap,
then update the pick. If two scouts buy at the same time, both checks could pass and the
board would overspend. This is the classic **write skew**.

```python
from psycopg import errors
from .db import transaction

def buy_player(board_id, pick_id, price_cr, expected_version, scout_id):
    with transaction("READ COMMITTED") as conn:
        # 1) Lock the board row: a second Buy on the same board waits here until we commit.
        board = conn.execute(
            "SELECT * FROM draft_board WHERE board_id = %s FOR UPDATE", (board_id,)).fetchone()
        s = conn.execute("SELECT * FROM v_draft_board_summary WHERE board_id = %s",
                         (board_id,)).fetchone()
        pick = conn.execute(
            """SELECT dp.*, p.is_overseas FROM draft_pick dp JOIN player p USING (player_id)
               WHERE dp.pick_id = %s AND dp.board_id = %s""", (pick_id, board_id)).fetchone()
        # 2) Business rules (read AFTER the lock, so they see the other scout's committed buy)
        if pick is None:                                   raise ValueError("Pick not found")
        if pick["status"] == "Bought":                     raise ValueError("Already bought")
        if price_cr > s["remaining_cr"]:                   raise ValueError("Not enough purse left")
        if s["squad_count"] >= board["max_squad"]:         raise ValueError("Squad is full (25)")
        if pick["is_overseas"] and s["overseas_count"] >= board["max_overseas"]:
                                                           raise ValueError("No overseas slots left (8)")
        if pick["is_overseas"] and board["overseas_cap_cr"] and price_cr > board["overseas_cap_cr"]:
                                                           raise ValueError("Overseas fee cap is ₹18 cr")
        # 3) Optimistic check: the row must not have changed since the user opened the form
        cur = conn.execute(
            """UPDATE draft_pick SET status = 'Bought', price_paid_cr = %s, updated_by = %s,
                      updated_at = now(), version = version + 1
               WHERE pick_id = %s AND version = %s""",
            (price_cr, scout_id, pick_id, expected_version))
        if cur.rowcount == 0:
            raise ValueError("Someone else changed this pick, reload and try again")
    # leaving the with-block commits; any exception above rolls everything back
```

Ordinary edits (bid, notes, priority) use the same `version` check without the board lock.

### 8.5 Acceptance criteria (demo these)
- Add Kohli as BAT, priority 1, max bid 20, and he appears in the list. Edit his bid to 22 and
  the change shows. Delete him and he's gone. The header numbers update each time.
- Buying a player with more money than the purse has left shows an error and changes nothing.
- Adding the same player twice shows a friendly error (the UNIQUE constraint).
- A ninth overseas buy is refused.
- Two browser windows as two scouts, editing the same pick: the second save shows "someone
  else changed this pick".

**Claude Code prompt:** *"Read plan.md sections 8 and 10 and CLAUDE.md. Build the Draft Board:
app/draft.py blueprint (endpoint `board` at /draft), templates draft/board.html and
draft/edit.html, the player search endpoint with a small vanilla-JS autocomplete, and the buy
transaction exactly as in 8.4. Register the blueprint in app/__init__.py. Add pytest tests in
tests/test_draft.py for add/edit/delete, purse limit, overseas limit, and the version
conflict. Then walk me through every SQL statement."*

---

## 9. Phase 3: Requirement 2, Scouting Report

### 9.1 Filters (left panel, GET form so the URL is shareable)

| Filter | Control | Source (built from the DB) |
|---|---|---|
| Season from / to | 2 dropdowns | `SELECT DISTINCT season_year FROM match ORDER BY 1` |
| Phase | 3 checkboxes | `SELECT DISTINCT phase FROM mv_player_phase_stats` (fixed order: Powerplay, Middle, Death) |
| Role | checkboxes | `SELECT role_code, description FROM role ORDER BY sort_order` |
| Current team | dropdown (+ "Any") | `SELECT franchise_id, current_name FROM franchise WHERE is_active ORDER BY current_name` |
| Nationality | radio: Any / Indian / Overseas | fixed |
| Bowling type | dropdown: Any / Pace / Spin | `SELECT DISTINCT bowling_type FROM player WHERE bowling_type IS NOT NULL` |
| Age min / max | 2 number inputs | — |
| Salary min / max (₹ cr) | 2 number inputs | — |
| Min balls (faced or bowled) | number, default 60 | — |
| Hide players already on my board | checkbox | — |
| Sort by | dropdown | whitelist below |

Defaults: the last 3 seasons, all phases, all roles, min balls 60, sorted by MVP points.

### 9.2 Query
Use **`app/queries/scouting_report.sql`** (already tested: 8 ms). Load it once at import and
append the ORDER BY from a whitelist:

```python
SORT_COLUMNS = {   # user picks a KEY; only these fixed SQL strings are ever appended
    "mvp": "mvp_points DESC NULLS LAST",
    "value": "mvp_per_crore DESC NULLS LAST",
    "sr": "strike_rate DESC NULLS LAST",
    "runs": "runs DESC NULLS LAST",
    "avg": "batting_avg DESC NULLS LAST",
    "econ": "economy ASC NULLS LAST",
    "wkts": "wickets DESC NULLS LAST",
    "dot": "dot_pct_bowled DESC NULLS LAST",
    "price": "price_cr DESC NULLS LAST",
}
order = SORT_COLUMNS.get(request.args.get("sort"), SORT_COLUMNS["mvp"])
sql = REPORT_SQL + f" ORDER BY {order}, player LIMIT 200"   # order comes from the dict, never from the user
```

Run it with `transaction("REPEATABLE READ", read_only=True)` together with the
board-summary query, so the table and the summary are one consistent snapshot.

### 9.3 Output
- **Summary cards:** number of players, average salary, total runs, overall strike rate
  (Σruns/Σballs), overall economy, best value (top MVP per crore). Plus the board panel from
  `v_draft_board_summary`: purse left, squad x/25, overseas x/8.
- **Table:** player (link to profile, optional), team, role, age, overseas flag, salary,
  matches, runs, SR, avg, boundary %, SR vs pace / spin, wickets, economy, dot %, MVP,
  MVP/crore, **Board status** (Target / Bought / Lost / –) with an "Add to board" button
  that posts to `/draft/picks`.
- Empty state: "No players match. Try lowering Min balls."

### 9.4 Before/after demo (the rubric asks for it explicitly)
1. Run the report: overseas death-over pacers 2024–2026, sorted by economy. Note that
   Pathirana's status is "–" and purse left is ₹125 cr.
2. Go to the Draft Board, add Pathirana, then mark him Bought for ₹14 cr.
3. Re-run the same report URL. His status is now **Bought**, purse left is **₹111 cr**,
   overseas is **1/8**, and with "hide players already on my board" ticked he disappears.

**Claude Code prompt:** *"Read plan.md sections 9–11 and CLAUDE.md. Build the Scouting Report
blueprint (endpoint `scouting` at /report) using app/queries/scouting_report.sql unchanged,
with all dropdowns and checkboxes loaded from the database as listed in 9.1, the
SORT_COLUMNS whitelist, a REPEATABLE READ read-only transaction, summary cards, and an
'Add to board' button. Add tests in tests/test_report.py, including one that passes a
SQL-injection string as a filter value and as the sort key. Then explain the query to me
line by line."*

---

## 10. UI built from the database (Stage 2: 5%)

Every list the user picks from is queried, never hard-coded:

| Component | Query |
|---|---|
| Scout selector | `SELECT scout_id, display_name FROM scout ORDER BY display_name` |
| Role slot (Draft Board) and role checkboxes (report) | `SELECT role_code, description FROM role ORDER BY sort_order` |
| Season range | `SELECT DISTINCT season_year FROM match ORDER BY season_year` |
| Team dropdown | `SELECT franchise_id, current_name FROM franchise WHERE is_active ORDER BY current_name` |
| Bowling type | `SELECT DISTINCT bowling_type FROM player WHERE bowling_type IS NOT NULL ORDER BY 1` |
| Player search | `/draft/players/search?q=` (section 8.3) |

**Demo proof:** insert a row in `role` or `scout` in psql, refresh the page, and the new
option appears. Then show the query in `app/report.py`.

---

## 11. Security: SQL injection and more (Stage 3: 7%)

1. **Parameterized queries everywhere.** psycopg sends the SQL text and the values
   separately (`%s` / `%(name)s`); a value can never become SQL. `tests/test_report.py`
   proves it: `bowling_type = "Pace' OR '1'='1"` returns 0 rows instead of every player.
2. **No dynamic SQL from input.**
   - Optional filters use `(%(x)s IS NULL OR col = %(x)s)`.
   - The one dynamic piece, ORDER BY, comes from the `SORT_COLUMNS` dict.
   - `LIKE` searches escape `%` and `_` in the user's text.
3. **Input validation:** convert to int/Decimal, check ranges and allowed values (status ∈
   {Target, Bought, Lost}), and return 400 on bad input.
4. **Least privilege:** the app connects as `ipl_app`, which can SELECT everything but only
   write `draft_board`, `draft_pick` and `scout`. Demo: run `DELETE FROM match` as
   `ipl_app` → `permission denied`.
5. **Database rules as the last line of defense:** CHECK, UNIQUE and FK constraints reject bad
   data even if app code has a bug.
6. **XSS:** Jinja autoescapes all output; never use `|safe` on user text.
7. **CSRF:** add `Flask-WTF` `CSRFProtect` and put `{{ csrf_token() }}` in every POST form.
8. **Secrets:** no passwords in git. Locally they live in `.env` (git-ignored); in the cloud
   they live in Secret Manager.

---

## 12. Indexes (Stage 3: 6%)

The index definitions and their justifications are in `db/indexes.sql`. Measured on this data:

| Index | Serves | Evidence |
|---|---|---|
| `ix_mv_phase_season_phase (season_year, phase)` | Scouting Report season + phase filter (every report run) | Bitmap Index Scan, 0.5 ms |
| `ix_mv_season_season (season_year)` | Report season-level columns (matches, 50s, MVP) | |
| `ix_contract_season_franchise (season_year, franchise_id)` | Report "current team" filter + salary join; team → squad list | |
| `ix_delivery_batter`, `ix_delivery_bowler` | Player profile / pace-vs-spin for one player | Kohli: **2.7 ms with index vs 17 ms seq scan** over 295,732 rows |
| `ix_dismissal_player_out` | One player's dismissals (batting average) | |
| `ix_match_season_date`, `ix_match_venue` | Team/venue pages by season; match lists | |
| (PK/UNIQUE) `draft_pick (board_id, player_id)` | Board list + purse check in the Buy transaction | already indexed by the constraint |
| **Rejected:** trigram index on player names | Player search box | Planner still seq-scans 816 rows (0.5 ms), so not worth it |

**Demo recipe:**
```sql
EXPLAIN (ANALYZE) <report query or single-player query>;          -- with index
BEGIN; DROP INDEX ix_delivery_batter;
EXPLAIN (ANALYZE) SELECT count(*) FROM delivery WHERE batter_id = 1;  -- now a Seq Scan
ROLLBACK;                                                          -- index comes back
```
(DDL is transactional in Postgres, so `ROLLBACK` restores the index. Another nice talking point.)

Optional Phase 4 extra: a player profile page `/players/<id>` with season-by-season numbers
and pace/spin splits, which exercises indexes 4–5.

---

## 13. Transactions, concurrency, isolation (Stage 3: 6%)

| Operation | Isolation | Mechanism | Why |
|---|---|---|---|
| Load one match (ETL) | READ COMMITTED | One transaction per match file | A bad file never leaves half a match. Shown in `etl/load_cricsheet.py` |
| Add / edit / delete pick | READ COMMITTED | `version` column (optimistic locking) | Prevents **lost updates** when two scouts edit the same pick |
| **Buy** (purse / slot rules) | READ COMMITTED + `SELECT … FOR UPDATE` on the board row | Pessimistic lock | Prevents **write skew**: two buys that each fit the purse alone but not together |
| Scouting Report + board summary | REPEATABLE READ, READ ONLY | Snapshot | Table and summary come from the same instant; no locks taken |

**Why not SERIALIZABLE for Buy?** It would also prevent write skew, but the loser gets a
serialization failure and the app would need retry logic. Locking one board row is
simpler, explicit and cheap; only buys on the same board wait. Mention this trade-off.

**Concurrency demo (`tests/concurrency_demo.py`, Phase 4):**
- Two threads try to buy two different **Indian** players for ₹70 cr each on the same ₹125 cr
  board. They must be Indian because the ₹18 cr overseas cap would block an overseas buy.
- With the lock, one succeeds and the other gets "Not enough purse left".
- Remove `FOR UPDATE` and both succeed, so the purse goes to −₹15 cr.
- Print timings to show the second thread waiting.
- Also show the lost-update case with and without the version check.

**Claude Code prompt:** *"Read plan.md sections 12–13. Write tests/concurrency_demo.py: two
threads using app.db.transaction to show the write-skew problem without FOR UPDATE and the fix
with it, plus a lost-update demo with and without the version check. Add a script
docs/explain_demo.sql with the EXPLAIN recipe. Explain both to me."*

---

## 14. Phase 5: Deploy to Google Cloud (extra credit +1%)

**Why App Engine Standard + Cloud SQL:** the course recommends App Engine, it scales to zero,
and its built-in Unix socket reaches Cloud SQL without opening the database to the internet.

**Cost:** about $8/month for db-f1-micro + about $2 storage. App Engine F1 at low traffic is
mostly free-tier. New Google Cloud accounts get a $300 credit. **Do not** use the Cloud SQL
"free trial instance": it stops after 30 days, so one created now ends before 12/23.

**Steps (run on your laptop):**
1. Install the gcloud CLI, then `gcloud auth login`. Create a project and link billing in the console.
2. `cp deploy/gcp.env.example deploy/gcp.env` and set `PROJECT_ID` (optionally `BILLING_ACCOUNT`).
3. `make deploy-setup`. This enables APIs, creates Postgres 16 (about 10 min), the `ipl` DB, the
   `ipl_app` user with a random password, secrets, IAM, App Engine and the import bucket.
4. `make load && make deploy-db`. This dumps the local DB, imports it into Cloud SQL, applies grants
   and deletes the dump.
5. `make deploy-app`. It prints `https://<project>.uc.r.appspot.com`.
6. Check: `/healthz` returns `{"status":"ok"}`; the home page shows 1,243 matches; add/edit/delete a
   pick and see the report change.

**Security checklist (FAQ #3 warns about hacked databases):**
- [x] No authorized networks: Postgres is not reachable from the internet.
- [x] `--ssl-mode=ENCRYPTED_ONLY`.
- [x] Random 28-character passwords, kept only in Secret Manager; nothing in git.
- [x] The app uses `ipl_app` (least privilege), not `postgres`.
- [x] The App Engine service account has only `cloudsql.client` + access to its two secrets.
- [x] `secure: always` (HTTPS only); `max_instances: 2` caps cost.
- [x] Budget alert at $20 (if `BILLING_ACCOUNT` is set).
- [ ] After 12/23 11:59 pm: `bash deploy/teardown.sh` deletes the project.

**For the TA (put this in the README and the Stage 3 submission):** URL, plus "Go to Draft
Board → add any player → mark Bought → open Scouting Report and tick *hide players on my
board*". In the demo, show the Cloud SQL instance and the App Engine dashboard in the console
as proof of hosting.

If something fails: `gcloud app logs tail -s default`. A typical cause is a missing IAM role or
a secret name typo in `app.yaml`.

---

## 15. Testing

- `tests/test_data.py`: data matches official results (already green).
- `tests/test_draft.py` (Phase 2): CRUD, rule violations, version conflict.
- `tests/test_report.py` (Phase 3): filters, sort whitelist, injection strings, before/after.
- Run `make test` before every commit and before recording.

---

## 16. Demo scripts

### Stage 2 (5–15 min, aim for ~10)
1. **(1 min) Intro:** what the app is, the stack, the data source (Cricsheet, 295k balls).
2. **(2 min) Database design:** open `db/schema.sql`.
   - Walk the PKs and FKs.
   - Show the weak entities `innings` and `delivery`.
   - Show the generated columns, the CHECKs, and why `contract` has a composite PK.
   - Show the ERD.
3. **(3 min) Requirement 1:**
   - Add, edit and delete a pick, and Buy one.
   - Show the purse/overseas rule refusing a bad buy.
   - Then walk the code: route → SQL → transaction.
4. **(3 min) Requirement 2:**
   - Run the report with filters and show the results and summary.
   - Change data (Buy a player), re-run, and point out what changed.
   - Walk `scouting_report.sql` and the Python that runs it.
5. **(1 min) Dynamic UI:** show the dropdown queries; insert a `scout` row live and refresh.
6. **(30 s) Known limitations:** wash-outs aren't in the data; the MVP total is slightly off
   the published figure for some seasons.

### Stage 3 (5–10 min)
1. **(2 min) SQL injection:** show the parameterized code, the ORDER BY whitelist and LIKE
   escaping, then the injection test live. Also show the least-privilege user being denied
   `DELETE FROM match`.
2. **(2 min) Indexes:** go through the table in section 12, run the EXPLAIN before/after, and
   say which report each index serves.
3. **(2 min) Transactions:** show the Buy code, run the concurrency demo, explain the isolation
   choices and why not SERIALIZABLE.
4. **(1.5 min) AI usage:** tools (Claude / Claude Code), what each helped with, how you
   verified it (tests against official stats, EXPLAIN, reading docs), and what you changed
   yourself.
5. **(1 min) Cloud:** the live URL, the Cloud SQL and App Engine consoles, a TA-style edit
   showing the report updating.
6. **(30 s)** Changes since Stage 2, and any known bugs.

---

## 17. Schedule

| Date | Goal |
|---|---|
| Mon 11/9 (night) | Phase 0: local setup, `make test` green |
| Tue 11/10 | Phase 2 Draft Board + Phase 3 Scouting Report |
| Wed 11/11 | Polish, rehearse, **record + submit the Stage 2 demo** |
| 11/12–11/20 | Phase 5 deploy (do it early so cloud problems surface early) |
| 11/21–12/4 | Phase 4: concurrency demo, EXPLAIN demo, CSRF, player profile page (optional) |
| 12/5–12/10 | README "AI Usage", rehearse, **record Stage 3**, submit URL + GitHub link |
| 12/11–12/23 | Keep the app live; don't redeploy breaking changes |
| after 12/23 | `deploy/teardown.sh` |

---

## 18. Known limitations
- Matches abandoned without a ball are not in Cricsheet, so a team's "matches" can be lower
  than the official table (KKR 2024 shows 14, not 16).
- Player bios for 27 recent debutants: country assumed India; role inferred from play; bowling
  style blank (they are excluded from the pace/spin filter until filled in).
- The 2027 auction rules are assumed to equal 2026's until the BCCI announces them (edit the
  `season` row).
- MVP points for some seasons differ slightly from published figures (section 4).
