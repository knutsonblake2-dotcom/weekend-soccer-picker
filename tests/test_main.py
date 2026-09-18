"""Sanity tests for the email-building logic in src/main.py - no network
needed, everything here is constructed in-memory.

Run with:  python -m tests.test_main
"""
from __future__ import annotations

from datetime import datetime, timezone

from src import main
from src.pick_best_game import ScoredMatch
from src.replay_pick import ReplayPick
from src.scrape_schedule import Match
from src.standings import TeamStanding


def _match(competition: str, teams: str, url: str = "https://example.com/m") -> Match:
    return Match(
        competition=competition,
        teams=teams,
        kickoff_utc=datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc),
        match_url=url,
        finished=False,
    )


def _scored(competition: str, teams: str, score: float | None) -> ScoredMatch:
    standing = TeamStanding("A", 1, 30, 10)
    return ScoredMatch(
        match=_match(competition, teams),
        score=score,
        blurb="A blurb.",
        home_standing=standing if score is not None else None,
        away_standing=standing if score is not None else None,
    )


def test_upcoming_picks_are_symmetric_top_two_per_competition():
    scored = [
        _scored("champions_league", "CL Game 1", 0.9),
        _scored("champions_league", "CL Game 2", 0.7),
        _scored("champions_league", "CL Game 3", 0.5),
        _scored("premier_league", "PL Game 1", 0.8),
    ]
    cl_picks = main._upcoming_picks(scored, "champions_league")
    pl_picks = main._upcoming_picks(scored, "premier_league")

    assert [sm.match.teams for sm in cl_picks] == ["CL Game 1", "CL Game 2"]
    assert [sm.match.teams for sm in pl_picks] == ["PL Game 1"]
    print("test_upcoming_picks_are_symmetric_top_two_per_competition: OK")


def test_upcoming_picks_excludes_unranked():
    scored = [_scored("champions_league", "Unranked Game", None)]
    cl_picks = main._upcoming_picks(scored, "champions_league")
    assert cl_picks == []
    print("test_upcoming_picks_excludes_unranked: OK")


def test_build_email_text_includes_secondary_picks_for_all_four_categories():
    scored = [
        _scored("champions_league", "CL Top", 0.9),
        _scored("champions_league", "CL Second", 0.6),
        _scored("premier_league", "PL Top", 0.8),
        _scored("premier_league", "PL Second", 0.5),
    ]
    cl_replays = [
        ReplayPick(match=_match("champions_league", "CL Replay Top"), picked_by="llm"),
        ReplayPick(match=_match("champions_league", "CL Replay Second"), picked_by="llm"),
    ]
    pl_replays = [
        ReplayPick(match=_match("premier_league", "PL Replay Top"), picked_by="heuristic"),
        ReplayPick(match=_match("premier_league", "PL Replay Second"), picked_by="heuristic"),
    ]

    subject, body = main.build_email_text(scored, cl_replays, pl_replays)

    assert "CL Top" in subject
    for teams in [
        "CL Top", "CL Second", "PL Top", "PL Second",
        "CL Replay Top", "CL Replay Second", "PL Replay Top", "PL Replay Second",
    ]:
        assert teams in body, f"missing {teams} in body"
    assert body.count("Also good:") == 4  # one secondary per category
    print("test_build_email_text_includes_secondary_picks_for_all_four_categories: OK")


def test_build_email_html_renders_all_picks_and_handles_empty_categories():
    scored = [_scored("champions_league", "Only CL Game", 0.9)]
    html = main.build_email_html(scored, cl_replays=[], pl_replays=[])

    assert "<!DOCTYPE html>" in html
    assert "Only CL Game" in html
    assert "No ranked game in the next" in html  # Premier League upcoming, empty
    assert "No standout game found in the last" in html  # both replay sections, empty
    print("test_build_email_html_renders_all_picks_and_handles_empty_categories: OK")


def test_build_email_text_handles_totally_empty_week():
    subject, body = main.build_email_text([], [], [])
    assert "no Champions League or Premier League games" in subject
    assert "no ranked game in the next" in body
    assert "no standout game found in the last" in body
    print("test_build_email_text_handles_totally_empty_week: OK")


if __name__ == "__main__":
    test_upcoming_picks_are_symmetric_top_two_per_competition()
    test_upcoming_picks_excludes_unranked()
    test_build_email_text_includes_secondary_picks_for_all_four_categories()
    test_build_email_html_renders_all_picks_and_handles_empty_categories()
    test_build_email_text_handles_totally_empty_week()
    print("All tests passed.")
