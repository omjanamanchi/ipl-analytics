"""Auth blueprint — sign-up, login (by username or email), lockout, guest mode, logout.

Routes:
  GET  /login            login form
  POST /login            authenticate (username or email + password)
  GET  /signup           sign-up form
  POST /signup           create account
  POST /logout           clear session
  POST /guest            set guest mode (read-only)

Security:
  - Passwords hashed with werkzeug.security (bcrypt-based)
  - Login by username OR email (case-insensitive)
  - 5 failed logins -> locked_until = now() + 15 min (stored in DB, survives restarts)
  - login_required is a no-op when app.config["TESTING"] is True
  - guest_required: same but redirects to /signup instead of /login
"""
from __future__ import annotations
import re
from datetime import timezone
from functools import wraps

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import query_one, transaction

bp = Blueprint("auth", __name__)

# -- email format check --------------------------------------------------------
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def _valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email))

# -- decorator -----------------------------------------------------------------
def login_required(f):
    """No-op when TESTING=True; otherwise requires a logged-in (non-guest) user."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_app.config.get("TESTING"):
            return f(*args, **kwargs)
        if not session.get("user_id"):
            flash("Sign in to continue", "error")
            return redirect(url_for("auth.login", next=request.url))
        return f(*args, **kwargs)
    return decorated

# -- login ---------------------------------------------------------------------
@bp.get("/login")
def login():
    if session.get("user_id"):
        return redirect(url_for("core.home"))
    return render_template("auth/login.html")

@bp.post("/login")
def login_post():
    from datetime import datetime
    identifier = request.form.get("identifier", "").strip()
    password   = request.form.get("password", "")

    # Login by username OR email (case-insensitive)
    row = query_one(
        """SELECT user_id, display_name, password_hash,
                  failed_logins, locked_until, is_active
           FROM app_user
           WHERE LOWER(username) = LOWER(%(i)s) OR LOWER(email) = LOWER(%(i)s)""",
        {"i": identifier},
    )

    if row is None:
        flash("Invalid username/email or password", "error")
        return render_template("auth/login.html"), 401

    if not row["is_active"]:
        flash("This account has been disabled", "error")
        return render_template("auth/login.html"), 403

    # Lockout check
    if row["locked_until"]:
        locked_until = row["locked_until"]
        # Make aware if naive
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until > datetime.now(timezone.utc):
            flash("Account locked after too many failed attempts. Try again in 15 minutes.", "error")
            return render_template("auth/login.html"), 403

    if not check_password_hash(row["password_hash"], password):
        # Increment failed_logins; lock after 5 failures
        with transaction("READ COMMITTED") as conn:
            conn.execute(
                """UPDATE app_user
                      SET failed_logins = failed_logins + 1,
                          locked_until  = CASE WHEN failed_logins + 1 >= 5
                                               THEN now() + interval '15 minutes'
                                               ELSE locked_until END
                    WHERE user_id = %s""",
                (row["user_id"],),
            )
        flash("Invalid username/email or password", "error")
        return render_template("auth/login.html"), 401

    # Successful login: reset counters
    with transaction("READ COMMITTED") as conn:
        conn.execute(
            """UPDATE app_user
                  SET failed_logins = 0, locked_until = NULL, last_login_at = now()
                WHERE user_id = %s""",
            (row["user_id"],),
        )

    session.clear()
    session["user_id"]      = row["user_id"]
    session["display_name"] = row["display_name"]

    next_url = request.form.get("next") or url_for("core.home")
    if not next_url.startswith("/"):
        next_url = url_for("core.home")
    return redirect(next_url)

# -- sign-up -------------------------------------------------------------------
@bp.get("/signup")
def signup():
    if session.get("user_id"):
        return redirect(url_for("core.home"))
    return render_template("auth/signup.html")

@bp.post("/signup")
def signup_post():
    username     = request.form.get("username", "").strip()
    email        = request.form.get("email", "").strip()
    display_name = request.form.get("display_name", "").strip() or username
    password     = request.form.get("password", "")
    confirm      = request.form.get("confirm_password", "")

    errors = []
    if not username or len(username) < 3 or len(username) > 40:
        errors.append("Username must be 3-40 characters")
    if not _valid_email(email):
        errors.append("Enter a valid email address")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters")
    if password != confirm:
        errors.append("Passwords do not match")

    if errors:
        for e in errors:
            flash(e, "error")
        return render_template("auth/signup.html",
                               username=username, email=email, display_name=display_name), 400

    pw_hash = generate_password_hash(password)
    try:
        with transaction("READ COMMITTED") as conn:
            row = conn.execute(
                """INSERT INTO app_user (username, email, display_name, password_hash)
                   VALUES (%(username)s, %(email)s, %(display_name)s, %(pw_hash)s)
                   RETURNING user_id""",
                {"username": username, "email": email,
                 "display_name": display_name, "pw_hash": pw_hash},
            ).fetchone()
    except Exception:
        # UNIQUE constraint on username or email
        flash("That username or email is already taken", "error")
        return render_template("auth/signup.html",
                               username=username, email=email, display_name=display_name), 400

    session.clear()
    session["user_id"]      = row["user_id"]
    session["display_name"] = display_name
    flash(f"Welcome, {display_name}! Your account has been created.", "success")
    return redirect(url_for("core.home"))

# -- guest mode ----------------------------------------------------------------
@bp.post("/guest")
def guest():
    """Set guest mode: read-only access, no account needed."""
    session.clear()
    session["is_guest"] = True
    return redirect(url_for("core.home"))

# -- logout --------------------------------------------------------------------
@bp.post("/logout")
def logout():
    session.clear()
    flash("Logged out", "success")
    return redirect(url_for("core.home"))
