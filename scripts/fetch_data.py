#!/usr/bin/env python3
"""
fetch_data.py — Fetch 2026 World Cup data from football-data.org.

Writes:
  data/matches.json   — all competition matches with live scores
  data/standings.json — group stage standings tables

Run every 5 minutes via GitHub Actions during the tournament.
API key is read from the FOOTBALL_DATA_API_KEY environment variable.
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

BASE    = "https://api.football-data.org/v4"
API_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "").strip()
UA      = "WCDashboard/1.0 (+https://github.com/mattt-lab/world-cup)"


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

    matches   = fetch("/competitions/WC/matches")
    standings = fetch("/competitions/WC/standings")

    # Stamp update time so the dashboard can display it
    meta = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    matches["_meta"]   = meta
    standings["_meta"] = meta

    write("data/matches.json",   matches)
    write("data/standings.json", standings)

    n_matches = len(matches.get("matches", []))
    n_groups  = len(standings.get("standings", []))
    live      = sum(1 for m in matches.get("matches", []) if m.get("status") in ("LIVE", "IN_PLAY", "PAUSED"))

    print(f"\n  matches:   {n_matches} total, {live} live")
    print(f"  standings: {n_groups} group entries")
    print(f"\n✓  data/ written")


if __name__ == "__main__":
    main()
