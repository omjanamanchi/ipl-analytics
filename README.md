# IPL Analytics

A database-backed web app that helps an IPL franchise plan its **2027 auction**. It scouts every
player using ball-by-ball data from 2008 to 2026 and builds a squad that obeys the real auction
rules: ₹125 cr purse, at most 25 players, at most 8 overseas, overseas fee capped at ₹18 cr.

CS348 (Purdue, Fall 2026) semester project · Flask + PostgreSQL 16 · Google App Engine + Cloud SQL

- **Live app:** _add URL after deployment_
- **Build plan / design doc:** [plan.md](plan.md)

## Features
- **Draft Board (Requirement 1):** add, edit and delete target players. Mark them Bought or
  Lost. The database checks purse, squad-size and overseas limits inside a transaction.
- **Scouting Report (Requirement 2):** filter by season range, game phase, role, team,
  nationality, bowling type, age and salary. Ranks players by strike rate, economy, phase and
  pace/spin splits, IPL MVP points and **MVP points per crore** (value for money).
- **The data:**
  - 1,243 matches and 295,732 deliveries.
  - Player bios for 816 players and 2026 salaries for 226.
  - Checked against the official 2024–2026 Orange and Purple Caps, the 2025 MVP, net run rates
    and every champion.

## Quick start
```bash
cp .env.example .env
make setup && make db-up      # Python venv + PostgreSQL 16 in Docker
make data && make load        # download Cricsheet data and load it (~15 s)
make test                     # data checks against official results
make run                      # http://localhost:8080
```
Deployment: see [plan.md, section 14](plan.md#14-phase-5-deploy-to-google-cloud-extra-credit-1).

## Repository
| Path | Contents |
|---|---|
| `db/` | `schema.sql` (tables, keys, constraints), `views.sql` (metrics), `indexes.sql`, `grants.sql`, `seed_reference.sql` |
| `etl/` | Cricsheet download + loader (one transaction per match), 2026 salary matching |
| `app/` | Flask app, `db.py` (pool + transactions with explicit isolation), `queries/` |
| `deploy/` | Google Cloud setup, DB push, deploy and teardown scripts |
| `tests/` | pytest |

## Data sources and credits
- **Ball-by-ball match data:** [Cricsheet](https://cricsheet.org), licensed under the
  [Open Data Commons Attribution License](https://cricsheet.org/licensing/). Mirror used as a
  fallback: [ritesh-ojha/IPL-DATASET](https://github.com/ritesh-ojha/IPL-DATASET).
- **Player metadata** (DOB, country, batting/bowling style, role): `player_meta` from the
  [cricketdata](https://github.com/robjhyndman/cricketdata) R package (GPL-3), sourced from
  ESPNcricinfo.
- **2026 squads and salaries:** compiled from Wikipedia's *List of 2026 Indian Premier League
  personnel changes* (CC BY-SA), in `data/sources/ipl_2026_squads.csv`.

## AI Usage
_Required by the course AI policy. Keep this up to date and discuss it in the Stage 3 demo._

**Tools used:**
- Claude (claude.ai) for planning, research and the initial database/ETL/deployment setup.
- Claude Code for building the features from `plan.md`.

**What AI assisted with:**
- Researching IPL data sources and the 2026 auction rules.
- Designing the schema.
- Writing the Cricsheet loader, SQL views and deployment scripts.
- Drafting `plan.md`.
- Building the user accounts system: replaced `scout` table with `app_user`, added `board_member` and `owner_id` to `draft_board`, rewrote `auth.py` with sign-up/login (by username or email)/lockout/guest mode, updated `draft.py` with `_require_editor` checks and `my_boards`/`share_board` routes, updated all templates, and added `tests/test_auth.py` with 11 new tests (all 52 tests pass).

**How the output was verified or modified:**
- The loaded data is tested against published figures (`tests/test_data.py`): Orange and
  Purple Caps, 2025 MVP, net run rates, champions.
- Indexes were checked with `EXPLAIN ANALYZE`. A trigram index was rejected because the
  planner did not use it.
- The 2026 salary-to-player matching was reviewed by hand. About 10 wrong automatic matches
  were fixed with explicit overrides, and a duplicate-id guard was added.
- Cloud setup choices were checked against the Google Cloud documentation.
- _(add what you personally reviewed, changed or rewrote, e.g. "rewrote the Buy transaction
  validation messages", "changed default filters")_

### AI usage log
| Date | Tool | Task | How I verified / what I changed |
|---|---|---|---|
| 2026-11-09 | Claude | Schema, loader, views, indexes, deploy scripts, plan.md | Ran the loader and 15 tests against official stats; reviewed the schema |
| 2026-11-09 | Claude Code | Added .gitattributes (LF for .sh/.sql), python-dotenv, renamed app title to IPL Analytics | Ran 15 tests (all passed); verified app starts on port 8080 |
| 2026-11-09 | Claude Code | Built Draft Board blueprint (Phase 2): all CRUD routes, buy transaction, Flask-WTF CSRF, autocomplete, 8 new tests | Ran 23 tests (all passed); walked through every SQL statement |
| 2026-11-10 | Claude Code | Built Scouting Report blueprint (Phase 3): all filters from DB, SORT_COLUMNS whitelist, REPEATABLE READ snapshot, before/after demo, 18 new tests | Ran 41 tests (all passed); performed the before/after demo manually |
