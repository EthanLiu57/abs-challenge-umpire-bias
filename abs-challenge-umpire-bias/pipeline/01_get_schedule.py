"""
01_get_schedule.py

Pulls the 2026 MLB regular-season schedule via the MLB Stats API and
resolves the home-plate umpire for each completed game.

Output: data/schedule_2026.csv with one row per game:
    game_pk, game_date, home_team, away_team, hp_umpire, status

Requires: requests, pandas
"""

import time
from pathlib import Path

import pandas as pd
import requests

OUT_DIR = Path("data")
OUT_DIR.mkdir(exist_ok=True)

SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
BOXSCORE_URL_TMPL = "https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"

SEASON = 2026
SPORT_ID = 1  # MLB


def get_schedule(season: int) -> list[dict]:
    """Fetch all regular-season game_pks and basic metadata for a season."""
    games = []
    params = {
        "sportId": SPORT_ID,
        "season": season,
        "gameType": "R",  # regular season only
    }
    resp = requests.get(SCHEDULE_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    for date_entry in data.get("dates", []):
        for g in date_entry.get("games", []):
            games.append(
                {
                    "game_pk": g["gamePk"],
                    "game_date": date_entry["date"],
                    "home_team": g["teams"]["home"]["team"]["name"],
                    "away_team": g["teams"]["away"]["team"]["name"],
                    "status": g["status"]["detailedState"],
                }
            )
    return games


def get_hp_umpire(game_pk: int) -> str | None:
    """
    Pull the home-plate umpire from a game's boxscore.

    """
    url = BOXSCORE_URL_TMPL.format(game_pk=game_pk)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    officials = data.get("officials", [])
    for off in officials:
        official_type = off.get("officialType", "")
        if "Home Plate" in official_type:
            return off.get("official", {}).get("fullName")
    return None


def main():
    print(f"Fetching {SEASON} schedule...")
    games = get_schedule(SEASON)
    print(f"Found {len(games)} games.")

    completed = [g for g in games if g["status"] == "Final"]
    print(f"{len(completed)} completed games -- pulling HP umpires...")

    for i, g in enumerate(completed):
        try:
            g["hp_umpire"] = get_hp_umpire(g["game_pk"])
        except Exception as e:
            print(f"  [warn] game_pk {g['game_pk']}: {e}")
            g["hp_umpire"] = None
        if i % 25 == 0:
            print(f"  {i}/{len(completed)}")
        time.sleep(0.3)  # be polite to the API

    df = pd.DataFrame(completed)
    out_path = OUT_DIR / f"schedule_{SEASON}.csv"
    df.to_csv(out_path, index=False)
    print(f"Wrote {len(df)} rows to {out_path}")


if __name__ == "__main__":
    main()
