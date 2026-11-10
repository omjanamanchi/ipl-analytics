"""Tests for the Scouting Report blueprint (Requirement 2).

Covers:
  - Default report returns rows
  - Each filter category narrows results
  - All sort-whitelist keys work
  - SQL-injection string as a filter value: 0 rows, no error
  - SQL-injection string as a sort key: ignored, page loads fine
  - Before/after demo (plan.md § 9.4): buy a player, status and purse update
"""
from __future__ import annotations

import pytest


# ── shared clean-up fixture (mirrors the one in test_draft.py) ───────────────

@pytest.fixture
def clean_picks(conn, board_id):
    """Remove all picks for the seeded board before and after each test."""
    conn.execute("DELETE FROM draft_pick WHERE board_id = %s", (board_id,))
    conn.commit()
    yield
    conn.execute("DELETE FROM draft_pick WHERE board_id = %s", (board_id,))
    conn.commit()


# ── default report ────────────────────────────────────────────────────────────

class TestDefaultReport:
    def test_returns_200(self, client):
        resp = client.get("/report")
        assert resp.status_code == 200

    def test_has_rows_with_defaults(self, client):
        """The default filter (last 3 seasons, min 60 balls) must yield results."""
        resp = client.get("/report")
        assert resp.status_code == 200
        assert b"No players match" not in resp.data

    def test_nav_link_visible(self, client):
        """The Scouting Report link appears in the nav on every page."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Scouting Report" in resp.data


# ── individual filters narrow the result set ─────────────────────────────────

class TestFilters:
    BASE = "season_from=2024&season_to=2026&min_balls=60"

    def test_overseas_filter(self, client):
        all_resp = client.get(f"/report?{self.BASE}")
        ovs_resp = client.get(f"/report?{self.BASE}&nationality=Overseas")
        assert all_resp.status_code == ovs_resp.status_code == 200
        # Overseas subset produces a smaller (or equal) table
        assert len(ovs_resp.data) <= len(all_resp.data)

    def test_indian_filter(self, client):
        resp = client.get(f"/report?{self.BASE}&nationality=Indian")
        assert resp.status_code == 200
        # With a large dataset there should be results for Indian players
        assert b"No players match" not in resp.data

    def test_single_phase(self, client):
        resp = client.get(f"/report?{self.BASE}&phase=Death&min_balls=20")
        assert resp.status_code == 200

    def test_all_three_phases_explicit(self, client):
        resp = client.get(
            f"/report?{self.BASE}&phase=Powerplay&phase=Middle&phase=Death"
        )
        assert resp.status_code == 200

    def test_role_filter(self, client):
        resp = client.get(f"/report?{self.BASE}&role=BOWL")
        assert resp.status_code == 200

    def test_pace_bowling_type(self, client):
        resp = client.get(f"/report?{self.BASE}&bowling_type=Pace")
        assert resp.status_code == 200

    def test_high_min_balls_returns_empty(self, client):
        """An absurdly high min_balls threshold should produce the empty-state message."""
        # Omit the BASE min_balls so there is only one min_balls param in the URL.
        resp = client.get("/report?season_from=2024&season_to=2026&min_balls=99999")
        assert resp.status_code == 200
        assert b"No players match" in resp.data

    def test_hide_on_board_param(self, client):
        resp = client.get(f"/report?{self.BASE}&hide_on_board=1")
        assert resp.status_code == 200


# ── sort whitelist ────────────────────────────────────────────────────────────

class TestSortWhitelist:
    BASE = "season_from=2024&season_to=2026&min_balls=60"

    def test_all_valid_sort_keys(self, client):
        for key in ["mvp", "value", "sr", "runs", "avg", "econ", "wkts", "dot", "price"]:
            resp = client.get(f"/report?{self.BASE}&sort={key}")
            assert resp.status_code == 200, f"sort={key!r} returned {resp.status_code}"

    def test_unknown_sort_key_falls_back(self, client):
        """An unknown sort key silently falls back to 'mvp'; no error or crash."""
        resp = client.get(f"/report?{self.BASE}&sort=unknown_key")
        assert resp.status_code == 200

    def test_injection_in_sort_key_is_ignored(self, client, conn):
        """An SQL-injection string in the sort parameter falls back to the default.

        SORT_COLUMNS.get() returns the 'mvp' fragment for any unknown key,
        so the injected text is never appended to the SQL.  The player table
        must still exist after the request.
        """
        resp = client.get(
            f"/report?{self.BASE}&sort=mvp; DROP TABLE player--"
        )
        assert resp.status_code == 200
        # Confirm the table is intact
        count = conn.execute("SELECT COUNT(*) AS n FROM player").fetchone()["n"]
        assert count > 100, "player table was affected — injection not properly blocked"


# ── SQL-injection via filter value ────────────────────────────────────────────

class TestSQLInjection:
    BASE = "season_from=2024&season_to=2026&min_balls=1"

    def test_bowling_type_injection_returns_zero_rows(self, client):
        """Security demo (plan.md § 11): passing an injection string as bowling_type.

        psycopg sends the value as a parameter (not embedded SQL).
        PostgreSQL compares it literally against bowling_type; no row matches.
        Returns 0 rows instead of every player — the page shows the empty state.
        """
        # URL-encoded form of: Pace' OR '1'='1
        resp = client.get(
            f"/report?{self.BASE}&bowling_type=Pace%27+OR+%271%27%3D%271"
        )
        assert resp.status_code == 200
        assert b"No players match" in resp.data

    def test_injection_in_team_id_is_safe(self, client):
        """A non-integer team_id is coerced to None (no team filter), not SQL."""
        resp = client.get(f"/report?{self.BASE}&team_id=1 OR 1=1")
        assert resp.status_code == 200   # int() fails → team_id = None → no crash

    def test_page_has_no_sql_error_text(self, client):
        """No raw psycopg / PostgreSQL error text should leak to the browser."""
        resp = client.get(f"/report?{self.BASE}&bowling_type=anything&sort=bad")
        assert b"ERROR" not in resp.data
        assert b"psycopg" not in resp.data
        assert b"syntax error" not in resp.data.lower()


# ── before / after demo (plan.md § 9.4) ──────────────────────────────────────

class TestBeforeAfter:
    FILTER = (
        "phase=Death&nationality=Overseas&bowling_type=Pace"
        "&season_from=2024&season_to=2026&min_balls=60&sort=econ"
    )

    def test_buy_updates_status_and_purse(self, client, conn, board_id, clean_picks):
        """Buy Matheesha Pathirana for ₹14 cr; the report and board panel update.

        Before: Pathirana has no board_status, purse left = ₹125 cr.
        After:  board_status = Bought, purse left = ₹111 cr, overseas = 1/8.
        """
        # Find Pathirana by name in case player_id ever shifts
        pathirana = conn.execute(
            "SELECT player_id FROM player WHERE display_name ILIKE %s LIMIT 1",
            ("%pathirana%",),
        ).fetchone()
        if pathirana is None:
            pytest.skip("Matheesha Pathirana not in test database")
        pid = pathirana["player_id"]

        # ── BEFORE ──────────────────────────────────────────────────────────
        resp_before = client.get(f"/report?{self.FILTER}")
        assert resp_before.status_code == 200
        # Board panel must show full purse
        assert b"125.00" in resp_before.data
        # Pathirana's row must not show Bought / Target / Lost yet
        assert b"Bought" not in resp_before.data

        # ── add and buy via the draft routes ────────────────────────────────
        client.post("/draft/picks", data={
            "player_id": pid,
            "role_slot": "BOWL",
            "priority": "1",
            "max_bid_cr": "14",
            "notes": "before/after demo",
        })
        pick = conn.execute(
            "SELECT * FROM draft_pick WHERE board_id = %s AND player_id = %s",
            (board_id, pid),
        ).fetchone()
        assert pick is not None, "Pick was not created by add route"

        resp_buy = client.post(f"/draft/picks/{pick['pick_id']}", data={
            "role_slot": "BOWL",
            "priority": "1",
            "max_bid_cr": "14",
            "status": "Bought",
            "price_paid_cr": "14",
            "notes": "before/after demo",
            "version": str(pick["version"]),
        })
        # Must redirect (no flash-error page)
        assert resp_buy.status_code == 302

        # ── AFTER ───────────────────────────────────────────────────────────
        resp_after = client.get(f"/report?{self.FILTER}")
        assert resp_after.status_code == 200
        # Pathirana's status should now show Bought
        assert b"Bought" in resp_after.data
        # Purse: 125 - 14 = 111
        assert b"111" in resp_after.data
        # Overseas count must reflect the purchase
        assert b"1 / 8" in resp_after.data

        # ── hide_on_board removes him ────────────────────────────────────────
        resp_hide = client.get(f"/report?{self.FILTER}&hide_on_board=1")
        assert resp_hide.status_code == 200
        # With hide enabled, Pathirana's row should be absent
        assert "Matheesha Pathirana".encode() not in resp_hide.data
