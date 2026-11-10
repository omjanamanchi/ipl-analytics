"""Checks the loaded data against published IPL results. Run after `make load`."""
import pytest


def one(conn, sql, params=None):
    return conn.execute(sql, params).fetchone()


def test_row_counts(conn):
    r = one(conn, "SELECT (SELECT COUNT(*) FROM match) m, (SELECT COUNT(*) FROM delivery) d")
    assert r["m"] >= 1243 and r["d"] >= 295_000


@pytest.mark.parametrize("season,award,player,value", [
    (2024, "Orange Cap", "V Kohli", 741),
    (2024, "Purple Cap", "HV Patel", 24),
    (2025, "Orange Cap", "B Sai Sudharsan", 759),
    (2025, "Purple Cap", "M Prasidh Krishna", 25),
    (2025, "Most Valuable Player", "SA Yadav", 320.5),
    (2026, "Orange Cap", "V Suryavanshi", 776),
    (2026, "Purple Cap", "K Rabada", 29),
])
def test_awards_match_official(conn, season, award, player, value):
    r = one(conn, """SELECT p.cricsheet_name, sa.stat_value FROM season_award sa
                     JOIN award a USING (award_id) JOIN player p USING (player_id)
                     WHERE sa.season_year = %s AND a.award_name = %s""", (season, award))
    assert r["cricsheet_name"] == player and float(r["stat_value"]) == value


@pytest.mark.parametrize("season,team,nrr", [(2024, "KKR", 1.428), (2024, "SRH", 0.414), (2025, "PBKS", 0.372)])
def test_net_run_rate_matches_points_table(conn, season, team, nrr):
    r = one(conn, "SELECT net_run_rate FROM v_team_season_stats WHERE season_year=%s AND short_code=%s", (season, team))
    assert float(r["net_run_rate"]) == pytest.approx(nrr, abs=0.002)


def test_champions(conn):
    rows = conn.execute("""SELECT s.season_year, f.short_code FROM season s
                           JOIN franchise f ON f.franchise_id = s.champion_id
                           WHERE s.season_year IN (2008, 2016, 2025, 2026)""").fetchall()
    assert {r["season_year"]: r["short_code"] for r in rows} == {2008: "RR", 2016: "SRH", 2025: "RCB", 2026: "RCB"}


def test_phase_and_season_views_agree(conn):
    r = one(conn, """SELECT (SELECT SUM(runs) FROM mv_player_phase_stats WHERE season_year = 2026) a,
                            (SELECT SUM(runs) FROM mv_player_season_stats WHERE season_year = 2026) b""")
    assert r["a"] == r["b"]


def test_2026_salaries_within_purse(conn):
    rows = conn.execute("""SELECT franchise_id, SUM(price_cr) s FROM contract
                           WHERE season_year = 2026 GROUP BY 1""").fetchall()
    assert rows and all(r["s"] <= 125 for r in rows)


def test_home_page(client):
    r = client.get("/")
    assert r.status_code == 200 and b"deliveries" in r.data
    assert client.get("/healthz").json == {"status": "ok"}
