"""Entry point: scrape this week's Champions League (Paramount+) and
Premier League (Peacock) games, score them, and email Blake the picks.

Every category - Champions League upcoming, Premier League upcoming,
Champions League replay, Premier League replay - gets a top pick and,
when there's a genuine second candidate, a secondary "also good" option
too. That's up to eight picks on a normal week, fewer whenever a
competition is between matchdays (see replay_pick.py's module docstring
for why a quiet week never costs an LLM call).

Run manually with:  python -m src.main
"""
from __future__ import annotations

import logging
from html import escape
from zoneinfo import ZoneInfo

from . import config
from .email_sender import send_email
from .pick_best_game import COMPETITION_LABELS, ScoredMatch, score_matches
from .replay_pick import ReplayPick, get_best_replays
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


def _upcoming_picks(scored: list[ScoredMatch], competition: str) -> list[ScoredMatch]:
    """Up to 2 ranked upcoming picks for `competition`, best first."""
    ranked = [
        sm
        for sm in scored
        if sm.match.competition == competition and sm.score is not None
    ]
    return ranked[:2]


def _subject_line(scored: list[ScoredMatch]) -> str:
    ranked = [sm for sm in scored if sm.score is not None]
    if ranked:
        top = ranked[0]
        label = COMPETITION_LABELS[top.match.competition]
        return f"This week's pick: {top.match.teams} ({label})"
    if scored:
        return "This week's Champions League & Premier League games (unranked - standings unavailable)"
    return "This week: no Champions League or Premier League games on Paramount+/Peacock"


# ---------------------------------------------------------------------------
# Plain text body
# ---------------------------------------------------------------------------


def _text_upcoming_section(
    title: str, broadcaster: str, picks: list[ScoredMatch], lookahead_days: int
) -> list[str]:
    lines = [f"{title.upper()} ({broadcaster})", "=" * 40]
    if not picks:
        lines.append(f"(no ranked game in the next {lookahead_days} days)")
        lines.append("")
        return lines

    top = picks[0]
    lines.append("Top pick: " + top.match.teams)
    lines.append(top.match.kickoff_local_str(PACIFIC))
    if top.match.match_url:
        lines.append(top.match.match_url)
    lines.append(top.blurb)

    if len(picks) > 1:
        second = picks[1]
        lines.append("")
        lines.append("Also good: " + second.match.teams)
        lines.append(second.match.kickoff_local_str(PACIFIC))
        if second.match.match_url:
            lines.append(second.match.match_url)
        lines.append(second.blurb)

    lines.append("")
    return lines


def _text_replay_section(
    title: str, broadcaster: str, picks: list[ReplayPick], lookback_days: int
) -> list[str]:
    lines = [f"{title.upper()} ({broadcaster})", "=" * 40]
    if not picks:
        lines.append(f"(no standout game found in the last {lookback_days} days)")
        lines.append("")
        return lines

    top = picks[0]
    lines.append("Top pick: " + top.match.teams)
    if top.match.match_url:
        lines.append(top.match.match_url)

    if len(picks) > 1:
        second = picks[1]
        lines.append("")
        lines.append("Also good: " + second.match.teams)
        if second.match.match_url:
            lines.append(second.match.match_url)

    lines.append("")
    return lines


def build_email_text(
    scored: list[ScoredMatch],
    cl_replays: list[ReplayPick],
    pl_replays: list[ReplayPick],
) -> tuple[str, str]:
    """Returns (subject, plain_text_body)."""
    subject = _subject_line(scored)

    lines: list[str] = []
    lines.extend(
        _text_upcoming_section(
            "Champions League - coming up",
            "Paramount+",
            _upcoming_picks(scored, "champions_league"),
            config.LOOKAHEAD_DAYS,
        )
    )
    lines.extend(
        _text_upcoming_section(
            "Premier League - coming up",
            "Peacock",
            _upcoming_picks(scored, "premier_league"),
            config.LOOKAHEAD_DAYS,
        )
    )
    lines.extend(
        _text_replay_section(
            "Champions League - best replay",
            "Paramount+",
            cl_replays,
            config.LOOKBACK_DAYS,
        )
    )
    lines.extend(
        _text_replay_section(
            "Premier League - best replay",
            "Peacock",
            pl_replays,
            config.LOOKBACK_DAYS,
        )
    )

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

    unranked = [sm for sm in scored if sm.score is None]
    ranked = [sm for sm in scored if sm.score is not None]
    if unranked and ranked:
        lines.append("")
        lines.append(
            "(Some games above aren't ranked because standings for one or "
            "both teams weren't available yet.)"
        )

    return subject, "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML body - same content as the plain-text version, formatted as cards
# with a bigger font and more breathing room so it's easy to skim on a
# phone. Inline styles throughout (no <style> block) since that's what
# renders most reliably across mail clients.
# ---------------------------------------------------------------------------

_SECTION_HEADER_STYLE = (
    "font-size:20px; font-weight:600; color:#1a1a1a; margin:0 0 14px 0; "
    "padding-bottom:8px; border-bottom:2px solid #2e7d32;"
)
_CARD_STYLE = (
    "background-color:#f3f8f3; border-left:4px solid #2e7d32; border-radius:8px; "
    "padding:20px 22px; margin-bottom:16px;"
)
_SECONDARY_CARD_STYLE = (
    "background-color:#fafafa; border-left:4px solid #bdbdbd; border-radius:8px; "
    "padding:18px 22px; margin-bottom:16px;"
)
_LABEL_STYLE = (
    "font-size:13px; font-weight:700; letter-spacing:0.5px; text-transform:uppercase; "
    "color:#2e7d32; margin:0 0 8px 0;"
)
_SECONDARY_LABEL_STYLE = (
    "font-size:13px; font-weight:700; letter-spacing:0.5px; text-transform:uppercase; "
    "color:#828282; margin:0 0 8px 0;"
)
_MATCHUP_STYLE = "font-size:20px; font-weight:600; color:#1a1a1a; margin:0 0 8px 0;"
_META_STYLE = "font-size:16px; color:#555555; margin:0 0 10px 0;"
_BLURB_STYLE = "font-size:16px; color:#333333; line-height:1.65; margin:0;"
_LINK_STYLE = "font-size:15px; color:#2e7d32; text-decoration:none; font-weight:600;"
_EMPTY_STYLE = "font-size:16px; color:#8a8a8a; font-style:italic; margin:0;"


def _html_pick_card(label: str, sm: ScoredMatch, primary: bool) -> str:
    m = sm.match
    card_style = _CARD_STYLE if primary else _SECONDARY_CARD_STYLE
    label_style = _LABEL_STYLE if primary else _SECONDARY_LABEL_STYLE
    parts = [f'<div style="{card_style}">']
    parts.append(f'<p style="{label_style}">{escape(label)}</p>')
    parts.append(f'<p style="{_MATCHUP_STYLE}">{escape(m.teams)}</p>')
    parts.append(f'<p style="{_META_STYLE}">{escape(m.kickoff_local_str(PACIFIC))}</p>')
    if sm.blurb:
        parts.append(f'<p style="{_BLURB_STYLE}">{escape(sm.blurb)}</p>')
    if m.match_url:
        parts.append(
            f'<p style="margin:12px 0 0 0;"><a href="{escape(m.match_url)}" '
            f'style="{_LINK_STYLE}">Match details &rarr;</a></p>'
        )
    parts.append("</div>")
    return "".join(parts)


_MATCHUP_NO_MARGIN_STYLE = "font-size:20px; font-weight:600; color:#1a1a1a; margin:0;"


def _html_replay_card(label: str, pick: ReplayPick, primary: bool) -> str:
    m = pick.match
    card_style = _CARD_STYLE if primary else _SECONDARY_CARD_STYLE
    label_style = _LABEL_STYLE if primary else _SECONDARY_LABEL_STYLE
    parts = [f'<div style="{card_style}">']
    parts.append(f'<p style="{label_style}">{escape(label)}</p>')
    parts.append(f'<p style="{_MATCHUP_NO_MARGIN_STYLE}">{escape(m.teams)}</p>')
    if m.match_url:
        parts.append(
            f'<p style="margin:12px 0 0 0;"><a href="{escape(m.match_url)}" '
            f'style="{_LINK_STYLE}">Match details &rarr;</a></p>'
        )
    parts.append("</div>")
    return "".join(parts)


def _html_upcoming_section(
    title: str, broadcaster: str, picks: list[ScoredMatch], lookahead_days: int
) -> str:
    html = ['<div style="margin-bottom:36px;">']
    html.append(
        f'<p style="{_SECTION_HEADER_STYLE}">{escape(title)} '
        f'<span style="font-weight:400; color:#828282;">({escape(broadcaster)})</span></p>'
    )
    if not picks:
        html.append(
            f'<p style="{_EMPTY_STYLE}">No ranked game in the next {lookahead_days} days.</p>'
        )
    else:
        html.append(_html_pick_card("Top pick", picks[0], True))
        if len(picks) > 1:
            html.append(_html_pick_card("Also good", picks[1], False))
    html.append("</div>")
    return "".join(html)


def _html_replay_section(
    title: str, broadcaster: str, picks: list[ReplayPick], lookback_days: int
) -> str:
    html = ['<div style="margin-bottom:36px;">']
    html.append(
        f'<p style="{_SECTION_HEADER_STYLE}">{escape(title)} '
        f'<span style="font-weight:400; color:#828282;">({escape(broadcaster)})</span></p>'
    )
    if not picks:
        html.append(
            f'<p style="{_EMPTY_STYLE}">No standout game found in the last {lookback_days} days.</p>'
        )
    else:
        html.append(_html_replay_card("Top pick", picks[0], True))
        if len(picks) > 1:
            html.append(_html_replay_card("Also good", picks[1], False))
    html.append("</div>")
    return "".join(html)


def _html_all_games_list(title: str, matches: list[ScoredMatch], lookahead_days: int) -> str:
    html = ['<div style="margin-bottom:36px;">']
    html.append(f'<p style="{_SECTION_HEADER_STYLE}">{escape(title)}</p>')
    if not matches:
        html.append(
            f'<p style="{_EMPTY_STYLE}">None in the next {lookahead_days} days.</p>'
        )
    else:
        html.append('<ul style="margin:0; padding-left:22px;">')
        for sm in matches:
            m = sm.match
            html.append(
                '<li style="font-size:16px; color:#333333; line-height:1.9; margin-bottom:6px;">'
                f"{escape(m.teams)} &mdash; {escape(m.kickoff_local_str(PACIFIC))}"
                "</li>"
            )
        html.append("</ul>")
    html.append("</div>")
    return "".join(html)


def build_email_html(
    scored: list[ScoredMatch],
    cl_replays: list[ReplayPick],
    pl_replays: list[ReplayPick],
) -> str:
    cl_matches = [sm for sm in scored if sm.match.competition == "champions_league"]
    pl_matches = [sm for sm in scored if sm.match.competition == "premier_league"]
    unranked = [sm for sm in scored if sm.score is None]
    ranked = [sm for sm in scored if sm.score is not None]

    body = "".join(
        [
            _html_upcoming_section(
                "Champions League - coming up",
                "Paramount+",
                _upcoming_picks(scored, "champions_league"),
                config.LOOKAHEAD_DAYS,
            ),
            _html_upcoming_section(
                "Premier League - coming up",
                "Peacock",
                _upcoming_picks(scored, "premier_league"),
                config.LOOKAHEAD_DAYS,
            ),
            _html_replay_section(
                "Champions League - best replay",
                "Paramount+",
                cl_replays,
                config.LOOKBACK_DAYS,
            ),
            _html_replay_section(
                "Premier League - best replay",
                "Peacock",
                pl_replays,
                config.LOOKBACK_DAYS,
            ),
            _html_all_games_list(
                "All Champions League games on Paramount+", cl_matches, config.LOOKAHEAD_DAYS
            ),
            _html_all_games_list(
                "All Premier League games on Peacock", pl_matches, config.LOOKAHEAD_DAYS
            ),
        ]
    )

    footer = ""
    if unranked and ranked:
        footer = (
            '<p style="font-size:14px; color:#999999; font-style:italic; margin-top:4px;">'
            "Some games above aren't ranked because standings for one or both "
            "teams weren't available yet.</p>"
        )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0; padding:0; background-color:#eef1ee; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<div style="max-width:640px; margin:0 auto; padding:40px 28px 48px 28px; background-color:#ffffff;">
<h1 style="font-size:28px; font-weight:700; color:#1a1a1a; margin:0 0 8px 0;">&#9917; Weekend Soccer Picks</h1>
<p style="font-size:16px; color:#828282; margin:0 0 36px 0;">Champions League on Paramount+ &middot; Premier League on Peacock</p>
{body}
{footer}
</div>
</body>
</html>"""


def main() -> None:
    logger.info("Fetching Champions League games on Paramount+...")
    cl_matches = get_upcoming_matches("champions_league")
    logger.info("Found %d Champions League game(s) on Paramount+.", len(cl_matches))

    logger.info("Fetching Premier League games on Peacock...")
    pl_matches = get_upcoming_matches("premier_league")
    logger.info("Found %d Premier League game(s) on Peacock.", len(pl_matches))

    all_matches = cl_matches + pl_matches
    scored = score_matches(all_matches)

    logger.info("Picking last week's best Champions League replays...")
    cl_replays = get_best_replays("champions_league", n=2)
    logger.info("Picking last week's best Premier League replays...")
    pl_replays = get_best_replays("premier_league", n=2)

    subject, body_text = build_email_text(scored, cl_replays, pl_replays)
    body_html = build_email_html(scored, cl_replays, pl_replays)
    logger.info("Subject: %s", subject)
    print(body_text)

    send_email(subject, body_text, body_html)


if __name__ == "__main__":
    main()
