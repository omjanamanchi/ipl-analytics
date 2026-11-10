"""
Load Cricsheet IPL ball-by-ball JSON into PostgreSQL.

Usage:
    python -m etl.download_data                    # fetch data/raw/ipl_json/*.json
    python -m etl.load_cricsheet --reset           # build schema + load everything

The loader:
  1. (--reset) runs db/schema.sql, loads venues, runs db/seed_reference.sql
  2. inserts every player once, with biography data from data/player_meta_*.csv
  3. loads each match (match, XI, innings, deliveries, dismissals, fielders)
     in ONE transaction per match - a bad file never leaves half a match behind
  4. derives contracts, season dates, champions, missing roles, awards
  5. refreshes the materialized views, builds secondary indexes, ANALYZE
All SQL uses parameters (%s) - no string formatting of values.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "db"
DATA_DIR = ROOT / "data"
SPIN_WORDS = ("offbreak", "legbreak", "orthodox", "wrist spin", "googly", "slow left")
PACE_WORDS = ("medium", "fast")


# ----------------------------------------------------------------------------- helpers
def run_sql_file(conn: psycopg.Connection, path: Path) -> None:
    print(f"  running {path.relative_to(ROOT)}")
    with conn.cursor() as cur:
        cur.execute(path.read_text())


def parse_bowling(style: str | None) -> tuple[str | None, str | None]:
    """'Right arm Fast medium' -> ('Right', 'Pace'); 'Legbreak Googly' -> ('Right', 'Spin')."""
    if not style:
        return None, None
    first = style.split(",")[0].strip().lower()
    arm = "Left" if "left" in first else ("Right" if ("right" in first or "legbreak" in first) else None)
    if any(w in first for w in SPIN_WORDS):
        kind = "Spin"
    elif any(w in first for w in PACE_WORDS):
        kind = "Pace"
    else:
        kind = None
    return arm, kind


def parse_role(playing_role: str | None) -> str | None:
    r = (playing_role or "").lower()
    if "wicketkeeper" in r:
        return "WK"
    if "allrounder" in r:
        return "AR"
    if "bowler" in r:
        return "BOWL"
    if "batter" in r:
        return "BAT"
    return None


def parse_hand(batting_style: str | None) -> str | None:
    s = (batting_style or "").lower()
    return "Left" if s.startswith("left") else ("Right" if s.startswith("right") else None)


def load_player_meta() -> dict[str, dict]:
    meta: dict[str, dict] = {}
    with open(DATA_DIR / "player_meta_ipl.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["source"] = "cricketdata"
            meta[r["cricsheet_id"]] = r
    sup = DATA_DIR / "player_meta_supplement.csv"
    if sup.exists():
        with open(sup, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                r.setdefault("full_name", "")
                r["source"] = "supplement"
                meta.setdefault(r["cricsheet_id"], r)
    return meta


def match_files(data_dir: Path) -> list[Path]:
    files = sorted(data_dir.glob("*.json"))
    if not files:
        sys.exit(f"No JSON files in {data_dir}. Run: python -m etl.download_data")
    return files


# ----------------------------------------------------------------------------- steps
def seed_reference(conn: psycopg.Connection) -> None:
    run_sql_file(conn, DB_DIR / "schema.sql")
    with open(DATA_DIR / "venue_aliases.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with conn.cursor() as cur:
        for r in rows:
            cur.execute(
                "INSERT INTO venue (name, city, country) VALUES (%s, %s, %s) ON CONFLICT (name) DO NOTHING",
                (r["venue_name"], r["city"], r["country"]),
            )
        for r in rows:
            cur.execute(
                "INSERT INTO venue_alias (alias, venue_id) SELECT %s, venue_id FROM venue WHERE name = %s",
                (r["alias"], r["venue_name"]),
            )
    run_sql_file(conn, DB_DIR / "seed_reference.sql")
    conn.commit()


def load_players(conn: psycopg.Connection, files: list[Path]) -> dict[str, int]:
    """Insert every person who appears in a match (XI, batter, bowler, fielder, POTM)."""
    names_by_id: dict[str, Counter] = defaultdict(Counter)
    for path in files:
        doc = json.loads(path.read_text())
        info, reg = doc["info"], doc["info"]["registry"]["people"]
        used = {p for ps in info["players"].values() for p in ps}
        used.update(info.get("player_of_match", []))
        for inn in doc["innings"]:
            for over in inn["overs"]:
                for b in over["deliveries"]:
                    used.update((b["batter"], b["bowler"], b["non_striker"]))
                    for w in b.get("wickets", []):
                        used.add(w["player_out"])
                        used.update(fl["name"] for fl in w.get("fielders", []) if "name" in fl)
        for name in used:
            names_by_id[reg[name]][name] += 1

    meta = load_player_meta()
    # Common names ("Sam Curran") from the 2026 squad list; everyone else keeps the Cricsheet name.
    display: dict[str, str] = {}
    prices = DATA_DIR / "contracts_prices.csv"
    if prices.exists():
        with open(prices, newline="", encoding="utf-8") as f:
            display = {r["cricsheet_id"]: r["source_name"] for r in csv.DictReader(f)}
    with conn.cursor() as cur:
        for cid, names in names_by_id.items():
            m = meta.get(cid, {})
            arm, kind = parse_bowling(m.get("bowling_style"))
            cur.execute(
                """INSERT INTO player (cricsheet_id, cricsheet_name, display_name, full_name, cricinfo_id, dob,
                                       country, batting_hand, bowling_arm, bowling_style, bowling_type,
                                       role_code, meta_source)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (cricsheet_id) DO NOTHING""",
                (
                    cid,
                    names.most_common(1)[0][0],
                    display.get(cid, names.most_common(1)[0][0]),
                    m.get("full_name") or None,
                    int(m["cricinfo_id"]) if m.get("cricinfo_id") else None,
                    m.get("dob") or None,
                    m.get("country") or None,
                    parse_hand(m.get("batting_style")),
                    arm,
                    m.get("bowling_style") or None,
                    kind,
                    parse_role(m.get("playing_role")),
                    m.get("source", "none"),
                ),
            )
        cur.execute("SELECT cricsheet_id, player_id FROM player")
        ids = dict(cur.fetchall())
    conn.commit()
    print(f"  players: {len(ids)}  (with bio data: {sum(1 for c in names_by_id if c in meta)})")
    return ids


def load_match(conn, doc: dict, match_id: int, pid: dict, fid: dict, vid: dict) -> int:
    info = doc["info"]
    reg = info["registry"]["people"]
    p = lambda name: pid[reg[name]]  # noqa: E731  name -> player_id via Cricsheet registry
    t1, t2 = (fid[t] for t in info["teams"])
    outcome = info["outcome"]
    if "winner" in outcome:
        result, winner = "win", fid[outcome["winner"]]
    elif outcome.get("result") == "tie":
        result, winner = "tie", fid[outcome["eliminator"]] if "eliminator" in outcome else None
    else:
        result, winner = "no result", None
    by = outcome.get("by", {})
    potm = info.get("player_of_match", [None])[0]
    event = info.get("event", {})

    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO match (match_id, season_year, match_number, match_date, stage, venue_id,
                                  team1_id, team2_id, toss_winner_id, toss_decision, result, winner_id,
                                  win_by_runs, win_by_wickets, method, potm_player_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                match_id, int(info["dates"][0][:4]), event.get("match_number"), info["dates"][0],
                event.get("stage", "League"), vid[info["venue"]], t1, t2,
                fid[info["toss"]["winner"]], info["toss"]["decision"], result, winner,
                by.get("runs"), by.get("wickets"), outcome.get("method"), p(potm) if potm else None,
            ),
        )
        cur.executemany(
            "INSERT INTO match_player (match_id, player_id, franchise_id) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            [(match_id, p(name), fid[team]) for team, names in info["players"].items() for name in names],
        )

        deliveries, dismissals, fielders = [], [], []
        for n, inn in enumerate(doc["innings"], start=1):
            bat = fid[inn["team"]]
            target = inn.get("target", {})
            cur.execute(
                """INSERT INTO innings (match_id, innings_no, batting_team_id, bowling_team_id,
                                        is_super_over, target_runs, target_overs)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (match_id, n, bat, t2 if bat == t1 else t1, bool(inn.get("super_over")),
                 target.get("runs"), target.get("overs")),
            )
            seq = 0
            for over in inn["overs"]:
                for ball_no, b in enumerate(over["deliveries"], start=1):
                    seq += 1
                    ex = b.get("extras", {})
                    deliveries.append((
                        match_id, n, seq, over["over"], ball_no,
                        p(b["batter"]), p(b["non_striker"]), p(b["bowler"]), b["runs"]["batter"],
                        ex.get("wides", 0), ex.get("noballs", 0), ex.get("byes", 0),
                        ex.get("legbyes", 0), ex.get("penalty", 0),
                    ))
                    for w in b.get("wickets", []):
                        out = p(w["player_out"])
                        dismissals.append((match_id, n, seq, out, w["kind"]))
                        for fl in w.get("fielders", []):
                            if "name" in fl:
                                fielders.append((match_id, n, seq, out, p(fl["name"]), bool(fl.get("substitute"))))

        # COPY is the fastest way to bulk insert; still inside this match's transaction.
        with cur.copy(
            """COPY delivery (match_id, innings_no, seq, over_no, ball_in_over, batter_id, non_striker_id,
                              bowler_id, batter_runs, wides, noballs, byes, legbyes, penalty) FROM STDIN"""
        ) as copy:
            for row in deliveries:
                copy.write_row(row)
        cur.executemany(
            "INSERT INTO dismissal (match_id, innings_no, seq, player_out_id, kind) VALUES (%s,%s,%s,%s,%s)",
            dismissals,
        )
        cur.executemany(
            """INSERT INTO dismissal_fielder (match_id, innings_no, seq, player_out_id, fielder_id, is_substitute)
               VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
            fielders,
        )
    return len(deliveries)


def derive_after_load(conn: psycopg.Connection, board_franchise: str) -> None:
    with conn.cursor() as cur:
        # Season dates.
        cur.execute(
            """UPDATE season s SET start_date = x.mn, end_date = x.mx
               FROM (SELECT season_year, MIN(match_date) mn, MAX(match_date) mx FROM match GROUP BY 1) x
               WHERE s.season_year = x.season_year"""
        )
        # Champion / runner-up from each season's Final.
        cur.execute(
            """UPDATE season s
                  SET champion_id  = m.winner_id,
                      runner_up_id = CASE WHEN m.winner_id = m.team1_id THEN m.team2_id ELSE m.team1_id END
                 FROM match m
                WHERE m.season_year = s.season_year AND m.stage = 'Final' AND m.winner_id IS NOT NULL"""
        )
        # Contracts: the franchise a player appeared for most often that season.
        cur.execute(
            """INSERT INTO contract (player_id, season_year, franchise_id, acquisition)
               SELECT DISTINCT ON (mp.player_id, m.season_year) mp.player_id, m.season_year, mp.franchise_id, 'Unknown'
               FROM match_player mp JOIN match m USING (match_id)
               GROUP BY mp.player_id, m.season_year, mp.franchise_id
               ORDER BY mp.player_id, m.season_year, COUNT(*) DESC
               ON CONFLICT DO NOTHING"""
        )
        prices = DATA_DIR / "contracts_prices.csv"
        if prices.exists():
            n = 0
            with open(prices, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    cur.execute(
                        """INSERT INTO contract (player_id, season_year, franchise_id, price_cr, acquisition)
                           SELECT p.player_id, %s, f.franchise_id, %s, %s
                             FROM player p, franchise f
                            WHERE p.cricsheet_id = %s AND f.short_code = %s
                           ON CONFLICT (player_id, season_year) DO UPDATE
                              SET price_cr = EXCLUDED.price_cr, acquisition = EXCLUDED.acquisition,
                                  franchise_id = EXCLUDED.franchise_id""",
                        (int(r["season_year"]), r["price_cr"] or None, r["acquisition"] or "Unknown",
                         r["cricsheet_id"], r["franchise_code"]),
                    )
                    n += cur.rowcount
            print(f"  contract prices applied: {n}")

    print("  refreshing materialized views ...")
    with conn.cursor() as cur:
        cur.execute("REFRESH MATERIALIZED VIEW mv_player_phase_stats")
        cur.execute("REFRESH MATERIALIZED VIEW mv_player_season_stats")
        # Infer a role for players with no bio data, from how they actually played.
        cur.execute(
            """UPDATE player p SET role_code = CASE
                    WHEN s.stumpings > 0                                   THEN 'WK'
                    WHEN s.balls_bowled >= 9 * s.matches AND s.balls_faced >= 8 * s.matches THEN 'AR'
                    WHEN s.balls_bowled >= 9 * s.matches                   THEN 'BOWL'
                    ELSE 'BAT' END
                 FROM (SELECT player_id, SUM(matches) matches, SUM(stumpings) stumpings,
                              SUM(legal_balls_bowled) balls_bowled, SUM(balls_faced) balls_faced
                         FROM mv_player_season_stats GROUP BY player_id) s
                WHERE p.player_id = s.player_id AND p.role_code IS NULL"""
        )
        # Season awards computed from the data.
        for award, expr in [
            ("Orange Cap", "runs"),
            ("Purple Cap", "wickets"),
            ("Most Valuable Player", "mvp_points"),
            ("Most Sixes", "sixes"),
        ]:
            cur.execute(
                f"""INSERT INTO season_award (season_year, award_id, player_id, stat_value)
                    SELECT DISTINCT ON (season_year) season_year,
                           (SELECT award_id FROM award WHERE award_name = %s), player_id, {expr}
                    FROM mv_player_season_stats
                    ORDER BY season_year, {expr} DESC""",  # expr is a fixed column name from the list above
                (award,),
            )
        # Demo draft board for the 2027 auction.
        cur.execute(
            """INSERT INTO draft_board (name, franchise_id, target_season, purse_cr, max_squad, max_overseas, overseas_cap_cr)
               SELECT '2027 Auction Plan', f.franchise_id, s.season_year, s.purse_cr, s.max_squad, s.max_overseas, s.overseas_cap_cr
               FROM franchise f, season s WHERE f.short_code = %s AND s.season_year = 2027""",
            (board_franchise,),
        )
    conn.commit()
    run_sql_file(conn, DB_DIR / "indexes.sql")
    conn.commit()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("ANALYZE")
    conn.autocommit = False


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=str(DATA_DIR / "raw" / "ipl_json"))
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL", "postgresql://localhost/ipl"))
    ap.add_argument("--reset", action="store_true", help="drop and recreate all tables first")
    ap.add_argument("--board-franchise", default=os.environ.get("BOARD_FRANCHISE", "RCB"),
                    help="short code of the franchise the demo draft board belongs to")
    args = ap.parse_args()

    files = match_files(Path(args.data_dir))
    t0 = time.time()
    with psycopg.connect(args.database_url) as conn:
        if args.reset:
            print("Building schema and reference data")
            seed_reference(conn)
            run_sql_file(conn, DB_DIR / "views.sql")
            conn.commit()
        print(f"Loading players from {len(files)} match files")
        pid = load_players(conn, files)
        with conn.cursor() as cur:
            cur.execute("SELECT name, franchise_id FROM franchise_name")
            fid = dict(cur.fetchall())
            cur.execute("SELECT alias, venue_id FROM venue_alias")
            vid = dict(cur.fetchall())
            cur.execute("SELECT match_id FROM match")
            done = {r[0] for r in cur.fetchall()}
        conn.commit()  # end the read transaction so each match below gets its OWN transaction

        print("Loading matches (one transaction per match)")
        balls = loaded = 0
        for path in files:
            match_id = int(path.stem)
            if match_id in done:
                continue
            doc = json.loads(path.read_text())
            try:
                with conn.transaction():
                    balls += load_match(conn, doc, match_id, pid, fid, vid)
                loaded += 1
            except Exception as exc:  # the transaction is already rolled back here
                print(f"  ! match {match_id} skipped: {exc}")
            if loaded and loaded % 200 == 0:
                print(f"  {loaded} matches ...")
        conn.commit()
        print(f"  loaded {loaded} matches, {balls} deliveries")
        print("Deriving contracts, champions, roles, awards; refreshing views; indexing")
        derive_after_load(conn, args.board_franchise)
    print(f"Done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
