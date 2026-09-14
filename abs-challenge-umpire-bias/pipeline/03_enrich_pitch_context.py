"""
03_enrich_pitch_context.py

Re-parses the already-cached raw play-by-play JSON (data/raw_pbp/*.json,
saved by 02_get_pbp_events.py) to pull count, outs, and base-state context
onto each pitch. This is needed for the run-value lookups in later steps
(05+) -- delta run expectancy depends on the base-out state at the time of
the pitch, not just pitch location, and 02 didn't capture that.

Output: data/pitch_events_enriched_2026.csv
    (all columns from pitch_events_2026.csv, plus:
     balls, strikes, outs, on_1b, on_2b, on_3b)

Requires: pandas
"""

import json
from pathlib import Path

import pandas as pd

DATA_DIR = Path("data")
RAW_DIR = DATA_DIR / "raw_pbp"
SEASON = 2026


def base_state_after_play(play: dict) -> dict:
    """
    Determine which bases were occupied at the END of a play, from the
    play's `runners` movement list. Returns {"on_1b": bool, "on_2b": bool,
    "on_3b": bool}.

    """
    bases = {"on_1b": False, "on_2b": False, "on_3b": False}
    for runner in play.get("runners", []):
        movement = runner.get("movement", {})
        end = movement.get("end")
        is_out = movement.get("isOut", False)
        if is_out or end is None:
            continue
        if end == "1B":
            bases["on_1b"] = True
        elif end == "2B":
            bases["on_2b"] = True
        elif end == "3B":
            bases["on_3b"] = True
        # end == "score" -> runner scored, not on base anymore
    return bases


def enrich_game(game_pk: int, feed: dict) -> list[dict]:
    rows = []
    plays = feed.get("liveData", {}).get("plays", {}).get("allPlays", [])

    # base state carried over from the end of the previous play
    running_base_state = {"on_1b": False, "on_2b": False, "on_3b": False}

    for play in plays:
        about = play.get("about", {})
        at_bat_index = about.get("atBatIndex")

        # base state entering this plate appearance = however the last
        # play left it
        base_state_for_this_pa = dict(running_base_state)

        for event in play.get("playEvents", []):
            if not event.get("isPitch"):
                continue
            count = event.get("count", {})
            rows.append(
                {
                    "game_pk": game_pk,
                    "at_bat_index": at_bat_index,
                    "pitch_number": event.get("pitchNumber"),
                    "event_index": event.get("index"),
                    "balls": count.get("balls"),
                    "strikes": count.get("strikes"),
                    "outs": count.get("outs"),
                    "on_1b": base_state_for_this_pa["on_1b"],
                    "on_2b": base_state_for_this_pa["on_2b"],
                    "on_3b": base_state_for_this_pa["on_3b"],
                }
            )

        # update running base state for the NEXT play using how this one
        # resolved
        running_base_state = base_state_after_play(play)

    return rows


def main():
    pitch_events_path = DATA_DIR / f"pitch_events_{SEASON}.csv"
    pitch_events = pd.read_csv(pitch_events_path)
    game_pks = pitch_events["game_pk"].unique().tolist()
    print(f"Enriching context for {len(game_pks)} games...")

    context_rows = []
    for i, game_pk in enumerate(game_pks):
        raw_path = RAW_DIR / f"{game_pk}.json"
        if not raw_path.exists():
            print(f"  [warn] no cached raw JSON for game_pk {game_pk}, skipping")
            continue
        feed = json.loads(raw_path.read_text())
        context_rows.extend(enrich_game(game_pk, feed))
        if i % 25 == 0:
            print(f"  {i}/{len(game_pks)} games processed")

    context_df = pd.DataFrame(context_rows)

    merged = pitch_events.merge(
        context_df,
        on=["game_pk", "at_bat_index", "pitch_number", "event_index"],
        how="left",
    )

    n_missing = merged["outs"].isna().sum()
    if n_missing > 0:
        print(f"  [warn] {n_missing} pitches failed to merge context -- inspect before proceeding")

    out_path = DATA_DIR / f"pitch_events_enriched_{SEASON}.csv"
    merged.to_csv(out_path, index=False)
    print(f"Wrote {len(merged)} rows to {out_path}")


if __name__ == "__main__":
    main()
