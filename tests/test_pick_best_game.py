"""Sanity tests for team name matching and match scoring - no network
needed, everything here is constructed in-memory.

Run with:  python -m tests.test_pick_best_game
"""
from __future__ import annotations

from datetime import datetime, timezone

from src import team_aliases
from src.pick_best_game import score_match
from src.scrape_schedule import Match
from src.standings import TeamStanding


def test_team_alias_matching():
    lookup = {
        team_aliases.normalize("Manchester United FC"): TeamStanding(
            "Manchester United FC", 8, 20, 10
        ),
        team_aliases.normalize("Tottenham Hotspur FC"): TeamStanding(
            "Tottenham Hotspur FC", 3, 24, 10
        ),
    }
    assert team_aliases.find_standing("Man Utd", lookup) is not None
    assert team_aliases.find_standing("Spurs", lookup) is not None
    assert team_aliases.find_standing("Some Random FC", lookup) is None
    print("test_team_alias_matching: OK")


def test_score_match_close_top_teams_beats_mismatch():
    lookup = {
        team_aliases.normalize("Arsenal FC"): TeamStanding("Arsenal FC", 1, 30, 12),
        team_aliases.normalize("Manchester City FC"): TeamStanding(
            "Manchester City FC", 2, 29, 12
        ),
        team_aliases.normalize("Sunderland AFC"): TeamStanding(
            "Sunderland AFC", 19, 8, 12
        ),
    }
    # pad lookup to a realistic table size so quality/closeness aren't
    # distorted by a tiny denominator
    for i, name in enumerate(
        ["Team%d FC" % i for i in range(3, 18)], start=3
    ):
        lookup[team_aliases.normalize(name)] = TeamStanding(name, i, 40 - i, 12)

    close_top_match = Match(
        competition="premier_league",
        teams="Arsenal vs Manchester City",
        kickoff_utc=datetime.now(timezone.utc),
        match_url="",
    )
    mismatch = Match(
        competition="premier_league",
        teams="Arsenal vs Sunderland",
        kickoff_utc=datetime.now(timezone.utc),
        match_url="",
    )

    scored_top = score_match(close_top_match, lookup)
    scored_mismatch = score_match(mismatch, lookup)

    assert scored_top.score is not None and scored_mismatch.score is not None
    assert scored_top.score > scored_mismatch.score, (
        scored_top.score,
        scored_mismatch.score,
    )
    print("test_score_match_close_top_teams_beats_mismatch: OK")


def test_score_match_missing_standings_is_unranked():
    unknown_match = Match(
        competition="premier_league",
        teams="Totally Unknown FC vs Another Mystery FC",
        kickoff_utc=datetime.now(timezone.utc),
        match_url="",
    )
    scored = score_match(unknown_match, {})
    assert scored.score is None
    print("test_score_match_missing_standings_is_unranked: OK")


if __name__ == "__main__":
    test_team_alias_matching()
    test_score_match_close_top_teams_beats_mismatch()
    test_score_match_missing_standings_is_unranked()
    print("All tests passed.")
