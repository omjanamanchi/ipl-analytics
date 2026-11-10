"""Core pages: home (database status) and a health check for App Engine."""
from flask import Blueprint, jsonify, render_template

from .db import query, query_one

bp = Blueprint("core", __name__)


@bp.get("/")
def home():
    counts = query_one(
        """SELECT (SELECT COUNT(*) FROM match)      AS matches,
                  (SELECT COUNT(*) FROM delivery)   AS deliveries,
                  (SELECT COUNT(*) FROM player)     AS players,
                  (SELECT MIN(season_year) FROM match) AS first_season,
                  (SELECT MAX(season_year) FROM match) AS last_season"""
    )
    champions = query(
        """SELECT s.season_year, c.current_name AS champion, r.current_name AS runner_up
           FROM season s
           JOIN franchise c ON c.franchise_id = s.champion_id
           JOIN franchise r ON r.franchise_id = s.runner_up_id
           ORDER BY s.season_year DESC LIMIT 5"""
    )
    leaders = query(
        """SELECT a.award_name, p.display_name, p.player_id, sa.stat_value
           FROM season_award sa JOIN award a USING (award_id) JOIN player p USING (player_id)
           WHERE sa.season_year = (SELECT MAX(season_year) FROM match)
           ORDER BY a.award_id"""
    )
    return render_template("home.html", counts=counts, champions=champions, leaders=leaders)


@bp.get("/healthz")
def healthz():
    row = query_one("SELECT 1 AS ok")
    return jsonify(status="ok" if row and row["ok"] == 1 else "error")
