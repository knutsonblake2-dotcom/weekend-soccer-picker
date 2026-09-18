"""Fetches current league tables and recent results from
football-data.org's free tier.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional

import requests

from . import config

logger = logging.getLogger(__name__)

API_BASE = "https://api.football-data.org/v4"


@dataclass
class TeamStanding:
    name: str
    position: int
    points: int
    played: int


@dataclass
class MatchResult:
    home_name: str
    away_name: str
    home_ft: int
    away_ft: int
    home_ht: Optional[int]
    away_ht: Optional[int]
    matchday: Optional[int]


def get_standings(competition: str) -> Optional[List[TeamStanding]]:
    """Returns the current table for `competition` ("premier_league" or
    "champions_league"), or None if unavailable (missing API key, API
    error, or the season/phase hasn't produced a table yet - e.g. before
    the Champions League league phase kicks off each season).
    """
    if not config.FOOTBALL_DATA_API_KEY:
        logger.warning("No FOOTBALL_DATA_API_KEY set - skipping standings lookup.")
        return None

    code = config.FOOTBALL_DATA_CODES[competition]
    url = f"{API_BASE}/competitions/{code}/standings"
    try:
        resp = requests.get(
            url,
            headers={"X-Auth-Token": config.FOOTBALL_DATA_API_KEY},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.warning("Failed to fetch standings for %s: %s", competition, exc)
        return None

    standings_blocks = data.get("standings", [])
    if not standings_blocks:
        return None

    # Prefer a block literally called TOTAL; otherwise take the first one
    # (the Champions League's single league-phase table may be labelled
    # differently across seasons).
    table = None
    for block in standings_blocks:
        if block.get("type") == "TOTAL":
            table = block.get("table")
            break
    if table is None:
        table = standings_blocks[0].get("table")

    if not table:
        return None

    result = []
    for row in table:
        team = row.get("team", {})
        name = team.get("name") or team.get("shortName") or ""
        if not name:
            continue
        result.append(
            TeamStanding(
                name=name,
                position=row.get("position", 0),
                points=row.get("points", 0),
                played=row.get("playedGames", 0),
            )
        )
    return result or None


def _score_side(score_block: dict | None, side: str) -> Optional[int]:
    """football-data.org has used slightly different key names across API
    versions for score sub-objects ("home"/"away" vs "homeTeam"/"awayTeam").
    Handle both defensively rather than assuming one.
    """
    if not score_block:
        return None
    if side in score_block:
        return score_block.get(side)
    return score_block.get(f"{side}Team")


def get_recent_results(
    competition: str, lookback_days: int | None = None
) -> List[MatchResult]:
    """Returns finished matches for `competition` from the last
    `lookback_days` days, with final and half-time scores. Returns an
    empty list (never None) if unavailable, so callers can treat "no
    data" and "no games" the same way.
    """
    if not config.FOOTBALL_DATA_API_KEY:
        return []

    lookback_days = lookback_days or config.LOOKBACK_DAYS
    code = config.FOOTBALL_DATA_CODES[competition]
    date_to = date.today()
    date_from = date_to - timedelta(days=lookback_days)

    url = f"{API_BASE}/competitions/{code}/matches"
    try:
        resp = requests.get(
            url,
            headers={"X-Auth-Token": config.FOOTBALL_DATA_API_KEY},
            params={
                "dateFrom": date_from.isoformat(),
                "dateTo": date_to.isoformat(),
                "status": "FINISHED",
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.warning("Failed to fetch recent results for %s: %s", competition, exc)
        return []

    results = []
    for m in data.get("matches", []):
        score = m.get("score", {}) or {}
        full_time = score.get("fullTime") or {}
        half_time = score.get("halfTime") or {}
        home_ft = _score_side(full_time, "home")
        away_ft = _score_side(full_time, "away")
        if home_ft is None or away_ft is None:
            continue
        home = m.get("homeTeam", {}) or {}
        away = m.get("awayTeam", {}) or {}
        home_name = home.get("name") or home.get("shortName") or ""
        away_name = away.get("name") or away.get("shortName") or ""
        if not home_name or not away_name:
            continue
        results.append(
            MatchResult(
                home_name=home_name,
                away_name=away_name,
                home_ft=home_ft,
                away_ft=away_ft,
                home_ht=_score_side(half_time, "home"),
                away_ht=_score_side(half_time, "away"),
                matchday=m.get("matchday"),
            )
        )
    return results


def build_lookup(standings: List[TeamStanding]) -> Dict[str, TeamStanding]:
    """Maps normalized team name -> TeamStanding, for use with
    team_aliases.find_standing().
    """
    from . import team_aliases

    return {team_aliases.normalize(s.name): s for s in standings}
