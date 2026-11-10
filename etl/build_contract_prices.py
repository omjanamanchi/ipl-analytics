"""
Match the 2026 squad/salary list (data/sources/ipl_2026_squads.csv, compiled from
Wikipedia's "List of 2026 Indian Premier League personnel changes") to Cricsheet
player ids and write data/contracts_prices.csv, which the loader applies.

    python -m etl.build_contract_prices      # needs a loaded database

Matching: prefer players who actually appeared for that franchise in 2026, then
anyone from 2024-2026, scoring by surname + name similarity. Players with no IPL
appearance yet (no Cricsheet id) are listed as unmatched - they have no stats to scout.
"""
import csv
import difflib
import os
import re
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "sources" / "ipl_2026_squads.csv"
OUT = ROOT / "data" / "contracts_prices.csv"
# Names the automatic matcher gets wrong or cannot see (squad name -> Cricsheet name).
OVERRIDES = {
    "T. Natarajan": "T Natarajan",
    "Allah Ghazanfar": "AM Ghazanfar",
    "Vaibhav Sooryavanshi": "V Suryavanshi",
    "Smaran Ravichandran": "R Smaran",
    "Sai Kishore": "R Sai Kishore",
    "Manimaran Siddharth": "M Siddharth",
    "Prasidh Krishna": "M Prasidh Krishna",
    "Vijaykumar Vyshak": "Vijaykumar Vyshak",
    "Varun Chakravarthy": "CV Varun",
    "Ramakrishna Ghosh": "RS Ghosh",
    "Ishant Sharma": "I Sharma",
    "Jayant Yadav": "J Yadav",
    "Yudhvir Singh": "Yudhvir Singh",
    "Swapnil Singh": "Swapnil Singh",
    "Aman Khan": "Aman Hakim Khan",
    "Prithvi Raj": "Y Prithvi Raj",
    "Shivam Mavi": "Shivam Mavi",
    "Gurnoor Brar": "Gurnoor Brar",
    "Prashant Solanki": "PH Solanki",
    "Tom Banton": "T Banton",
    # No IPL appearance yet - must NOT be matched to a namesake.
    "Tejasvi Singh": None,
    "Naman Tiwari": None,
    "Mangesh Yadav": None,
    "Amit Kumar": None,
}


def norm(s: str) -> str:
    return re.sub(r"[^a-z ]", "", s.lower().replace("-", " ")).strip()


def score(squad_name: str, cand: tuple) -> float:
    _, cs_name, full = cand
    sq = norm(squad_name).split()
    surname = sq[-1]
    names = [norm(cs_name), norm(full or "")]
    tokens = set(" ".join(names).split())
    sur = max(difflib.SequenceMatcher(None, surname, t).ratio() for t in tokens) if tokens else 0
    whole = max(difflib.SequenceMatcher(None, " ".join(sq), n).ratio() for n in names if n)
    first_ok = any(t.startswith(sq[0][0]) for t in tokens) or norm(cs_name).startswith(sq[0][0])
    return sur * 0.6 + whole * 0.4 + (0.1 if first_ok else 0)


def main() -> None:
    url = os.environ.get("DATABASE_URL", "postgresql://localhost/ipl")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT name, f.short_code FROM franchise_name n JOIN franchise f USING (franchise_id)")
        code = dict(cur.fetchall())
        cur.execute("""SELECT DISTINCT p.player_id, p.cricsheet_name, p.full_name, f.short_code, m.season_year,
                              p.cricsheet_id
                       FROM match_player mp JOIN match m USING (match_id)
                       JOIN player p USING (player_id) JOIN franchise f ON f.franchise_id = mp.franchise_id
                       WHERE m.season_year >= 2024""")
        rows = cur.fetchall()
        cur.execute("SELECT cricsheet_name, cricsheet_id FROM player")
        by_cs_name = dict(cur.fetchall())

    ids = {r[0]: r[5] for r in rows}
    out, unmatched, used = [], [], {}
    for r in csv.DictReader(open(SRC, newline="", encoding="utf-8")):
        team = code[r["team"]]
        if r["player"] in OVERRIDES:
            cid = by_cs_name.get(OVERRIDES[r["player"]]) if OVERRIDES[r["player"]] else None
            best = (1.0, cid) if cid else (0, None)
        else:
            pools = [
                {(x[0], x[1], x[2]) for x in rows if x[3] == team and x[4] == 2026},
                {(x[0], x[1], x[2]) for x in rows},
            ]
            best = (0, None)
            for pool in pools:
                if pool:
                    s, cand = max((score(r["player"], c), c) for c in pool)
                    if s >= 0.85:
                        best = (s, ids[cand[0]])
                        break
        if best[1] and best[1] in used:
            raise SystemExit(f"{r['player']} matched an id already used by {used[best[1]]} - add an OVERRIDE")
        if best[1]:
            used[best[1]] = r["player"]
            out.append({"cricsheet_id": best[1], "season_year": 2026, "franchise_code": team,
                        "price_cr": r["price_cr"], "acquisition": r["acquisition"], "source_name": r["player"]})
        else:
            unmatched.append(r["player"])

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print(f"matched {len(out)}, unmatched {len(unmatched)} (no IPL appearance yet): {', '.join(unmatched)}")


if __name__ == "__main__":
    main()
