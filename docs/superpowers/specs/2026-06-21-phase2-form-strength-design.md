# Phase 2: Team Real-Time Strength (Residual Form Signal) — Design

**Date:** 2026-06-21
**Status:** Approved design, pending spec review
**Scope:** Add a residualized recent-form adjustment to live team strength, gated by a new walk-forward in-tournament backtest. Ship it ON only if it improves out-of-sample accuracy on the 2014/2018/2022 World Cups; otherwise ship the no-op and document the negative result.

---

## 1. Problem

Live team strength is `live_elo = tsfm_forecast + (current_elo − asof_elo)` (`prediction/ensemble.py:28-33`). Elo reacts to results via a World-Cup K-factor of 60 plus a margin-of-victory multiplier `g = 1 + ln(1+|gd|)` (`data/elo.py:35-37, 93-94`). The open question for "real-time strength": **does Elo under-adjust during a tournament** — i.e., does a team that is over/under-performing its Elo expectation in its group games carry momentum that Elo's K-update hasn't fully priced in? If so, a small form nudge improves in-tournament predictions; if not, it is noise.

This is genuinely uncertain (K=60 is already responsive), so the feature is **evidence-gated**: it defaults OFF and is only enabled with backtest proof.

## 2. Goal & Non-Goals

**Goal:** A residual-form Elo adjustment, plus a walk-forward in-tournament backtest that measures its out-of-sample value on past World Cups, and a go/no-go decision wired to that evidence.

**Non-goals (Phase 2):**
- No daily TSFM snapshot refresh (separate, low-value lever; explicitly deferred).
- No new data sources — residuals derive from final scores already in `data/cache/matches.parquet` (no xG).
- No reviving `data/feature_engineering.py` wholesale (it computes *raw* rolling form, which double-counts — see §6). We build a focused new `prediction/form.py` instead.
- No change to Phase 1 calibration.

## 3. Binding Principles

- **Evidence-gated shipping (the truthfulness backbone).** The form signal is controlled by `FORM_LAMBDA` (config), default **0.0 ⇒ byte-identical to current behaviour**. A non-zero λ is committed ONLY if the walk-forward backtest shows a real out-of-sample improvement (§7). If it does not, we ship λ=0 and record the negative result honestly — we do not ship a signal just because we built it.
- **Walk-forward / no lookahead.** The form residual for predicting matchday *d* uses only matches with `kickoff < d`. The backtest predicts each matchday using strictly prior matches. No future information ever enters a prediction or its score.
- **No double-counting.** The signal is a *residual* — performance relative to Elo expectation — and is small and capped, so it nudges only the part Elo has not yet absorbed, never re-rewarding raw results (§6).

## 4. The Residual Form Signal

For a team T with played tournament matches `m_1..m_k` (each before the prediction time):

- **Points-residual variant:** per match, `actual_points − E_elo[points]`, where actual ∈ {3 win, 1 draw, 0 loss} and `E_elo[points] = 3·P(win) + 1·P(draw)` from `match_probabilities` evaluated at T's Elo *as of that match's kickoff*. `residual = mean over m_1..m_k`. Units: points (≈ [−3, +3]).
- **GD-residual variant:** per match, `actual_gd − E_elo[gd]`, where `E_elo[gd] = λ_home − λ_away` from `expected_goals` (`prediction/score_predictor.py:25-41`). `residual = mean`. Units: goals.

The Elo bump applied to live strength:

```
form_bump(T) = clamp(FORM_LAMBDA * residual(T), -FORM_CAP, +FORM_CAP)
live_elo(T) = tsfm_forecast(T) + (current_elo(T) - asof_elo(T)) + form_bump(T)
```

`FORM_LAMBDA` (Elo points per unit residual) and the chosen variant are set from backtest evidence. `FORM_CAP` (e.g. 100 Elo) bounds the nudge so a hot streak can't dominate the rating. With `FORM_LAMBDA = 0`, `form_bump ≡ 0` and live strength is unchanged.

`prediction/form.py` (new, pure, unit-tested) exposes:
- `points_residual(matches, elo_lookup) -> float`
- `gd_residual(matches, elo_lookup) -> float`
- `form_bump(residual, lam, cap) -> float`

where `matches` is the team's played-match records (opponent, scores, the team's Elo at kickoff) and `elo_lookup`/probabilities come from the existing predictors. The module does no I/O.

## 5. Walk-Forward In-Tournament Backtest (core deliverable)

Extends `evaluation/backtester.py`. The existing backtest forecasts champions at a fixed pre-tournament horizon (`backtest_elo_baseline:299`, `backtest_tsfm:439`, week-4 cutoff `:481-483`); it has **no in-tournament loop**. We add one.

**Data source:** actual historical WC matches from `data/cache/matches.parquet` — verified to hold all 64 matches each for 2014, 2018, 2022 with `home_score/away_score/date` (`tournament == "FIFA World Cup"`). This is per-match granularity, exactly what a walk-forward needs.

**Isolation:** the backtest measures the *marginal* value of the form bump on top of the Elo-through-played-matches strength (the realized-delta analog). It does NOT run the TSFM models in the loop — TSFM is a frozen base the bump adds to identically, so including it would only add cost and noise. Base strength in the backtest = Elo rebuilt from all internationals before the tournament, with each WC match folded in as it "happens."

**Loop (per WC year, per candidate `(variant, λ)`):**
1. Build Elo history from `matches.parquet` up to the tournament start.
2. Order that year's WC matches by date into matchdays.
3. For each matchday *d* (left to right): predict every match in *d* using `match_probabilities` on `Elo(through < d) + form_bump(variant, λ; matches < d)`; score 3-way (group) / 2-way (knockout) Brier against the actual result; then fold matchday *d*'s real results into Elo before moving on.
4. Accumulate mean match Brier over the year.

**Output:** a table of mean OOS match Brier per `(variant, λ)` per WC year and averaged across all three, written to `results/evaluations/form_backtest.csv`. `λ = 0` is the baseline row.

A small grid is swept (e.g. λ ∈ {0, 25, 50, 100, 150} Elo-per-unit × {points, gd}); the grid is a fitting choice, reported in full (no silent truncation).

## 6. Double-Counting Mitigation

The realized-delta term `(current_elo − asof_elo)` already encodes win-rate and margin (Elo K·g·(S−E), `data/elo.py:93-94`). The form signal avoids re-rewarding it by being a **residual against Elo expectation**: if a team performs exactly as Elo predicted, `residual = 0` and there is no bump. A non-zero bump only fires when results deviate from what Elo already expected — the component Elo has *not* yet priced — and even then it is capped. The backtest is the ultimate guard: if residual form merely echoes the Elo delta, λ=0 wins and we ship the no-op.

## 7. Go / No-Go Gate

After the backtest:
- **Ship λ>0** (the best `(variant, λ)`) only if it improves mean OOS match Brier **on all three WCs** (not just one) and the across-WC average improvement is meaningful (target ≥ ~0.5% relative, i.e. not within run-to-run noise — the backtest is deterministic, so any consistent sign across three independent tournaments is the real bar).
- **Otherwise ship λ=0** (`FORM_LAMBDA = 0.0`, the no-op) and write the negative result into the spec/PR and a short note in `results/evaluations/form_backtest.csv`'s companion log. The code path stays (cheap, off) so it can be revisited with more data.

The chosen `(variant, λ)` and the deciding numbers are recorded in config comments and the evidence report.

## 8. Components & Data Flow

- **`prediction/form.py`** (new, pure): residual + bump math. Unit-tested.
- **`evaluation/backtester.py`** (extend): `walk_forward_form_backtest(years, grid) -> DataFrame`; a `__main__`/script entry to run it and write `form_backtest.csv`.
- **`prediction/ensemble.py:live_model_elos`**: add `form_bump` as a third addend, reading `FORM_LAMBDA`/`FORM_CAP`/`FORM_VARIANT` from config and the team's played-match form. Default λ=0 ⇒ byte-identical (regression test).
- **`pipeline/matchday_run.py`**: `live_model_elos` is already called at Step 5; it picks up the form bump automatically once λ>0. The played-match set for form is the same `wc_df` already fetched. No new step needed beyond passing the played matches into `live_model_elos`.
- **Elo-at-kickoff for the residual:** the residual needs each played match's *pre-match* Elo (not `current_elo`, which already includes that match's update). This comes from the rebuilt Elo history (`build_elo_history`, already produced at Step 2) — the implementation threads a "team Elo as of date" lookup into the form computation so both the live path and the backtest compute the residual the same way. (If threading the full history proves heavy, an acceptable fallback is the team's Elo snapshot just before the matchday; the plan picks one and uses it identically in backtest and live to avoid backtest/live skew.)
- **`config.py`**: `FORM_LAMBDA = 0.0`, `FORM_CAP = 100.0`, `FORM_VARIANT = "points"` (the chosen variant; irrelevant while λ=0).
- **Dashboard (optional, small):** if λ>0 ships, add per-team `form_bump` to the match-card detail so the adjustment is visible; skip if λ=0.

Because live strength remains a single scalar Elo per team, the bump flows into the Monte Carlo (champion probs), match cards, and edges automatically — same single-chokepoint property Phase 1 relied on (`evaluation/live_scoring.py:92-96`, `pipeline/matchday_run.py` `run_monte_carlo`).

## 9. Testing

- **`tests/test_form.py`** (TDD): `points_residual`/`gd_residual` zero when results match Elo expectation; positive when over-performing; `form_bump` clamps at ±cap and is 0 when λ=0; walk-forward — a residual computed for a match never reads that match or later ones.
- **Regression:** `live_model_elos` with `FORM_LAMBDA=0` returns byte-identical Elo to pre-Phase-2 (golden test).
- **Backtest harness test:** on a tiny synthetic 2-matchday fixture, the walk-forward predicts matchday 2 using only matchday-1 results (asserts no lookahead) and produces a Brier number; λ=0 vs λ>0 produce different numbers only when results deviate from Elo.
- **Evidence run:** execute `walk_forward_form_backtest` on 2014/2018/2022, capture the real table, apply the §7 gate, set `FORM_LAMBDA` accordingly. Full existing suite stays green.

## 10. Out of Scope → Later

- **Phase 3:** extend edge detection from the champion market to per-match markets.
- **Phase 4:** Dixon-Coles low-score correlation + re-estimate Poisson goal rates from observed WC scoring.
- Daily TSFM snapshot refresh (deferred — low marginal value, the realized delta is already daily-fresh).
