"""Matches team names as they appear on livesoccertv.com against the
(sometimes differently-formatted) names football-data.org uses, e.g.
"Man Utd" (scraper) vs "Manchester United FC" (API).
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Dict, Optional

# Manual overrides for common short names / nicknames that a plain fuzzy
# match won't reliably catch. Keys and values are both run through
# normalize() before comparison, so casing/punctuation here doesn't matter.
ALIASES = {
    "man utd": "manchester united",
    "man united": "manchester united",
    "man city": "manchester city",
    "spurs": "tottenham hotspur",
    "wolves": "wolverhampton wanderers",
    "nottm forest": "nottingham forest",
    "nott m forest": "nottingham forest",
    "brighton": "brighton hove albion",
    "newcastle": "newcastle united",
    "west ham": "west ham united",
    "leeds": "leeds united",
    "psg": "paris saint germain",
    "inter": "internazionale milano",
    "internazionale": "internazionale milano",
    "bayern munchen": "bayern munchen",
    "bayern munich": "bayern munchen",
    "atletico madrid": "atletico madrid",
    "atletico de madrid": "atletico madrid",
    "dortmund": "borussia dortmund",
    "gladbach": "borussia monchengladbach",
    "borussia m gladbach": "borussia monchengladbach",
    "leverkusen": "bayer leverkusen",
    "sporting cp": "sporting clube de portugal",
    "sporting lisbon": "sporting clube de portugal",
}

# Suffixes/prefixes that appear in one naming scheme but not the other.
_STRIP_WORDS = {
    "fc",
    "cf",
    "afc",
    "sc",
    "ac",
    "cd",
    "the",
    "football",
    "club",
    "calcio",
    "deportivo",
}


def normalize(name: str) -> str:
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower()
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    words = [w for w in name.split() if w not in _STRIP_WORDS]
    normalized = " ".join(words).strip()
    return ALIASES.get(normalized, normalized)


def find_standing(team_name: str, lookup: Dict[str, "object"]) -> Optional[object]:
    """Looks up `team_name` (as scraped) in `lookup` (normalized name ->
    TeamStanding, from standings.build_lookup). Falls back to fuzzy
    matching against the known keys if there's no exact hit.
    """
    key = normalize(team_name)
    if key in lookup:
        return lookup[key]

    close = difflib.get_close_matches(key, lookup.keys(), n=1, cutoff=0.72)
    if close:
        return lookup[close[0]]

    # Try substring containment both ways (handles cases like "villarreal"
    # vs "villarreal cf" that survived stripping differently).
    for candidate_key, standing in lookup.items():
        if key in candidate_key or candidate_key in key:
            return standing

    return None
