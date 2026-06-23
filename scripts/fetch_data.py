#!/usr/bin/env python3
"""
fetch_data.py — Fetch 2026 World Cup data.

Writes:
  data/matches.json   — all competition matches (football-data.org)
  data/standings.json — group stage standings (football-data.org)
  data/live.json      — live scores (ESPN unofficial scoreboard API, no key)

Run every 5 minutes via GitHub Actions during the tournament.
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

BASE    = "https://api.football-data.org/v4"
API_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "").strip()
UA      = "WCDashboard/1.0 (+https://github.com/mattt-lab/world-cup)"

ESPN_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
)


def fetch(path):
    req = urllib.request.Request(f"{BASE}{path}")
    req.add_header("X-Auth-Token", API_KEY)
    req.add_header("User-Agent", UA)
    with urllib.request.urlopen(req, timeout=15) as r:
        remaining = r.headers.get("X-Requests-Available-Minute", "?")
        print(f"  GET {path}  →  {r.status}  (quota left: {remaining}/min)")
        return json.loads(r.read().decode())


def fetch_espn():
    """Fetch live scores from ESPN's unofficial scoreboard API. No key needed."""
    try:
        req = urllib.request.Request(ESPN_URL)
        req.add_header("User-Agent", "Mozilla/5.0")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=10) as r:
            print(f"  GET ESPN scoreboard  →  {r.status}")
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"  ESPN fetch failed: {e}")
        return None


def parse_espn(data):
    """
    Return a dict keyed by 'HOME_TLA:AWAY_TLA' with live score info.
    Covers all match states (pre / in / post) so the dashboard can
    cross-reference for clock display even on finished matches.
    """
    if not data:
        return {}
    out = {}
    for event in data.get("events", []):
        comps = event.get("competitions", [])
        if not comps:
            continue
        competitors = comps[0].get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not (home and away):
            continue

        home_tla = home.get("team", {}).get("abbreviation", "")
        away_tla = away.get("team", {}).get("abbreviation", "")
        if not (home_tla and away_tla):
            continue

        status     = event.get("status", {})
        st_type    = status.get("type", {})
        state      = st_type.get("state", "")        # "pre" | "in" | "post"
        detail     = st_type.get("shortDetail", "")  # e.g. "2nd Half, 67:00" or "FT"

        out[f"{home_tla}:{away_tla}"] = {
            "homeScore": int(home.get("score") or 0),
            "awayScore": int(away.get("score") or 0),
            "state":     state,
            "clock":     status.get("displayClock", ""),
            "period":    status.get("period", 1),
            "detail":    detail,
        }
    return out


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False)


def main():
    print("=" * 60)
    print(f"fetch_data.py  —  {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}")
    print("=" * 60)

    if not API_KEY:
        print("ERROR: FOOTBALL_DATA_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    matches   = fetch("/competitions/WC/matches")
    standings = fetch("/competitions/WC/standings")

    meta = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    matches["_meta"]   = meta
    standings["_meta"] = meta

    write("data/matches.json",   matches)
    write("data/standings.json", standings)

    # ESPN live scores — always fetch so the dashboard has fresh clock data
    espn_raw   = fetch_espn()
    espn_scores = parse_espn(espn_raw)
    live_json  = {
        "_meta":   {**meta, "source": "ESPN"},
        "matches": espn_scores,
    }
    write("data/live.json", live_json)

    n_matches = len(matches.get("matches", []))
    n_groups  = len(standings.get("standings", []))
    live_count = sum(
        1 for m in matches.get("matches", [])
        if m.get("status") in ("LIVE", "IN_PLAY", "PAUSED")
    )

    print(f"\n  matches:   {n_matches} total, {live_count} live")
    print(f"  standings: {n_groups} group entries")
    print(f"  ESPN live: {len(espn_scores)} match(es) tracked")
    print(f"\n✓  data/ written")


if __name__ == "__main__":
    main()
