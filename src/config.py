"""Central place for environment-driven configuration."""
from __future__ import annotations

import os


def _load_dotenv_if_present() -> None:
    """Very small .env loader so local testing works without extra deps.

    In GitHub Actions, real environment variables (from repo secrets) are
    already set, so this is a no-op there.
    """
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


_load_dotenv_if_present()

FOOTBALL_DATA_API_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "")
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO") or GMAIL_ADDRESS
LOOKAHEAD_DAYS = int(os.environ.get("LOOKAHEAD_DAYS", "7"))

# Competition IDs used by livesoccertv.com (verified by inspecting the live
# site in September 2026 - see README "If the scraper breaks" section if
# these ever need updating).
LIVESOCCERTV_COMPETITION_IDS = {
    "premier_league": "6",
    "champions_league": "50",
}

# football-data.org competition codes (https://www.football-data.org/documentation/quickstart)
FOOTBALL_DATA_CODES = {
    "premier_league": "PL",
    "champions_league": "CL",
}

BROADCASTERS = {
    "premier_league": "Peacock",
    "champions_league": "Paramount+",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
