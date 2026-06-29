#!/usr/bin/env python3
"""
fetch_data.py — Fetch 2026 World Cup data from football-data.org, and
generate AI match previews and recaps using the Claude API.

Writes:
  data/matches.json          — all competition matches
  data/standings.json        — group stage standings
  data/previews/<id>.json    — Claude-generated pre-match preview (one per match)
  data/summaries/<id>.json   — Claude-generated post-match recap (one per match)

Live scores are fetched directly by the browser from ESPN's scoreboard
API (no key, CORS-open) and are not handled here.

Runs every 5 minutes via GitHub Actions; exits early when no match is
active or imminent to save API quota across the tournament.
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

BASE    = "https://api.football-data.org/v4"
API_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "").strip()
UA      = "WCDashboard/1.0 (+https://github.com/mattt-lab/world-cup)"

ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODEL   = "claude-haiku-4-5-20251001"

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
ESPN_SUMMARY    = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary"
SUMMARIES_DIR   = Path("data/summaries")
PREVIEWS_DIR    = Path("data/previews")

ARTICLE_TIMEOUT_H = 1.0   # give up waiting for ESPN recap article after this long
PREVIEW_WINDOW_H  = 36    # generate previews for matches within this many hours
PRE_MATCH_MIN     = 10
POST_MATCH_MIN    = 180   # 90 min + 30 ET + 25 penalties + ~35 FDO lag

STAGE_LABEL = {
    "LAST_32":        "Round of 32",
    "LAST_16":        "Round of 16",
    "QUARTER_FINALS": "Quarterfinals",
    "SEMI_FINALS":    "Semifinals",
    "THIRD_PLACE":    "3rd Place Playoff",
    "FINAL":          "Final",
}
NEXT_ROUND = {
    "LAST_32":        "the Round of 16",
    "LAST_16":        "the Quarterfinals",
    "QUARTER_FINALS": "the Semifinals",
    "SEMI_FINALS":    "the Final",
}


# ── Window check ──────────────────────────────────────────────────────────────

def in_match_window():
    """
    Return True if any match is live or within the fetch window, or if any
    pending summary is still within its article-retry window.
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

    # Stay active while any pending summary is still within its retry window
    if SUMMARIES_DIR.exists():
        for path in SUMMARIES_DIR.glob("*.json"):
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
                if state.get("status") == "pending" and state.get("first_detected"):
                    first = datetime.fromisoformat(state["first_detected"])
                    if (now - first).total_seconds() / 3600 < ARTICLE_TIMEOUT_H + 0.25:
                        return True
            except Exception:
                pass

    # Stay active if any upcoming match within the preview window has no preview yet
    for m in data.get("matches", []):
        if m.get("status") not in ("SCHEDULED", "TIMED"):
            continue
        try:
            kickoff = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        hours_until = (kickoff - now).total_seconds() / 3600
        if 0 < hours_until <= PREVIEW_WINDOW_H:
            if not (PREVIEWS_DIR / f"{m['id']}.json").exists():
                return True

    return False


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def fetch(path):
    req = urllib.request.Request(f"{BASE}{path}")
    req.add_header("X-Auth-Token", API_KEY)
    req.add_header("User-Agent", UA)
    with urllib.request.urlopen(req, timeout=15) as r:
        remaining = r.headers.get("X-Requests-Available-Minute", "?")
        print(f"  GET {path}  →  {r.status}  (quota left: {remaining}/min)")
        return json.loads(r.read().decode())


def fetch_url(url):
    """Unauthenticated fetch (ESPN APIs)."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False)


# ── ESPN helpers ──────────────────────────────────────────────────────────────

def get_espn_event_map():
    """Fetch ESPN scoreboard → dict mapping 'HTla:ATla' to ESPN event ID."""
    try:
        data = fetch_url(ESPN_SCOREBOARD)
    except Exception as e:
        print(f"  ESPN scoreboard fetch failed: {e}")
        return {}
    result = {}
    for event in data.get("events", []):
        competitors = event.get("competitions", [{}])[0].get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if home and away:
            ht = home.get("team", {}).get("abbreviation", "")
            at = away.get("team", {}).get("abbreviation", "")
            if ht and at:
                result[f"{ht}:{at}"] = event.get("id", "")
    return result


def espn_id_for(match, espn_map):
    ht = match.get("homeTeam", {}).get("tla", "")
    at = match.get("awayTeam", {}).get("tla", "")
    return espn_map.get(f"{ht}:{at}", "")


# ── Claude recap generation ───────────────────────────────────────────────────

def call_claude(prompt):
    payload = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": 250,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload, method="POST",
    )
    req.add_header("x-api-key", ANTHROPIC_KEY)
    req.add_header("anthropic-version", "2023-06-01")
    req.add_header("content-type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())["content"][0]["text"].strip()


def strip_html(html):
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def build_facts(summary_data, match):
    """Structured facts string used when no article is available."""
    hn   = match.get("homeTeam", {}).get("shortName") or match.get("homeTeam", {}).get("name", "Home")
    an   = match.get("awayTeam", {}).get("shortName") or match.get("awayTeam", {}).get("name", "Away")
    hTla = match.get("homeTeam", {}).get("tla", "")
    sc   = match.get("score", {}).get("fullTime", {})
    lines = [f"Result: {hn} {sc.get('home','?')}–{sc.get('away','?')} {an}"]

    goals = []
    for play in summary_data.get("scoringPlays", []):
        name   = (play.get("athletes", [{}])[0].get("shortDisplayName") or
                  play.get("athletes", [{}])[0].get("displayName", ""))
        minute = play.get("clock", {}).get("displayValue", "")
        tla    = play.get("team", {}).get("abbreviation", "")
        team_name = hn if tla == hTla else an
        if name:
            goals.append(f"{name} ({minute}) — {team_name}")
    if goals:
        lines.append("Goals: " + "; ".join(goals))

    for side in summary_data.get("boxscore", {}).get("teams", []):
        tla = side.get("team", {}).get("abbreviation", "")
        for stat in side.get("statistics", []):
            if stat.get("name") == "possessionPct":
                team_name = hn if tla == hTla else an
                lines.append(f"{team_name} possession: {stat.get('displayValue')}%")
                break

    return "\n".join(lines)


def generate_recap(content, is_article):
    if is_article:
        prompt = (
            "Below is a match report from the 2026 FIFA World Cup.\n\n"
            f"{content[:3000]}\n\n"
            "Write a 2–3 sentence match recap capturing the drama and key moments. "
            "Be specific: comebacks, late goals, dominant spells, key saves, red cards, penalties. "
            "Past tense, no preamble, no clichés."
        )
    else:
        prompt = (
            "Here are the facts from a 2026 FIFA World Cup match:\n\n"
            f"{content}\n\n"
            "Write a 2–3 sentence recap that brings these facts to life. "
            "Infer the narrative from the data: a dominant win, a tense one-goal game, "
            "a comeback, a late winner, an early red card, etc. "
            "Past tense, no preamble, no clichés."
        )
    return call_claude(prompt)


# ── Preview generation ───────────────────────────────────────────────────────

def build_preview_prompt(match, standings_list, espn_summary=None):
    hn    = match.get("homeTeam", {}).get("shortName") or match.get("homeTeam", {}).get("name", "Home")
    an    = match.get("awayTeam", {}).get("shortName") or match.get("awayTeam", {}).get("name", "Away")
    stage = match.get("stage", "")

    # Try ESPN preview article first
    if espn_summary:
        article_html = espn_summary.get("article", {}).get("story", "")
        article_text = strip_html(article_html) if article_html else ""
        if article_text:
            return (
                f"Here is a preview article for an upcoming 2026 FIFA World Cup match.\n\n"
                f"{article_text[:2500]}\n\n"
                f"Write a 2-sentence match preview capturing what makes this fixture compelling: "
                f"the key tactical battle, what's at stake, or standout players to watch. "
                f"Present tense, no preamble, no clichés."
            )

    # Build structured context
    lines = [f"Match: {hn} vs {an}"]

    if stage == "GROUP_STAGE":
        grp_label = match.get("group", "").replace("GROUP_", "Group ")
        md        = match.get("matchday", 1)
        lines.append(f"Stage: {grp_label}, Matchday {md} of 3")
        total_groups = [s for s in standings_list if s.get("type") == "TOTAL"]
        grp = next((s for s in total_groups if s.get("group") == grp_label), None)
        if grp:
            for row in grp.get("table", []):
                tid = row.get("team", {}).get("id")
                if tid in (match.get("homeTeam", {}).get("id"), match.get("awayTeam", {}).get("id")):
                    tname = row.get("team", {}).get("shortName") or row.get("team", {}).get("name", "")
                    lines.append(
                        f"  {tname}: {row.get('points',0)} pts, "
                        f"{row.get('goalDifference',0):+d} GD, "
                        f"{row.get('won',0)}W-{row.get('draw',0)}D-{row.get('lost',0)}L"
                    )
    else:
        stage_name = STAGE_LABEL.get(stage, stage)
        next_round = NEXT_ROUND.get(stage, "")
        lines.append(f"Stage: {stage_name}")
        if next_round:
            lines.append(f"Winner advances to: {next_round}")

    context = "\n".join(lines)
    return (
        f"Here is context for an upcoming 2026 FIFA World Cup match:\n\n"
        f"{context}\n\n"
        f"Write a 2-sentence match preview capturing what makes this fixture compelling. "
        f"Draw on your knowledge of both teams' styles, key players, and what's at stake. "
        f"Present tense, no preamble, no clichés."
    )


def process_previews(upcoming_matches, standings_list, espn_map):
    PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    now       = datetime.now(timezone.utc)
    generated = 0

    for match in upcoming_matches:
        mid  = match["id"]
        path = PREVIEWS_DIR / f"{mid}.json"

        if path.exists():
            continue

        # Only generate within the preview window
        try:
            kickoff = datetime.fromisoformat(match["utcDate"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        hours_until = (kickoff - now).total_seconds() / 3600
        if hours_until < 0 or hours_until > PREVIEW_WINDOW_H:
            continue

        # Try ESPN for a preview article
        espn_summary = None
        espn_id = espn_id_for(match, espn_map)
        if espn_id:
            try:
                espn_summary = fetch_url(f"{ESPN_SUMMARY}?event={espn_id}")
            except Exception:
                pass

        try:
            prompt  = build_preview_prompt(match, standings_list, espn_summary)
            preview = call_claude(prompt)
            path.write_text(json.dumps({
                "status":       "complete",
                "match_id":     mid,
                "preview":      preview,
                "generated_at": now.isoformat(),
            }, ensure_ascii=False))
            print(f"  ✓ Preview ({mid}): {preview[:100]}…")
            generated += 1
        except Exception as e:
            print(f"  Match {mid}: preview generation failed — {e}")

    return generated


# ── Summary orchestration ─────────────────────────────────────────────────────

def process_summaries(finished_matches, espn_map):
    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    now       = datetime.now(timezone.utc)
    generated = 0

    for match in finished_matches:
        mid  = match["id"]
        path = SUMMARIES_DIR / f"{mid}.json"

        # Load existing state
        state = {}
        if path.exists():
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass

        if state.get("status") == "complete":
            continue

        # Resolve first-detected timestamp
        first_detected = now
        if state.get("first_detected"):
            try:
                first_detected = datetime.fromisoformat(state["first_detected"])
            except Exception:
                pass
        age_h = (now - first_detected).total_seconds() / 3600

        # Prefer stored ESPN ID so we keep it after the scoreboard window closes
        espn_id = state.get("espn_event_id") or espn_id_for(match, espn_map)
        if not espn_id:
            print(f"  Match {mid}: no ESPN event ID — skipping")
            continue

        # Write pending file on first detection (locks in timestamp + ESPN ID)
        if not state:
            path.write_text(json.dumps({
                "status":         "pending",
                "match_id":       mid,
                "first_detected": first_detected.isoformat(),
                "espn_event_id":  espn_id,
            }, ensure_ascii=False))

        # Fetch ESPN match summary
        try:
            summary_data = fetch_url(f"{ESPN_SUMMARY}?event={espn_id}")
        except Exception as e:
            print(f"  Match {mid}: ESPN summary fetch failed — {e}")
            continue

        # Look for article
        article_html = summary_data.get("article", {}).get("story", "")
        article_text = strip_html(article_html) if article_html else ""
        timed_out    = age_h >= ARTICLE_TIMEOUT_H

        if not article_text and not timed_out:
            print(f"  Match {mid}: no article yet ({age_h:.1f}h elapsed) — will retry")
            continue

        # Generate Claude recap
        try:
            if article_text:
                print(f"  Match {mid}: article found ({len(article_text)} chars) — generating recap")
                recap = generate_recap(article_text, is_article=True)
            else:
                print(f"  Match {mid}: timed out — generating from match facts")
                recap = generate_recap(build_facts(summary_data, match), is_article=False)

            path.write_text(json.dumps({
                "status":       "complete",
                "match_id":     mid,
                "recap":        recap,
                "generated_at": now.isoformat(),
                "source":       "article" if article_text else "facts",
            }, ensure_ascii=False))
            print(f"  ✓ Recap ({mid}): {recap[:100]}…")
            generated += 1
        except Exception as e:
            print(f"  Match {mid}: Claude call failed — {e}")

    return generated


# ── Main ──────────────────────────────────────────────────────────────────────

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

    if ANTHROPIC_KEY:
        espn_map  = get_espn_event_map()
        all_matches = matches.get("matches", [])

        # Generate previews for upcoming matches within the preview window
        upcoming = [m for m in all_matches if m.get("status") in ("SCHEDULED", "TIMED")]
        if upcoming:
            print(f"\n  Processing previews for {len(upcoming)} upcoming matches…")
            generated = process_previews(upcoming, standings.get("standings", []), espn_map)
            if generated:
                print(f"  ✓ {generated} new preview(s) generated")

        # Generate recaps for finished matches
        finished = [m for m in all_matches if m.get("status") in ("FINISHED", "AWARDED")]
        if finished:
            print(f"\n  Processing recaps for {len(finished)} finished matches…")
            generated = process_summaries(finished, espn_map)
            if generated:
                print(f"  ✓ {generated} new recap(s) generated")
    else:
        print("\n  ANTHROPIC_API_KEY not set — skipping preview/recap generation")

    print(f"\n✓  data/ written")


if __name__ == "__main__":
    main()
