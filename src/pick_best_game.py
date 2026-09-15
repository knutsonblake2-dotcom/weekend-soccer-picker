"""Scores upcoming matches by how good a watch they're likely to be, using
current league standings, and writes a short plain-English blurb for each.

Heuristic (deliberately simple - this is a hobby project, not a betting
model): a match scores well when (a) both teams are high in the table,
and (b) they're closely matched in the table, since that usually means
something is on the line. Both factors are normalized 0-1 by table size
so Premier League and Champions League scores are roughly comparable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from . import standings as standings_mod
from . import team_aliases
from .scrape_schedule import Match

COMPETITION_LABELS = {
    "premier_league": "Premier League",
    "champions_league": "Champions League",
}


@dataclass
class ScoredMatch:
    match: Match
    score: Optional[float]
    blurb: str
    home_standing: Optional[standings_mod.TeamStanding] = None
    away_standing: Optional[standings_mod.TeamStanding] = None


def _split_teams(teams: str) -> tuple[str, str]:
    for sep in (" vs ", " v "):
        if sep in teams:
            home, _, away = teams.partition(sep)
            return home.strip(), away.strip()
    # Unexpected format - treat the whole string as "home" so we don't crash.
    return teams, ""


def _quality(position: int, size: int) -> float:
    if size <= 1:
        return 0.5
    return (size - position) / (size - 1)


def _closeness(pos_a: int, pos_b: int, size: int) -> float:
    if size <= 1:
        return 0.5
    return 1 - abs(pos_a - pos_b) / (size - 1)


def _quality_line(avg_position: float, size: int) -> str:
    frac = avg_position / size
    if frac <= 0.2:
        return "Two of the competition's strongest teams right now."
    if frac <= 0.5:
        return "A solid clash between two mid-to-upper table sides."
    return "Not the flashiest matchup on paper, but table position isn't everything."


def _closeness_line(pos_a: int, pos_b: int, points_a: int, points_b: int) -> str:
    gap = abs(pos_a - pos_b)
    point_gap = abs(points_a - points_b)
    if gap <= 2:
        return f"They're separated by just {point_gap} point{'s' if point_gap != 1 else ''} in the table, so expect it to matter."
    return "One side has a clear edge on paper, but that's exactly when upsets happen."


def score_match(match: Match, lookup) -> ScoredMatch:
    home_name, away_name = _split_teams(match.teams)
    size = len(lookup)

    home_standing = team_aliases.find_standing(home_name, lookup) if lookup else None
    away_standing = team_aliases.find_standing(away_name, lookup) if lookup else None

    if not home_standing or not away_standing or size == 0:
        return ScoredMatch(
            match=match,
            score=None,
            blurb="Standings for one or both teams aren't available yet, so this one isn't ranked.",
        )

    quality = (
        _quality(home_standing.position, size) + _quality(away_standing.position, size)
    ) / 2
    closeness = _closeness(home_standing.position, away_standing.position, size)
    score = 0.6 * quality + 0.4 * closeness

    avg_position = (home_standing.position + away_standing.position) / 2
    blurb = (
        f"{home_standing.name} (#{home_standing.position}, {home_standing.points} pts) vs "
        f"{away_standing.name} (#{away_standing.position}, {away_standing.points} pts). "
        f"{_quality_line(avg_position, size)} "
        f"{_closeness_line(home_standing.position, away_standing.position, home_standing.points, away_standing.points)}"
    )

    return ScoredMatch(
        match=match,
        score=score,
        blurb=blurb,
        home_standing=home_standing,
        away_standing=away_standing,
    )


def score_matches(matches: List[Match]) -> List[ScoredMatch]:
    """Scores a list of matches, which may span multiple competitions."""
    lookups = {}
    scored: List[ScoredMatch] = []
    for match in matches:
        if match.competition not in lookups:
            table = standings_mod.get_standings(match.competition)
            lookups[match.competition] = (
                standings_mod.build_lookup(table) if table else {}
            )
        scored.append(score_match(match, lookups[match.competition]))

    # Ranked (scored) matches first, best first; unscored ones after, in
    # chronological order (score_matches receives matches pre-sorted by
    # kickoff time from the scraper, and this sort is stable).
    scored.sort(key=lambda sm: (sm.score is None, -(sm.score or 0)))
    return scored
