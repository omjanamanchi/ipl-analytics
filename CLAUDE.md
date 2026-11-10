# CLAUDE.md — house rules for this repo

CS348 database course project: **IPL Auction War Room** (Flask + PostgreSQL 16, deployed to
Google App Engine + Cloud SQL). The full build plan, specs and demo scripts are in
**plan.md**: read the relevant section before starting any task.

## Commands
- `make setup` / `make db-up` / `make data` / `make load`: local environment and data
- `make test`: pytest against the local DB (must stay green)
- `make run`: http://localhost:8080
- `make deploy-db`, `make deploy-app`: cloud (see plan.md section 14)

## Non-negotiable rules (they are graded)
1. **Parameterized SQL only.** Pass every value as `%s` / `%(name)s` to psycopg.
   - Never build SQL with f-strings, `+` or `.format()` from request data.
   - The only allowed f-string in SQL is appending a value looked up from a hard-coded
     whitelist dict (e.g. `SORT_COLUMNS`).
   - Escape `%` and `_` before LIKE/ILIKE.
2. **No ORM.** Use `app/db.py`:
   - `query()` / `query_one()` for reads.
   - `transaction(isolation=..., read_only=...)` for anything that writes or needs a
     consistent snapshot.
   - Always state the isolation level explicitly.
3. **Dropdowns and checkboxes are loaded from the database**, never hard-coded (plan.md section 10).
4. **The app writes only** `draft_board`, `draft_pick`, `scout`. Match/stat tables are
   read-only (the production DB user cannot write them anyway; see db/grants.sql).
5. Updates to `draft_pick` must check and bump `version` (optimistic locking). Buying must use
   the board-row `FOR UPDATE` transaction in plan.md section 8.4.
6. Keep SQL readable and commented. The student must explain every query on camera, so
   prefer clear CTEs over clever tricks, and don't add abstractions.
7. Schema changes go in `db/*.sql` and must keep `make load` + `make test` working.
   Statistics come from the views in `db/views.sql`; don't recompute metrics in Python.
8. Jinja autoescaping stays on; never mark user input `|safe`. POST forms carry a CSRF token
   once Flask-WTF is added.
9. No secrets in git (`.env`, `deploy/gcp.env` and `app.yaml` are ignored).

## Layout
- `app/`: Flask app. Feature blueprints: `draft.py` (Requirement 1), `report.py` (Requirement 2)
- `app/queries/scouting_report.sql`: the tested report query; use it as-is
- `db/`: schema, seed, views, indexes, grants
- `etl/`: Cricsheet download and load; contract price matching
- `deploy/`: Google Cloud scripts
- `tests/`: pytest

## Data facts worth knowing
- Players are keyed by `player_id` (FK) / `cricsheet_id` (natural key), never by name.
  Show `display_name` in the UI.
- `delivery.phase`: Powerplay overs 1–6, Middle 7–15, Death 16–20 (`over_no` is 0-based).
- Super-over innings (`innings.is_super_over`) are excluded from all stats.
- Current salaries are in `contract` for `season_year = 2026`. The draft board targets 2027.
- Credit Cricsheet (ODC-BY) wherever data is displayed (already in the footer).

## When you finish a task
Run `make test`, then summarize for the student: what changed, each new SQL statement and
why, and anything they should verify themselves. Add a line to the "AI Usage log" in
README.md describing what you helped with.
