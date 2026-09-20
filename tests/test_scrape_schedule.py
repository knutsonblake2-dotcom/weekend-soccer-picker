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
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch

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


def test_finished_matches_score_extraction_and_ft_filter():
    rows = _rows_from_fixture("fixture_finished_matches.html")
    ucl_rows = [r for r in rows if r.get("data-cid") == "50"]
    assert len(ucl_rows) == 3  # includes the postponed row

    ft_rows = [r for r in ucl_rows if r.get("data-timer") == "FT"]
    assert len(ft_rows) == 2, "the postponed row must not count as FT"

    scores = {s._extract_teams(r): s._extract_score(r) for r in ft_rows}
    assert scores["Barcelona vs Feyenoord"] == "5 - 1"
    assert scores["PSG vs Slovan Bratislava"] == "6 - 1"

    postponed = [r for r in ucl_rows if r.get("data-timer") == "Postp."][0]
    assert s._extract_score(postponed) is None

    print("test_finished_matches_score_extraction_and_ft_filter: OK")


def test_fetch_html_is_cached_per_day_across_competitions():
    # Every tracked competition asks _fetch_html for the same day - this
    # verifies that only results in ONE actual HTTP request, not one per
    # competition (this is what fixed the 429 rate-limiting once a fourth
    # competition was added - see the comment above _fetch_html).
    s._fetch_html.cache_clear()
    fake_day = date(2099, 1, 1)  # a date nothing else in the suite touches
    fake_response = Mock()
    fake_response.status_code = 200
    fake_response.text = "<html>fake schedule page</html>"
    fake_response.raise_for_status = Mock()

    with patch.object(s, "_throttle") as mock_throttle, patch(
        "src.scrape_schedule.requests.get", return_value=fake_response
    ) as mock_get:
        first = s._fetch_html(fake_day)
        second = s._fetch_html(fake_day)
        third = s._fetch_html(fake_day)

    assert first == second == third == "<html>fake schedule page</html>"
    assert mock_get.call_count == 1, "expected exactly one HTTP request for a cached day"
    assert mock_throttle.call_count == 1, "throttle should only run on the actual (uncached) fetch"
    s._fetch_html.cache_clear()
    print("test_fetch_html_is_cached_per_day_across_competitions: OK")


def test_fetch_html_retries_once_on_429_then_succeeds():
    s._fetch_html.cache_clear()
    fake_day = date(2099, 1, 2)
    rate_limited = Mock()
    rate_limited.status_code = 429
    ok_response = Mock()
    ok_response.status_code = 200
    ok_response.text = "<html>ok after retry</html>"
    ok_response.raise_for_status = Mock()

    with patch.object(s, "_throttle"), patch(
        "src.scrape_schedule.requests.get", side_effect=[rate_limited, ok_response]
    ) as mock_get, patch("src.scrape_schedule.time.sleep") as mock_sleep:
        result = s._fetch_html(fake_day)

    assert result == "<html>ok after retry</html>"
    assert mock_get.call_count == 2, "expected a retry after the 429"
    assert mock_sleep.called, "expected a backoff pause before retrying"
    s._fetch_html.cache_clear()
    print("test_fetch_html_retries_once_on_429_then_succeeds: OK")


if __name__ == "__main__":
    test_real_premier_league_fixture()
    test_synthetic_champions_league_fixture()
    test_finished_matches_score_extraction_and_ft_filter()
    test_fetch_html_is_cached_per_day_across_competitions()
    test_fetch_html_retries_once_on_429_then_succeeds()
    print("All tests passed.")
