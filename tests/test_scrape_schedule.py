"""Sanity tests for the HTML-parsing logic in src/scrape_schedule.py,
run against saved fixture HTML rather than the live site (see
fixture_2026-09-19.html, captured from the real site, and
fixture_synthetic_ucl.html, hand-built for cases that weren't available
live when this was written - both files explain their provenance at the
top).

Run with:  python -m tests.test_scrape_schedule
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from src import scrape_schedule as s

FIXTURES_DIR = os.path.dirname(__file__)


def _rows_from_fixture(filename: str):
    path = os.path.join(FIXTURES_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    return soup.select("tr.matchrow")


def test_real_premier_league_fixture():
    rows = _rows_from_fixture("fixture_2026-09-19.html")
    pl_rows = [r for r in rows if r.get("data-cid") == "6"]
    assert len(pl_rows) == 4, f"expected 4 PL rows, got {len(pl_rows)}"

    for row in pl_rows:
        assert s._row_has_broadcaster(row, "Peacock"), "expected Peacock in channel list"
        teams = s._extract_teams(row)
        assert teams and " vs " in teams
        kickoff = s._parse_kickoff(row)
        assert kickoff is not None
        assert kickoff.tzinfo is not None

    mls_rows = [r for r in rows if r.get("data-cid") == "43"]
    assert len(mls_rows) == 1
    for row in mls_rows:
        assert not s._row_has_broadcaster(row, "Peacock")

    print("test_real_premier_league_fixture: OK")


def test_synthetic_champions_league_fixture():
    rows = _rows_from_fixture("fixture_synthetic_ucl.html")
    ucl_rows = [r for r in rows if r.get("data-cid") == "50"]
    assert len(ucl_rows) == 1
    row = ucl_rows[0]
    assert s._row_has_broadcaster(row, "Paramount+")
    teams = s._extract_teams(row)
    assert teams == "Real Madrid vs Juventus", teams
    kickoff = s._parse_kickoff(row)
    assert kickoff == datetime.fromtimestamp(1760385600000 / 1000, tz=timezone.utc)
    url = s._extract_match_url(row)
    assert url == "https://www.livesoccertv.com/match/real-madrid-vs-juventus/synthetic1#9000001"

    pl_rows = [r for r in rows if r.get("data-cid") == "6"]
    assert len(pl_rows) == 1
    assert not s._row_has_broadcaster(pl_rows[0], "Peacock"), "Chelsea vs Fulham has no Peacock and must be excluded"

    print("test_synthetic_champions_league_fixture: OK")


if __name__ == "__main__":
    test_real_premier_league_fixture()
    test_synthetic_champions_league_fixture()
    print("All tests passed.")
