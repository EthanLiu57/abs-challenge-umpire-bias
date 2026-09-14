"""
04_reconstruct_challenge_state.py

Parses the raw ABS review-event JSON captured in
data/challenge_events_2026.csv (the `raw_review_block` column), then walks
each game in pitch order to reconstruct a running "challenges remaining"
count for both teams, stamped onto every pitch in
data/pitch_events_enriched_2026.csv.

Confirmed raw_review_block schema (from a real sample row):
    {
      "isOverturned": bool,      # true = challenge succeeded (call flipped)
      "inProgress": bool,
      "reviewType": str,         # meaning unclear (e.g. "MJ"); carried
                                   through but not used in modeling
      "challengeTeamId": int,    # numeric MLB team id of the challenging team
      "player": {"id": int, "fullName": str, ...}  # who initiated it
    }

Challenge rules encoded here (per MLB's 2026 ABS rules):
    - each team starts a game with 2 challenges
    - a successful challenge (isOverturned == True) is NOT consumed --
      team keeps it
    - an unsuccessful challenge (isOverturned == False) decrements
      remaining by 1
    - entering any extra inning (10+), if a team's remaining == 0, they
      are topped up to 1 for that inning (assumed non-cumulative -- if
      they already have >=1 remaining, nothing changes). 

Team IDs: pitch_events/schedule only carry team NAMES, not the numeric
ids used in challengeTeamId, so this script fetches the team id/name
lookup once from the Stats API and joins on name. If any team name
doesn't match exactly, that game's rows will fail to join -- check the
join diagnostics printed at the end before assuming full coverage.

Output: data/pitch_events_with_challenge_state_2026.csv
    (all columns from pitch_events_enriched_2026.csv, plus:
     batting_team_challenges_remaining, fielding_team_challenges_remaining)

Requires: pandas, requests
"""

import json
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path("data")
SEASON = 2026
TEAMS_URL = "https://statsapi.mlb.com/api/v1/teams?sportId=1"


def get_team_id_lookup() -> pd.DataFrame:
    """One-time fetch of team id -> full name, cached to disk."""
    cache_path = DATA_DIR / "teams.json"
    if cache_path.exists():
        teams = json.loads(cache_path.read_text())
    else:
        resp = requests.get(TEAMS_URL, timeout=30)
        resp.raise_for_status()
        teams = resp.json()["teams"]
        cache_path.write_text(json.dumps(teams))
    return pd.DataFrame([{"team_id": t["id"], "team_name": t["name"]} for t in teams])


def parse_challenge_events(raw_path: Path) -> pd.DataFrame:
    raw = pd.read_csv(raw_path)
    parsed_rows = []
    for _, row in raw.iterrows():
        try:
            block = json.loads(row["raw_review_block"])
        except (json.JSONDecodeError, TypeError):
            continue
        if block.get("reviewType") != "MJ":
            continue
        parsed_rows.append(
            {
                "game_pk": row["game_pk"],
                "at_bat_index": row["at_bat_index"],
                "pitch_number": row.get("pitch_number"),
                "challenge_team_id": block.get("challengeTeamId"),
                "success": block.get("isOverturned"),
                "review_type": block.get("reviewType"),
                "challenger_player_id": block.get("player", {}).get("id"),
                "challenger_name": block.get("player", {}).get("fullName"),
            }
        )
    return pd.DataFrame(parsed_rows)


def reconstruct_game(
    game_pitches: pd.DataFrame,
    game_challenges: pd.DataFrame,
    home_team_id: int,
    away_team_id: int,
) -> pd.DataFrame:
    """Walk one game's pitches in order, tracking challenges remaining."""
    remaining = {home_team_id: 2, away_team_id: 2}
    topped_up_innings = {home_team_id: set(), away_team_id: set()}

    game_pitches = game_pitches.sort_values(["at_bat_index", "pitch_number"]).copy()
    challenges_by_key = {
        (r["at_bat_index"], r["pitch_number"]): r
        for _, r in game_challenges.iterrows()
    }

    batting_remaining_col = []
    fielding_remaining_col = []

    for _, pitch in game_pitches.iterrows():
        inning = pitch["inning"]
        half = pitch["half_inning"]
        batting_team_id = away_team_id if half == "top" else home_team_id
        fielding_team_id = home_team_id if half == "top" else away_team_id

        # extra-innings top-up: applied once per team per inning >= 10
        if inning >= 10:
            for team_id in (home_team_id, away_team_id):
                if inning not in topped_up_innings[team_id]:
                    if remaining[team_id] == 0:
                        remaining[team_id] = 1
                    topped_up_innings[team_id].add(inning)

        # record state BEFORE this pitch's own challenge (if any) resolves --
        # a challenge on this pitch's call can only affect FUTURE pitches
        batting_remaining_col.append(remaining[batting_team_id])
        fielding_remaining_col.append(remaining[fielding_team_id])

        key = (pitch["at_bat_index"], pitch["pitch_number"])
        challenge = challenges_by_key.get(key)
        if challenge is not None and pd.notna(challenge.get("challenge_team_id")):
            team_id = int(challenge["challenge_team_id"])
            if team_id in remaining and challenge.get("success") is False:
                remaining[team_id] = max(0, remaining[team_id] - 1)
            # success == True: no change, they keep the challenge

    game_pitches["batting_team_challenges_remaining"] = batting_remaining_col
    game_pitches["fielding_team_challenges_remaining"] = fielding_remaining_col
    return game_pitches


def main():
    pitches = pd.read_csv(DATA_DIR / f"pitch_events_enriched_{SEASON}.csv")
    challenges = parse_challenge_events(DATA_DIR / f"challenge_events_{SEASON}.csv")
    schedule = pd.read_csv(DATA_DIR / f"schedule_{SEASON}.csv")
    team_lookup = get_team_id_lookup()

    schedule = schedule.merge(
        team_lookup.rename(columns={"team_id": "home_team_id", "team_name": "home_team"}),
        on="home_team",
        how="left",
    ).merge(
        team_lookup.rename(columns={"team_id": "away_team_id", "team_name": "away_team"}),
        on="away_team",
        how="left",
    )

    n_unmatched = schedule["home_team_id"].isna().sum() + schedule["away_team_id"].isna().sum()
    if n_unmatched > 0:
        print(f"  [warn] {n_unmatched} team-name joins failed -- check naming mismatches")

    all_results = []
    for game_pk, game_pitches in pitches.groupby("game_pk"):
        sched_row = schedule.loc[schedule["game_pk"] == game_pk]
        if sched_row.empty or sched_row["home_team_id"].isna().any():
            print(f"  [warn] no team ids for game_pk {game_pk}, skipping")
            continue
        home_id = int(sched_row["home_team_id"].iloc[0])
        away_id = int(sched_row["away_team_id"].iloc[0])
        game_challenges = challenges[challenges["game_pk"] == game_pk]
        result = reconstruct_game(game_pitches, game_challenges, home_id, away_id)
        all_results.append(result)

    final = pd.concat(all_results, ignore_index=True)
    out_path = DATA_DIR / f"pitch_events_with_challenge_state_{SEASON}.csv"
    final.to_csv(out_path, index=False)
    print(f"Wrote {len(final)} rows to {out_path}")


if __name__ == "__main__":
    main()
