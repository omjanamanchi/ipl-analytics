"""Draft Board blueprint — Requirement 1 (main table: draft_pick).

Routes (all under /draft):
  GET  /draft                       board()         board page (endpoint "board")
  GET  /draft/players/search?q=     player_search() JSON autocomplete
  POST /draft/picks                 add_pick()      add a target pick
  GET  /draft/picks/<id>/edit       edit_pick()     edit form
  POST /draft/picks/<id>            update_pick()   ordinary edit or Buy/Lost
  POST /draft/picks/<id>/delete     delete_pick()   remove a pick
  GET  /draft/boards                my_boards()     boards the user owns or is a member of
  POST /draft/boards/<id>/share     share_board()   invite a user by username
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from flask import (Blueprint, current_app, flash, jsonify, redirect,
                   render_template, request, session, url_for)
from psycopg.errors import UniqueViolation

from .auth import login_required
from .db import query, query_one, transaction

bp = Blueprint("draft", __name__, url_prefix="/draft")


# -- helpers -------------------------------------------------------------------

def _board_id() -> int:
    """Return the active board id.

    In TESTING mode, falls back to first board (no auth needed).
    In production, returns a board the current user is a member of.
    """
    board_id = session.get("active_board_id")
    user_id  = session.get("user_id")

    if current_app.config.get("TESTING"):
        # Testing: no user in session, just use first board
        if board_id:
            row = query_one("SELECT board_id FROM draft_board WHERE board_id = %s", (board_id,))
            if row:
                return row["board_id"]
        row = query_one("SELECT board_id FROM draft_board ORDER BY board_id LIMIT 1")
        if row is None:
            raise RuntimeError("No draft board found — run make load")
        return row["board_id"]

    if board_id and user_id:
        # Verify user is a member of the requested board
        row = query_one(
            """SELECT db.board_id FROM draft_board db
               JOIN board_member bm ON bm.board_id = db.board_id
               WHERE db.board_id = %s AND bm.user_id = %s""",
            (board_id, user_id),
        )
        if row:
            return row["board_id"]

    if user_id:
        # Fall back to first board the user is a member of
        row = query_one(
            """SELECT db.board_id FROM draft_board db
               JOIN board_member bm ON bm.board_id = db.board_id
               WHERE bm.user_id = %s
               ORDER BY db.board_id LIMIT 1""",
            (user_id,),
        )
        if row:
            return row["board_id"]

    # Guest or no user: show demo board
    row = query_one("SELECT board_id FROM draft_board ORDER BY board_id LIMIT 1")
    if row is None:
        raise RuntimeError("No draft board found — run make load")
    return row["board_id"]


def _require_editor(board_id: int) -> bool:
    """Returns True if the current user is an owner or editor of the board.
    Always True in TESTING mode.
    """
    if current_app.config.get("TESTING"):
        return True
    user_id = session.get("user_id")
    if not user_id:
        return False
    row = query_one(
        """SELECT role FROM board_member
           WHERE board_id = %s AND user_id = %s AND role = ANY(%s)""",
        (board_id, user_id, ['owner', 'editor']),
    )
    return row is not None


def _int_or_none(value: str | None) -> int | None:
    s = (value or "").strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


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


# -- board page ----------------------------------------------------------------

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
    # the 2026 contract for last-known salary and team, and app_user for the editor name.
    picks = query(
        """
        SELECT dp.pick_id, dp.player_id, dp.priority, dp.max_bid_cr, dp.status, dp.price_paid_cr,
               dp.notes, dp.version, dp.role_slot,
               p.display_name, p.is_overseas, p.country,
               r.description  AS role_name,
               c.price_cr     AS last_salary,
               f.short_code   AS last_team,
               au.display_name AS updated_by_name
        FROM draft_pick dp
        JOIN player    p  USING (player_id)
        JOIN role      r  ON r.role_code = dp.role_slot
        LEFT JOIN contract  c  ON c.player_id = dp.player_id AND c.season_year = 2026
        LEFT JOIN franchise f  ON f.franchise_id = c.franchise_id
        LEFT JOIN app_user  au ON au.user_id = dp.updated_by
        WHERE dp.board_id = %(board_id)s
        ORDER BY dp.status, dp.priority, p.display_name
        """,
        {"board_id": board_id},
    )

    # Dropdowns loaded from the database — plan.md section 10
    roles  = query("SELECT role_code, description FROM role ORDER BY sort_order")

    # All boards for the switcher dropdown
    boards = query("SELECT board_id, name FROM draft_board ORDER BY board_id")

    # Is current user the owner of this board?
    is_owner = False
    user_id = session.get("user_id")
    if user_id:
        om = query_one(
            "SELECT role FROM board_member WHERE board_id = %s AND user_id = %s AND role = 'owner'",
            (board_id, user_id),
        )
        is_owner = om is not None

    return render_template(
        "draft/board.html",
        summary=summary,
        picks=picks,
        roles=roles,
        boards=boards,
        board_id=board_id,
        user_id=user_id,
        is_owner=is_owner,
    )


# -- player search (JSON for the autocomplete widget) -------------------------

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


# -- add pick ------------------------------------------------------------------

@bp.route("/picks", methods=["POST"])
@login_required
def add_pick():
    board_id = _board_id()
    if not _require_editor(board_id):
        flash("You need editor or owner access to modify this board", "error")
        return redirect(url_for("draft.board"))

    user_id = session.get("user_id")

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
                        %(priority)s, %(max_bid_cr)s, %(notes)s, %(user_id)s)
                """,
                {
                    "board_id": board_id,
                    "player_id": player_id,
                    "role_slot": role_slot,
                    "priority": priority,
                    "max_bid_cr": max_bid,
                    "notes": notes,
                    "user_id": user_id,
                },
            )
    except UniqueViolation:
        # The UNIQUE(board_id, player_id) constraint caught a duplicate
        flash("That player is already on the board", "error")
        return redirect(url_for("draft.board"))

    flash("Player added to the board", "success")
    return redirect(url_for("draft.board"))


# -- edit form -----------------------------------------------------------------

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


# -- update pick (ordinary edit or Bought / Lost) -----------------------------

@bp.route("/picks/<int:pick_id>", methods=["POST"])
@login_required
def update_pick(pick_id: int):
    board_id = _board_id()
    if not _require_editor(board_id):
        flash("You need editor or owner access to modify this board", "error")
        return redirect(url_for("draft.board"))

    user_id = session.get("user_id")

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
            _buy_player(board_id, pick_id, price_paid, version, user_id)
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
                       updated_by    = %(user_id)s,
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
                    "user_id": user_id,
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


# -- delete pick ---------------------------------------------------------------

@bp.route("/picks/<int:pick_id>/delete", methods=["POST"])
@login_required
def delete_pick(pick_id: int):
    board_id = _board_id()
    if not _require_editor(board_id):
        flash("You need editor or owner access to modify this board", "error")
        return redirect(url_for("draft.board"))

    with transaction("READ COMMITTED") as conn:
        # board_id guard prevents deleting a pick that belongs to a different board
        conn.execute(
            "DELETE FROM draft_pick WHERE pick_id = %(pick_id)s AND board_id = %(board_id)s",
            {"pick_id": pick_id, "board_id": board_id},
        )
    flash("Pick removed", "success")
    return redirect(url_for("draft.board"))


# -- buy transaction (plan.md section 8.4) ------------------------------------

def _buy_player(
    board_id: int,
    pick_id: int,
    price_cr: Decimal,
    expected_version: int,
    user_id: int | None,
) -> None:
    """Mark a pick as Bought inside a READ COMMITTED transaction.

    Uses SELECT ... FOR UPDATE on draft_board to prevent write skew:
    if two users buy simultaneously on the same board, the second one
    blocks at step 1, then re-reads the summary at step 2 and sees the
    first user's committed spend — so the purse/overseas checks are fresh.

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
            (price_cr, user_id, pick_id, expected_version),
        )
        if cur.rowcount == 0:
            raise ValueError("Someone else changed this pick — reload and try again")
    # Exiting the `with` block commits; any exception above rolls everything back.


# -- create board --------------------------------------------------------------

@bp.route("/create", methods=["GET"])
def create_board():
    """Show the create-board form."""
    franchises = query(
        "SELECT franchise_id, current_name FROM franchise WHERE is_active ORDER BY current_name"
    )
    seasons = query(
        "SELECT season_year FROM season WHERE season_year >= 2027 ORDER BY season_year"
    )
    return render_template("draft/create_board.html", franchises=franchises, seasons=seasons)


@bp.route("/create", methods=["POST"])
@login_required
def create_board_post():
    """Create a new draft board from the posted form."""
    name = request.form.get("name", "").strip()
    franchise_id = _int_or_none(request.form.get("franchise_id"))
    target_season = _int_or_none(request.form.get("target_season"))

    if not name:
        flash("Board name is required", "error")
        return redirect(url_for("draft.create_board"))
    if franchise_id is None or target_season is None:
        flash("Franchise and season are required", "error")
        return redirect(url_for("draft.create_board"))

    # Validate franchise and season exist in the DB
    fr = query_one("SELECT franchise_id FROM franchise WHERE franchise_id = %s AND is_active", (franchise_id,))
    if fr is None:
        flash("Invalid franchise", "error")
        return redirect(url_for("draft.create_board"))
    s = query_one("SELECT season_year FROM season WHERE season_year = %s", (target_season,))
    if s is None:
        flash("Invalid season", "error")
        return redirect(url_for("draft.create_board"))

    owner_id = session.get("user_id")
    try:
        with transaction("READ COMMITTED") as conn:
            row = conn.execute(
                """
                INSERT INTO draft_board
                    (name, franchise_id, target_season, purse_cr,
                     max_squad, max_overseas, overseas_cap_cr, owner_id)
                SELECT %(name)s, %(franchise_id)s, s.season_year,
                       COALESCE(s.purse_cr, 120),
                       COALESCE(s.max_squad, 25),
                       COALESCE(s.max_overseas, 8),
                       s.overseas_cap_cr,
                       %(owner_id)s
                FROM season s
                WHERE s.season_year = %(target_season)s
                RETURNING board_id
                """,
                {"name": name, "franchise_id": franchise_id,
                 "target_season": target_season, "owner_id": owner_id},
            ).fetchone()
            new_board_id = row["board_id"]
            if owner_id:
                conn.execute(
                    """INSERT INTO board_member (board_id, user_id, role)
                       VALUES (%s, %s, 'owner')
                       ON CONFLICT DO NOTHING""",
                    (new_board_id, owner_id),
                )
    except Exception:
        flash("Could not create board (name may already exist for this franchise/season)", "error")
        return redirect(url_for("draft.create_board"))

    session["active_board_id"] = new_board_id
    flash(f"Board '{name}' created", "success")
    return redirect(url_for("draft.board"))


# -- board switcher ------------------------------------------------------------

@bp.route("/switch", methods=["POST"])
@login_required
def switch_board():
    """Set the active board in the session."""
    board_id = _int_or_none(request.form.get("board_id"))
    if board_id is None:
        flash("No board selected", "error")
        return redirect(url_for("draft.board"))

    row = query_one("SELECT board_id FROM draft_board WHERE board_id = %s", (board_id,))
    if row is None:
        flash("Board not found", "error")
    else:
        session["active_board_id"] = board_id
        flash("Switched board", "success")
    return redirect(url_for("draft.board"))


# -- my boards -----------------------------------------------------------------

@bp.route("/boards")
@login_required
def my_boards():
    user_id = session.get("user_id")
    boards = query(
        """SELECT db.board_id, db.name, db.target_season, bm.role,
                  f.current_name AS franchise_name,
                  f.short_code   AS franchise_code,
                  db.created_at
           FROM draft_board db
           JOIN board_member bm ON bm.board_id = db.board_id
           JOIN franchise    f  ON f.franchise_id = db.franchise_id
           WHERE bm.user_id = %s
           ORDER BY db.created_at DESC""",
        (user_id,),
    )
    return render_template("draft/my_boards.html", boards=boards)


# -- share board ---------------------------------------------------------------

@bp.route("/boards/<int:board_id>/share", methods=["POST"])
@login_required
def share_board(board_id: int):
    """Invite a user by username as editor or viewer."""
    # Only owners can share
    owner_check = query_one(
        """SELECT role FROM board_member
           WHERE board_id = %s AND user_id = %s AND role = 'owner'""",
        (board_id, session.get("user_id")),
    )
    if owner_check is None and not current_app.config.get("TESTING"):
        flash("Only the board owner can share it", "error")
        return redirect(url_for("draft.my_boards"))

    invitee_username = request.form.get("username", "").strip()
    role = request.form.get("role", "viewer").strip()
    if role not in ("editor", "viewer"):
        flash("Role must be editor or viewer", "error")
        return redirect(url_for("draft.my_boards"))

    target = query_one(
        "SELECT user_id FROM app_user WHERE LOWER(username) = LOWER(%s)",
        (invitee_username,),
    )
    if target is None:
        flash(f"No user found with username '{invitee_username}'", "error")
        return redirect(url_for("draft.my_boards"))

    with transaction("READ COMMITTED") as conn:
        conn.execute(
            """INSERT INTO board_member (board_id, user_id, role)
               VALUES (%s, %s, %s)
               ON CONFLICT (board_id, user_id) DO UPDATE SET role = EXCLUDED.role""",
            (board_id, target["user_id"], role),
        )
    flash(f"Shared with {invitee_username} as {role}", "success")
    return redirect(url_for("draft.my_boards"))
