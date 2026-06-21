# Phase 1: Live Calibration — Design

**Date:** 2026-06-21
**Status:** Approved design, pending spec review
**Scope:** Calibrate match-outcome probabilities against actual WC-2026 results, walk-forward, flowing into match cards, Monte Carlo, and edges.

---

## 1. Problem

With 36 of 104 World Cup matches played, the live prediction quality is only marginally above chance:

- **Mean Brier = 0.603** vs uniform 3-way baseline **0.667** — barely better than guessing.
- **Winner hit-rate = 55.6%** — the model *has* signal on who wins, but the probabilities are poorly calibrated.
- **Draws underpredicted:** actual draws **11/36 = 30.6%**, mean predicted `p_draw` = **23.1%** (~7.5pp gap).

Diagnosis — two distinct miscalibrations:

1. **Overconfidence.** High Brier with decent hit-rate means the model pushes too much mass to a single outcome and gets punished hard on upsets (e.g. Ecuador 0.75 home → actual 0-0 draw, single-match Brier 1.25).
2. **Draw underprediction.** Confirmed above: draws happen ~31% of the time, model predicts ~23%.

Root cause: the Davidson outcome map (`BRADLEY_TERRY_SCALE=405`, `BRADLEY_TERRY_DRAW_NU=0.79`, `config.py:120-121`) is a **frozen 2010–2023 fit** (`scripts/calibrate_probability_map.py`, train 2010–2023 / holdout 2024+). It is never recalibrated on actual WC-2026 outcomes. World Cup group play has more parity (and more draws) than the average historical international.

## 2. Goal & Non-Goals

**Goal:** A walk-forward calibration layer, fit on actual results, that (a) reduces overconfidence and (b) corrects the draw rate — applied to *future* predictions only, flowing consistently into match cards, the Monte Carlo champion simulation, and Polymarket edges.

**Non-goals (Phase 1):**
- No change to Elo, the TSFM snapshot cadence, or the score/Poisson model (those are Phases 2 & 4).
- No retroactive rewriting of already-locked predictions.
- No isotonic/Platt binning (overfits on 36 matches).
- No Elo-dependent (conditional) draw correction — flat δ only; revisit if data warrants.

## 3. Honesty Constraint (binding)

Calibration is applied **at prediction time**. Predictions are locked once in `evaluation/live_scoring.py` (`predict_upcoming_matches`, first-prediction-wins, keyed on `(kickoff_utc, home, away)`). Therefore:

- Future, not-yet-kicked-off fixtures get calibrated probabilities using the **current** calibration parameters.
- Already-locked predictions are **never** re-scored or rewritten.
- We **never** fit calibration on a match and then report that same match's Brier. The fit set is strictly matches with `kickoff_utc < now` (plus the static 2024 holdout); the reported live Brier remains an honest out-of-sample number.

## 3.1 Truthfulness Invariants — reported accuracy must be real (no inflation, no hallucination)

The headline risk of any "calibrate on results" feature is making the model *look* more accurate than it is. These are **enforced, testable invariants**, not conventions. If any is violated the pipeline must fail loudly rather than report an optimistic number.

- **I1 — Disjoint fit / eval, enforced in code.** `fit_calibration` ingests only matches with `kickoff_utc < run_time` plus the static 2024 holdout. A runtime assertion rejects any fit record with `kickoff_utc >= run_time`. The live scoreboard Brier (`live_scoring.score_completed_matches`) is computed on locked predictions on a separate code path and never shares samples with the fit's in-sample Brier.
- **I2 — Headline accuracy = locked, out-of-sample only.** The single number ever surfaced as "AI 准确率 / Brier" comes from locked pre-match predictions scored *after* kickoff. The artifact's `brier_before/after` are tagged `"in_sample_fit_diagnostic": true`; the dashboard must never render them as accuracy.
- **I3 — Immutable locked predictions, with provenance.** Once a fixture's row is written to `match_predictions.csv` it is never mutated by the calibration step. Each row records the `(T, δ)` active at lock time (`calib_T`, `calib_delta` columns) — a real, reproducible audit trail. A test asserts re-running the pipeline does not change any existing row's probabilities.
- **I4 — No retroactive recalibration of history.** New `(T, δ)` affects only future, not-yet-kicked-off fixtures. There is no job that re-scores past predictions to improve historical Brier.
- **I5 — Full population, visible coverage.** Every completed match with a locked pre-match prediction is scored; none are dropped or cherry-picked. `n_scored` is always reported next to Brier so coverage is auditable.
- **I6 — Evidence-based claims (build discipline).** No claim that accuracy improved is made without actually running the scoring and showing the real command output. Per `verification-before-completion`: evidence before assertions, always. The success criterion is the **honest out-of-sample live Brier on future matches trending down**, never the in-sample fit number.

## 4. Calibration Model (2-parameter)

Given raw Davidson probabilities `(p_h, p_d, p_a)` from `match_probabilities`, the calibrated probabilities are:

```
l_h = log(p_h) / T
l_d = log(p_d) / T + δ
l_a = log(p_a) / T
(p'_h, p'_d, p'_a) = softmax(l_h, l_d, l_a)
```

- **T** (temperature, prior 1.0): T > 1 flattens toward uniform → fixes overconfidence.
- **δ** (draw-class logit bias, prior 0.0): δ > 0 lifts draw mass → fixes the draw rate independently of T.

**Knockout (2-way, no draw):** δ is dropped; only T applies over `(p_h, p_a)`. (All 36 played matches are group-stage 3-way; the artifact and code support both.)

Properties (unit-testable):
- `T=1, δ=0` ⇒ identity (`softmax(log p) == p`).
- `T>1` ⇒ strictly lower max-prob (flatter).
- `δ>0` ⇒ strictly higher `p'_d`.

## 5. Fitting

`fit_calibration(records, *, draw_prior_weight, temp_prior_weight, wc_weight)`:

- **Records:** static 2024 holdout matches (replayed from `data/cache/matches.parquet`, same source as the offline script) + played WC-2026 matches (`kickoff_utc < now`). WC records carry weight `wc_weight > 1` so live data dominates as the tournament progresses.
- **Objective:** weighted mean Brier of calibrated probs vs one-hot outcome, plus L2 priors `temp_prior_weight·(T-1)² + draw_prior_weight·δ²`.
- **Optimizer:** Nelder-Mead / L-BFGS over 2 params (smooth, well-conditioned). Deterministic.
- **Shrinkage rationale:** 36 WC matches alone is too few for a stable fit; priors pull (T, δ) toward (1, 0) and the WC up-weighting + accumulating sample size let the data take over naturally over the remaining ~68 matches.

The priors’ weights are config constants (`CALIB_TEMP_PRIOR`, `CALIB_DRAW_PRIOR`, `CALIB_WC_WEIGHT`) with sane defaults chosen so the early-tournament fit stays close to identity and tightens as `n` grows.

## 6. Components & Data Flow

> **Architecture note (verified against code).** There is no single match-level
> ensemble probability shared by all consumers. **Locked predictions** come from
> `score_predictor.ensemble_match_prediction` (averages per-model
> `match_probabilities`, then conditions the scoreline) — the ensemble prob exists
> here, and this is the exact object scored by `live_scoring`. The **Monte Carlo**
> (`tournament_simulator`) runs *per model* (`matchday_run.py:142-146`) and
> ensembles at the *champion* level, so no match-level ensemble prob exists inside
> it. Calibrating naively inside `match_probabilities` would apply the transform
> per-model *before* averaging — **not** the object `(T, δ)` is fit on. To keep
> "what we fit is what we apply" (I1/I6), calibration is applied at the **finalised
> probability** of each consumer, via a `calib` parameter threaded explicitly (no
> global state, fully testable).

### New module: `prediction/calibration.py` (pure, fully unit-tested)
- `@dataclass Calibration{T: float = 1.0, delta: float = 0.0}` — the params; identity default.
- `calibrate(probs: dict, calib: Calibration | None) -> dict` — applies the §4 transform to a `{"win_a","draw","win_b"}` (3-way) or `{"win_a","win_b"}` (2-way; δ ignored) dict. `calib is None` ⇒ returns probs unchanged (graceful degradation = current behaviour, byte-identical).
- `fit_calibration(records, *, temp_prior, draw_prior, wc_weight) -> tuple[Calibration, dict]` — returns fitted params + diagnostics.
- `load_calibration(path) -> Calibration` (missing/invalid ⇒ identity) and `save_calibration(calib, diagnostics, path)`.

### Application sites (each takes an optional `calib`, default `None` = identity)
1. **`score_predictor.ensemble_match_prediction(..., calib=None)`** — average per-model raw probs → calibrate the **ensemble 3-way** → condition the scoreline grid on the *calibrated* probs (keeps scoreline ↔ outcome consistent). Used by `live_scoring.predict_upcoming_matches` (locked predictions) and the dashboard match cards. **This is the object the honest match-Brier is computed on — fit and application match exactly.**
2. **`match_probabilities(..., calib=None)` / `knockout_probabilities(..., calib=None)`** — calibrate the per-call 3-way (knockout calibrates the 90-min 3-way *before* its ET/penalty redistribution). Used by the **Monte Carlo** per-model sims (`_simulate_group`, `_simulate_knockout_match`), threaded via `run_monte_carlo → simulate_tournament`. This honours "calibration into Monte Carlo". *Documented approximation:* the fit object is the ensemble group match; the MC applies the same `(T, δ)` per-model at match level. Champion-prob quality remains honestly evaluated out-of-sample by `update_scoreboard`, so this cannot inflate a reported number.
3. **`live_scoring.predict_upcoming_matches` single-Elo fallback** (no `model_elos`) — pass `calib` to its `match_probabilities`/`knockout_probabilities` calls.

### Storage & provenance (truthfulness backbone, in `match_predictions.csv`)
`predict_upcoming_matches` writes, per locked fixture: the **calibrated** `p_home/p_draw/p_away` (what gets scored), **plus raw** `p_home_raw/p_draw_raw/p_away_raw` and `calib_T/calib_delta`. The fit (next run) consumes **raw + outcome** only; the reported Brier (`score_completed_matches`) uses the **calibrated locked** probs. So we never refit on the reported number, and any `(T, δ)` is fully reproducible. Pre-existing rows (locked before this feature, calib was identity) have no `*_raw` columns ⇒ the fit treats `raw := locked`, `calib=(1,0)` for them; **no existing row is mutated** (I3).

### New pipeline step: `step_calibrate` in `pipeline/matchday_run.py`
Runs **before** Monte Carlo / scoring each day:
1. Build the fit set: played-WC records (raw ensemble probs + outcome) from `match_scores.csv`/`match_predictions.csv` with `kickoff_utc < now` (I1 assertion), plus the static 2024 holdout (single-Elo Davidson replay from `data/cache/matches.parquet`).
2. `fit_calibration(...)` → `(Calibration, diagnostics)`.
3. Write `results/calibration/calibration_latest.json`:
   ```json
   {
     "as_of": "2026-06-21",
     "T": 1.18, "delta": 0.42,
     "n_wc": 36, "n_holdout": 412,
     "draw_rate_observed": 0.306, "draw_rate_predicted_raw": 0.231,
     "in_sample_fit_diagnostic": true,
     "brier_before": 0.603, "brier_after": 0.561
   }
   ```
4. Steps 6 (MC) and 8 (scoring) load this artifact via `load_calibration` and pass `calib` to the application sites.

`brier_before/after` are **in-sample on the fit set**, flagged `in_sample_fit_diagnostic: true` (I2). The honest live Brier continues to come from `live_scoring.score_completed_matches` on locked predictions.

### Dashboard (small): `visualization/dashboard.py`
- Add to `data.json` `meta`: `calibration: {T, delta, n_wc, draw_rate_observed, draw_rate_predicted}`.
- Frontend "AI 战绩" tab: when `|T-1|` or `|δ|` is non-trivial, show one line — e.g. "已按实战校准 (T=1.18, 平局+)". No new components, no emoji.

## 7. Testing

- **`tests/test_calibration.py`** (TDD, write first):
  - `calibrate` identity at `(1, 0)`; monotonic flattening in T; monotonic draw lift in δ; rows sum to 1; 2-way path ignores δ.
  - `fit_calibration` recovers planted `(T, δ)` on synthetic data; shrinks to `(1, 0)` on empty/tiny WC set; respects priors.
- **Truthfulness invariant tests (§3.1):** I1 — `fit_calibration` raises if handed a record with `kickoff_utc >= run_time`. I3 — re-running the pipeline leaves existing `match_predictions.csv` probability rows byte-identical, and new rows carry `calib_T`/`calib_delta`. I2 — the value the dashboard reads for "accuracy" is sourced from `score_completed_matches`, never from the artifact's `brier_*` fields. I5 — `n_scored` equals the count of completed matches that have a locked prediction.
- **Regression:** golden test that `match_probabilities` with default (missing) artifact equals pre-change output (T=1, δ=0 ⇒ byte-identical predictions) — proves graceful degradation.
- **Validation script / check:** recompute Brier on the 36 played matches under fitted `(T, δ)` (in-sample, for the design record only) to confirm the direction and magnitude; sanity-check that calibrated champion probabilities still sum to 1 and aren't degenerately flat (top teams still rank sensibly).
- Full existing suite (76 tests) stays green; Phase B dry-run end-to-end incl. deploy.

## 8. Rollout & Risk

- **Graceful degradation:** missing/invalid artifact ⇒ `(T=1, δ=0)` ⇒ identical to today. Safe to ship before the first fit.
- **Walk-forward purity:** never fit on `kickoff_utc >= now`; never rewrite locked rows. Re-lock guard already in `live_scoring`.
- **Blast radius:** flattening match probs also flattens champion probs and shifts edges. Intended, but **must validate** champion ranking remains sensible (Spain/Argentina/France still top) and edges don't collapse to noise. If champion probs look distorted, fall back to calibrating only the match-card/edge path and keep raw probs inside the MC (config switch `CALIB_IN_MONTE_CARLO`, default on per user requirement).
- **Determinism:** fit is deterministic; no `Date.now`/random in core math (seeded where needed).

## 9. Out of Scope → Later Phases

- **Phase 2:** daily TSFM snapshot refresh + revive `feature_engineering.py` recent-form signal.
- **Phase 3:** extend edge detection from champion market to per-match markets.
- **Phase 4:** Dixon-Coles low-score correlation + re-estimate Poisson goal rates from observed WC scoring.
