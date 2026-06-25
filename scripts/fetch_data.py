#!/usr/bin/env python3
"""
fetch_data.py — Fetch 2026 World Cup data from football-data.org.

Writes:
  data/matches.json   — all competition matches
  data/standings.json — group stage standings

Live scores are fetched directly by the browser from ESPN's scoreboard
API (no key, CORS-open) and are not handled here.

Runs every 5 minutes via GitHub Actions; exits early when no match is
active or imminent to save API quota across the tournament.
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

BASE    = "https://api.football-data.org/v4"
API_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "").strip()
UA      = "WCDashboard/1.0 (+https://github.com/mattt-lab/world-cup)"

PRE_MATCH_MIN  = 10
POST_MATCH_MIN = 180  # 90 min + 30 ET + 25 penalties + ~35 FDO lag


def in_match_window():
    """
    Read the existing data/matches.json (no API call) and return True if
    any match is live or within the fetch window around its kickoff time.
    Returns True if the file is missing/unreadable, or data is >24h old.
    """
    try:
        with open("data/matches.json", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("  No existing data/matches.json — fetching to seed.")
        return True

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

    n_matches  = len(matches.get("matches", []))
    n_groups   = len(standings.get("standings", []))
    live_count = sum(
        1 for m in matches.get("matches", [])
        if m.get("status") in ("LIVE", "IN_PLAY", "PAUSED")
    )

    print(f"\n  matches:   {n_matches} total, {live_count} live")
    print(f"  standings: {n_groups} group entries")
    print(f"\n✓  data/ written")


if __name__ == "__main__":
    main()
