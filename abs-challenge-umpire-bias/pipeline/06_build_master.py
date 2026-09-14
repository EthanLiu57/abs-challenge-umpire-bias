"""
06_build_master.py

Builds the master pitch-level dataset for modeling by merging
pitch_events_flagged_2026.csv with:
  - the score BEFORE each pitch's play began (score only changes at play
    boundaries in the raw feed, not per pitch, so this is reconstructed
    by walking each game's plays in order -- same pattern as the
    challenge-state walk in step 04, just at play granularity)
  - park (venue name), pulled from the already-cached raw_pbp JSON
  - batting_team / fielding_team names, derived from home_team/away_team
    + half_inning (no new data needed, just not assembled yet)
  - score_margin (batting team's score minus fielding team's, entering
    the pitch) and a simple late_and_close flag as a coarse leverage
    proxy -- NOT a real win-probability-based Leverage Index. Building
    an actual leverage/WPA model is a separate undertaking; this is a
    placeholder control variable, not a substitute for one.

Output: data/master_pitches_2026.csv

Requires: pandas
"""

import json
from pathlib import Path

import pandas as pd

DATA_DIR = Path("data")
RAW_DIR = DATA_DIR / "raw_pbp"
SEASON = 2026


def get_score_timeline(feed: dict) -> dict:
    """
    Returns {at_bat_index: (away_score_entering, home_score_entering)} --
    the score as it stood BEFORE each play began, which is the score
    that applies to every pitch within that play (including its last
    pitch, since that pitch's own outcome is what produces the play's
    final result score).
    """
    timeline = {}
    running_away, running_home = 0, 0
    plays = feed.get("liveData", {}).get("plays", {}).get("allPlays", [])
    for play in plays:
        at_bat_index = play.get("about", {}).get("atBatIndex")
        timeline[at_bat_index] = (running_away, running_home)
        result = play.get("result", {})
        running_away = result.get("awayScore", running_away)
        running_home = result.get("homeScore", running_home)
    return timeline


def get_venue(feed: dict) -> str:
    return feed.get("gameData", {}).get("venue", {}).get("name")


def main():
    pitches = pd.read_csv(DATA_DIR / f"pitch_events_flagged_{SEASON}.csv")
    schedule = pd.read_csv(DATA_DIR / f"schedule_{SEASON}.csv")

    score_rows = []
    venue_rows = []
    game_pks = pitches["game_pk"].unique().tolist()

    for i, game_pk in enumerate(game_pks):
        raw_path = RAW_DIR / f"{game_pk}.json"
        if not raw_path.exists():
            print(f"  [warn] no cached raw JSON for game_pk {game_pk}, skipping")
            continue
        feed = json.loads(raw_path.read_text())

        venue_rows.append({"game_pk": game_pk, "venue": get_venue(feed)})

        timeline = get_score_timeline(feed)
        for at_bat_index, (away_score, home_score) in timeline.items():
            score_rows.append(
                {
                    "game_pk": game_pk,
                    "at_bat_index": at_bat_index,
                    "away_score_entering": away_score,
                    "home_score_entering": home_score,
                }
            )
        if i % 25 == 0:
            print(f"  {i}/{len(game_pks)} games processed")

    score_df = pd.DataFrame(score_rows)
    venue_df = pd.DataFrame(venue_rows)

    master = pitches.merge(score_df, on=["game_pk", "at_bat_index"], how="left")
    master = master.merge(venue_df, on="game_pk", how="left")
    master = master.merge(
        schedule[["game_pk", "game_date", "home_team", "away_team", "hp_umpire"]],
        on="game_pk",
        how="left",
    )

    n_missing_score = master["away_score_entering"].isna().sum()
    if n_missing_score > 0:
        print(f"  [warn] {n_missing_score} pitches failed to match a score -- check for at_bat_index gaps")

    master["batting_team"] = master.apply(
        lambda r: r["away_team"] if r["half_inning"] == "top" else r["home_team"], axis=1
    )
    master["fielding_team"] = master.apply(
        lambda r: r["home_team"] if r["half_inning"] == "top" else r["away_team"], axis=1
    )
    master["batting_team_score"] = master.apply(
        lambda r: r["away_score_entering"] if r["half_inning"] == "top" else r["home_score_entering"], axis=1
    )
    master["fielding_team_score"] = master.apply(
        lambda r: r["home_score_entering"] if r["half_inning"] == "top" else r["away_score_entering"], axis=1
    )
    master["score_margin"] = master["batting_team_score"] - master["fielding_team_score"]

    # Coarse leverage proxy -- NOT a real Leverage Index / WPA measure.
    # A proper one would need a base-out/inning win-probability model,
    # which isn't built here. This just flags "plausibly high-stakes"
    # situations for use as a control, not a precise leverage metric.
    master["late_and_close"] = (master["inning"] >= 7) & (master["score_margin"].abs() <= 3)

    out_path = DATA_DIR / f"master_pitches_{SEASON}.csv"
    master.to_csv(out_path, index=False)
    print(f"Wrote {len(master)} rows to {out_path}")


if __name__ == "__main__":
    main()
