"""Scrapes livesoccertv.com's day-by-day schedule pages to find which
Champions League games are on Paramount+ and which Premier League games
are on Peacock.

How this works (reverse-engineered from the live site in Sept 2026):

- https://www.livesoccertv.com/schedules/YYYY-MM-DD/ lists every match
  worldwide on that date. Each match is a <tr class="matchrow"> with a
  data-cid="<competition id>" attribute - a stable numeric ID per
  competition (Premier League = 6, Champions League = 50).
- For matches that haven't kicked off yet, the row also contains a
  div.mchannels with one <a title="..."> per broadcaster carrying that
  match, and a <span dv="..."> holding the exact kickoff time as a
  millisecond Unix timestamp (unambiguous, no timezone guessing needed).
- Finished matches collapse their channel list to a single "Available
  on-demand" link, which is fine for us since we only care about
  upcoming games.

If livesoccertv.com changes its markup, this is the file that will need
updating - see the README's "If the scraper breaks" section.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import List

import requests
from bs4 import BeautifulSoup

from . import config

logger = logging.getLogger(__name__)

BASE_URL = "https://www.livesoccertv.com/schedules/{date}/"


@dataclass
class Match:
    competition: str  # "premier_league" or "champions_league"
    teams: str  # e.g. "Arsenal vs Manchester City"
    kickoff_utc: datetime
    match_url: str

    def kickoff_local_str(self, tz) -> str:
        return self.kickoff_utc.astimezone(tz).strftime("%a %b %-d, %-I:%M %p %Z")


def _fetch_html(day: date) -> str | None:
    url = BASE_URL.format(date=day.isoformat())
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": config.USER_AGENT},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None


def _parse_kickoff(row) -> datetime | None:
    dv_span = row.select_one("span[dv]")
    if dv_span and dv_span.get("dv"):
        try:
            return datetime.fromtimestamp(int(dv_span["dv"]) / 1000, tz=timezone.utc)
        except (ValueError, TypeError):
            pass
    # Fallback: the tr's own data-ko attribute, e.g. "2026-09-19 10:00:00".
    # Empirically this is also UTC-ish (matches the dv timestamp), but the
    # dv attribute above is the authoritative source when present.
    ko_str = row.get("data-ko")
    if ko_str:
        try:
            return datetime.strptime(ko_str, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            pass
    return None


def _row_has_broadcaster(row, broadcaster_substr: str) -> bool:
    channels_div = row.select_one("div.mchannels")
    if not channels_div:
        return False
    for a in channels_div.select("a"):
        haystack = f"{a.get('title', '')} {a.get_text()}"
        if broadcaster_substr.lower() in haystack.lower():
            return True
    return False


def _extract_teams(row) -> str | None:
    link = row.select_one("#match a") or row.select_one("td.matchcol a")
    if not link:
        return None
    return (link.get("title") or link.get_text()).strip()


def _extract_match_url(row) -> str:
    link = row.select_one("#match a") or row.select_one("td.matchcol a")
    href = link.get("href") if link else None
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return f"https://www.livesoccertv.com{href}"


def get_upcoming_matches(
    competition: str, lookahead_days: int | None = None
) -> List[Match]:
    """Returns upcoming matches for `competition` ("premier_league" or
    "champions_league") that are airing on that competition's configured
    broadcaster, within the next `lookahead_days` days.
    """
    lookahead_days = lookahead_days or config.LOOKAHEAD_DAYS
    competition_id = config.LIVESOCCERTV_COMPETITION_IDS[competition]
    broadcaster = config.BROADCASTERS[competition]

    now = datetime.now(timezone.utc)
    today = now.date()
    matches: List[Match] = []

    for offset in range(lookahead_days + 1):
        day = today + timedelta(days=offset)
        html = _fetch_html(day)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select(f'tr.matchrow[data-cid="{competition_id}"]')
        for row in rows:
            kickoff = _parse_kickoff(row)
            if not kickoff or kickoff <= now:
                continue
            if not _row_has_broadcaster(row, broadcaster):
                continue
            teams = _extract_teams(row)
            if not teams:
                continue
            matches.append(
                Match(
                    competition=competition,
                    teams=teams,
                    kickoff_utc=kickoff,
                    match_url=_extract_match_url(row),
                )
            )

    # De-duplicate (a match can appear on two adjacent date pages if kickoff
    # is right at a day boundary in some timezone interpretation).
    seen = set()
    unique_matches = []
    for m in matches:
        key = (m.teams, m.kickoff_utc)
        if key not in seen:
            seen.add(key)
            unique_matches.append(m)

    unique_matches.sort(key=lambda m: m.kickoff_utc)
    return unique_matches
