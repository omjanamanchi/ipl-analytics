"""Scouting Report blueprint — Requirement 2.

One fixed SQL text (app/queries/scouting_report.sql) loaded once at import.
The only dynamic part is ORDER BY, appended from the SORT_COLUMNS whitelist.
Everything else is a psycopg parameter — no SQL is ever built from user input.
"""
from __future__ import annotations

import pathlib
from decimal import Decimal, InvalidOperation

from flask import Blueprint, render_template, request

from .db import query, query_one, transaction

bp = Blueprint("report", __name__, url_prefix="/report")

# ── SQL loaded once at import time ────────────────────────────────────────────
_SQL_FILE = pathlib.Path(__file__).parent / "queries" / "scouting_report.sql"
REPORT_SQL = _SQL_FILE.read_text()

# ── ORDER BY whitelist (plan.md section 9.2) ──────────────────────────────────
# The user sends a KEY; Python looks up the fixed SQL fragment from this dict.
# The fragment is appended with an f-string, but it comes from this hard-coded
# dict, never from user input directly.
SORT_COLUMNS: dict[str, str] = {
    "mvp":   "mvp_points DESC NULLS LAST",
    "value": "mvp_per_crore DESC NULLS LAST",
    "sr":    "strike_rate DESC NULLS LAST",
    "runs":  "runs DESC NULLS LAST",
    "avg":   "batting_avg DESC NULLS LAST",
    "econ":  "economy ASC NULLS LAST",
    "wkts":  "wickets DESC NULLS LAST",
    "dot":   "dot_pct_bowled DESC NULLS LAST",
    "price": "price_cr DESC NULLS LAST",
}

SORT_LABELS: dict[str, str] = {
    "mvp":   "MVP points",
    "value": "MVP / cr (value)",
    "sr":    "Strike rate",
    "runs":  "Runs",
    "avg":   "Batting avg",
    "econ":  "Economy",
    "wkts":  "Wickets",
    "dot":   "Dot % (bowling)",
    "price": "Salary",
}

_CONTRACT_SEASON = 2026
_PHASE_ORDER     = {"Powerplay": 0, "Middle": 1, "Death": 2}


# ── helpers ───────────────────────────────────────────────────────────────────

def _board_id() -> int:
    row = query_one("SELECT board_id FROM draft_board ORDER BY board_id LIMIT 1")
    if row is None:
        raise RuntimeError("No draft board — run make load")
    return row["board_id"]


def _int_or_none(value: str | None) -> int | None:
    s = (value or "").strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _decimal_or_none(value: str | None) -> Decimal | None:
    s = (value or "").strip()
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


# ── route ─────────────────────────────────────────────────────────────────────

@bp.route("")
def scouting():
    # ── load every dropdown / checkbox from the database (plan.md section 10) ─
    seasons_db = query("SELECT DISTINCT season_year FROM match ORDER BY season_year")
    all_seasons = [r["season_year"] for r in seasons_db]

    # Phase checkboxes — Powerplay / Middle / Death display order
    phases_db  = query("SELECT DISTINCT phase FROM mv_player_phase_stats ORDER BY phase")
    all_phases = sorted(
        [r["phase"] for r in phases_db],
        key=lambda p: _PHASE_ORDER.get(p, 99),
    )

    roles_db  = query("SELECT role_code, description FROM role ORDER BY sort_order")
    all_roles = [(r["role_code"], r["description"]) for r in roles_db]

    franchises = query(
        "SELECT franchise_id, current_name FROM franchise WHERE is_active ORDER BY current_name"
    )

    bowling_types_db  = query(
        "SELECT DISTINCT bowling_type FROM player WHERE bowling_type IS NOT NULL ORDER BY bowling_type"
    )
    all_bowling_types = [r["bowling_type"] for r in bowling_types_db]

    # ── defaults: last 3 seasons, all phases / roles, min 60 balls ───────────
    last_season  = all_seasons[-1] if all_seasons else _CONTRACT_SEASON
    default_from = last_season - 2
    default_to   = last_season

    # ── parse & validate every URL parameter ──────────────────────────────────
    a = request.args

    season_from = _int_or_none(a.get("season_from")) or default_from
    season_to   = _int_or_none(a.get("season_to"))   or default_to
    if season_from not in all_seasons:
        season_from = default_from
    if season_to not in all_seasons:
        season_to = default_to
    if season_from > season_to:
        season_from, season_to = season_to, season_from

    # Checkboxes: an empty list means "none submitted" → default to all
    checked_phases = a.getlist("phase")
    valid_phases   = set(all_phases)
    phases         = [p for p in checked_phases if p in valid_phases] or all_phases

    checked_roles    = a.getlist("role")
    valid_role_codes = {r[0] for r in all_roles}
    roles = [r for r in checked_roles if r in valid_role_codes] or [r[0] for r in all_roles]

    team_id = _int_or_none(a.get("team_id"))
    if team_id not in {r["franchise_id"] for r in franchises}:
        team_id = None

    nationality = a.get("nationality", "").strip() or None
    if nationality not in (None, "Indian", "Overseas"):
        nationality = None

    # bowling_type is NOT sanitised to None on unknown values: an unknown string
    # returns 0 rows via psycopg parameterisation (the security demo in section 11).
    bowling_type = a.get("bowling_type", "").strip() or None

    age_min   = _int_or_none(a.get("age_min"))
    age_max   = _int_or_none(a.get("age_max"))
    price_min = _decimal_or_none(a.get("price_min"))
    price_max = _decimal_or_none(a.get("price_max"))

    min_balls = _int_or_none(a.get("min_balls")) or 60
    if min_balls < 0:
        min_balls = 60

    hide_on_board = a.get("hide_on_board") == "1"

    sort_key = a.get("sort", "mvp")
    # SORT_COLUMNS.get falls back to "mvp" for any key not in the whitelist
    order = SORT_COLUMNS.get(sort_key, SORT_COLUMNS["mvp"])
    if sort_key not in SORT_COLUMNS:
        sort_key = "mvp"

    # ── assemble SQL: f-string is safe because `order` comes from the dict ────
    sql = REPORT_SQL + f" ORDER BY {order}, player LIMIT 200"

    board_id = _board_id()
    params = {
        "season_from":     season_from,
        "season_to":       season_to,
        "phases":          phases,
        "roles":           roles,
        "team_id":         team_id,
        "nationality":     nationality,
        "bowling_type":    bowling_type,
        "age_min":         age_min,
        "age_max":         age_max,
        "price_min":       price_min,
        "price_max":       price_max,
        "min_balls":       min_balls,
        "board_id":        board_id,
        "hide_on_board":   hide_on_board,
        "contract_season": _CONTRACT_SEASON,
    }

    # ── run report + board summary in one REPEATABLE READ snapshot ─────────────
    # Both queries read the same DB state: the report table and board panel
    # always refer to the same instant — no inconsistency between them.
    with transaction("REPEATABLE READ", read_only=True) as conn:
        rows    = conn.execute(sql, params).fetchall()
        summary = conn.execute(
            "SELECT * FROM v_draft_board_summary WHERE board_id = %s", (board_id,)
        ).fetchone()

    rows = [dict(r) for r in rows]

    # ── compute summary aggregates from the result set ─────────────────────────
    # Numeric columns from psycopg arrive as Decimal; convert to int/float for
    # Python arithmetic (Decimal * float raises TypeError).
    n_players   = len(rows)
    total_runs  = sum(int(r["runs"]  or 0) for r in rows)
    total_balls = sum(int(r["balls"] or 0) for r in rows)
    overall_sr  = round(100.0 * total_runs / total_balls, 1) if total_balls else None

    # Overall economy = 6 * sum(runs_conceded) / sum(balls_bowled).
    # Both are encoded per row as: runs_conceded = economy * overs,
    # balls_bowled = overs * 6.  Weighted average by overs gives the same result.
    bowl_rows   = [r for r in rows if r["economy"] is not None and r["overs"]]
    total_overs = sum(float(r["overs"]) for r in bowl_rows)
    overall_econ = (
        round(
            sum(float(r["economy"]) * float(r["overs"]) for r in bowl_rows) / total_overs,
            2,
        )
        if total_overs else None
    )

    salaries   = [float(r["price_cr"]) for r in rows if r["price_cr"] is not None]
    avg_salary = round(sum(salaries) / len(salaries), 2) if salaries else None

    best_value = max(
        (r for r in rows if r["mvp_per_crore"] is not None),
        key=lambda r: r["mvp_per_crore"],
        default=None,
    )

    cards = {
        "n_players":    n_players,
        "avg_salary":   avg_salary,
        "total_runs":   total_runs,
        "overall_sr":   overall_sr,
        "overall_econ": overall_econ,
        "best_value":   best_value,
    }

    # Active filter values — used to repopulate the form on the next render
    filters = {
        "season_from":   season_from,
        "season_to":     season_to,
        "phases":        phases,
        "roles":         roles,
        "team_id":       team_id,
        "nationality":   nationality or "",
        "bowling_type":  bowling_type or "",
        "age_min":       age_min,
        "age_max":       age_max,
        "price_min":     price_min,
        "price_max":     price_max,
        "min_balls":     min_balls,
        "hide_on_board": hide_on_board,
        "sort":          sort_key,
    }

    return render_template(
        "report/scouting.html",
        rows=rows,
        cards=cards,
        summary=summary,
        filters=filters,
        all_seasons=all_seasons,
        all_phases=all_phases,
        all_roles=all_roles,
        franchises=franchises,
        all_bowling_types=all_bowling_types,
        sort_labels=SORT_LABELS,
    )
