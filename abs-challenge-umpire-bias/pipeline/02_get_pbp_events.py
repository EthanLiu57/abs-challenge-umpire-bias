"""
02_get_pbp_events.py

For each game_pk in data/schedule_2026.csv, pulls the live-feed play-by-play
and extracts:
  - every pitch event (inning, half, at-bat index, pitch index, count,
    call, batter/pitcher IDs, location/zone data)
  - any attached review/challenge event for that pitch

Output:
  - one raw JSON dump per game: data/raw_pbp/{game_pk}.json
  - data/pitch_events_2026.csv
  - data/challenge_events_2026.csv

Requires: requests, pandas
"""

import json
import time
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path("data")
RAW_DIR = DATA_DIR / "raw_pbp"
RAW_DIR.mkdir(parents=True, exist_ok=True)

LIVE_FEED_URL_TMPL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
SEASON = 2026


def fetch_live_feed(game_pk: int) -> dict:
    url = LIVE_FEED_URL_TMPL.format(game_pk=game_pk)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def extract_pitch_events(game_pk: int, feed: dict) -> list[dict]:
    """Flatten every pitch event out of the live feed's play-by-play."""
    rows = []
    plays = feed.get("liveData", {}).get("plays", {}).get("allPlays", [])

    for play in plays:
        about = play.get("about", {})
        matchup = play.get("matchup", {})
        for event in play.get("playEvents", []):
            if not event.get("isPitch"):
                continue
            details = event.get("details", {})
            pitch_data = event.get("pitchData", {})
            coords = pitch_data.get("coordinates", {})
            rows.append(
                {
                    "game_pk": game_pk,
                    "at_bat_index": about.get("atBatIndex"),
                    "inning": about.get("inning"),
                    "half_inning": about.get("halfInning"),
                    "pitch_number": event.get("pitchNumber"),
                    "event_index": event.get("index"),
                    "batter_id": matchup.get("batter", {}).get("id"),
                    "pitcher_id": matchup.get("pitcher", {}).get("id"),
                    "call_code": details.get("code"),
                    "call_description": details.get("description"),
                    "is_in_play": details.get("isInPlay"),
                    "px": coords.get("pX"),
                    "pz": coords.get("pZ"),
                    "sz_top": pitch_data.get("strikeZoneTop"),
                    "sz_bot": pitch_data.get("strikeZoneBottom"),
                }
            )
    return rows


def extract_challenge_events(game_pk: int, feed: dict) -> list[dict]:
    rows = []
    plays = feed.get("liveData", {}).get("plays", {}).get("allPlays", [])

    for play in plays:
        about = play.get("about", {})

        play_review = play.get("reviewDetails") or play.get("replayReview")
        if play_review:
            rows.append(
                {
                    "game_pk": game_pk,
                    "at_bat_index": about.get("atBatIndex"),
                    "pitch_number": None,
                    "raw_review_block": json.dumps(play_review),
                }
            )

        for event in play.get("playEvents", []):
            event_review = event.get("reviewDetails") or event.get("replayReview")
            if event_review:
                rows.append(
                    {
                        "game_pk": game_pk,
                        "at_bat_index": about.get("atBatIndex"),
                        "pitch_number": event.get("pitchNumber"),
                        "raw_review_block": json.dumps(event_review),
                    }
                )
    return rows


def main():
    schedule_path = DATA_DIR / f"schedule_{SEASON}.csv"
    games = pd.read_csv(schedule_path)["game_pk"].tolist()
    print(f"Loaded {len(games)} game_pks.")

    all_pitches = []
    all_challenges = []

    for i, game_pk in enumerate(games):
        raw_path = RAW_DIR / f"{game_pk}.json"
        if raw_path.exists():
            feed = json.loads(raw_path.read_text())
        else:
            try:
                feed = fetch_live_feed(game_pk)
                raw_path.write_text(json.dumps(feed))
                time.sleep(0.3)  # be polite to the API
            except Exception as e:
                print(f"  [warn] game_pk {game_pk}: {e}")
                continue

        all_pitches.extend(extract_pitch_events(game_pk, feed))
        all_challenges.extend(extract_challenge_events(game_pk, feed))

        if i % 25 == 0:
            print(f"  {i}/{len(games)} games processed")

    pd.DataFrame(all_pitches).to_csv(DATA_DIR / f"pitch_events_{SEASON}.csv", index=False)
    pd.DataFrame(all_challenges).to_csv(
        DATA_DIR / f"challenge_events_{SEASON}.csv", index=False
    )
    print(f"Wrote {len(all_pitches)} pitch rows, {len(all_challenges)} challenge rows.")


if __name__ == "__main__":
    main()
