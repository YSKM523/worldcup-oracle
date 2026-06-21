# Phase 4: Scoreline Quality (Dixon-Coles + Goal-Rate) — Design

**Date:** 2026-06-21
**Status:** Approved design, pending spec review
**Scope:** Improve the *scoreline* distribution (exact score, over/under, BTTS) with two evidence-gated levers — a re-estimated goal rate and a Dixon-Coles low-score correlation — validated by a new scoreline metric added to the walk-forward backtest. Ship each lever ON only if it beats baseline on the 2014/2018/2022 World Cups; otherwise ship the no-op and record the result.

---

## 1. Problem

Scorelines come from `prediction/score_predictor.py`: `expected_goals` splits a fixed total (`POISSON_AVG_GOALS = 2.5`) into per-team Poisson means by Elo diff; `score_grid` takes the **independent** outer product of two Poisson PMFs (`np.outer`); `condition_grid` rescales the win/draw/loss blocks to the Davidson outcome masses. Two known weaknesses:

1. **Goal rate is stale.** This World Cup is averaging **3.03 total goals/match** (37 played) vs the static **2.5** — the grid systematically predicts scores that are too low (~21% under).
2. **Independent Poisson under-weights correlated low scores.** Real football has positive draw dependence at 0-0 and 1-1; the outer-product model spreads too little mass there. This is the classic Dixon-Coles (1997) correction.

Symptom: exact-score hit rate is **4/34**. (W/D/L outcome quality is *not* the problem here — `condition_grid` already pins outcomes to the Davidson/Phase-1-calibrated masses; see §6.)

## 2. Goal & Non-Goals

**Goal:** Two evidence-gated scoreline levers — (a) re-estimated goal rate, (b) Dixon-Coles ρ — plus a scoreline metric in the walk-forward backtest and a go/no-go decision wired to it.

**Non-goals (Phase 4):**
- No change to W/D/L outcome probabilities (Phase 1 owns those; §6 explains why Phase 4 cannot move them).
- No new data sources — goal counts come from `data/cache/matches.parquet` / live `wc_df`.
- No bivariate-Poisson or full maximum-likelihood team-attack/defence model (YAGNI; DC τ + rate captures the two measured gaps).

## 3. Binding Principles (consistent with Phase 1/2)

- **Evidence-gated, default OFF / byte-identical.** `DC_RHO = 0.0` ⇒ τ ≡ 1 ⇒ independent Poisson (unchanged). The goal rate defaults to the static `POISSON_AVG_GOALS` (blend weight 0) ⇒ unchanged. A lever ships ON only if the walk-forward backtest improves the scoreline metric **on all three WCs**; otherwise it ships as the no-op and the result is recorded.
- **Walk-forward / no lookahead.** The live goal-rate re-estimate uses only completed matches before each prediction; the backtest predicts each match using strictly prior matches (reuses the Phase-2 `elo_as_of` machinery).
- **Truthfulness.** Report the real backtest numbers; do not ship a lever that doesn't beat baseline. The tuning metric is a proper scoring rule; the intuitive exact-hit% is reported alongside, never used to rig the decision.

## 4. The Two Levers

### 4a. Goal-rate re-estimate (shrinkage, like Phase 1)
Effective total rate = a shrinkage blend of the static prior and the observed tournament rate:
```
effective_rate = (1 - GOAL_RATE_BLEND) * POISSON_AVG_GOALS + GOAL_RATE_BLEND * observed_rate
```
`observed_rate` = mean total goals over completed matches **before** the prediction (live: this WC so far; backtest: prior matches that year). `GOAL_RATE_BLEND ∈ [0,1]`, default **0.0** ⇒ pure static 2.5 (byte-identical). The blend (not a raw swap) keeps the early-tournament rate stable when few matches are in. `effective_rate` is passed as `expected_goals(..., total_goals=effective_rate)`.

### 4b. Dixon-Coles correlation
Multiply the four low-score cells of the grid by the DC τ factor, then renormalize:
```
τ(0,0) = 1 − λ·μ·ρ      τ(0,1) = 1 + λ·ρ
τ(1,0) = 1 + μ·ρ        τ(1,1) = 1 − ρ        τ(x,y) = 1 otherwise
```
where λ = home Poisson mean, μ = away Poisson mean, ρ = `DC_RHO`. With ρ<0: 0-0 and 1-1 inflate, 1-0/0-1 deflate (the empirical draw-dependence). `DC_RHO` default **0.0** ⇒ all τ = 1 ⇒ identical to the current outer product. ρ is selected by the backtest (typical football range ≈ −0.2..0; the grid sweep covers it).

## 5. Walk-Forward Scoreline Backtest (core deliverable)

New `evaluation/backtester.walk_forward_scoreline_backtest(years, grid)`, reusing the Phase-2 per-match walk-forward Elo lookup (`elo_as_of`, strictly-before). For each WC year and each candidate `(rho, blend)`:
1. Walk matches in date order; for each, look up pre-match Elo (`elo_as_of`), compute the W/D/L probs (`match_probabilities`) and the effective rate from prior matches, build the **conditioned DC grid** (`expected_goals` → `score_grid(..., rho)` → `condition_grid` on the outcome probs).
2. Score the **actual** scoreline two ways: the proper **negative log-likelihood** `−log P(actual cell)` (clipped to MAX_GOALS; out-of-grid scores clipped to the max cell), and the **exact-hit** indicator (argmax cell == actual).
3. Aggregate mean NLL and hit-rate per year; baseline is `(rho=0, blend=0)`.

Output: `results/evaluations/scoreline_backtest.csv` with columns `year, rho, blend, mean_nll, hit_rate, n_matches`. Full grid reported (e.g. ρ ∈ {0, −0.05, −0.1, −0.15} × blend ∈ {0, 0.5, 1.0}); no silent truncation.

## 6. Why Phase 4 Cannot Move W/D/L (clean separation)

`condition_grid` rescales each outcome block (i>j, i==j, i<j) to exactly the Davidson `p_win/p_draw/p_loss` (which Phase 1 calibrates). DC and the goal rate reshape the grid *before* conditioning, so they change only the **within-block** scoreline distribution — the argmax cell, P(0-0), over/under, BTTS — never the W/D/L masses. So the gate metric is a **scoreline** metric (NLL / exact-hit), and Phase 4 is orthogonal to Phase 1. (The W/D/L Brier is unchanged by construction; a regression test asserts this.)

## 7. Go / No-Go Gate

- **Ship the best `(rho, blend)`** (possibly only one lever non-zero) **only if** it improves mean OOS scoreline **NLL on all three WCs** and the across-WC average improvement is meaningful (a consistent sign across three independent tournaments is the bar; the backtest is deterministic). Exact-hit% is reported as the headline but is not the deciding metric (too coarse to tune ρ/rate).
- **Otherwise ship the no-op** (`DC_RHO=0.0`, `GOAL_RATE_BLEND=0.0`) and record the result. Each lever is judged independently — it is valid to ship, e.g., the goal-rate blend but not DC, if only one passes.

The chosen `(rho, blend)` and the deciding numbers are recorded in config comments and the evidence report.

## 8. Components & Data Flow

- **`prediction/score_predictor.py`:**
  - `score_grid(lam_a, lam_b, max_goals=MAX_GOALS, rho=0.0)` — apply DC τ to the four low cells when ρ≠0, renormalize; ρ=0 ⇒ unchanged.
  - `predict_scoreline(..., rho=0.0, total_goals=POISSON_AVG_GOALS)` and `ensemble_match_prediction(..., rho=0.0, total_goals=None)` — thread ρ and the effective rate through `expected_goals`/`score_grid`/`condition_grid`. Defaults reproduce current output exactly.
  - `effective_goal_rate(observed_rate, blend)` helper.
- **`evaluation/backtester.py`:** `walk_forward_scoreline_backtest` + NLL/exact-hit scorers + a `run_scoreline_backtest_and_save()` entry writing the CSV.
- **`evaluation/live_scoring.py` / `pipeline/matchday_run.py`:** compute live `observed_rate` from completed `wc_df`, pass `rho=DC_RHO` and `total_goals=effective_goal_rate(observed_rate, GOAL_RATE_BLEND)` into `ensemble_match_prediction`. With both config knobs at 0 ⇒ byte-identical locked predictions/scorelines.
- **`config.py`:** `DC_RHO = 0.0`, `GOAL_RATE_BLEND = 0.0` (chosen from backtest evidence).
- **Dashboard:** none required; existing scoreline fields (`pred_score`, `p_over25`, `p_btts`) automatically improve once the knobs are non-zero. (No emoji / no gradient rules N/A — no UI change.)

Since the scoreline flows through the same `ensemble_match_prediction` chokepoint (Phase 1), the improved grid reaches locked predictions, match cards, and the dashboard automatically.

## 9. Testing

- **`tests/test_score_predictor.py` (extend):** ρ=0 ⇒ `score_grid` byte-identical to the outer product (regression); ρ<0 inflates P(0-0)+P(1-1) and deflates P(1-0)+P(0-1); grid still sums to 1 after DC + renormalize; `effective_goal_rate(blend=0)` returns the static rate; `predict_scoreline`/`ensemble_match_prediction` with defaults reproduce current output (golden); raising the rate shifts mass to higher totals.
- **W/D/L invariance:** a test asserts that for fixed outcome probs, changing ρ or the rate leaves the conditioned block sums (p_home/p_draw/p_away) unchanged (proves §6).
- **`tests/test_backtester_scoreline.py` (new):** synthetic walk-forward asserts no-lookahead (a match scored before its result enters the prior set), NLL and hit-rate are produced, and ρ≠0/blend≠0 change the NLL.
- **Evidence run:** `scripts/run_scoreline_backtest.py` on 2014/2018/2022; capture the real table; apply the §7 gate; set `DC_RHO`/`GOAL_RATE_BLEND` (or leave 0). Full existing suite stays green.

## 10. Out of Scope → Later

- **Phase 3:** extend edge detection from the champion market to per-match markets (independent of scoreline work).
- Bivariate-Poisson / team-level attack-defence ratings; in-play scoreline models.
