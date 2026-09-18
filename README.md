# Weekend Soccer Picker

Every Sunday evening, this repo emails four picks:

1. The best upcoming Champions League game on Paramount+ this week.
2. The best upcoming Premier League game on Peacock this week.
3. The best Champions League game to go back and watch as a replay from
   last week.
4. The best Premier League game to go back and watch as a replay from
   last week.

It also lists every other Paramount+ Champions League / Peacock Premier
League game coming up, for context. It runs for free on GitHub Actions -
no server to maintain.

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
position of both teams - and picks whichever one sounds like it was the
most exciting to watch (comeback, late drama, upset, goal-fest).
Without that key, it falls back to a simpler formula: total goals, how
much the score swung after half-time, and how big an upset it was
against the table. Either way, the email itself just names the matchup -
no spoilers on the score.

Replay picks are drawn from *all* finished Champions League / Premier
League games in the last week, on the assumption that Paramount+
carries every Champions League match and Peacock carries every Premier
League match in the US (true as of when this was built - see "If the
scraper breaks" below if that assumption ever stops holding).

## One-time setup

You'll need a few things: a free API key for standings data, a Gmail
app password for sending mail, optionally an Anthropic API key for
smarter replay picks, and to add them all as secrets on this repo.

### 1. Get a football-data.org API key (free)

1. Go to <https://www.football-data.org/client/register> and register.
2. Copy the API token they email/show you.

The free tier covers the Premier League and Champions League standings
this project needs, at 10 requests/minute - way more than we need for a
once-a-week run.

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

If you skip this, the two replay picks still work, just using the
simpler stats-only formula instead of Claude's judgment.

### 4. Add repo secrets

In this repo on GitHub: **Settings -> Secrets and variables -> Actions ->
New repository secret**. Add:

| Secret name | Value |
|---|---|
| `FOOTBALL_DATA_API_KEY` | the token from step 1 |
| `GMAIL_ADDRESS` | your Gmail address |
| `GMAIL_APP_PASSWORD` | the 16-character app password from step 2 |
| `ANTHROPIC_API_KEY` | *(optional)* the key from step 3, for smarter replay picks |
| `EMAIL_TO` | *(optional)* where to send the email, if different from `GMAIL_ADDRESS` |

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
  internal numeric IDs for the Premier League (6) and Champions League
  (50). These have been stable but aren't guaranteed to stay that way.
- The scraper looks for `<tr class="matchrow" data-cid="...">` rows with
  a `div.mchannels` broadcaster list and a `<span dv="...">` kickoff
  timestamp. If GitHub Actions runs start failing, check the Action's
  logs first - `src/scrape_schedule.py` logs a warning for every page it
  can't fetch or parse.
- Replay picks (last week's games) don't check the broadcaster at all -
  finished-match rows on livesoccertv.com collapse their channel list to
  a generic "Available on-demand" link, so instead the code assumes
  every Champions League game is on Paramount+ and every Premier League
  game is on Peacock (true in the US as of when this was built). If a
  rights deal ever changes that, `src/replay_pick.py` would need a real
  broadcaster check re-added.

## Project layout

```
src/
  config.py          - environment variables and constants
  scrape_schedule.py - finds upcoming/recent games on Paramount+ / Peacock
  standings.py        - fetches league tables + recent results from football-data.org
  team_aliases.py     - matches team names between data sources
  pick_best_game.py   - scores upcoming games and writes explanation blurbs
  replay_pick.py       - picks the best game to rewatch from last week
  email_sender.py     - sends the email via Gmail SMTP
  main.py             - ties it all together
.github/workflows/weekly-pick.yml - the schedule
```
