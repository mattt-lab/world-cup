# 2026 FIFA World Cup Dashboard

A real-time, three-page World Cup dashboard hosted on GitHub Pages. No backend, no build step — just static HTML served from committed JSON files that a GitHub Actions workflow keeps fresh every five minutes.

**Live site:** https://mattt-lab.github.io/world-cup/

---

## Pages

### Today (`wc-dashboard.html`)
The main view. Shows what's happening right now and what's on today.

- **Phase banner** — detects the current tournament stage (Group Stage, Round of 32, etc.) and matchday automatically from live match data. Shows a pulsing live count when games are in progress.
- **Live match hero card** — any in-progress match gets a full-width hero treatment: large 52px team crests, bold 44px score, green glow border, and a rich 2–4 sentence blurb that covers:
  - *What's at stake* — computed from live standings (who needs a win, who's already through, must-not-lose situations)
  - *Who to watch* — a hand-written player spotlight sentence for every nation in the tournament (48+ teams)
- **Today's matches** — compact cards for all other games on the day, each with a one-sentence "what this match means" blurb based on the current group table.
- **Auto-refresh** — when a live match is detected, the page quietly re-fetches data every 60 seconds so scores stay current.

### Groups (`wc-groups.html`)
Full group stage standings for all 12 groups in a responsive grid.

- Qualification colour coding: green bar for automatic qualifiers (top 2), amber for possible third-place qualifiers, dimmed for eliminated teams.
- Real team crest images from the API alongside TLA codes, W/D/L, goal difference, and points.
- Points are highlighted green for qualifiers, amber for third place.

### Schedule (`wc-schedule.html`)
All 104 matches across the tournament, filterable by stage.

- **Stage filter tabs** — All, Group Stage, Round of 32, Round of 16, Quarterfinals, Semifinals, 3rd Place Playoff, Final. Tabs wrap cleanly to a second row rather than overflowing.
- **Defaults to the current stage** — automatically opens on Group Stage during the group phase, Round of 32 when the knockouts begin, and so on.
- Group stage matches are organised by date. Knockout rounds are organised by round then date.
- TBD slots for undetermined knockout teams display cleanly as "TBD" rather than crashing or showing "null".
- Win/loss dimming — in finished matches, the losing team's name is visually muted.

---

## Data pipeline

Data comes from the [football-data.org](https://www.football-data.org/) v4 API. Because the free tier restricts cross-origin requests to `http://localhost`, the browser can't call the API directly from GitHub Pages. Instead, a GitHub Actions workflow fetches data server-side and commits the results as static JSON files.

```
GitHub Actions (every 5 min during match hours)
    └─ scripts/fetch_data.py
          ├─ GET /competitions/WC/matches   → data/matches.json
          └─ GET /competitions/WC/standings → data/standings.json

GitHub Pages serves data/*.json same-origin → no CORS issues
```

The workflow runs every 5 minutes between noon and 3 AM UTC (covering all match windows) and hourly overnight. It only commits when data actually changes, so the git history stays clean.

---

## Smart features

**Phase detection** — rather than hardcoding dates, the dashboard inspects match statuses: the current stage is whichever stage has the most recent `FINISHED` or `LIVE` matches. This means the banner automatically advances from Group Stage → Round of 32 → ... → Final as the tournament progresses.

**Computed match blurbs** — no LLM required. Each blurb is generated from the live standings table using a set of conditional templates covering every meaningful matchday-2 and matchday-3 scenario (both teams won, one lost, both drew, elimination pressure, already qualified, etc.). The output reads like editorial copy.

**Player spotlights** — a curated one-sentence description of the key player to watch for every nation in the tournament. Combined with the stakes text, each live hero card gives you a genuine reason to care about the match even if you've just tuned in.

**localStorage caching** — match and standings data is cached for 120 seconds so navigating between pages doesn't trigger redundant fetches.

**Team crests** — all team logos come directly from the football-data.org CDN (`crests.football-data.org`). Flag emoji were avoided because Windows renders most national flag emoji as two-letter ISO codes rather than actual flags.

---

## Setup

1. Fork or clone the repo.
2. Sign up for a free API key at [football-data.org](https://www.football-data.org/).
3. Add the key as a GitHub Actions secret named `FOOTBALL_DATA_API_KEY`.
4. Enable GitHub Pages (Settings → Pages → Deploy from branch: `main`, root `/`).
5. Trigger the `Update World Cup Data` workflow manually once to seed the JSON files.

The site will be live at `https://<your-username>.github.io/world-cup/`.

---

## Tech stack

| Layer | Choice |
|---|---|
| Hosting | GitHub Pages (static) |
| Data pipeline | GitHub Actions + Python (`urllib`, no dependencies) |
| Frontend | Vanilla HTML/CSS/JS — no framework, no bundler |
| API | football-data.org v4 (free tier) |
| Caching | `localStorage` with TTL |
