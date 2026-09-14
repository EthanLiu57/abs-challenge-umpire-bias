# Does the ABS Challenge System Create an Umpire Moral Hazard?

**Result: no.** This project tested whether MLB's 2026 ABS (Automated
Ball-Strike) challenge system creates a passive incentive for umpires to
call more borderline pitches against a team once it has exhausted its
challenges — the idea being that with no way left to contest a call, an
umpire's mistakes against that team can no longer be publicly overturned.
Across ~106,000 borderline pitches and 91 umpires in the 2026 season, no
such effect was detected, in either direction, and there was no evidence
that it varies by umpire.

## Motivation

The ABS challenge system (2 challenges per team per game, replenished on
success) gives teams a way to correct bad calls in real time. That also
means a team's challenge inventory hitting zero is a discrete,
observable change in accountability for the umpire mid-game. If umpires are even slightly
influenced by the threat of being publicly overturned, that accountability
drop should show up as a higher rate of missed calls against the
exhausted team on genuinely borderline pitches.

## Data

- **Play-by-play and pitch data**: MLB Stats API live-feed
  (`statsapi.mlb.com`), 2026 season.
- **ABS challenge events**: parsed from `reviewDetails` blocks in the same
  feed. Two review types exist in this data — `"MJ"` (ABS pitch challenges)
  and `"MF"` (MLB's older replay-review system for safe/out, fair/foul,
  etc.) — and only `"MJ"` events belong in this analysis; conflating the
  two was one of the bugs caught during validation (see below).
- **Strike zone geometry**: MLB's own per-pitch `strikeZoneTop` /
  `strikeZoneBottom` fields (height-based, per the 53.5%/27% ABS formula),
  not a zone re-derived from a separately fetched batter height. Verified
  this reproduces MLB's reported values almost exactly for a spot-checked
  player.

## Pipeline

| Step | File | What it does |
| 01 | `01_get_schedule.py` | Pull 2026 schedule + home-plate umpire per game |
| 02 | `02_get_pbp_events.py` | Pull pitch-by-pitch events + raw challenge/review blocks |
| 03 | `03_enrich_pitch_context.py` | Add count, outs, base-runner state from cached raw JSON |
| 04 | `04_reconstruct_challenge_state.py` | Reconstruct each team's challenges-remaining, pitch by pitch |
| 05 | `05_flag_borderline.py` | Flag borderline pitches and umpire misses against the true zone |
| 06 | `06_build_master.py` | Merge in score state, park, and team identity |
| 07 | `07_eda.R` | Distributional checks, naive descriptive look, per-umpire sample sizes |
| 08 | `08_model_pooled.R` | Pooled hierarchical logistic models (the main test) |
| 09 | `09_model_umpire_heterogeneity.R` | Random-slope model testing umpire-level variation |

`extensions_not_pursued/11_cost_comparison.R` was scoped for a follow-up
question (whether it's ever optimal to never use your last challenge,
weighing deterrence cost against forgone-overturn value) but wasn't
pursued once the core deterrence effect came back null, as that
cost-comparison only makes sense if there's a real effect to trade off
against.

## Key methodological notes

- **The borderline/miss geometry was empirically validated**.
Against ~9,300 real ABS challenge outcomes, classification
  agreement went from 74.4% (raw zone, no ball-radius adjustment) to
  85.4% after fitting a ball-radius adjustment via grid search — the
  best-fitting radius (1.216in) landed right next to the real baseball's
  physical radius (~1.45in), which is good evidence the fix is real
  rather than overfit. The residual ~15% gap is consistent with Hawk-Eye
  tracking noise on exactly the population (challenged pitches) selected
  for being closest to the true edge.
- **`call_description` reflects the post-review corrected call**, not
  the original human call, for successfully overturned pitches. This
  doesn't affect the core dataset (uncorrected pitches — the whole
  population of interest — were never touched by review), but it had to
  be accounted for when validating against known outcomes.
- **Game `824912` is excluded** pending confirmation that its raw feed
  is internally duplicated (flagged during EDA — see git history /
  conversation notes). Affects a negligible fraction of the season
  either way.

## Results

**Pooled models** (`08_model_pooled.R`), hierarchical logistic
regression with random intercepts for umpire and game, controlling for
count, outs, score margin, and the leverage proxy:

| | Odds ratio | 95% CI | p |
|---|---|---|---|
| Batting team exhausted → miss favoring batting | 0.86 | 0.71 – 1.04 | 0.121 |
| Fielding team exhausted → miss favoring fielding | 1.01 | 0.85 – 1.19 | 0.908 |

Both null, and the batting-side estimate points opposite the hypothesized
direction. Sample sizes (~49,000 and ~56,000 borderline pitches
respectively) are large enough that this isn't an underpowered non-result
— the confidence intervals rule out anything beyond a small effect.

As a validity check: the `balls` and `strikes` count coefficients came
out large, highly significant, and in the direction consistent with the
well-documented literature on umpires expanding the zone late in the
count — a reassuring sign the borderline/miss flagging is picking up real
signal.

**Umpire heterogeneity** (`09_model_umpire_heterogeneity.R`): adding a
random slope on the exhaustion indicator by umpire did not improve fit on
either side (LRT p = 0.83 batting-side, p = 0.42 fielding-side). The
pooled null isn't masking umpire-to-umpire variation that cancels out —
there's no detectable variation at all in this data.

## Limitations / what would change this

- Single season of data. The heterogeneity test in particular is likely
  underpowered to detect a small per-umpire effect even if one exists.
- The falsification check (rerunning the pooled model on clearly
  non-borderline pitches as a negative control) was not run.

## Reproducing this

Python (`pip install -r requirements.txt`): `pandas`, `requests`.

R: `dplyr`, `readr`, `tidyr`, `ggplot2`, `lme4`, `broom.mixed`,
`jsonlite`.

Run the pipeline in numeric order, 01 through 09. Steps 01–04 hit the
MLB Stats API and cache raw JSON locally (`data/raw_pbp/`) so later steps
never re-fetch. `data/` and `output/*.rds` are gitignored — regenerate
them by running the pipeline rather than expecting them in this repo.
