"""Tests for the Draft Board blueprint (Requirement 1).

Each test class uses the `clean_picks` fixture, which deletes all picks for
the seeded board before and after the test so tests are fully isolated and
the existing test_data.py suite stays green.

CSRF is disabled in conftest.py via WTF_CSRF_ENABLED = False.
"""
from __future__ import annotations

from decimal import Decimal

import pytest


# ── fixtures ──────────────────────────────────────────────────────────────────
# board_id is defined in conftest.py and shared across test files.

@pytest.fixture
def clean_picks(conn, board_id):
    """Remove all picks for the seeded board before and after each test."""
    conn.execute("DELETE FROM draft_pick WHERE board_id = %s", (board_id,))
    conn.commit()
    yield
    conn.execute("DELETE FROM draft_pick WHERE board_id = %s", (board_id,))
    conn.commit()


def _indian_id(conn) -> int:
    """Return player_id of a confirmed Indian player."""
    row = conn.execute(
        "SELECT player_id FROM player WHERE is_overseas = FALSE LIMIT 1"
    ).fetchone()
    return row["player_id"]


def _overseas_ids(conn, n: int) -> list[int]:
    """Return n distinct overseas player_ids."""
    rows = conn.execute(
        "SELECT player_id FROM player WHERE is_overseas = TRUE LIMIT %s", (n,)
    ).fetchall()
    assert len(rows) >= n, "Not enough overseas players in the test database"
    return [r["player_id"] for r in rows]


def _add_via_route(client, board_id, player_id, role="BAT", priority=3,
                   max_bid="10", notes="") -> None:
    """POST to /draft/picks and assert a redirect (no flash error expected)."""
    resp = client.post("/draft/picks", data={
        "player_id": player_id,
        "role_slot": role,
        "priority": priority,
        "max_bid_cr": max_bid,
        "notes": notes,
    })
    assert resp.status_code == 302


def _get_pick(conn, board_id, player_id) -> dict:
    """Fetch the pick row for the given player on the board."""
    row = conn.execute(
        "SELECT * FROM draft_pick WHERE board_id = %s AND player_id = %s",
        (board_id, player_id),
    ).fetchone()
    assert row is not None, f"Pick for player {player_id} not found on board {board_id}"
    return dict(row)


# ── add / edit / delete ───────────────────────────────────────────────────────

class TestAddEditDelete:
    def test_add_appears_in_list(self, client, conn, board_id, clean_picks):
        """POST /draft/picks → player appears in the board page."""
        pid = _indian_id(conn)
        _add_via_route(client, board_id, pid, role="BAT", max_bid="20", notes="test add")

        resp = client.get("/draft", follow_redirects=True)
        assert resp.status_code == 200

        # Row exists in the database with correct values
        pick = _get_pick(conn, board_id, pid)
        assert pick["max_bid_cr"] == Decimal("20")
        assert pick["status"] == "Target"
        assert pick["role_slot"] == "BAT"

    def test_edit_changes_bid(self, client, conn, board_id, clean_picks):
        """POST /draft/picks/<id> (ordinary edit) updates max_bid_cr and bumps version."""
        pid = _indian_id(conn)
        conn.execute(
            """INSERT INTO draft_pick (board_id, player_id, role_slot, priority, max_bid_cr)
               VALUES (%s, %s, 'BAT', 1, 20)""",
            (board_id, pid),
        )
        conn.commit()
        pick = _get_pick(conn, board_id, pid)
        old_version = pick["version"]

        resp = client.post(f"/draft/picks/{pick['pick_id']}", data={
            "role_slot": "BAT",
            "priority": "1",
            "max_bid_cr": "22",
            "status": "Target",
            "notes": "",
            "version": str(old_version),
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Pick updated" in resp.data

        updated = conn.execute(
            "SELECT max_bid_cr, version FROM draft_pick WHERE pick_id = %s",
            (pick["pick_id"],),
        ).fetchone()
        assert updated["max_bid_cr"] == Decimal("22")
        assert updated["version"] == old_version + 1

    def test_delete_removes_row(self, client, conn, board_id, clean_picks):
        """POST /draft/picks/<id>/delete removes the row from the database."""
        pid = _indian_id(conn)
        conn.execute(
            "INSERT INTO draft_pick (board_id, player_id, role_slot, priority, max_bid_cr) "
            "VALUES (%s, %s, 'BAT', 2, 10)",
            (board_id, pid),
        )
        conn.commit()
        pick_id = conn.execute(
            "SELECT pick_id FROM draft_pick WHERE board_id = %s AND player_id = %s",
            (board_id, pid),
        ).fetchone()["pick_id"]

        resp = client.post(f"/draft/picks/{pick_id}/delete", follow_redirects=True)
        assert resp.status_code == 200
        assert b"Pick removed" in resp.data

        gone = conn.execute(
            "SELECT pick_id FROM draft_pick WHERE pick_id = %s", (pick_id,)
        ).fetchone()
        assert gone is None


# ── duplicate player ──────────────────────────────────────────────────────────

class TestDuplicatePlayer:
    def test_duplicate_flashes_error(self, client, conn, board_id, clean_picks):
        """Adding the same player twice triggers the UNIQUE constraint and
        flashes 'already on the board' instead of raising a 500."""
        pid = _indian_id(conn)
        data = {
            "player_id": pid,
            "role_slot": "BAT",
            "priority": "2",
            "max_bid_cr": "10",
            "notes": "",
        }
        client.post("/draft/picks", data=data)
        resp = client.post("/draft/picks", data=data, follow_redirects=True)
        assert resp.status_code == 200
        assert b"already on the board" in resp.data

        # Only one row should exist
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM draft_pick WHERE board_id = %s AND player_id = %s",
            (board_id, pid),
        ).fetchone()["n"]
        assert count == 1


# ── buy-transaction rule enforcement ─────────────────────────────────────────

class TestBuyRules:
    def test_purse_limit_refused(self, client, conn, board_id, clean_picks):
        """Buying over the available purse is refused with an error flash."""
        pid = _indian_id(conn)
        conn.execute(
            "INSERT INTO draft_pick (board_id, player_id, role_slot, priority, max_bid_cr) "
            "VALUES (%s, %s, 'BAT', 1, 1)",
            (board_id, pid),
        )
        conn.commit()
        pick = _get_pick(conn, board_id, pid)

        # ₹200 cr bid on a ₹125 cr purse board
        resp = client.post(f"/draft/picks/{pick['pick_id']}", data={
            "role_slot": "BAT",
            "priority": "1",
            "max_bid_cr": "1",
            "status": "Bought",
            "price_paid_cr": "200",
            "notes": "",
            "version": str(pick["version"]),
        }, follow_redirects=True)
        assert resp.status_code == 200
        # Either "purse" or "Not enough" must appear in the response
        low = resp.data.lower()
        assert b"purse" in low or b"not enough" in low

        # Pick must NOT have been marked Bought
        still_target = conn.execute(
            "SELECT status FROM draft_pick WHERE pick_id = %s", (pick["pick_id"],)
        ).fetchone()["status"]
        assert still_target == "Target"

    def test_ninth_overseas_refused(self, client, conn, board_id, clean_picks):
        """A 9th overseas purchase is refused; the board allows only 8."""
        ovs = _overseas_ids(conn, 9)

        # Insert 8 overseas players already Bought (₹5 cr each = ₹40 cr spent)
        for pid in ovs[:8]:
            conn.execute(
                """INSERT INTO draft_pick
                       (board_id, player_id, role_slot, priority, max_bid_cr,
                        status, price_paid_cr)
                   VALUES (%s, %s, 'BOWL', 3, 5, 'Bought', 5)""",
                (board_id, pid),
            )
        conn.commit()

        # 9th overseas as a target pick
        conn.execute(
            "INSERT INTO draft_pick (board_id, player_id, role_slot, priority, max_bid_cr) "
            "VALUES (%s, %s, 'BOWL', 3, 5)",
            (board_id, ovs[8]),
        )
        conn.commit()
        pick = _get_pick(conn, board_id, ovs[8])

        resp = client.post(f"/draft/picks/{pick['pick_id']}", data={
            "role_slot": "BOWL",
            "priority": "3",
            "max_bid_cr": "5",
            "status": "Bought",
            "price_paid_cr": "5",
            "notes": "",
            "version": str(pick["version"]),
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"overseas" in resp.data.lower()

        status = conn.execute(
            "SELECT status FROM draft_pick WHERE pick_id = %s", (pick["pick_id"],)
        ).fetchone()["status"]
        assert status == "Target"

    def test_overseas_cap_refused(self, client, conn, board_id, clean_picks):
        """An overseas buy above the ₹18 cr cap is refused."""
        pid = _overseas_ids(conn, 1)[0]
        conn.execute(
            "INSERT INTO draft_pick (board_id, player_id, role_slot, priority, max_bid_cr) "
            "VALUES (%s, %s, 'BOWL', 3, 20)",
            (board_id, pid),
        )
        conn.commit()
        pick = _get_pick(conn, board_id, pid)

        resp = client.post(f"/draft/picks/{pick['pick_id']}", data={
            "role_slot": "BOWL",
            "priority": "3",
            "max_bid_cr": "20",
            "status": "Bought",
            "price_paid_cr": "20",    # ₹20 cr > ₹18 cr cap
            "notes": "",
            "version": str(pick["version"]),
        }, follow_redirects=True)
        assert resp.status_code == 200
        low = resp.data.lower()
        assert b"cap" in low or b"18" in resp.data

        status = conn.execute(
            "SELECT status FROM draft_pick WHERE pick_id = %s", (pick["pick_id"],)
        ).fetchone()["status"]
        assert status == "Target"

    def test_version_conflict_flashes_reload(self, client, conn, board_id, clean_picks):
        """Submitting an edit with a stale version number surfaces a friendly error."""
        pid = _indian_id(conn)
        conn.execute(
            "INSERT INTO draft_pick (board_id, player_id, role_slot, priority, max_bid_cr) "
            "VALUES (%s, %s, 'BAT', 1, 10)",
            (board_id, pid),
        )
        conn.commit()
        pick = _get_pick(conn, board_id, pid)
        stale_version = pick["version"]

        # Simulate another scout editing the same pick (bumps the version in the DB)
        conn.execute(
            "UPDATE draft_pick SET version = version + 1 WHERE pick_id = %s",
            (pick["pick_id"],),
        )
        conn.commit()

        # Submit with the now-stale version
        resp = client.post(f"/draft/picks/{pick['pick_id']}", data={
            "role_slot": "BAT",
            "priority": "1",
            "max_bid_cr": "12",
            "status": "Target",
            "notes": "",
            "version": str(stale_version),
        }, follow_redirects=True)
        assert resp.status_code == 200
        low = resp.data.lower()
        assert b"reload" in low or b"someone else" in low

        # The edit must NOT have been applied
        current_bid = conn.execute(
            "SELECT max_bid_cr FROM draft_pick WHERE pick_id = %s", (pick["pick_id"],)
        ).fetchone()["max_bid_cr"]
        assert current_bid == Decimal("10")   # original value unchanged
