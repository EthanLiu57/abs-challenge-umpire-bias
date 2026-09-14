# 11_cost_comparison.R
#
# Compares two season-level costs of a team's challenge inventory hitting
# zero:
#   Cost A (deterrence cost)   - excess run value lost to umpire bias once
#                                a team has zero challenges remaining
#   Cost B (forgone-overturn)  - run value left on the table by teams that
#                                conserved a challenge instead of using it
# INPUTS:
#   data/master_pitches_2026.csv
#       game_pk, at_bat_index, pitch_number, hp_umpire,
#       batting_team, fielding_team,
#       batting_team_challenges_remaining, fielding_team_challenges_remaining,
#       is_borderline (reasonable-challenge-opportunity flag),
#       miss_flag, miss_favors ("batting" | "fielding"),
#       run_value  (signed delta run expectancy of the call actually made,
#                   from the batting team's perspective)
#   data/challenge_events_2026.csv (post step-02 parsing, cleaned)
#       game_pk, team, at_bat_index, pitch_number, success (TRUE/FALSE),
#       run_value_if_overturned
#   models/umpire_effects.csv (output of 08/09 hierarchical model)
#       hp_umpire, excess_miss_prob, excess_miss_prob_se
#
# OUTPUT:
#   output/cost_comparison_by_umpire.csv
#   output/cost_comparison_league_total.csv
#   output/cost_comparison_plot.png

library(dplyr)
library(readr)
library(ggplot2)

dir.create("output", showWarnings = FALSE)

pitches <- read_csv("data/master_pitches_2026.csv", show_col_types = FALSE)
challenges <- read_csv("data/challenge_events_2026.csv", show_col_types = FALSE)
umpire_effects <- read_csv("models/umpire_effects.csv", show_col_types = FALSE)


# Cost A: deterrence cost
#
# For every borderline pitch where the disadvantaged team (whichever side
# the miss would favor against) has zero challenges remaining, multiply
# that umpire's estimated excess miss probability by the run value of the
# call, and sum.


cost_a_pitches <- pitches %>%
  filter(is_borderline) %>%
  mutate(
    exhausted_team_at_risk = case_when(
      batting_team_challenges_remaining == 0 ~ "batting",
      fielding_team_challenges_remaining == 0 ~ "fielding",
      TRUE ~ NA_character_
    )
  ) %>%
  filter(!is.na(exhausted_team_at_risk)) %>%
  left_join(umpire_effects, by = "hp_umpire") %>%
  mutate(
    # run_value is signed from the batting team's perspective; flip sign
    # when the exhausted team is on defense so "cost" is always positive
    # harm to the exhausted team
    signed_cost = if_else(
      exhausted_team_at_risk == "batting",
      excess_miss_prob * abs(run_value),
      excess_miss_prob * abs(run_value)
    )
  )

cost_a_by_umpire <- cost_a_pitches %>%
  group_by(hp_umpire) %>%
  summarise(cost_a_total = sum(signed_cost, na.rm = TRUE), .groups = "drop")

cost_a_league_total <- sum(cost_a_by_umpire$cost_a_total, na.rm = TRUE)


# Cost B: forgone-overturn cost
# League-average inputs first.


league_avg_success_rate <- challenges %>%
  summarise(rate = mean(success, na.rm = TRUE)) %>%
  pull(rate)

league_avg_overturn_value <- challenges %>%
  filter(success) %>%
  summarise(v = mean(run_value_if_overturned, na.rm = TRUE)) %>%
  pull(v)

# Team-games that finished with >=1 unused challenge (conserved). Assumes
# a separate per-team-game challenge tally is derivable from the raw
# challenge log -- adjust once the actual starting-allotment /
# replenishment-on-overturn rules from step 04 are nailed down.
conserved_team_games <- challenges %>%
  group_by(game_pk, team) %>%
  summarise(challenges_used = n(), .groups = "drop") %>%
  # NOTE: placeholder threshold -- replace `2` with the real starting
  # allotment logic from 04_reconstruct_challenge_state.py, including any
  # replenishment from successful challenges
  filter(challenges_used < 2)

# For each conserved team-game, find the point after which they still held
# a challenge but stopped using it (last actual challenge, or start of
# game if none used), then count eligible borderline misses against them
# after that point.
last_challenge_by_game <- challenges %>%
  group_by(game_pk, team) %>%
  summarise(last_challenge_pitch = max(pitch_number, na.rm = TRUE), .groups = "drop")

cost_b_pitches <- pitches %>%
  filter(is_borderline) %>%
  inner_join(conserved_team_games, by = c("game_pk" = "game_pk")) %>%
  # keep only misses against the conserving team
  filter(
    (team == batting_team & miss_favors == "fielding") |
    (team == fielding_team & miss_favors == "batting")
  ) %>%
  left_join(last_challenge_by_game, by = c("game_pk", "team")) %>%
  mutate(last_challenge_pitch = coalesce(last_challenge_pitch, 0)) %>%
  filter(pitch_number > last_challenge_pitch)

cost_b_by_umpire <- cost_b_pitches %>%
  mutate(forgone_value = league_avg_success_rate * league_avg_overturn_value) %>%
  group_by(hp_umpire) %>%
  summarise(cost_b_total = sum(forgone_value, na.rm = TRUE), .groups = "drop")

cost_b_league_total <- sum(cost_b_by_umpire$cost_b_total, na.rm = TRUE)


# Combine and write output


comparison_by_umpire <- full_join(cost_a_by_umpire, cost_b_by_umpire, by = "hp_umpire") %>%
  mutate(
    cost_a_total = coalesce(cost_a_total, 0),
    cost_b_total = coalesce(cost_b_total, 0),
    net_deterrence_dominance = cost_a_total - cost_b_total
  ) %>%
  arrange(desc(net_deterrence_dominance))

write_csv(comparison_by_umpire, "output/cost_comparison_by_umpire.csv")

league_total <- tibble::tibble(
  cost_a_league_total = cost_a_league_total,
  cost_b_league_total = cost_b_league_total,
  net_deterrence_dominance = cost_a_league_total - cost_b_league_total
)
write_csv(league_total, "output/cost_comparison_league_total.csv")

# Plot: which umpires show Cost A >> Cost B (candidates for "never use your
# last challenge against this ump") vs. the reverse
plot_data <- comparison_by_umpire %>%
  tidyr::pivot_longer(
    cols = c(cost_a_total, cost_b_total),
    names_to = "cost_type",
    values_to = "run_value"
  )

p <- ggplot(plot_data, aes(x = reorder(hp_umpire, run_value), y = run_value, fill = cost_type)) +
  geom_col(position = "dodge") +
  coord_flip() +
  labs(
    title = "Deterrence cost vs. forgone-overturn cost by umpire",
    x = "Home plate umpire",
    y = "Run value (season total)",
    fill = "Cost type"
  ) +
  theme_minimal()

ggsave("output/cost_comparison_plot.png", p, width = 10, height = 8)

cat(sprintf(
  "League totals -- Cost A: %.2f runs, Cost B: %.2f runs, net: %.2f\n",
  cost_a_league_total, cost_b_league_total,
  cost_a_league_total - cost_b_league_total
))
