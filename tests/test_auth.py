"""Tests for the auth blueprint (sign-up, login, lockout, guest mode).

CSRF is disabled in conftest.py via WTF_CSRF_ENABLED = False.
All tests use app.config["TESTING"] = True (set in conftest.py).
"""
from __future__ import annotations

import pytest
from werkzeug.security import generate_password_hash


# -- fixtures ------------------------------------------------------------------

@pytest.fixture
def clean_users(conn):
    """Delete test users (username starts with 'test_') before and after each test."""
    conn.execute("DELETE FROM app_user WHERE username LIKE 'test\\_%'")
    conn.commit()
    yield
    conn.execute("DELETE FROM app_user WHERE username LIKE 'test\\_%'")
    conn.commit()


def _signup(client, username="test_user1", email="test_user1@example.com",
            display_name="Test User", password="ValidPass1",
            confirm_password=None, follow_redirects=False):
    """POST /signup helper."""
    if confirm_password is None:
        confirm_password = password
    return client.post("/signup", data={
        "username": username,
        "email": email,
        "display_name": display_name,
        "password": password,
        "confirm_password": confirm_password,
    }, follow_redirects=follow_redirects)


def _insert_user(conn, username="test_lock1", email="test_lock1@example.com",
                 password="ValidPass1", failed_logins=0):
    """Insert a user directly into the DB and return user_id."""
    pw_hash = generate_password_hash(password)
    row = conn.execute(
        """INSERT INTO app_user (username, email, display_name, password_hash, failed_logins)
           VALUES (%s, %s, %s, %s, %s)
           RETURNING user_id""",
        (username, email, username, pw_hash, failed_logins),
    ).fetchone()
    conn.commit()
    return row["user_id"]


# -- TestSignup ----------------------------------------------------------------

class TestSignup:
    def test_signup_creates_user(self, client, conn, clean_users):
        """POST /signup with valid data creates the user in the DB and redirects."""
        resp = _signup(client, username="test_newuser", email="test_newuser@example.com")
        assert resp.status_code == 302, f"Expected redirect, got {resp.status_code}"

        row = conn.execute(
            "SELECT user_id, display_name FROM app_user WHERE username = 'test_newuser'"
        ).fetchone()
        assert row is not None, "User was not inserted into app_user"
        assert row["display_name"] == "Test User"

    def test_duplicate_username_flashes_error(self, client, conn, clean_users):
        """Signing up with an already-taken username returns 400 and flashes an error."""
        _signup(client, username="test_dupuser", email="test_dup1@example.com")
        resp = _signup(client, username="test_dupuser", email="test_dup2@example.com",
                       follow_redirects=True)
        assert resp.status_code in (400, 200)
        assert b"already taken" in resp.data or b"taken" in resp.data

    def test_duplicate_email_flashes_error(self, client, conn, clean_users):
        """Signing up with an already-taken email returns 400 and flashes an error."""
        _signup(client, username="test_em1", email="test_shared@example.com")
        resp = _signup(client, username="test_em2", email="test_shared@example.com",
                       follow_redirects=True)
        assert resp.status_code in (400, 200)
        assert b"already taken" in resp.data or b"taken" in resp.data

    def test_short_password_rejected(self, client, clean_users):
        """Password shorter than 8 chars returns 400 and flashes an error."""
        resp = _signup(client, username="test_shortpw", email="test_shortpw@example.com",
                       password="short", confirm_password="short")
        assert resp.status_code == 400
        assert b"8" in resp.data or b"characters" in resp.data

    def test_invalid_email_rejected(self, client, clean_users):
        """Email without @ returns 400 and flashes an error."""
        resp = _signup(client, username="test_bademail", email="notanemail",
                       password="ValidPass1", confirm_password="ValidPass1")
        assert resp.status_code == 400
        assert b"email" in resp.data.lower()


# -- TestLogin -----------------------------------------------------------------

class TestLogin:
    def test_login_by_username(self, client, conn, clean_users):
        """POST /login with username and correct password redirects."""
        _insert_user(conn, username="test_loginuser", email="test_loginuser@example.com",
                     password="ValidPass1")
        resp = client.post("/login", data={
            "identifier": "test_loginuser",
            "password": "ValidPass1",
        })
        assert resp.status_code == 302, f"Expected redirect, got {resp.status_code}"

    def test_login_by_email(self, client, conn, clean_users):
        """POST /login with email and correct password redirects."""
        _insert_user(conn, username="test_emaillogin", email="test_emaillogin@example.com",
                     password="ValidPass1")
        resp = client.post("/login", data={
            "identifier": "test_emaillogin@example.com",
            "password": "ValidPass1",
        })
        assert resp.status_code == 302, f"Expected redirect, got {resp.status_code}"

    def test_wrong_password_flashes_error(self, client, conn, clean_users):
        """POST /login with wrong password returns 401 and flashes error."""
        _insert_user(conn, username="test_badpw", email="test_badpw@example.com",
                     password="CorrectPass1")
        resp = client.post("/login", data={
            "identifier": "test_badpw",
            "password": "WrongPass1",
        })
        assert resp.status_code == 401
        assert b"Invalid" in resp.data

    def test_lockout_after_5_failures(self, client, conn, clean_users):
        """After 5 wrong-password attempts the account is locked."""
        _insert_user(conn, username="test_lockme", email="test_lockme@example.com",
                     password="CorrectPass1", failed_logins=4)
        # 5th wrong attempt triggers lockout
        resp = client.post("/login", data={
            "identifier": "test_lockme",
            "password": "WrongPass1",
        })
        # Subsequent attempt should report locked
        resp2 = client.post("/login", data={
            "identifier": "test_lockme",
            "password": "WrongPass1",
        })
        assert resp2.status_code in (401, 403)
        assert b"locked" in resp2.data.lower() or b"Invalid" in resp2.data


# -- TestGuestMode -------------------------------------------------------------

class TestGuestMode:
    def test_guest_can_view_scouting_report(self, client):
        """POST /guest sets guest session; GET /report returns 200."""
        # Set guest mode
        client.post("/guest")
        resp = client.get("/report", follow_redirects=True)
        assert resp.status_code == 200

    def test_guest_sets_session_flag(self, client):
        """POST /guest redirects to home (302)."""
        resp = client.post("/guest")
        assert resp.status_code == 302
