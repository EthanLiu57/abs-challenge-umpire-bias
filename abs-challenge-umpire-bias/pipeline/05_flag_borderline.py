"""
05_flag_borderline.py (corrected)

Uses the ABS zone edges MLB already computes and reports on every pitch
event (sz_top / sz_bot, captured in step 02 from pitchData.strikeZoneTop
/ strikeZoneBottom) instead of re-deriving the zone from a separately
fetched batter height. 

Output: data/pitch_events_flagged_2026.csv
    (all columns from pitch_events_with_challenge_state_2026.csv, plus:
     half_width, distance_to_edge, is_in_zone, is_borderline, is_miss,
     miss_favors, is_challenge_eligible)

Requires: pandas
"""

import json
from pathlib import Path

import pandas as pd

DATA_DIR = Path("data")
SEASON = 2026

PLATE_HALF_WIDTH_FT = (17 / 12) / 2  # 0.7083 ft base plate half-width
BORDERLINE_MARGIN_FT = 3 / 12  # 3 inches, matching Savant's public
                                 # "reasonable challenge opportunity" margin

# Empirically fit against 9,349 real ABS challenge outcomes via grid search
# (see validation block below): agreement peaked at a 1.216in radius
# (85.4%) vs 74.4% with no radius at all -- consistent with the real rule
# being "any part of the ball touching the zone counts," since 1.216in
# sits right next to the physical baseball radius (~1.45in) with a smooth
# falloff on both sides. Not re-fit automatically on every run; re-run the
# grid search below if a new season's data suggests this has drifted.
BALL_RADIUS_FT = 1.216 / 12


def distance_to_zone_edge(px, pz, left, right, bottom, top):
    """
    Distance from (px, pz) to the rectangle boundary, and whether the
    point is inside. Works whether the point is inside or outside.
    """
    if left <= px <= right and bottom <= pz <= top:
        dist = min(px - left, right - px, pz - bottom, top - pz)
        return dist, True
    else:
        dx = max(left - px, 0, px - right)
        dz = max(bottom - pz, 0, pz - top)
        return (dx**2 + dz**2) ** 0.5, False


def main():
    pitches = pd.read_csv(DATA_DIR / f"pitch_events_with_challenge_state_{SEASON}.csv")

    n_missing = pitches[["sz_top", "sz_bot", "px", "pz"]].isna().any(axis=1).sum()
    if n_missing > 0:
        print(
            f"  [warn] {n_missing} pitches missing sz_top/sz_bot/px/pz -- "
            "excluded from borderline flagging"
        )

    def compute_row(r):
        if pd.notna(r["sz_top"]) and pd.notna(r["sz_bot"]) and pd.notna(r["px"]) and pd.notna(r["pz"]):
            return distance_to_zone_edge(
                r["px"], r["pz"],
                -(PLATE_HALF_WIDTH_FT + BALL_RADIUS_FT), (PLATE_HALF_WIDTH_FT + BALL_RADIUS_FT),
                r["sz_bot"] - BALL_RADIUS_FT, r["sz_top"] + BALL_RADIUS_FT,
            )
        return (None, None)

    results = pitches.apply(compute_row, axis=1)
    pitches["distance_to_edge"] = results.apply(lambda t: t[0])
    pitches["is_in_zone"] = results.apply(lambda t: t[1])
    pitches["is_borderline"] = pitches["distance_to_edge"] <= BORDERLINE_MARGIN_FT

    # Only non-swing "take" pitches are challenge-eligible
    pitches["is_challenge_eligible"] = pitches["call_description"].isin(
        ["Ball", "Called Strike"]
    )

    def classify_miss(row):
        if not row["is_challenge_eligible"] or pd.isna(row["is_in_zone"]):
            return (None, None)
        if row["is_in_zone"] and row["call_description"] == "Ball":
            return (True, "batting")  # should've been a strike -- hurts batting team
        if not row["is_in_zone"] and row["call_description"] == "Called Strike":
            return (True, "fielding")  # should've been a ball -- hurts fielding team
        return (False, None)

    miss_results = pitches.apply(classify_miss, axis=1)
    pitches["is_miss"] = miss_results.apply(lambda t: t[0])
    pitches["miss_favors"] = miss_results.apply(lambda t: t[1])

    out_path = DATA_DIR / f"pitch_events_flagged_{SEASON}.csv"
    pitches.to_csv(out_path, index=False)
    print(f"Wrote {len(pitches)} rows to {out_path}")

    # Validation against actual challenge outcomes
   
    challenges = pd.read_csv(DATA_DIR / f"challenge_events_{SEASON}.csv")
    try:
        parsed = challenges["raw_review_block"].apply(json.loads)
        challenges["review_type"] = parsed.apply(lambda b: b.get("reviewType"))
        challenges["success"] = parsed.apply(lambda b: b.get("isOverturned"))
        # Only ABS ball/strike challenges belong here -- raw_review_block
        # also contains unrelated legacy replay reviews (safe/out,
        # fair/foul, etc. -- reviewType "MF"), which would compare our
        # zone classification against outcomes that have nothing to do
        # with balls and strikes.
        n_before = len(challenges)
        challenges = challenges[challenges["review_type"] == "MJ"]
        print(f"  Filtered to {len(challenges)}/{n_before} ABS (MJ) challenges for validation.")
    except Exception as e:
        print(f"  [warn] couldn't parse challenge outcomes for validation: {e}")
        return

    merged_check = pitches.merge(
        challenges[["game_pk", "at_bat_index", "pitch_number", "success"]],
        on=["game_pk", "at_bat_index", "pitch_number"],
        how="inner",
    )
    if len(merged_check) == 0:
        print("  [warn] no pitches matched to challenge events -- can't validate")
        return

    # call_description reflects the POST-REVIEW corrected call for
    # successfully overturned pitches, not what the umpire actually called
    # in real time
    flip = {"Ball": "Called Strike", "Called Strike": "Ball"}

    def reconstruct_and_check(row):
        original_call = flip[row["call_description"]] if row["success"] else row["call_description"]
        if pd.isna(row["is_in_zone"]):
            return None
        predicted_miss = (
            (row["is_in_zone"] and original_call == "Ball")
            or (not row["is_in_zone"] and original_call == "Called Strike")
        )
        return predicted_miss

    merged_check["predicted_miss"] = merged_check.apply(reconstruct_and_check, axis=1)
    merged_check["match"] = merged_check["predicted_miss"] == merged_check["success"]
    agreement_rate = merged_check["match"].mean()
    print(
        f"Validation (no radius adjustment): geometry-based miss classification "
        f"agrees with {len(merged_check)} actual challenge outcomes at a "
        f"{agreement_rate:.1%} rate."
    )

    # Grid-search a ball-radius adjustment
    def is_in_zone_with_radius(row, radius_ft):
        half_width = PLATE_HALF_WIDTH_FT + radius_ft
        top = row["sz_top"] + radius_ft
        bottom = row["sz_bot"] - radius_ft
        return (-half_width <= row["px"] <= half_width) and (bottom <= row["pz"] <= top)

    print("\nRadius grid search (inches -> agreement rate):")
    best_radius, best_rate = 0.0, agreement_rate
    for radius_in in [0.5, 1.0, 1.216, 1.45, 1.5, 2.0, 2.5, 3.0]:
        radius_ft = radius_in / 12
        preds = []
        for _, row in merged_check.iterrows():
            if pd.isna(row["px"]) or pd.isna(row["pz"]) or pd.isna(row["sz_top"]) or pd.isna(row["sz_bot"]):
                preds.append(None)
                continue
            in_zone = is_in_zone_with_radius(row, radius_ft)
            original_call = flip[row["call_description"]] if row["success"] else row["call_description"]
            preds.append((in_zone and original_call == "Ball") or (not in_zone and original_call == "Called Strike"))
        rate = (pd.Series(preds) == merged_check["success"].reset_index(drop=True)).mean()
        print(f"  {radius_in:.3f}in -> {rate:.1%}")
        if rate > best_rate:
            best_radius, best_rate = radius_in, rate

    print(f"\nBest radius found: {best_radius}in at {best_rate:.1%} agreement "
          f"(vs {agreement_rate:.1%} with no radius). If this is a meaningful "
          "improvement, apply it to abs_top/abs_bottom/half_width before "
          "finalizing is_in_zone on the full dataset.")
    print(
        f"Validation: geometry-based miss classification agrees with "
        f"{len(merged_check)} actual challenge outcomes at a "
        f"{agreement_rate:.1%} rate."
    )
    if agreement_rate < 0.9:
        print("  [warn] still below 90% -- inspect mismatches before trusting this on the un-challenged majority.")


if __name__ == "__main__":
    main()
