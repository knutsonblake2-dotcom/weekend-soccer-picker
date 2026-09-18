"""Picks the best "replay" (most worth rewatching) Champions League and
Premier League game from the past week.

Unlike the forward-looking picks in pick_best_game.py (which only have
table position to go on), a finished game has an actual result - so this
tries to capture "the vibe": comebacks, late drama, goal tallies, and
upsets against the table. When an Anthropic API key is configured, an LLM
does that judgment call directly (it's the kind of narrative reasoning a
fixed formula does badly); otherwise it falls back to a simple stats-only
heuristic so the tool still works without that key.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional

from . import config
from . import standings as standings_mod
from . import team_aliases
from .pick_best_game import COMPETITION_LABELS
from .scrape_schedule import Match, get_recent_matches
from .standings import MatchResult

logger = logging.getLogger(__name__)


@dataclass
class ReplayPick:
    match: Match
    picked_by: str  # "llm" or "heuristic", for logging only


def _split_teams(teams: str) -> tuple[str, str]:
    for sep in (" vs ", " v "):
        if sep in teams:
            home, _, away = teams.partition(sep)
            return home.strip(), away.strip()
    return teams, ""


def _build_result_lookup(
    results: List[MatchResult],
) -> Dict[FrozenSet[str], MatchResult]:
    lookup = {}
    for r in results:
        key = frozenset(
            {team_aliases.normalize(r.home_name), team_aliases.normalize(r.away_name)}
        )
        lookup[key] = r
    return lookup


def _find_result(
    match: Match, result_lookup: Dict[FrozenSet[str], MatchResult]
) -> Optional[MatchResult]:
    home, away = _split_teams(match.teams)
    key = frozenset({team_aliases.normalize(home), team_aliases.normalize(away)})
    if key in result_lookup:
        return result_lookup[key]
    # Fuzzy fallback: at least one team name matches exactly after
    # normalization. Small risk of mismatching if a team played twice in
    # the lookback window, but that's rare enough for a hobby project.
    for cand_key, result in result_lookup.items():
        if key & cand_key:
            return result
    return None


def _heuristic_score(
    result: MatchResult, home_standing, away_standing
) -> float:
    total_goals = result.home_ft + result.away_ft

    swing = 0
    if result.home_ht is not None and result.away_ht is not None:
        ht_diff = result.home_ht - result.away_ht
        ft_diff = result.home_ft - result.away_ft
        swing = abs(ft_diff - ht_diff)  # how much the game turned after half-time

    upset = 0.0
    if home_standing and away_standing:
        gap = abs(home_standing.position - away_standing.position)
        home_won = result.home_ft > result.away_ft
        away_won = result.away_ft > result.home_ft
        underdog_won = (home_won and home_standing.position > away_standing.position) or (
            away_won and away_standing.position > home_standing.position
        )
        if underdog_won:
            upset = gap * 0.5

    return total_goals * 1.0 + swing * 1.5 + upset


def _heuristic_pick(candidates: List[dict]) -> Optional[int]:
    if not candidates:
        return None
    best_idx = max(range(len(candidates)), key=lambda i: candidates[i]["_score"])
    return best_idx


def _llm_pick(candidates: List[dict], competition_label: str) -> Optional[int]:
    if not config.ANTHROPIC_API_KEY or not candidates:
        return None
    try:
        import anthropic
    except ImportError:
        logger.warning(
            "anthropic package not installed - falling back to heuristic replay pick."
        )
        return None

    listing = [
        {
            "index": i,
            "matchup": f"{c['home']} {c['home_ft']}-{c['away_ft']} {c['away']}",
            "halftime_score": c["halftime"],
            "home_table_position": c["home_position"],
            "away_table_position": c["away_position"],
        }
        for i, c in enumerate(candidates)
    ]

    prompt = (
        f"Here are last week's finished {competition_label} matches, as JSON. "
        "Pick the SINGLE most exciting one to recommend as a replay - weigh "
        "comebacks and late drama (compare halftime_score to the final "
        "score in matchup), total goals, upsets against the table "
        "positions, and rivalry/stakes implied by those positions. "
        'Respond with ONLY compact JSON of the form {"pick_index": <int>} '
        "and nothing else - no explanation, no markdown.\n\n"
        f"{json.dumps(listing)}"
    )

    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(getattr(block, "text", "") for block in resp.content)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            logger.warning("LLM replay pick returned no JSON: %r", text)
            return None
        data = json.loads(match.group(0))
        idx = data.get("pick_index")
        if isinstance(idx, int) and 0 <= idx < len(candidates):
            return idx
        logger.warning("LLM replay pick returned out-of-range index: %r", idx)
    except Exception as exc:  # the anthropic client can raise several error types
        logger.warning("LLM replay pick failed, falling back to heuristic: %s", exc)
    return None


def get_best_replay(competition: str) -> Optional[ReplayPick]:
    """Returns the best replay pick for `competition`, or None if there's
    nothing to recommend (no finished games in the lookback window, or no
    result data to score them with).
    """
    finished = [m for m in get_recent_matches(competition) if m.finished]
    if not finished:
        return None

    result_lookup = _build_result_lookup(standings_mod.get_recent_results(competition))

    table = standings_mod.get_standings(competition)
    standing_lookup = standings_mod.build_lookup(table) if table else {}

    candidates: List[dict] = []
    candidate_matches: List[Match] = []
    for m in finished:
        result = _find_result(m, result_lookup)
        if not result:
            continue  # no result data to score this one - skip rather than guess
        home, away = _split_teams(m.teams)
        home_standing = (
            team_aliases.find_standing(home, standing_lookup) if standing_lookup else None
        )
        away_standing = (
            team_aliases.find_standing(away, standing_lookup) if standing_lookup else None
        )
        candidates.append(
            {
                "home": result.home_name,
                "away": result.away_name,
                "home_ft": result.home_ft,
                "away_ft": result.away_ft,
                "halftime": (
                    f"{result.home_ht}-{result.away_ht}"
                    if result.home_ht is not None and result.away_ht is not None
                    else "unknown"
                ),
                "home_position": home_standing.position if home_standing else None,
                "away_position": away_standing.position if away_standing else None,
                "_score": _heuristic_score(result, home_standing, away_standing),
            }
        )
        candidate_matches.append(m)

    if not candidates:
        return None

    label = COMPETITION_LABELS[competition]
    idx = _llm_pick(candidates, label)
    picked_by = "llm"
    if idx is None:
        idx = _heuristic_pick(candidates)
        picked_by = "heuristic"
    if idx is None:
        return None

    return ReplayPick(match=candidate_matches[idx], picked_by=picked_by)
