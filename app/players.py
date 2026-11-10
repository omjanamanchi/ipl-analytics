"""Players blueprint — player profile pages and search.

Routes:
  GET /players                    → search_page()  player search/listing
  GET /players/<int:player_id>    → profile()      full profile page
"""
from __future__ import annotations

from flask import Blueprint, abort, render_template, request, session

from .db import query, query_one

bp = Blueprint("players", __name__, url_prefix="/players")

# ── constants ─────────────────────────────────────────────────────────────────

_PHASE_ORDER = {"Powerplay": 0, "Middle": 1, "Death": 2}

AVATAR_COLORS = [
    "#1B3A8C", "#C62828", "#2E7D32", "#6A1B9A",
    "#E65100", "#0277BD", "#558B2F",
]


# ── helpers ───────────────────────────────────────────────────────────────────

def _initials(name: str) -> str:
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return name[:2].upper()


def _board_id() -> int | None:
    """Return the active board id from session, or fall back to first board."""
    board_id = session.get("active_board_id")
    if board_id:
        row = query_one("SELECT board_id FROM draft_board WHERE board_id = %s", (board_id,))
        if row:
            return row["board_id"]
    row = query_one("SELECT board_id FROM draft_board ORDER BY board_id LIMIT 1")
    return row["board_id"] if row else None


# ── routes ────────────────────────────────────────────────────────────────────

@bp.get("")
def search_page():
    """Simple player search page — text input, results as clickable cards."""
    q = request.args.get("q", "").strip()
    rows = []
    if len(q) >= 2:
        # Escape ILIKE wildcards in user input before wrapping
        safe_q = q.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        pattern = "%" + safe_q + "%"
        rows = query(
            """
            SELECT p.player_id, p.display_name, p.country, p.role_code,
                   r.description AS role_description, p.is_overseas,
                   f.short_code AS last_team
            FROM player p
            LEFT JOIN role r ON r.role_code = p.role_code
            LEFT JOIN contract c ON c.player_id = p.player_id AND c.season_year = 2026
            LEFT JOIN franchise f ON f.franchise_id = c.franchise_id
            WHERE p.display_name ILIKE %(pattern)s OR p.cricsheet_name ILIKE %(pattern)s
            ORDER BY p.display_name
            LIMIT 60
            """,
            {"pattern": pattern},
        )
    return render_template("players/search.html", rows=rows, q=q)


@bp.get("/<int:player_id>")
def profile(player_id: int):
    """Full player profile page."""
    # 1. Player bio
    player = query_one(
        """
        SELECT p.*,
               r.description AS role_description,
               EXTRACT(YEAR FROM age(p.dob))::int AS age_years
        FROM player p
        LEFT JOIN role r ON r.role_code = p.role_code
        WHERE p.player_id = %(player_id)s
        """,
        {"player_id": player_id},
    )
    if player is None:
        abort(404)

    # 2. Career totals
    career = query_one(
        """
        SELECT SUM(matches)       AS matches,
               SUM(fifties)       AS fifties,
               SUM(hundreds)      AS hundreds,
               MAX(highest_score) AS highest_score,
               SUM(catches)       AS catches,
               SUM(stumpings)     AS stumpings,
               ROUND(SUM(mvp_points), 1) AS mvp_points
        FROM mv_player_season_stats
        WHERE player_id = %(player_id)s
        """,
        {"player_id": player_id},
    )

    # 3. Phase career splits
    phase_rows = query(
        """
        SELECT phase,
               SUM(runs)              AS runs,
               SUM(balls_faced)       AS balls,
               ROUND(100.0 * SUM(runs) / NULLIF(SUM(balls_faced), 0), 1) AS strike_rate,
               SUM(legal_balls_bowled) AS balls_bowled,
               SUM(wickets)           AS wickets,
               ROUND(6.0 * SUM(runs_conceded) / NULLIF(SUM(legal_balls_bowled), 0), 2) AS economy
        FROM mv_player_phase_stats
        WHERE player_id = %(player_id)s
        GROUP BY phase
        """,
        {"player_id": player_id},
    )
    # Sort Powerplay(0) → Middle(1) → Death(2)
    phases = sorted(phase_rows, key=lambda r: _PHASE_ORDER.get(r["phase"], 99))

    # 4. Season-by-season
    seasons = query(
        """
        SELECT mps.season_year,
               mps.matches,
               mps.fifties,
               mps.hundreds,
               mps.highest_score,
               mps.catches,
               mps.stumpings,
               ROUND(SUM(ph.runs), 0)::int AS runs,
               SUM(ph.balls_faced) AS balls,
               ROUND(100.0 * SUM(ph.runs) / NULLIF(SUM(ph.balls_faced), 0), 1) AS sr,
               SUM(ph.wickets) AS wickets,
               ROUND(6.0 * SUM(ph.runs_conceded) / NULLIF(SUM(ph.legal_balls_bowled), 0), 2) AS economy,
               f.short_code AS team,
               c.price_cr
        FROM mv_player_season_stats mps
        JOIN mv_player_phase_stats ph
             ON ph.player_id = mps.player_id AND ph.season_year = mps.season_year
        LEFT JOIN contract c
             ON c.player_id = mps.player_id AND c.season_year = mps.season_year
        LEFT JOIN franchise f ON f.franchise_id = c.franchise_id
        WHERE mps.player_id = %(player_id)s
        GROUP BY mps.season_year, mps.matches, mps.fifties, mps.hundreds,
                 mps.highest_score, mps.catches, mps.stumpings, f.short_code, c.price_cr
        ORDER BY mps.season_year DESC
        LIMIT 10
        """,
        {"player_id": player_id},
    )

    # 5. 2026 contract
    contract = query_one(
        """
        SELECT c.price_cr, f.current_name AS team_name, f.short_code
        FROM contract c
        JOIN franchise f ON f.franchise_id = c.franchise_id
        WHERE c.player_id = %(player_id)s AND c.season_year = 2026
        """,
        {"player_id": player_id},
    )

    # 6. Board status for this player on the active board
    board_id = _board_id()
    board_status = None
    if board_id:
        board_status = query_one(
            """
            SELECT dp.status, dp.priority, dp.max_bid_cr, dp.pick_id
            FROM draft_pick dp
            WHERE dp.player_id = %(player_id)s AND dp.board_id = %(board_id)s
            """,
            {"player_id": player_id, "board_id": board_id},
        )

    # Avatar
    initials = _initials(player["display_name"])
    avatar_color = AVATAR_COLORS[player_id % len(AVATAR_COLORS)]

    return render_template(
        "players/profile.html",
        player=player,
        career=career,
        phases=phases,
        seasons=seasons,
        contract=contract,
        board_status=board_status,
        board_id=board_id,
        initials=initials,
        avatar_color=avatar_color,
    )
