"""Entry point: scrape this week's Champions League (Paramount+) and
Premier League (Peacock) games, score them, and email Blake the pick.

Run manually with:  python -m src.main
"""
from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from . import config
from .email_sender import send_email
from .pick_best_game import COMPETITION_LABELS, ScoredMatch, score_matches
from .replay_pick import ReplayPick, get_best_replay
from .scrape_schedule import get_upcoming_matches

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PACIFIC = ZoneInfo("America/Los_Angeles")


def _format_match_line(sm: ScoredMatch) -> str:
    m = sm.match
    label = COMPETITION_LABELS[m.competition]
    when = m.kickoff_local_str(PACIFIC)
    line = f"- [{label}] {m.teams} - {when}"
    if m.match_url:
        line += f"\n  {m.match_url}"
    return line


def _format_replay_line(label: str, pick: ReplayPick | None) -> str:
    if not pick:
        return f"{label}: (no standout game found in the last {config.LOOKBACK_DAYS} days)"
    line = f"{label}: {pick.match.teams}"
    if pick.match.match_url:
        line += f"\n  {pick.match.match_url}"
    return line


def build_email_body(
    scored: list[ScoredMatch],
    cl_replay: ReplayPick | None = None,
    pl_replay: ReplayPick | None = None,
) -> tuple[str, str]:
    """Returns (subject, plain_text_body)."""
    ranked = [sm for sm in scored if sm.score is not None]
    unranked = [sm for sm in scored if sm.score is None]

    replay_lines = [
        "LAST WEEK'S BEST REPLAY",
        "=" * 40,
        _format_replay_line("Champions League (Paramount+)", cl_replay),
        _format_replay_line("Premier League (Peacock)", pl_replay),
        "",
    ]

    if not scored:
        subject = "This week: no Champions League or Premier League games on Paramount+/Peacock"
        body_lines = [
            "No upcoming Champions League games on Paramount+ or Premier League "
            "games on Peacock were found in the next "
            f"{config.LOOKAHEAD_DAYS} days.",
            "",
            "(This can happen during international breaks or between "
            "Champions League matchdays - nothing's broken.)",
            "",
        ] + replay_lines
        return subject, "\n".join(body_lines)

    lines = []

    if ranked:
        top = ranked[0]
        label = COMPETITION_LABELS[top.match.competition]
        subject = f"This week's pick: {top.match.teams} ({label})"
        lines.append("THIS WEEK'S PICK")
        lines.append("=" * 40)
        lines.append(f"{top.match.teams} - {label}")
        lines.append(top.match.kickoff_local_str(PACIFIC))
        if top.match.match_url:
            lines.append(top.match.match_url)
        lines.append("")
        lines.append(top.blurb)
        lines.append("")
    else:
        subject = "This week's Champions League & Premier League games (unranked - standings unavailable)"

    lines.extend(replay_lines)

    lines.append("ALL CHAMPIONS LEAGUE GAMES ON PARAMOUNT+")
    lines.append("=" * 40)
    cl_matches = [sm for sm in scored if sm.match.competition == "champions_league"]
    if cl_matches:
        for sm in cl_matches:
            lines.append(_format_match_line(sm))
    else:
        lines.append("(none in the next %d days)" % config.LOOKAHEAD_DAYS)
    lines.append("")

    lines.append("ALL PREMIER LEAGUE GAMES ON PEACOCK")
    lines.append("=" * 40)
    pl_matches = [sm for sm in scored if sm.match.competition == "premier_league"]
    if pl_matches:
        for sm in pl_matches:
            lines.append(_format_match_line(sm))
    else:
        lines.append("(none in the next %d days)" % config.LOOKAHEAD_DAYS)

    if unranked and ranked:
        lines.append("")
        lines.append(
            "(Some games above aren't ranked because standings for one or "
            "both teams weren't available yet.)"
        )

    return subject, "\n".join(lines)


def main() -> None:
    logger.info("Fetching Champions League games on Paramount+...")
    cl_matches = get_upcoming_matches("champions_league")
    logger.info("Found %d Champions League game(s) on Paramount+.", len(cl_matches))

    logger.info("Fetching Premier League games on Peacock...")
    pl_matches = get_upcoming_matches("premier_league")
    logger.info("Found %d Premier League game(s) on Peacock.", len(pl_matches))

    all_matches = cl_matches + pl_matches
    scored = score_matches(all_matches)

    logger.info("Picking last week's best Champions League replay...")
    cl_replay = get_best_replay("champions_league")
    logger.info("Picking last week's best Premier League replay...")
    pl_replay = get_best_replay("premier_league")

    subject, body = build_email_body(scored, cl_replay, pl_replay)
    logger.info("Subject: %s", subject)
    print(body)

    send_email(subject, body)


if __name__ == "__main__":
    main()
