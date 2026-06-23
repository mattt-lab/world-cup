#!/usr/bin/env python3
"""
fetch_data.py — Fetch 2026 World Cup data.

Writes:
  data/matches.json   — all competition matches (football-data.org)
  data/standings.json — group stage standings (football-data.org)
  data/live.json      — live scores (ESPN unofficial scoreboard, no key)

Runs every 5 minutes via GitHub Actions. Exits early when no match is
active or imminent, saving ~80% of API calls across the tournament.
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

# Minutes before kickoff to start fetching, and after kickoff to keep fetching.
# 140 covers 90 min match + 15 min HT + ~35 min extra time / rain delay buffer.
PRE_MATCH_MIN  = 10
POST_MATCH_MIN = 140


def in_match_window():
    """
    Read the existing data/matches.json (no API call) and return True if
    any match is live or within the fetch window around its kickoff time.
    Returns True if the file is missing/unreadable (forces initial seed fetch),
    and also if the data is more than 24 hours old.
    """
    try:
        with open("data/matches.json", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("  No existing data/matches.json — fetching to seed.")
        return True

    # Force a refresh if data is stale (e.g. after a long CI outage)
    updated_str = data.get("_meta", {}).get("updated", "")
    if updated_str:
        try:
            last_updated = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
            age_h = (datetime.now(timezone.utc) - last_updated).total_seconds() / 3600
            if age_h > 24:
                print(f"  Data is {age_h:.0f}h old — fetching regardless.")
                return True
        except ValueError:
            pass

    now = datetime.now(timezone.utc)
    for m in data.get("matches", []):
        # Already marked live by the API
        if m.get("status") in ("LIVE", "IN_PLAY", "PAUSED"):
            return True
        try:
            kickoff = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        elapsed_min = (now - kickoff).total_seconds() / 60
        if -PRE_MATCH_MIN <= elapsed_min <= POST_MATCH_MIN:
            return True

    return False


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
    Return a dict keyed by 'HOME_TLA:AWAY_TLA' with live score + clock info.
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

        status  = event.get("status", {})
        st_type = status.get("type", {})

        out[f"{home_tla}:{away_tla}"] = {
            "homeScore": int(home.get("score") or 0),
            "awayScore": int(away.get("score") or 0),
            "state":     st_type.get("state", ""),        # "pre" | "in" | "post"
            "clock":     status.get("displayClock", ""),  # e.g. "67:23"
            "period":    status.get("period", 1),         # 1 or 2
            "detail":    st_type.get("shortDetail", ""),  # e.g. "2nd Half, 67:00"
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

    if not in_match_window():
        print("  Quiet period — no active or imminent matches. Skipping fetches.")
        return

    matches   = fetch("/competitions/WC/matches")
    standings = fetch("/competitions/WC/standings")

    meta = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    matches["_meta"]   = meta
    standings["_meta"] = meta

    write("data/matches.json",   matches)
    write("data/standings.json", standings)

    espn_raw    = fetch_espn()
    espn_scores = parse_espn(espn_raw)
    write("data/live.json", {
        "_meta":   {**meta, "source": "ESPN"},
        "matches": espn_scores,
    })

    n_matches  = len(matches.get("matches", []))
    n_groups   = len(standings.get("standings", []))
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
