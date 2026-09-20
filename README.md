# Weekend Soccer Picker

Every Sunday evening, this repo emails a **top pick and a secondary
"also good" option** for both upcoming games and last week's best
replay, for each of four leagues:

1. Champions League on Paramount+.
2. Premier League on Peacock.
3. Serie A on Paramount+.
4. Bundesliga on Fandango.

That's up to sixteen picks on a normal week - fewer whenever a category
doesn't have a real second candidate (e.g. only one game airs, or a
league is between matchdays).

It also lists every other game coming up in each league/broadcaster
pairing, for context. The email arrives as a nicely formatted HTML
message (with a plain-text fallback for mail clients that want it). It
runs for free on GitHub Actions - no server to maintain.

Adding another league later is just a `src/config.py` change (see the
comment above `COMPETITIONS` there) - nothing else in the codebase
hardcodes which leagues exist.

## How it decides the "best" game

**Upcoming games** are scored using current league standings, on two
things:

1. **Quality** - how high both teams are in the table.
2. **Closeness** - how near each other in the table they are (a game
   between two closely-matched teams tends to matter more than a
   mismatch).

It combines those into a single score and picks the highest. This is a
simple heuristic, not a betting model - treat the pick as a nudge, not
gospel. If standings for a team aren't available yet (e.g. very early in
a season, or during the days before the Champions League league phase
starts), that game is listed but left unranked rather than guessed at.

**Replay picks** (last week's games) work differently, since an actual
result is more informative than a table position: when an
`ANTHROPIC_API_KEY` secret is set (see setup below), Claude looks at
last week's finished games - final score, half-time score, and table
position of both teams - and ranks the top two most exciting ones to
rewatch (comeback, late drama, upset, goal-fest). Without that key, it
falls back to a simpler formula: total goals, how much the score swung
after half-time, and how big an upset it was against the table. Either
way, the email itself just names the matchups - no spoilers on the
score.

Replay picks are drawn from *all* finished games in the league's last
week, on the assumption that the league's configured broadcaster
carries every match in the US. That's true for Champions League/
Paramount+, Premier League/Peacock, and Serie A/Paramount+ (all
exclusive US deals as of when this was built).

**Bundesliga is the one exception worth knowing about:** Fandango only
carries *some* Bundesliga games (others are Telemundo/Universo-only, or
Peacock without a Fandango simulcast) - it's not a blanket-rights deal
like the other three. Upcoming-game picks are unaffected (the scraper
checks each game's actual channel list before including it), but
Bundesliga *replay* picks assume every finished game was on Fandango,
which occasionally won't be true. If that turns out to matter in
practice, the fix is either to drop `"bundesliga"` from
`config.COMPETITIONS` (upcoming Bundesliga picks would disappear too)
or to add a real broadcaster check to Bundesliga replay picks
specifically - see "If the scraper breaks" below.

**Cost control:** the Claude API call for replay picks is genuinely
optional and skipped automatically whenever there's nothing worth
ranking - no finished games in the lookback window (e.g. during a
Champions League break between matchdays), no results data to score
them with, or just a single candidate game. It's only called when
there are at least two real games to choose between, so a quiet week
costs nothing.

## One-time setup

You'll need a few things: a free API key for standings data, a Gmail
app password for sending mail, optionally an Anthropic API key for
smarter replay picks, and to add them all as secrets on this repo.

### 1. Get a football-data.org API key (free)

1. Go to <https://www.football-data.org/client/register> and register.
2. Copy the API token they email/show you.

The free tier covers all four leagues' standings this project needs, at
10 requests/minute - way more than we need for a once-a-week run.

### 2. Create a Gmail "app password"

Your regular Gmail password won't work for this (Google blocks it for
security). Instead:

1. Make sure 2-Step Verification is turned on for your Google account:
   <https://myaccount.google.com/security>
2. Go to <https://myaccount.google.com/apppasswords>
3. Create a new app password (name it anything, e.g. "soccer picker").
4. Copy the 16-character password it gives you.

The email will be sent from (and by default, to) this same Gmail
address.

### 3. Get an Anthropic API key (optional, for smarter replay picks)

1. Go to <https://console.anthropic.com> and sign up.
2. Create an API key under **API Keys**.
3. Note that unlike the other two services, this one isn't free - a
   once-a-week call to a small/cheap model costs a fraction of a cent,
   but it does need billing set up on the Anthropic Console.

If you skip this, replay picks still work for all four leagues, just
using the simpler stats-only formula instead of Claude's judgment.

### 4. Add repo secrets

In this repo on GitHub: **Settings -> Secrets and variables -> Actions ->
New repository secret**. Add:

| Secret name | Value |
|---|---|
| `FOOTBALL_DATA_API_KEY` | the token from step 1 |
| `GMAIL_ADDRESS` | your Gmail address |
| `GMAIL_APP_PASSWORD` | the 16-character app password from step 2 |
| `ANTHROPIC_API_KEY` | *(optional)* the key from step 3, for smarter replay picks |
| `EMAIL_TO` | *(optional)* where to send the email, if different from `GMAIL_ADDRESS`. Can be a comma-separated list (e.g. `me@gmail.com,dad@gmail.com`) to send to more than one person. |

### 5. Make sure Actions are enabled

New repos usually have Actions on by default. If not: **Settings ->
Actions -> General -> Allow all actions**.

That's it. The workflow in `.github/workflows/weekly-pick.yml` will run
automatically every Sunday evening (Pacific time) from then on.

## Testing it right now

Don't wait until Sunday to see if it works:

1. Go to the **Actions** tab on GitHub.
2. Click **Weekly game pick** in the left sidebar.
3. Click **Run workflow** -> **Run workflow**.
4. Watch it run, and check your email.

## Running it locally

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in your values
python -m src.main
```

The script prints the email body to the console either way, so you can
sanity-check it without actually sending anything (just leave
`GMAIL_APP_PASSWORD` blank).

## Adjusting the schedule

The cron schedule (`0 1 * * 1` = Monday 01:00 UTC, i.e. Sunday 6pm
Pacific Daylight Time) is in `.github/workflows/weekly-pick.yml`. GitHub
Actions cron is always UTC and doesn't auto-adjust for US daylight
saving time, so the actual local send time will drift by an hour between
PDT (spring-fall) and PST (winter). If you want the exact hour year
round, just update the cron line twice a year (or open an issue with
yourself as a reminder).

You can also change how many days ahead it looks for upcoming games with
a `LOOKAHEAD_DAYS` secret, or how many days back it looks for replay
picks with `LOOKBACK_DAYS` (both default to 7).

## If the scraper breaks

This project scrapes [livesoccertv.com](https://www.livesoccertv.com) for
schedule and broadcaster data, since there's no public API for "which
streaming service is showing which game." If livesoccertv.com changes
its page structure, the scraper in `src/scrape_schedule.py` may need
updating. In particular:

- `LIVESOCCERTV_COMPETITION_IDS` in `src/config.py` hardcodes the site's
  internal numeric IDs for each league (Premier League 6, Champions
  League 50, Serie A 39, Bundesliga 7). These have been stable but
  aren't guaranteed to stay that way.
- The scraper looks for `<tr class="matchrow" data-cid="...">` rows with
  a `div.mchannels` broadcaster list and a `<span dv="...">` kickoff
  timestamp. If GitHub Actions runs start failing, check the Action's
  logs first - `src/scrape_schedule.py` logs a warning for every page it
  can't fetch or parse.
- Replay picks (last week's games) don't check the broadcaster at all -
  finished-match rows on livesoccertv.com collapse their channel list to
  a generic "Available on-demand" link, so instead the code assumes
  every game in a league aired on that league's configured broadcaster
  (see the Bundesliga/Fandango caveat above - that one's a real,
  already-known exception rather than a hypothetical future one). If a
  rights deal ever changes for one of the other three leagues too,
  `src/replay_pick.py` would need a real broadcaster check added.

## Project layout

```
src/
  config.py          - environment variables, constants, and the list of tracked leagues
  scrape_schedule.py - finds upcoming/recent games on each league's broadcaster
  standings.py        - fetches league tables + recent results from football-data.org
  team_aliases.py     - matches team names between data sources
  pick_best_game.py   - scores upcoming games and writes explanation blurbs
  replay_pick.py       - picks the best game(s) to rewatch from last week
  email_sender.py     - sends the email via Gmail SMTP
  main.py             - ties it all together
.github/workflows/weekly-pick.yml - the schedule
```
