"""Draft Board blueprint — Requirement 1 (main table: draft_pick).

Routes (all under /draft):
  GET  /draft                       board()         board page (endpoint "board")
  GET  /draft/players/search?q=     player_search() JSON autocomplete
  POST /draft/picks                 add_pick()      add a target pick
  GET  /draft/picks/<id>/edit       edit_pick()     edit form
  POST /draft/picks/<id>            update_pick()   ordinary edit or Buy/Lost
  POST /draft/picks/<id>/delete     delete_pick()   remove a pick
  POST /draft/scout                 set_scout()     set session["scout_id"]
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from flask import (Blueprint, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from psycopg.errors import UniqueViolation

from .db import query, query_one, transaction

bp = Blueprint("draft", __name__, url_prefix="/draft")


# ── helpers ───────────────────────────────────────────────────────────────────

def _board_id() -> int:
    """Return the first (seeded) board's id."""
    row = query_one("SELECT board_id FROM draft_board ORDER BY board_id LIMIT 1")
    if row is None:
        raise RuntimeError("No draft board found — run make load")
    return row["board_id"]


def _escape_like(text: str) -> str:
    """Escape \\ % _ in user text before wrapping in ILIKE wildcards.

    PostgreSQL's LIKE/ILIKE uses \\ as the default escape character, so
    \\% becomes a literal percent and \\_ a literal underscore.
    We escape \\ first to avoid double-escaping.
    """
    return text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def _parse_decimal(value: str, name: str) -> Decimal:
    """Parse a Decimal from a form string; raise ValueError with a friendly message."""
    try:
        d = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValueError(f"{name} must be a number")
    if d <= 0:
        raise ValueError(f"{name} must be greater than 0")
    return d


def _parse_priority(value: str) -> int:
    try:
        p = int(str(value).strip())
    except (ValueError, TypeError):
        raise ValueError("Priority must be an integer")
    if not 1 <= p <= 5:
        raise ValueError("Priority must be between 1 and 5")
    return p


# ── scout selector ────────────────────────────────────────────────────────────

@bp.route("/scout", methods=["POST"])
def set_scout():
    """Save the chosen scout in the session so edits are attributed to them."""
    try:
        scout_id = int(request.form["scout_id"])
    except (ValueError, KeyError):
        flash("Invalid scout selection", "error")
        return redirect(url_for("draft.board"))

    # Verify the scout exists in the database (section 10: dropdown from scout table)
    row = query_one("SELECT scout_id FROM scout WHERE scout_id = %s", (scout_id,))
    if row is None:
        flash("Scout not found", "error")
    else:
        session["scout_id"] = scout_id
        flash("Scout updated", "success")
    return redirect(url_for("draft.board"))


# ── board page ────────────────────────────────────────────────────────────────

@bp.route("")
def board():
    board_id = _board_id()

    # Board header — purse remaining, squad/overseas counts, role balance.
    # The view v_draft_board_summary aggregates these live from draft_pick.
    summary = query_one(
        "SELECT * FROM v_draft_board_summary WHERE board_id = %(board_id)s",
        {"board_id": board_id},
    )

    # Pick list — joins player for name/overseas, role for description,
    # the 2026 contract for last-known salary and team, and scout for the editor name.
    picks = query(
        """
        SELECT dp.pick_id, dp.priority, dp.max_bid_cr, dp.status, dp.price_paid_cr,
               dp.notes, dp.version, dp.role_slot,
               p.display_name, p.is_overseas, p.country,
               r.description  AS role_name,
               c.price_cr     AS last_salary,
               f.short_code   AS last_team,
               s.display_name AS updated_by_name
        FROM draft_pick dp
        JOIN player    p  USING (player_id)
        JOIN role      r  ON r.role_code = dp.role_slot
        LEFT JOIN contract  c  ON c.player_id = dp.player_id AND c.season_year = 2026
        LEFT JOIN franchise f  ON f.franchise_id = c.franchise_id
        LEFT JOIN scout     s  ON s.scout_id = dp.updated_by
        WHERE dp.board_id = %(board_id)s
        ORDER BY dp.status, dp.priority, p.display_name
        """,
        {"board_id": board_id},
    )

    # Dropdowns loaded from the database — plan.md section 10
    scouts = query("SELECT scout_id, display_name FROM scout ORDER BY display_name")
    roles  = query("SELECT role_code, description FROM role ORDER BY sort_order")

    return render_template(
        "draft/board.html",
        summary=summary,
        picks=picks,
        scouts=scouts,
        roles=roles,
        board_id=board_id,
        scout_id=session.get("scout_id"),
    )


# ── player search (JSON for the autocomplete widget) ─────────────────────────

@bp.route("/players/search")
def player_search():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])

    # Escape % and _ before wrapping in wildcards (plan.md section 11)
    pattern = "%" + _escape_like(q) + "%"

    rows = query(
        """
        SELECT player_id, display_name, role_code, country
        FROM player
        WHERE display_name ILIKE %(pattern)s OR cricsheet_name ILIKE %(pattern)s
        ORDER BY display_name
        LIMIT 15
        """,
        {"pattern": pattern},
    )
    return jsonify([dict(r) for r in rows])


# ── add pick ──────────────────────────────────────────────────────────────────

@bp.route("/picks", methods=["POST"])
def add_pick():
    board_id = _board_id()
    scout_id = session.get("scout_id")

    try:
        player_id = int(request.form["player_id"])
        role_slot = request.form["role_slot"].strip()
        priority  = _parse_priority(request.form.get("priority", "3"))
        max_bid   = _parse_decimal(request.form.get("max_bid_cr", ""), "Max bid")
        notes     = request.form.get("notes", "").strip() or None
    except (ValueError, KeyError) as exc:
        flash(str(exc) or "Invalid input", "error")
        return redirect(url_for("draft.board"))

    # Validate role_slot against the database (not a hard-coded list)
    valid_roles = {r["role_code"] for r in query("SELECT role_code FROM role")}
    if role_slot not in valid_roles:
        flash("Invalid role", "error")
        return redirect(url_for("draft.board"))

    try:
        with transaction("READ COMMITTED") as conn:
            conn.execute(
                """
                INSERT INTO draft_pick
                    (board_id, player_id, role_slot, priority, max_bid_cr, notes, updated_by)
                VALUES (%(board_id)s, %(player_id)s, %(role_slot)s,
                        %(priority)s, %(max_bid_cr)s, %(notes)s, %(scout_id)s)
                """,
                {
                    "board_id": board_id,
                    "player_id": player_id,
                    "role_slot": role_slot,
                    "priority": priority,
                    "max_bid_cr": max_bid,
                    "notes": notes,
                    "scout_id": scout_id,
                },
            )
    except UniqueViolation:
        # The UNIQUE(board_id, player_id) constraint caught a duplicate
        flash("That player is already on the board", "error")
        return redirect(url_for("draft.board"))

    flash("Player added to the board", "success")
    return redirect(url_for("draft.board"))


# ── edit form ─────────────────────────────────────────────────────────────────

@bp.route("/picks/<int:pick_id>/edit")
def edit_pick(pick_id: int):
    board_id = _board_id()

    pick = query_one(
        """
        SELECT dp.*, p.display_name, p.is_overseas, p.country,
               r.description AS role_name
        FROM draft_pick dp
        JOIN player p USING (player_id)
        JOIN role   r ON r.role_code = dp.role_slot
        WHERE dp.pick_id = %(pick_id)s AND dp.board_id = %(board_id)s
        """,
        {"pick_id": pick_id, "board_id": board_id},
    )
    if pick is None:
        flash("Pick not found", "error")
        return redirect(url_for("draft.board"))

    roles = query("SELECT role_code, description FROM role ORDER BY sort_order")
    return render_template("draft/edit.html", pick=pick, roles=roles, board_id=board_id)


# ── update pick (ordinary edit or Bought / Lost) ──────────────────────────────

@bp.route("/picks/<int:pick_id>", methods=["POST"])
def update_pick(pick_id: int):
    board_id = _board_id()
    scout_id = session.get("scout_id")

    try:
        role_slot = request.form["role_slot"].strip()
        priority  = _parse_priority(request.form.get("priority", "3"))
        max_bid   = _parse_decimal(request.form.get("max_bid_cr", ""), "Max bid")
        notes     = request.form.get("notes", "").strip() or None
        status    = request.form.get("status", "Target").strip()
        version   = int(request.form["version"])
    except (ValueError, KeyError) as exc:
        flash(str(exc) or "Invalid input", "error")
        return redirect(url_for("draft.edit_pick", pick_id=pick_id))

    if status not in ("Target", "Bought", "Lost"):
        flash("Invalid status", "error")
        return redirect(url_for("draft.edit_pick", pick_id=pick_id))

    if status == "Bought":
        # Route through the buy transaction (plan.md section 8.4)
        try:
            price_paid = _parse_decimal(request.form.get("price_paid_cr", ""), "Price paid")
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("draft.edit_pick", pick_id=pick_id))

        try:
            _buy_player(board_id, pick_id, price_paid, version, scout_id)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("draft.edit_pick", pick_id=pick_id))

        flash("Player marked as Bought", "success")
        return redirect(url_for("draft.board"))

    # Ordinary edit — version check only, no board lock needed.
    # Setting price_paid_cr = NULL satisfies the CHECK: (status='Bought') = (price_paid_cr IS NOT NULL)
    try:
        with transaction("READ COMMITTED") as conn:
            cur = conn.execute(
                """
                UPDATE draft_pick
                   SET role_slot     = %(role_slot)s,
                       priority      = %(priority)s,
                       max_bid_cr    = %(max_bid_cr)s,
                       status        = %(status)s,
                       price_paid_cr = NULL,
                       notes         = %(notes)s,
                       updated_by    = %(scout_id)s,
                       updated_at    = now(),
                       version       = version + 1
                 WHERE pick_id  = %(pick_id)s
                   AND board_id = %(board_id)s
                   AND version  = %(version)s
                """,
                {
                    "role_slot": role_slot,
                    "priority": priority,
                    "max_bid_cr": max_bid,
                    "status": status,
                    "notes": notes,
                    "scout_id": scout_id,
                    "pick_id": pick_id,
                    "board_id": board_id,
                    "version": version,
                },
            )
            if cur.rowcount == 0:
                raise ValueError("Someone else changed this pick — reload and try again")
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("draft.edit_pick", pick_id=pick_id))

    flash("Pick updated", "success")
    return redirect(url_for("draft.board"))


# ── delete pick ───────────────────────────────────────────────────────────────

@bp.route("/picks/<int:pick_id>/delete", methods=["POST"])
def delete_pick(pick_id: int):
    board_id = _board_id()
    with transaction("READ COMMITTED") as conn:
        # board_id guard prevents deleting a pick that belongs to a different board
        conn.execute(
            "DELETE FROM draft_pick WHERE pick_id = %(pick_id)s AND board_id = %(board_id)s",
            {"pick_id": pick_id, "board_id": board_id},
        )
    flash("Pick removed", "success")
    return redirect(url_for("draft.board"))


# ── buy transaction (plan.md section 8.4) ────────────────────────────────────

def _buy_player(
    board_id: int,
    pick_id: int,
    price_cr: Decimal,
    expected_version: int,
    scout_id: int | None,
) -> None:
    """Mark a pick as Bought inside a READ COMMITTED transaction.

    Uses SELECT … FOR UPDATE on draft_board to prevent write skew:
    if two scouts buy simultaneously on the same board, the second one
    blocks at step 1, then re-reads the summary at step 2 and sees the
    first scout's committed spend — so the purse/overseas checks are fresh.

    Raises ValueError with a user-friendly message on any rule violation.
    The caller flashes that message; it never reaches the user as a stack trace.
    """
    with transaction("READ COMMITTED") as conn:
        # 1. Lock the board row.  Any concurrent buy on the same board waits here
        #    until our transaction commits or rolls back.
        board = conn.execute(
            "SELECT * FROM draft_board WHERE board_id = %s FOR UPDATE",
            (board_id,),
        ).fetchone()

        # 2. Read the live summary AFTER acquiring the lock, so we see any buy
        #    that committed just before us.
        s = conn.execute(
            "SELECT * FROM v_draft_board_summary WHERE board_id = %s",
            (board_id,),
        ).fetchone()

        # 3. Read the pick and its player's overseas flag in the same snapshot.
        pick = conn.execute(
            """SELECT dp.*, p.is_overseas
               FROM draft_pick dp
               JOIN player p USING (player_id)
               WHERE dp.pick_id = %s AND dp.board_id = %s""",
            (pick_id, board_id),
        ).fetchone()

        # 4. Business-rule checks (all read AFTER the lock, so values are fresh).
        if pick is None:
            raise ValueError("Pick not found")
        if pick["status"] == "Bought":
            raise ValueError("This player was already marked Bought")
        if price_cr > s["remaining_cr"]:
            raise ValueError(
                f"Not enough purse left "
                f"(₹{s['remaining_cr']} cr remaining, bid is ₹{price_cr} cr)"
            )
        if s["squad_count"] >= board["max_squad"]:
            raise ValueError(f"Squad is full ({board['max_squad']} players)")
        if pick["is_overseas"] and s["overseas_count"] >= board["max_overseas"]:
            raise ValueError(f"No overseas slots left ({board['max_overseas']} max)")
        if (
            pick["is_overseas"]
            and board["overseas_cap_cr"] is not None
            and price_cr > board["overseas_cap_cr"]
        ):
            raise ValueError(f"Overseas fee cap is ₹{board['overseas_cap_cr']} cr")

        # 5. Optimistic version check: if the row changed since the user opened
        #    the form, rowcount is 0 and we surface a friendly conflict message.
        cur = conn.execute(
            """UPDATE draft_pick
                  SET status        = 'Bought',
                      price_paid_cr = %s,
                      updated_by    = %s,
                      updated_at    = now(),
                      version       = version + 1
                WHERE pick_id = %s AND version = %s""",
            (price_cr, scout_id, pick_id, expected_version),
        )
        if cur.rowcount == 0:
            raise ValueError("Someone else changed this pick — reload and try again")
    # Exiting the `with` block commits; any exception above rolls everything back.
