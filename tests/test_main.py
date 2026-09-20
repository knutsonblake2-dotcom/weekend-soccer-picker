"""Sanity tests for the email-building logic in src/main.py - no network
needed, everything here is constructed in-memory.

Run with:  python -m tests.test_main
"""
from __future__ import annotations

from datetime import datetime, timezone

from src import config, main
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


def test_all_four_competitions_are_configured():
    # This is really a config sanity check: every competition listed in
    # config.COMPETITIONS needs an entry in every one of these dicts, or
    # main.py will KeyError at runtime.
    from src.pick_best_game import COMPETITION_LABELS

    for comp in config.COMPETITIONS:
        assert comp in config.LIVESOCCERTV_COMPETITION_IDS, comp
        assert comp in config.FOOTBALL_DATA_CODES, comp
        assert comp in config.BROADCASTERS, comp
        assert comp in COMPETITION_LABELS, comp
    assert "serie_a" in config.COMPETITIONS
    assert "bundesliga" in config.COMPETITIONS
    assert config.BROADCASTERS["serie_a"] == "Paramount+"
    assert config.BROADCASTERS["bundesliga"] == "Fandango"
    print("test_all_four_competitions_are_configured: OK")


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


def test_build_email_text_includes_secondary_picks_for_all_competitions():
    scored = [
        _scored("champions_league", "CL Top", 0.9),
        _scored("champions_league", "CL Second", 0.6),
        _scored("premier_league", "PL Top", 0.8),
        _scored("premier_league", "PL Second", 0.5),
        _scored("serie_a", "SA Top", 0.85),
        _scored("serie_a", "SA Second", 0.55),
        _scored("bundesliga", "BL Top", 0.75),
        _scored("bundesliga", "BL Second", 0.45),
    ]
    replays = {
        "champions_league": [
            ReplayPick(match=_match("champions_league", "CL Replay Top"), picked_by="llm"),
            ReplayPick(match=_match("champions_league", "CL Replay Second"), picked_by="llm"),
        ],
        "premier_league": [
            ReplayPick(match=_match("premier_league", "PL Replay Top"), picked_by="heuristic"),
            ReplayPick(match=_match("premier_league", "PL Replay Second"), picked_by="heuristic"),
        ],
        "serie_a": [
            ReplayPick(match=_match("serie_a", "SA Replay Top"), picked_by="llm"),
            ReplayPick(match=_match("serie_a", "SA Replay Second"), picked_by="llm"),
        ],
        "bundesliga": [
            ReplayPick(match=_match("bundesliga", "BL Replay Top"), picked_by="heuristic"),
            ReplayPick(match=_match("bundesliga", "BL Replay Second"), picked_by="heuristic"),
        ],
    }

    subject, body = main.build_email_text(scored, replays)

    assert "CL Top" in subject
    for teams in [
        "CL Top", "CL Second", "PL Top", "PL Second", "SA Top", "SA Second",
        "BL Top", "BL Second",
        "CL Replay Top", "CL Replay Second", "PL Replay Top", "PL Replay Second",
        "SA Replay Top", "SA Replay Second", "BL Replay Top", "BL Replay Second",
    ]:
        assert teams in body, f"missing {teams} in body"
    assert body.count("Also good:") == 8  # one secondary per category, 8 categories
    print("test_build_email_text_includes_secondary_picks_for_all_competitions: OK")


def test_build_email_html_renders_all_picks_and_handles_empty_categories():
    scored = [_scored("champions_league", "Only CL Game", 0.9)]
    html = main.build_email_html(scored, replays={})

    assert "<!DOCTYPE html>" in html
    assert "Only CL Game" in html
    assert "No ranked game in the next" in html  # other competitions' upcoming, empty
    assert "No standout game found in the last" in html  # all replay sections, empty
    print("test_build_email_html_renders_all_picks_and_handles_empty_categories: OK")


def test_build_email_text_handles_totally_empty_week():
    subject, body = main.build_email_text([], {})
    assert "no " in subject.lower() and "games found" in subject
    assert "no ranked game in the next" in body
    assert "no standout game found in the last" in body
    print("test_build_email_text_handles_totally_empty_week: OK")


if __name__ == "__main__":
    test_all_four_competitions_are_configured()
    test_upcoming_picks_are_symmetric_top_two_per_competition()
    test_upcoming_picks_excludes_unranked()
    test_build_email_text_includes_secondary_picks_for_all_competitions()
    test_build_email_html_renders_all_picks_and_handles_empty_categories()
    test_build_email_text_handles_totally_empty_week()
    print("All tests passed.")
