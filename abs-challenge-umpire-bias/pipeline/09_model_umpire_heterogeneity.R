# 09_model_umpire_heterogeneity.R
#
# The pooled models in 08 came back null on both sides. That doesn't
# rule out heterogeneity -- individual umpires could show the effect in
# opposite directions and cancel out on average. This adds a random
# slope on the exhaustion indicator by umpire and checks:
#   1. Does allowing per-umpire slopes improve fit at all (LRT against
#      the no-slope model)?
#   2. Do the shrunk per-umpire estimates show any umpires with a real,
#      credible effect once shrinkage accounts for their sample size?
#
# Expect possible convergence/singular-fit warnings here -- some umpires
# have very few exhausted-situation pitches and a variance component estimated near zero for
# the random slope is itself a legitimate finding (no detectable
# heterogeneity), not a failure to report around.

library(dplyr)
library(readr)
library(lme4)
library(broom.mixed)
library(ggplot2)

master <- read_csv("data/master_pitches_2026.csv", show_col_types = FALSE) %>%
  filter(game_pk != 824912)  # see 08_model_pooled.R note on this exclusion

borderline_eligible <- master %>%
  filter(is_challenge_eligible, is_borderline) %>%
  mutate(
    batting_exhausted = batting_team_challenges_remaining == 0,
    fielding_exhausted = fielding_team_challenges_remaining == 0,
    hp_umpire = factor(hp_umpire),
    game_pk = factor(game_pk)
  )

glmer_control <- glmerControl(optimizer = "bobyqa", optCtrl = list(maxfun = 2e5))

data_a <- borderline_eligible %>% filter(is_in_zone == TRUE)
data_b <- borderline_eligible %>% filter(is_in_zone == FALSE)


# Batting-side: no-slope vs. random-slope, with a likelihood ratio test

model_a_noslope <- glmer(
  is_miss ~ batting_exhausted + balls + strikes + outs + score_margin + late_and_close +
    (1 | hp_umpire) + (1 | game_pk),
  data = data_a, family = binomial, control = glmer_control
)

model_a_slope <- glmer(
  is_miss ~ batting_exhausted + balls + strikes + outs + score_margin + late_and_close +
    (1 + batting_exhausted | hp_umpire) + (1 | game_pk),
  data = data_a, family = binomial, control = glmer_control
)

cat("== Batting-side: LRT for random slope on batting_exhausted ==\n")
print(anova(model_a_noslope, model_a_slope))


# Fielding-side: same comparison

model_b_noslope <- glmer(
  is_miss ~ fielding_exhausted + balls + strikes + outs + score_margin + late_and_close +
    (1 | hp_umpire) + (1 | game_pk),
  data = data_b, family = binomial, control = glmer_control
)

model_b_slope <- glmer(
  is_miss ~ fielding_exhausted + balls + strikes + outs + score_margin + late_and_close +
    (1 + fielding_exhausted | hp_umpire) + (1 | game_pk),
  data = data_b, family = binomial, control = glmer_control
)

cat("\n== Fielding-side: LRT for random slope on fielding_exhausted ==\n")
print(anova(model_b_noslope, model_b_slope))


# Extract shrunk per-umpire effect estimates (fixed effect + random slope
# deviation), convert to odds ratios, and rank

extract_umpire_effects <- function(model, slope_term, side_label) {
  fixed_est <- fixef(model)[slope_term]
  re <- ranef(model, condVar = TRUE)$hp_umpire
  slope_col <- names(re)[names(re) == slope_term]

  umpire_effects <- tibble(
    hp_umpire = rownames(re),
    random_deviation = re[[slope_col]],
    total_log_odds = fixed_est + re[[slope_col]]
  ) %>%
    mutate(
      odds_ratio = exp(total_log_odds),
      side = side_label
    ) %>%
    arrange(desc(odds_ratio))

  umpire_effects
}

umpire_effects_a <- extract_umpire_effects(model_a_slope, "batting_exhaustedTRUE", "batting_side")
umpire_effects_b <- extract_umpire_effects(model_b_slope, "fielding_exhaustedTRUE", "fielding_side")

cat("\n== Batting-side: umpires with largest shrunk exhaustion effect (top 10) ==\n")
print(head(umpire_effects_a, 10))
cat("\n== Batting-side: umpires with smallest/most-negative shrunk exhaustion effect (bottom 10) ==\n")
print(tail(umpire_effects_a, 10))

cat("\n== Fielding-side: umpires with largest shrunk exhaustion effect (top 10) ==\n")
print(head(umpire_effects_b, 10))
cat("\n== Fielding-side: umpires with smallest/most-negative shrunk exhaustion effect (bottom 10) ==\n")
print(tail(umpire_effects_b, 10))


# Caterpillar plots -- shrunk odds ratio per umpire, sorted

plot_caterpillar <- function(umpire_effects, title, out_path) {
  p <- umpire_effects %>%
    mutate(hp_umpire = reorder(hp_umpire, odds_ratio)) %>%
    ggplot(aes(x = hp_umpire, y = odds_ratio)) +
    geom_point() +
    geom_hline(yintercept = 1, linetype = "dashed", color = "red") +
    coord_flip() +
    labs(title = title, x = "Umpire", y = "Shrunk odds ratio (exhaustion effect)") +
    theme_minimal(base_size = 7)
  ggsave(out_path, p, width = 8, height = 14)
}

dir.create("output", showWarnings = FALSE)
plot_caterpillar(umpire_effects_a, "Batting-side exhaustion effect by umpire (shrunk)",
                  "output/umpire_effects_batting.png")
plot_caterpillar(umpire_effects_b, "Fielding-side exhaustion effect by umpire (shrunk)",
                  "output/umpire_effects_fielding.png")

saveRDS(model_a_slope, "output/model_a_slope.rds")
saveRDS(model_b_slope, "output/model_b_slope.rds")
write_csv(umpire_effects_a, "output/umpire_effects_batting.csv")
write_csv(umpire_effects_b, "output/umpire_effects_fielding.csv")

cat("\nSaved model_a_slope.rds, model_b_slope.rds, umpire_effects_batting/fielding.csv/.png\n")
