"""Sanity tests for the replay-pick heuristic and team-name matching - no
network needed.

Run with:  python -m tests.test_replay_pick
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from src import replay_pick
from src.replay_pick import (
    _build_result_lookup,
    _find_result,
    _heuristic_pick,
    _heuristic_score,
    get_best_replays,
)
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


def test_heuristic_pick_returns_top_n_ranked_best_first():
    candidates = [
        {"_score": 5.0},
        {"_score": 9.0},
        {"_score": 1.0},
        {"_score": 7.0},
    ]
    assert _heuristic_pick(candidates, 2) == [1, 3]  # indices of the two highest scores
    print("test_heuristic_pick_returns_top_n_ranked_best_first: OK")


def test_get_best_replays_skips_llm_when_no_finished_games():
    # A Champions League break: no finished games in the lookback window at
    # all. This must return immediately without ever calling the LLM -
    # Blake cares about not spending API credits on a quiet week.
    with patch.object(replay_pick, "get_recent_matches", return_value=[]), patch.object(
        replay_pick, "_llm_pick"
    ) as mock_llm:
        picks = get_best_replays("champions_league", n=2)
        assert picks == []
        assert mock_llm.call_count == 0
    print("test_get_best_replays_skips_llm_when_no_finished_games: OK")


def test_get_best_replays_skips_llm_when_no_matched_results():
    # Games finished, but none of them could be matched to a scored result
    # (e.g. the results API hasn't caught up yet) - still no LLM call.
    finished_match = Match(
        competition="champions_league",
        teams="Some Team vs Other Team",
        kickoff_utc=datetime.now(timezone.utc),
        match_url="",
        finished=True,
        score="1 - 1",
    )
    with patch.object(
        replay_pick, "get_recent_matches", return_value=[finished_match]
    ), patch.object(
        replay_pick.standings_mod, "get_recent_results", return_value=[]
    ), patch.object(
        replay_pick.standings_mod, "get_standings", return_value=[]
    ), patch.object(
        replay_pick, "_llm_pick"
    ) as mock_llm:
        picks = get_best_replays("champions_league", n=2)
        assert picks == []
        assert mock_llm.call_count == 0
    print("test_get_best_replays_skips_llm_when_no_matched_results: OK")


def test_get_best_replays_skips_llm_with_only_one_candidate():
    # Exactly one scoreable game - nothing to rank, so this should be
    # returned directly without spending a call to find out there's only
    # one answer.
    finished_match = Match(
        competition="champions_league",
        teams="Arsenal vs Chelsea",
        kickoff_utc=datetime.now(timezone.utc),
        match_url="",
        finished=True,
        score="3 - 3",
    )
    result = MatchResult("Arsenal FC", "Chelsea FC", 3, 3, 1, 2, matchday=5)
    with patch.object(
        replay_pick, "get_recent_matches", return_value=[finished_match]
    ), patch.object(
        replay_pick.standings_mod, "get_recent_results", return_value=[result]
    ), patch.object(
        replay_pick.standings_mod, "get_standings", return_value=[]
    ), patch.object(
        replay_pick, "_llm_pick"
    ) as mock_llm:
        picks = get_best_replays("champions_league", n=2)
        assert len(picks) == 1
        assert picks[0].picked_by == "only-option"
        assert mock_llm.call_count == 0
    print("test_get_best_replays_skips_llm_with_only_one_candidate: OK")


if __name__ == "__main__":
    test_find_result_matches_by_team_names()
    test_heuristic_favors_comeback_over_one_sided_win()
    test_heuristic_rewards_upset()
    test_heuristic_pick_returns_top_n_ranked_best_first()
    test_get_best_replays_skips_llm_when_no_finished_games()
    test_get_best_replays_skips_llm_when_no_matched_results()
    test_get_best_replays_skips_llm_with_only_one_candidate()
    print("All tests passed.")
