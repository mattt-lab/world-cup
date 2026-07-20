# 2026 FIFA World Cup Dashboard

A real-time, four-page World Cup dashboard hosted on GitHub Pages. No backend, no build step — just static HTML served from committed JSON files that a GitHub Actions workflow kept fresh every five minutes during the tournament.

**Live site:** https://mattt-lab.github.io/world-cup/

> **STATUS: FROZEN — 2026 tournament complete.**
> The site displays the final tournament state and remains fully browsable. The data pipeline cron is disabled. See [Reactivating for 2030](#reactivating-for-2030) to bring it back to life.

---

## Pages

### Up Next (`wc-dashboard.html`) — v2.8
The main view. Always shows two sections — **Today** and **Tomorrow** — anchored to US Eastern Time so FIFA's match-day groupings stay intact regardless of the viewer's timezone. Kickoff times display in the viewer's local timezone.

- **Live match hero card** — any in-progress match gets a full-width hero treatment: large team crests, bold score, green glow border
- **AI blurbs** — each match card shows a Claude-written preview (pre-match) or recap (post-match); falls back to a computed standings-based blurb if neither exists
- **Live auto-refresh** — ESPN scoreboard API polled every 30 seconds during active match windows; self-limiting when no matches are live
- **KO navigation** — match cards on this page link to the Bracket for knockout matches, and to Groups for group stage matches

### Groups (`wc-groups.html`) — v2.8
Full group stage standings for all 12 groups in a responsive grid.

- Qualification colour coding: green for automatic qualifiers (top 2), amber for possible third-place qualifiers, dimmed for eliminated teams
- Real team crest images, W/D/L, goal difference, and points

### Bracket (`wc-bracket.html`) — v2.8
The 48-team knockout bracket — Round of 32 through the Final.

- Match pairs ordered by official FIFA match numbers (M73–M104), verified against the published schedule
- Each round renders as its own column; results fill in as matches complete

### Schedule (`wc-schedule.html`) — v2.8
All 104 matches across the tournament, filterable by stage.

- Stage filter tabs: All, Group Stage, R32, R16, QF, SF, 3rd Place Playoff, Final
- Defaults to the current/most-recent active stage automatically

---

## Data pipeline

Data comes from [football-data.org](https://www.football-data.org/) v4 API and [ESPN's CORS-open scoreboard API](https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard).

```
GitHub Actions cron (every 5 min during tournament; DISABLED post-tournament)
    └─ scripts/fetch_data.py
          ├─ GET football-data.org  → data/matches.json, data/standings.json
          │
          ├─ Previews — for each match kicking off within 36h with no preview
          │  file yet: try an ESPN article first, else build context from live
          │  standings → Claude Haiku writes 2 sentences → data/previews/<id>.json
          │
          └─ Recaps — for each finished match without a complete recap:
                mark "pending" on first detection, poll ESPN for match article
                for up to 1h, then → Claude writes 2-3 sentences past tense
                → data/summaries/<id>.json

Live scores fetched client-side from ESPN (CORS-open, no key) during match
windows only. FDO is used for schedule/standings backbone; ESPN is authoritative
for live status (FDO lags 30–60 min on FINISHED, stays PAUSED into the 2nd half).
```

### Static files committed to the repo

| File | Contents |
|---|---|
| `data/matches.json` | All 104 fixtures — final scores, statuses |
| `data/standings.json` | Final group A–L tables |
| `data/summaries/<id>.json` | Claude post-match recap (one per finished match) |
| `data/previews/<id>.json` | Claude pre-match preview (generated within 36h of kickoff) |

---

## Smart features

**ET-anchored day sections** — Today/Tomorrow on the Up Next page are defined by US Eastern Time, not the viewer's local clock, so all matches on a given FIFA match day always appear together regardless of timezone. Kickoff times display in local time.

**ESPN as live-status authority** — three specific FDO reliability issues are compensated for:
- FDO PAUSED status persists into the 2nd half → halftime detection reads ESPN's detail string instead
- FDO FINISHED can lag 30–60 min → ESPN `post` event state used to identify finished matches
- FDO quiet period check → overridden when ESPN shows a recently-finished match still needing a recap

**AI previews and recaps** — Claude Haiku writes a 2-sentence preview per match (within 36h of kickoff) and a 2–3 sentence recap once the match finishes, using real ESPN match reports when available. Each is stored as a per-match JSON file; a missing file falls back gracefully to the computed template blurb — never a blank card.

**Computed match blurbs (fallback)** — client-side standings logic covers every meaningful group-stage scenario (both teams won, one lost, both drew, elimination pressure, already qualified, etc.).

**Phase detection** — inspects match statuses to determine current stage automatically; no hardcoded dates.

**Host city lookup** — hardcoded match ID → city table covers all 104 matches (FDO free tier omits venue data).

**Player spotlights** — curated one-sentence "who to watch" for every nation in the tournament (48 teams).

**PWA-ready** — `site.webmanifest`, `apple-touch-icon.png` (500×500), `icon-192.png`, `icon-512.png`. Installs cleanly as a home-screen app on iOS and Android. OG/Twitter cards wired up for link previews.

**Google Analytics** — property `G-9K08FK3SWH` on all four pages.

---

## Tech stack

| Layer | Choice |
|---|---|
| Hosting | GitHub Pages (static, zero cost) |
| Data pipeline | GitHub Actions + Python (`urllib`, stdlib only — no pip installs) |
| Frontend | Vanilla HTML/CSS/JS — no framework, no bundler |
| Match data | football-data.org v4 free tier |
| Live scores | ESPN scoreboard/summary API (unauthenticated, CORS-open) |
| AI | Anthropic Claude Haiku (`claude-haiku-4-5-20251001`) |
| Caching | `localStorage` with TTL |
| Analytics | Google Analytics 4 (G-9K08FK3SWH) |

---

## Setup (for a future tournament)

1. Fork or clone the repo.
2. Sign up for a free API key at [football-data.org](https://www.football-data.org/).
3. Add the key as a GitHub Actions secret: `FOOTBALL_DATA_API_KEY`.
4. (Optional) Add `ANTHROPIC_API_KEY` for AI previews/recaps.
5. Enable GitHub Pages: Settings → Pages → Deploy from branch `main`, root `/`.
6. Follow the reactivation steps below, then trigger the workflow manually once to seed the JSON files.

---

## Reactivating for 2030

The following changes were made on **2026-07-20** to freeze the project. Reverse them when setting up for the next tournament.

### 1. Re-enable the cron (`.github/workflows/update-data.yml`)

```yaml
# Change this:
on:
  # FROZEN 2026-07-20: cron disabled — tournament complete.
  # To reactivate for 2030, uncomment the schedule block below.
  # schedule:
  #   - cron: '*/5 * * * *'
  workflow_dispatch:

# Back to this:
on:
  schedule:
    - cron: '*/5 * * * *'  # Every 5 min all day; script exits early outside match windows
  workflow_dispatch:
```

### 2. Update the competition ID in `scripts/fetch_data.py`

Check football-data.org for the 2030 World Cup competition ID and update the `BASE` URL or competition path accordingly. The 2026 tournament used competition code `WC` with the 2026 season.

### 3. Update bracket match IDs (`wc-bracket.html`)

The `R32_BRACKET` and `R16_BRACKET` arrays contain hardcoded football-data.org match IDs specific to the 2026 tournament (IDs in the 537xxx range). These must be replaced with 2030 match IDs once the schedule is published. The ordering follows official FIFA match numbers M73–M104.

### 4. Update player spotlights and city lookup

`wc-dashboard.html` contains:
- A hardcoded `PLAYER_SPOTLIGHTS` object (one entry per nation)
- A hardcoded `CITY_MAP` / match ID → city lookup for all 104 matches

Both need to be rebuilt for the 2030 tournament's participating nations and host cities.

### 5. Clear stale data files

Delete or archive the 2026 data before seeding fresh:
```
data/matches.json
data/standings.json
data/summaries/   (all files)
data/previews/    (all files)
```

### 6. Update version numbers and GA property (optional)

All four HTML pages show a version badge (`v2.8`). The GA property `G-9K08FK3SWH` is specific to this deployment — create a new GA4 property for the 2030 app if you want separate analytics.
