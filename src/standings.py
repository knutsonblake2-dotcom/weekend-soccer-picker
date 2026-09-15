"""Fetches current league tables from football-data.org's free tier."""
from __future__ import annotations

import logging
from dataclasses import dataclass
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


def build_lookup(standings: List[TeamStanding]) -> Dict[str, TeamStanding]:
    """Maps normalized team name -> TeamStanding, for use with
    team_aliases.find_standing().
    """
    from . import team_aliases

    return {team_aliases.normalize(s.name): s for s in standings}
