# 07_eda.R
#
# Distributional checks and a first, purely descriptive look at the core
# hypothesis before any modeling. Nothing here controls for anything --
# it's a sanity-check pass, not evidence.
#


library(dplyr)
library(readr)
library(ggplot2)

master <- read_csv("data/master_pitches_2026.csv", show_col_types = FALSE)
challenges_raw <- read_csv("data/challenge_events_2026.csv", show_col_types = FALSE)

cat("== Basic shape ==\n")
cat(sprintf("Games: %d\n", n_distinct(master$game_pk)))
cat(sprintf("Pitches: %d\n", nrow(master)))
cat(sprintf("Umpires: %d\n", n_distinct(master$hp_umpire)))


# Manual cross-check numbers 
# challenge tracker page for the same date range.

mj_challenges <- challenges_raw %>%
  mutate(parsed = lapply(raw_review_block, jsonlite::fromJSON)) %>%
  filter(sapply(parsed, function(p) p$reviewType) == "MJ") %>%
  mutate(success = sapply(parsed, function(p) p$isOverturned))

cat("\n== League-wide ABS challenge totals (compare to B-Ref by eye) ==\n")
cat(sprintf("Total ABS challenges: %d\n", nrow(mj_challenges)))
cat(sprintf("Overall success rate: %.1f%%\n", 100 * mean(mj_challenges$success, na.rm = TRUE)))
cat(sprintf("Avg challenges per game: %.2f\n", nrow(mj_challenges) / n_distinct(master$game_pk)))


# Distributional checks

cat("\n== Pitch-level flag rates ==\n")
cat(sprintf("Challenge-eligible (take) pitches: %.1f%%\n", 100 * mean(master$is_challenge_eligible, na.rm = TRUE)))
cat(sprintf("Borderline rate (of eligible takes): %.1f%%\n",
            100 * mean(master$is_borderline[master$is_challenge_eligible], na.rm = TRUE)))
cat(sprintf("Miss rate (of eligible takes): %.1f%%\n",
            100 * mean(master$is_miss[master$is_challenge_eligible], na.rm = TRUE)))
cat(sprintf("Miss rate (of BORDERLINE eligible takes): %.1f%%\n",
            100 * mean(master$is_miss[master$is_challenge_eligible & master$is_borderline], na.rm = TRUE)))

pitches_per_game <- master %>% count(game_pk)
p1 <- ggplot(pitches_per_game, aes(x = n)) +
  geom_histogram(binwidth = 5) +
  labs(title = "Pitches per game", x = "Pitches", y = "Games")
ggsave("output/eda_pitches_per_game.png", p1, width = 8, height = 5)


# Naive, uncontrolled first look at the core hypothesis: among borderline,
# challenge-eligible pitches, does the miss rate against a team differ
# when that team has zero challenges remaining vs. some remaining?
# This is descriptive only -- no game/umpire/count controls, no fixed
# effects. 

borderline_eligible <- master %>%
  filter(is_challenge_eligible, is_borderline)

naive_batting <- borderline_eligible %>%
  filter(miss_favors == "batting" | is.na(miss_favors)) %>%
  mutate(batting_exhausted = batting_team_challenges_remaining == 0) %>%
  group_by(batting_exhausted) %>%
  summarise(
    n_pitches = n(),
    miss_rate = mean(is_miss, na.rm = TRUE),
    .groups = "drop"
  )

naive_fielding <- borderline_eligible %>%
  filter(miss_favors == "fielding" | is.na(miss_favors)) %>%
  mutate(fielding_exhausted = fielding_team_challenges_remaining == 0) %>%
  group_by(fielding_exhausted) %>%
  summarise(
    n_pitches = n(),
    miss_rate = mean(is_miss, na.rm = TRUE),
    .groups = "drop"
  )

cat("\n== NAIVE (uncontrolled) look: miss rate vs. batting-team challenge exhaustion ==\n")
print(naive_batting)
cat("\n== NAIVE (uncontrolled) look: miss rate vs. fielding-team challenge exhaustion ==\n")
print(naive_fielding)


# Falsification-style check on borderline definition itself: agreement
# rate should be near what step 05 validated (~85%) restricted to the
# actually-challenged subset 

# Duplicate-key check BEFORE the join -- pitch events should be unique per
# (game_pk, at_bat_index, pitch_number) on both sides. A many-to-many join
# below usually means duplication crept in somewhere upstream; find out
# where before deciding whether to widen the join key or fix the source.
dup_master <- master %>%
  count(game_pk, at_bat_index, pitch_number) %>%
  filter(n > 1)
dup_challenges <- mj_challenges %>%
  count(game_pk, at_bat_index, pitch_number) %>%
  filter(n > 1)

cat(sprintf("\n== Duplicate-key check ==\nmaster: %d duplicated (game_pk, at_bat_index, pitch_number) keys\n",
            nrow(dup_master)))
cat(sprintf("mj_challenges: %d duplicated (game_pk, at_bat_index, pitch_number) keys\n",
            nrow(dup_challenges)))
if (nrow(dup_master) > 0) {
  cat("Sample duplicated master keys:\n")
  print(head(dup_master, 5))
}
if (nrow(dup_challenges) > 0) {
  cat("Sample duplicated mj_challenges keys:\n")
  print(head(dup_challenges, 5))
}

challenged_pitches <- master %>%
  inner_join(
    mj_challenges %>% select(game_pk, at_bat_index, pitch_number, success),
    by = c("game_pk", "at_bat_index", "pitch_number")
  )
cat(sprintf(paste0(
  "\nMatched %d master rows to known ABS challenge events ",
  "(expect this to be close to, but not necessarily equal to, the 9,349 used ",
  "in step 05's validation -- some may have been excluded there for missing ",
  "px/pz/sz_top/sz_bot).\n"
), nrow(challenged_pitches)))


# Per-umpire sample sizes -- check before step 09 whether any umpire has
# enough borderline-and-exhausted pitches to say anything about
# individually, vs. needing to lean on shrinkage in the hierarchical model.

umpire_counts <- borderline_eligible %>%
  mutate(either_exhausted = (batting_team_challenges_remaining == 0) |
                            (fielding_team_challenges_remaining == 0)) %>%
  group_by(hp_umpire) %>%
  summarise(
    n_borderline = n(),
    n_exhausted_situations = sum(either_exhausted, na.rm = TRUE),
    .groups = "drop"
  ) %>%
  arrange(desc(n_exhausted_situations))

cat("\n== Per-umpire exhausted-situation counts (top 10) ==\n")
print(head(umpire_counts, 10))
cat("\n== Per-umpire exhausted-situation counts (bottom 10) ==\n")
print(tail(umpire_counts, 10))

write_csv(umpire_counts, "output/eda_umpire_sample_sizes.csv")
cat("\nWrote output/eda_pitches_per_game.png and output/eda_umpire_sample_sizes.csv\n")
