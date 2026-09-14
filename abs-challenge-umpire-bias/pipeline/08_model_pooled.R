# 08_model_pooled.R
#
# Pooled test of the core hypothesis: does a team's own challenge
# exhaustion predict a higher rate of the umpire missing borderline
# calls against them? Two directional models, since a "batting-favoring
# miss" and a "fielding-favoring miss" are only possible for disjoint
# populations of pitches (a pitch can't be wrongly called both ways):
#
#   Model A: among truly IN-ZONE borderline pitches (where the only
#            possible miss is an incorrect "Ball" call hurting the
#            batting team), does batting_team_challenges_remaining == 0
#            predict is_miss?
#   Model B: among truly OUT-OF-ZONE borderline pitches (where the only
#            possible miss is an incorrect "Called Strike" hurting the
#            fielding team), does fielding_team_challenges_remaining == 0
#            predict is_miss?
#
# This differs slightly from 07_eda.R's naive tables, which used a
# looser filter (excluding only misses favoring the other side, rather
# than restricting to the population where a same-side miss is even
# possible). This version is the more principled one -- expect small
# numeric differences from the EDA printout, not a discrepancy to chase.
#
# NOTE: game_pk 824912 is excluded pending confirmation of the raw-feed
# duplication flagged in the EDA step (about 310 duplicated pitch rows
# traced to that single game). Remove this filter once that's confirmed
# either way -- it affects a negligible fraction of the season either way.

library(dplyr)
library(readr)
library(lme4)
library(broom.mixed)

master <- read_csv("data/master_pitches_2026.csv", show_col_types = FALSE) %>%
  filter(game_pk != 824912)

borderline_eligible <- master %>%
  filter(is_challenge_eligible, is_borderline) %>%
  mutate(
    batting_exhausted = batting_team_challenges_remaining == 0,
    fielding_exhausted = fielding_team_challenges_remaining == 0,
    hp_umpire = factor(hp_umpire),
    game_pk = factor(game_pk)
  )

glmer_control <- glmerControl(optimizer = "bobyqa", optCtrl = list(maxfun = 2e5))


# Model A: batting-side deterrence effect

data_a <- borderline_eligible %>% filter(is_in_zone == TRUE)
cat(sprintf("Model A (batting-side) data: %d pitches, %d exhausted-situation pitches\n",
            nrow(data_a), sum(data_a$batting_exhausted, na.rm = TRUE)))

model_a <- glmer(
  is_miss ~ batting_exhausted + balls + strikes + outs + score_margin + late_and_close +
    (1 | hp_umpire) + (1 | game_pk),
  data = data_a,
  family = binomial,
  control = glmer_control
)

cat("\n== Model A summary (batting-side) ==\n")
print(summary(model_a))

coef_a <- tidy(model_a, effects = "fixed", conf.int = TRUE) %>%
  filter(term == "batting_exhaustedTRUE") %>%
  mutate(odds_ratio = exp(estimate), or_low = exp(conf.low), or_high = exp(conf.high))
cat("\n== Model A key coefficient (odds ratio for batting team exhausted) ==\n")
print(coef_a %>% select(term, estimate, std.error, p.value, odds_ratio, or_low, or_high))


# Model B: fielding-side deterrence effect

data_b <- borderline_eligible %>% filter(is_in_zone == FALSE)
cat(sprintf("\nModel B (fielding-side) data: %d pitches, %d exhausted-situation pitches\n",
            nrow(data_b), sum(data_b$fielding_exhausted, na.rm = TRUE)))

model_b <- glmer(
  is_miss ~ fielding_exhausted + balls + strikes + outs + score_margin + late_and_close +
    (1 | hp_umpire) + (1 | game_pk),
  data = data_b,
  family = binomial,
  control = glmer_control
)

cat("\n== Model B summary (fielding-side) ==\n")
print(summary(model_b))

coef_b <- tidy(model_b, effects = "fixed", conf.int = TRUE) %>%
  filter(term == "fielding_exhaustedTRUE") %>%
  mutate(odds_ratio = exp(estimate), or_low = exp(conf.low), or_high = exp(conf.high))
cat("\n== Model B key coefficient (odds ratio for fielding team exhausted) ==\n")
print(coef_b %>% select(term, estimate, std.error, p.value, odds_ratio, or_low, or_high))


# Save models and coefficient summaries for later steps (09 heterogeneity,
# writeup) without needing to refit

dir.create("output", showWarnings = FALSE)
saveRDS(model_a, "output/model_a_batting.rds")
saveRDS(model_b, "output/model_b_fielding.rds")
write_csv(bind_rows(
  coef_a %>% mutate(model = "batting_side"),
  coef_b %>% mutate(model = "fielding_side")
), "output/pooled_model_coefficients.csv")

cat("\nSaved model_a_batting.rds, model_b_fielding.rds, pooled_model_coefficients.csv\n")
