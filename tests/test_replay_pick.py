"""Sanity tests for the replay-pick heuristic and team-name matching - no
network needed.

Run with:  python -m tests.test_replay_pick
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.replay_pick import _build_result_lookup, _find_result, _heuristic_score
from src.scrape_schedule import Match
from src.standings import MatchResult, TeamStanding


def test_find_result_matches_by_team_names():
    results = [
        MatchResult("Arsenal FC", "Chelsea FC", 3, 3, 1, 2, matchday=5),
        MatchResult("Liverpool FC", "Everton FC", 1, 0, 0, 0, matchday=5),
    ]
    lookup = _build_result_lookup(results)

    m = Match(
        competition="premier_league",
        teams="Arsenal vs Chelsea",
        kickoff_utc=datetime.now(timezone.utc),
        match_url="",
        finished=True,
        score="3 - 3",
    )
    found = _find_result(m, lookup)
    assert found is not None
    assert found.home_name == "Arsenal FC"
    print("test_find_result_matches_by_team_names: OK")


def test_heuristic_favors_comeback_over_one_sided_win():
    # 3-3 draw where the home team clawed back from 2-0 down at half:
    # a big swing (should score high).
    comeback = MatchResult("Arsenal FC", "Chelsea FC", 3, 3, 0, 2, matchday=5)
    # 3-0 win, all in the first half, nothing changes after (no swing).
    one_sided = MatchResult("Man City", "Sheffield United", 3, 0, 3, 0, matchday=5)

    top = TeamStanding("Arsenal FC", 1, 30, 12)
    bottom = TeamStanding("Chelsea FC", 15, 12, 12)

    comeback_score = _heuristic_score(comeback, top, bottom)
    one_sided_score = _heuristic_score(one_sided, top, bottom)

    assert comeback_score > one_sided_score, (comeback_score, one_sided_score)
    print("test_heuristic_favors_comeback_over_one_sided_win: OK")


def test_heuristic_rewards_upset():
    upset = MatchResult("Bottom FC", "Top FC", 2, 1, 1, 1, matchday=5)
    bottom_standing = TeamStanding("Bottom FC", 19, 8, 12)
    top_standing = TeamStanding("Top FC", 1, 32, 12)

    upset_score = _heuristic_score(upset, bottom_standing, top_standing)

    expected_win = MatchResult("Top FC", "Bottom FC", 2, 1, 1, 1, matchday=5)
    expected_score = _heuristic_score(expected_win, top_standing, bottom_standing)

    assert upset_score > expected_score, (upset_score, expected_score)
    print("test_heuristic_rewards_upset: OK")


if __name__ == "__main__":
    test_find_result_matches_by_team_names()
    test_heuristic_favors_comeback_over_one_sided_win()
    test_heuristic_rewards_upset()
    print("All tests passed.")
