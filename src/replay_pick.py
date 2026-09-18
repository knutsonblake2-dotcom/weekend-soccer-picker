"""Picks the best "replay" games (top pick + a runner-up) - the ones most
worth rewatching - from the past week, for both Champions League and
Premier League.

Unlike the forward-looking picks in pick_best_game.py (which only have
table position to go on), a finished game has an actual result - so this
tries to capture "the vibe": comebacks, late drama, goal tallies, and
upsets against the table. When an Anthropic API key is configured, an LLM
does that judgment call directly (it's the kind of narrative reasoning a
fixed formula does badly); otherwise it falls back to a simple stats-only
heuristic so the tool still works without that key.

Cost-consciousness: the LLM is only ever called when there are at least
two real candidates to choose between - see the early-outs in
get_best_replays() below. A quiet week (e.g. an international break, or a
gap between Champions League matchdays) costs nothing, not even a
skipped-but-billed call.
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
    picked_by: str  # "llm", "heuristic", or "only-option" - for logging only


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


def _heuristic_pick(candidates: List[dict], n: int) -> List[int]:
    order = sorted(range(len(candidates)), key=lambda i: -candidates[i]["_score"])
    return order[:n]


def _llm_pick(candidates: List[dict], competition_label: str, n: int) -> Optional[List[int]]:
    """Asks Claude to rank the top `n` candidates, best first. Returns None
    (never a partial/best-effort list) on any failure, so the caller falls
    back to the heuristic rather than trusting a malformed response.
    """
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
        f"Rank the top {n} most exciting ones to recommend as replays, best "
        "first - weigh comebacks and late drama (compare halftime_score to "
        "the final score in matchup), total goals, upsets against the "
        "table positions, and rivalry/stakes implied by those positions. "
        'Respond with ONLY compact JSON of the form {"pick_indices": '
        f'[<int>, ...]}} listing up to {n} distinct indices, best first, '
        "and nothing else - no explanation, no markdown.\n\n"
        f"{json.dumps(listing)}"
    )

    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(getattr(block, "text", "") for block in resp.content)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            logger.warning("LLM replay pick returned no JSON: %r", text)
            return None
        data = json.loads(match.group(0))
        idx_list = data.get("pick_indices")
        if not isinstance(idx_list, list):
            logger.warning("LLM replay pick missing pick_indices: %r", data)
            return None
        seen = set()
        clean: List[int] = []
        for idx in idx_list:
            if isinstance(idx, int) and 0 <= idx < len(candidates) and idx not in seen:
                seen.add(idx)
                clean.append(idx)
        if not clean:
            logger.warning("LLM replay pick had no valid indices: %r", idx_list)
            return None
        return clean[:n]
    except Exception as exc:  # the anthropic client can raise several error types
        logger.warning("LLM replay pick failed, falling back to heuristic: %s", exc)
        return None


def get_best_replays(competition: str, n: int = 2) -> List[ReplayPick]:
    """Returns up to `n` replay picks for `competition`, best first. Empty
    list if there's nothing to recommend (no finished games in the
    lookback window, or no result data to score them with) - see the
    module docstring for why that case never touches the LLM.
    """
    label = COMPETITION_LABELS[competition]

    finished = [m for m in get_recent_matches(competition) if m.finished]
    if not finished:
        logger.info(
            "No finished %s games in the last %d days - nothing to rank, "
            "skipping the replay pick entirely (no LLM call, no cost).",
            label,
            config.LOOKBACK_DAYS,
        )
        return []

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
        logger.info(
            "No %s results matched to a scoreable game - skipping the replay "
            "pick (no LLM call, no cost).",
            label,
        )
        return []

    if len(candidates) == 1:
        # Nothing to actually rank - don't spend a call finding out there's
        # only one answer.
        return [ReplayPick(match=candidate_matches[0], picked_by="only-option")]

    idx_list = None
    picked_by = "heuristic"
    if config.ANTHROPIC_API_KEY:
        idx_list = _llm_pick(candidates, label, n)
        if idx_list is not None:
            picked_by = "llm"
    if idx_list is None:
        idx_list = _heuristic_pick(candidates, n)

    return [ReplayPick(match=candidate_matches[i], picked_by=picked_by) for i in idx_list]
