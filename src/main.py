"""Entry point: scrape this week's games in every tracked competition
(see config.COMPETITIONS), score them, and email Blake the picks.

Every competition - currently Champions League (Paramount+), Premier
League (Peacock), Serie A (Paramount+), and Bundesliga (Fandango) - gets
a top pick and, when there's a genuine second candidate, a secondary
"also good" option, for both upcoming games AND last week's best replay.
That's up to 16 picks on a normal week, fewer whenever a competition is
between matchdays (see replay_pick.py's module docstring for why a quiet
week never costs an LLM call).

Adding a competition is a config.py change only (COMPETITIONS,
LIVESOCCERTV_COMPETITION_IDS, FOOTBALL_DATA_CODES, BROADCASTERS, plus a
label in pick_best_game.COMPETITION_LABELS) - nothing in this file
hardcodes which competitions exist.

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
from .scrape_schedule import Match, get_upcoming_matches

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
        return "This week's games (unranked - standings unavailable)"

    labels = " / ".join(COMPETITION_LABELS[c] for c in config.COMPETITIONS)
    broadcasters: list[str] = []
    for c in config.COMPETITIONS:
        b = config.BROADCASTERS[c]
        if b not in broadcasters:
            broadcasters.append(b)
    return f"This week: no {labels} games found on {'/'.join(broadcasters)}"


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
    replays: dict[str, list[ReplayPick]],
) -> tuple[str, str]:
    """Returns (subject, plain_text_body)."""
    subject = _subject_line(scored)

    lines: list[str] = []

    for comp in config.COMPETITIONS:
        label = COMPETITION_LABELS[comp]
        broadcaster = config.BROADCASTERS[comp]
        lines.extend(
            _text_upcoming_section(
                f"{label} - coming up",
                broadcaster,
                _upcoming_picks(scored, comp),
                config.LOOKAHEAD_DAYS,
            )
        )

    for comp in config.COMPETITIONS:
        label = COMPETITION_LABELS[comp]
        broadcaster = config.BROADCASTERS[comp]
        lines.extend(
            _text_replay_section(
                f"{label} - best replay",
                broadcaster,
                replays.get(comp, []),
                config.LOOKBACK_DAYS,
            )
        )

    for comp in config.COMPETITIONS:
        label = COMPETITION_LABELS[comp]
        broadcaster = config.BROADCASTERS[comp]
        lines.append(f"ALL {label.upper()} GAMES ON {broadcaster.upper()}")
        lines.append("=" * 40)
        comp_matches = [sm for sm in scored if sm.match.competition == comp]
        if comp_matches:
            for sm in comp_matches:
                lines.append(_format_match_line(sm))
        else:
            lines.append("(none in the next %d days)" % config.LOOKAHEAD_DAYS)
        lines.append("")

    unranked = [sm for sm in scored if sm.score is None]
    ranked = [sm for sm in scored if sm.score is not None]
    if unranked and ranked:
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
_MATCHUP_NO_MARGIN_STYLE = "font-size:20px; font-weight:600; color:#1a1a1a; margin:0;"
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
    replays: dict[str, list[ReplayPick]],
) -> str:
    unranked = [sm for sm in scored if sm.score is None]
    ranked = [sm for sm in scored if sm.score is not None]

    sections: list[str] = []
    for comp in config.COMPETITIONS:
        label = COMPETITION_LABELS[comp]
        broadcaster = config.BROADCASTERS[comp]
        sections.append(
            _html_upcoming_section(
                f"{label} - coming up",
                broadcaster,
                _upcoming_picks(scored, comp),
                config.LOOKAHEAD_DAYS,
            )
        )

    for comp in config.COMPETITIONS:
        label = COMPETITION_LABELS[comp]
        broadcaster = config.BROADCASTERS[comp]
        sections.append(
            _html_replay_section(
                f"{label} - best replay",
                broadcaster,
                replays.get(comp, []),
                config.LOOKBACK_DAYS,
            )
        )

    for comp in config.COMPETITIONS:
        label = COMPETITION_LABELS[comp]
        broadcaster = config.BROADCASTERS[comp]
        comp_matches = [sm for sm in scored if sm.match.competition == comp]
        sections.append(
            _html_all_games_list(
                f"All {label} games on {broadcaster}", comp_matches, config.LOOKAHEAD_DAYS
            )
        )

    body = "".join(sections)

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
<p style="font-size:16px; color:#828282; margin:0 0 36px 0;">Champions League &amp; Serie A on Paramount+ &middot; Premier League on Peacock &middot; Bundesliga on Fandango</p>
{body}
{footer}
</div>
</body>
</html>"""


def main() -> None:
    all_matches: list[Match] = []
    for comp in config.COMPETITIONS:
        label = COMPETITION_LABELS[comp]
        broadcaster = config.BROADCASTERS[comp]
        logger.info("Fetching %s games on %s...", label, broadcaster)
        matches = get_upcoming_matches(comp)
        logger.info("Found %d %s game(s) on %s.", len(matches), label, broadcaster)
        all_matches.extend(matches)

    scored = score_matches(all_matches)

    replays: dict[str, list[ReplayPick]] = {}
    for comp in config.COMPETITIONS:
        label = COMPETITION_LABELS[comp]
        logger.info("Picking last week's best %s replays...", label)
        replays[comp] = get_best_replays(comp, n=2)

    has_any_replays = any(replays.get(comp) for comp in config.COMPETITIONS)
    if not all_matches and not has_any_replays:
        # Nothing to report at all - no upcoming games on any tracked
        # broadcaster, and no replay picks from last week either (e.g. a
        # mid-season international break across every league at once).
        # Sending an email that's just eight "nothing found" sections isn't
        # useful, so skip it entirely rather than spamming an empty pick.
        logger.info(
            "No upcoming games and no replay picks found in any tracked "
            "competition this week - skipping the email."
        )
        return

    subject, body_text = build_email_text(scored, replays)
    body_html = build_email_html(scored, replays)
    logger.info("Subject: %s", subject)
    print(body_text)

    sent = send_email(subject, body_text, body_html)
    if not sent:
        # Make this loud: without this, a failed send (bad Gmail app
        # password, Gmail rejecting the login, etc.) still exits 0, so the
        # GitHub Actions run shows a green checkmark even though no email
        # went out - exactly what happened when this was silent. Raising
        # here turns that into a red X with the real error already printed
        # above by email_sender.send_email()'s logger.error call.
        raise SystemExit("Email failed to send - see the ERROR line above for why.")


if __name__ == "__main__":
    main()
