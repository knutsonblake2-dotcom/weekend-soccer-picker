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
  on-demand" link instead of naming the broadcaster. That's fine for
  upcoming games (we only care about the broadcaster there), but it means
  we CANNOT verify from this page alone that a finished game specifically
  aired on Paramount+/Peacock. For past games, this module instead relies
  on the fact that Paramount+ holds all US Champions League streaming
  rights and Peacock carries all Premier League matches - i.e. every
  finished match in these two competitions counts as "on that service."
  If that ever stops being true (a rights deal changes), the "replay"
  picks in src/replay_pick.py would need a broadcaster check re-added
  here, similar to _row_has_broadcaster() below.

If livesoccertv.com changes its markup, this is the file that will need
updating - see the README's "If the scraper breaks" section.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from . import config

logger = logging.getLogger(__name__)

BASE_URL = "https://www.livesoccertv.com/schedules/{date}/"

# Every tracked competition (config.COMPETITIONS) independently asks for
# the same day's schedule page - without caching, a 4-competition run was
# making up to 4x as many requests as necessary and tripping
# livesoccertv.com's rate limiting (HTTP 429 on nearly every fetch). This
# throttle+cache pair fixes that: each date is fetched at most once per
# run, and every actual request (including the first) is paced so a run
# doesn't burst requests fast enough to get rate-limited in the first
# place.
_MIN_REQUEST_INTERVAL_SECONDS = 0.5
_last_request_at = 0.0


def _throttle() -> None:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < _MIN_REQUEST_INTERVAL_SECONDS:
        time.sleep(_MIN_REQUEST_INTERVAL_SECONDS - elapsed)
    _last_request_at = time.monotonic()


@dataclass
class Match:
    competition: str  # "premier_league" or "champions_league"
    teams: str  # e.g. "Arsenal vs Manchester City"
    kickoff_utc: datetime
    match_url: str
    score: Optional[str] = None  # e.g. "5 - 1", only set for finished matches
    finished: bool = False

    def kickoff_local_str(self, tz) -> str:
        return self.kickoff_utc.astimezone(tz).strftime("%a %b %-d, %-I:%M %p %Z")


@lru_cache(maxsize=None)
def _fetch_html(day: date) -> str | None:
    """Fetches (and, via lru_cache, remembers for the rest of this run) the
    schedule page for `day`. Retries once after a longer pause if the
    first attempt is rate-limited (429) - see the module-level comment
    above for why that started happening once a fourth competition was
    added.
    """
    url = BASE_URL.format(date=day.isoformat())
    for attempt in range(2):
        _throttle()
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": config.USER_AGENT},
                timeout=20,
            )
            if resp.status_code == 429 and attempt == 0:
                logger.warning(
                    "Rate limited (429) fetching %s - waiting and retrying once...",
                    url,
                )
                time.sleep(5)
                continue
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            logger.warning("Failed to fetch %s: %s", url, exc)
            return None
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


def _extract_score(row) -> Optional[str]:
    link = row.select_one("#match a") or row.select_one("td.matchcol a")
    if not link:
        return None
    score_el = link.find("score")
    if not score_el:
        return None
    text = score_el.get_text(strip=True)
    return text or None


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


def get_recent_matches(
    competition: str, lookback_days: int | None = None
) -> List[Match]:
    """Returns finished matches for `competition` from the last
    `lookback_days` days (see the module docstring for why there's no
    broadcaster check here, unlike get_upcoming_matches).
    """
    lookback_days = lookback_days or config.LOOKBACK_DAYS
    competition_id = config.LIVESOCCERTV_COMPETITION_IDS[competition]

    today = datetime.now(timezone.utc).date()
    matches: List[Match] = []

    for offset in range(1, lookback_days + 1):
        day = today - timedelta(days=offset)
        html = _fetch_html(day)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select(f'tr.matchrow[data-cid="{competition_id}"]')
        for row in rows:
            if row.get("data-timer") != "FT":
                continue  # skip postponed/cancelled/still-scheduled rows
            teams = _extract_teams(row)
            if not teams:
                continue
            kickoff = _parse_kickoff(row) or datetime.combine(
                day, datetime.min.time(), tzinfo=timezone.utc
            )
            matches.append(
                Match(
                    competition=competition,
                    teams=teams,
                    kickoff_utc=kickoff,
                    match_url=_extract_match_url(row),
                    score=_extract_score(row),
                    finished=True,
                )
            )

    seen = set()
    unique_matches = []
    for m in matches:
        key = (m.teams, m.kickoff_utc)
        if key not in seen:
            seen.add(key)
            unique_matches.append(m)

    unique_matches.sort(key=lambda m: m.kickoff_utc)
    return unique_matches
