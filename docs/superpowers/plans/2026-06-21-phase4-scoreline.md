# Phase 4: Scoreline Quality (Dixon-Coles + Goal-Rate) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve scoreline quality (exact score, over/under, BTTS) via two evidence-gated levers — a re-estimated goal rate and a Dixon-Coles low-score correlation — proven (or refuted) by a new walk-forward scoreline backtest on the 2014/2018/2022 World Cups.

**Architecture:** `score_grid` gains an optional Dixon-Coles ρ correction on the four low-score cells; `expected_goals`'s total rate becomes a shrinkage blend of the static prior and the observed tournament rate. Both thread through `predict_scoreline`/`ensemble_match_prediction` and default to current behavior (byte-identical). A new `walk_forward_scoreline_backtest` scores each match's actual scoreline (NLL + exact-hit) to gate the levers; ship a lever only if it beats baseline on all three WCs.

**Tech Stack:** Python 3.11+, numpy, pandas, pytest. Reuses `prediction/score_predictor.py`, `data/elo.elo_as_of` (Phase 2), `prediction/match_predictor.match_probabilities`, `evaluation/backtester.py`.

## Global Constraints

- **Evidence-gated, default OFF / byte-identical.** `DC_RHO = 0.0` ⇒ τ ≡ 1 ⇒ independent Poisson (unchanged). `GOAL_RATE_BLEND = 0.0` ⇒ `effective_goal_rate` returns the static `POISSON_AVG_GOALS` (2.5). Every new param defaults so output is byte-identical until the backtest justifies a value.
- **Walk-forward / no lookahead.** Live observed rate uses only completed matches before each prediction; the backtest predicts each match using strictly prior matches (`elo_as_of`, strictly-before, from Phase 2).
- **W/D/L invariance.** `condition_grid` keeps the win/draw/loss masses fixed (Phase 1's domain); ρ and the rate only reshape the within-block scoreline. A regression test asserts changing ρ/rate does not change the conditioned block sums.
- **Gate metric = scoreline NLL across all three WCs** (a consistent improvement on 2014 AND 2018 AND 2022). Exact-hit% is reported as the headline but does not decide.
- **No new dependencies.** Commits must NOT contain a `Co-Authored-By` trailer. All existing tests stay green; test output pristine. Use `venv/bin/python -m pytest`.

**Verified current code (`prediction/score_predictor.py`):**
`expected_goals(elo_a, elo_b, home_advantage=0.0, total_goals=POISSON_AVG_GOALS) -> (lam_a, lam_b)`; `score_grid(lam_a, lam_b, max_goals=MAX_GOALS) -> np.ndarray` (uses `np.outer`, normalizes); `condition_grid(grid, p_win_a, p_draw, p_win_b)`; `MAX_GOALS=8`. `ensemble_match_prediction(elo_pairs, home_advantage=0.0, knockout=False, calib=None)` (Phase 1) builds per-model raw probs, calibrates the ensemble, conditions the grid, returns `p_home/p_draw/p_away` + `p_*_raw` + `scoreline{...}` + `per_model`. `grid[i,j] = P(A scores i, B scores j)`.

---

### Task 1: Dixon-Coles in `score_grid` + `effective_goal_rate` + config

**Files:**
- Modify: `prediction/score_predictor.py` (`score_grid` gains `rho`; add `effective_goal_rate`)
- Modify: `config.py` (add `DC_RHO`, `GOAL_RATE_BLEND` after `POISSON_AVG_GOALS`)
- Test: `tests/test_score_predictor.py` (extend)

**Interfaces:**
- Produces: `score_grid(lam_a, lam_b, max_goals=MAX_GOALS, rho=0.0) -> np.ndarray` (ρ=0 ⇒ identical to the current outer product); `effective_goal_rate(observed_rate: float, blend: float) -> float` (blend=0 ⇒ `POISSON_AVG_GOALS`); config `DC_RHO=0.0`, `GOAL_RATE_BLEND=0.0`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_score_predictor.py
import numpy as np
from prediction.score_predictor import score_grid, effective_goal_rate
from config import POISSON_AVG_GOALS

def test_score_grid_rho_zero_is_outer_product():
    a = score_grid(1.6, 1.2)
    b = score_grid(1.6, 1.2, rho=0.0)
    assert np.allclose(a, b) and np.array_equal(a, b)

def test_score_grid_sums_to_one_with_dc():
    g = score_grid(1.6, 1.2, rho=-0.1)
    assert abs(g.sum() - 1.0) < 1e-9

def test_dc_negative_rho_inflates_draws_deflates_split():
    base = score_grid(1.5, 1.5)
    dc = score_grid(1.5, 1.5, rho=-0.1)
    assert dc[0, 0] + dc[1, 1] > base[0, 0] + base[1, 1]   # 0-0 and 1-1 up
    assert dc[0, 1] + dc[1, 0] < base[0, 1] + base[1, 0]   # 1-0 and 0-1 down

def test_dc_grid_nonnegative_extreme_rho():
    g = score_grid(3.0, 3.0, rho=-0.2)
    assert (g >= 0).all() and abs(g.sum() - 1.0) < 1e-9

def test_effective_goal_rate_blend_zero_is_static():
    assert effective_goal_rate(3.03, 0.0) == POISSON_AVG_GOALS

def test_effective_goal_rate_blends():
    r = effective_goal_rate(3.0, 0.5)
    assert r == 0.5 * POISSON_AVG_GOALS + 0.5 * 3.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_score_predictor.py -q`
Expected: FAIL (`score_grid() got an unexpected keyword argument 'rho'` / `cannot import name 'effective_goal_rate'`).

- [ ] **Step 3: Add config constants**

In `config.py`, after `POISSON_AVG_GOALS = 2.5`:

```python
# ── Phase 4: scoreline quality (evidence-gated; default OFF) ──────────────────
DC_RHO = 0.0             # Dixon-Coles low-score correlation. 0 = independent Poisson (no-op).
GOAL_RATE_BLEND = 0.0    # weight on observed tournament goal rate vs static POISSON_AVG_GOALS. 0 = static.
```

- [ ] **Step 4: Implement in `prediction/score_predictor.py`**

Replace `score_grid` and add `effective_goal_rate` (keep `from config import POISSON_AVG_GOALS` — already imported):

```python
def score_grid(lam_a: float, lam_b: float, max_goals: int = MAX_GOALS, rho: float = 0.0) -> np.ndarray:
    """Score grid, grid[i, j] = P(A scores i, B scores j).

    Independent Poisson when rho == 0. With rho != 0 a Dixon-Coles (1997)
    low-score correction is applied to the (0-0, 0-1, 1-0, 1-1) cells:
    rho < 0 inflates 0-0 and 1-1 and deflates 1-0 / 0-1.
    """
    goals = np.arange(max_goals + 1)
    pa = np.exp(-lam_a) * lam_a ** goals / np.array([math.factorial(g) for g in goals])
    pb = np.exp(-lam_b) * lam_b ** goals / np.array([math.factorial(g) for g in goals])
    grid = np.outer(pa, pb)
    if rho != 0.0:
        grid[0, 0] *= 1.0 - lam_a * lam_b * rho
        grid[0, 1] *= 1.0 + lam_a * rho
        grid[1, 0] *= 1.0 + lam_b * rho
        grid[1, 1] *= 1.0 - rho
        grid = np.clip(grid, 0.0, None)  # extreme rho could drive a cell negative
    return grid / grid.sum()


def effective_goal_rate(observed_rate: float, blend: float) -> float:
    """Shrinkage blend of the static prior and the observed tournament rate.

    blend=0 -> POISSON_AVG_GOALS (static, byte-identical to pre-Phase-4).
    """
    return (1.0 - blend) * POISSON_AVG_GOALS + blend * observed_rate
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_score_predictor.py -q`
Expected: PASS (existing score tests + 6 new).

- [ ] **Step 6: Commit**

```bash
git add prediction/score_predictor.py config.py tests/test_score_predictor.py
git commit -m "feat(scoreline): Dixon-Coles rho in score_grid + effective_goal_rate (default off)"
```

---

### Task 2: Thread `rho` + `total_goals` through the public predictors

**Files:**
- Modify: `prediction/score_predictor.py` (`predict_scoreline`, `ensemble_match_prediction`)
- Test: `tests/test_score_predictor.py` (extend)

**Interfaces:**
- Consumes: `score_grid(..., rho)`, `effective_goal_rate` (Task 1).
- Produces: `predict_scoreline(elo_a, elo_b, home_advantage=0.0, outcome_probs=None, rho=0.0, total_goals=POISSON_AVG_GOALS)`; `ensemble_match_prediction(elo_pairs, home_advantage=0.0, knockout=False, calib=None, rho=0.0, total_goals=None)`. Defaults reproduce current output exactly. In `ensemble_match_prediction`, `total_goals=None` means "use `POISSON_AVG_GOALS`".

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_score_predictor.py
from prediction.score_predictor import ensemble_match_prediction, predict_scoreline

PAIRS = [(1700, 1500), (1680, 1520), (1720, 1490)]

def test_ensemble_defaults_byte_identical():
    # rho=0, total_goals=None must reproduce the pre-Phase-4 output
    a = ensemble_match_prediction(PAIRS)
    b = ensemble_match_prediction(PAIRS, rho=0.0, total_goals=None)
    assert a["scoreline"] == b["scoreline"]
    assert a["p_home"] == b["p_home"] and a["p_draw"] == b["p_draw"]

def test_ensemble_wdl_invariant_under_rho_and_rate():
    # rho / rate reshape the scoreline but NOT the conditioned W/D/L masses
    base = ensemble_match_prediction(PAIRS)
    changed = ensemble_match_prediction(PAIRS, rho=-0.12, total_goals=3.2)
    assert changed["p_home"] == base["p_home"]
    assert changed["p_draw"] == base["p_draw"]
    assert changed["p_away"] == base["p_away"]

def test_ensemble_rho_changes_scoreline():
    base = ensemble_match_prediction(PAIRS)
    dc = ensemble_match_prediction(PAIRS, rho=-0.12)
    assert dc["scoreline"]["p_btts"] != base["scoreline"]["p_btts"] \
        or dc["scoreline"]["most_likely"] != base["scoreline"]["most_likely"]

def test_higher_rate_raises_over25():
    base = ensemble_match_prediction(PAIRS, total_goals=2.0)
    hi = ensemble_match_prediction(PAIRS, total_goals=3.5)
    assert hi["scoreline"]["p_over25"] > base["scoreline"]["p_over25"]

def test_predict_scoreline_defaults_unchanged():
    a = predict_scoreline(1700, 1500)
    b = predict_scoreline(1700, 1500, rho=0.0, total_goals=POISSON_AVG_GOALS)
    assert a == b
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_score_predictor.py -q`
Expected: FAIL (`unexpected keyword argument 'rho'`).

- [ ] **Step 3: Implement**

In `predict_scoreline`, add `rho=0.0, total_goals=POISSON_AVG_GOALS` to the signature and use them:

```python
def predict_scoreline(elo_a, elo_b, home_advantage=0.0, outcome_probs=None,
                      rho=0.0, total_goals=POISSON_AVG_GOALS):
    if outcome_probs is None:
        outcome_probs = match_probabilities(elo_a, elo_b, home_advantage)
    lam_a, lam_b = expected_goals(elo_a, elo_b, home_advantage, total_goals=total_goals)
    grid = condition_grid(
        score_grid(lam_a, lam_b, rho=rho),
        outcome_probs["win_a"], outcome_probs["draw"], outcome_probs["win_b"],
    )
    # ... rest unchanged
```

In `ensemble_match_prediction`, add `rho=0.0, total_goals=None` to the signature; resolve the rate once and pass `rho`/`total_goals` into `expected_goals`/`score_grid`:

```python
def ensemble_match_prediction(elo_pairs, home_advantage=0.0, knockout=False,
                              calib=None, rho=0.0, total_goals=None):
    rate = POISSON_AVG_GOALS if total_goals is None else total_goals
    per_model = []
    grids = []
    lams = []
    for elo_h, elo_a in elo_pairs:
        probs = match_probabilities(elo_h, elo_a, home_advantage)
        m = {
            "p_home": round(probs["win_a"], 4),
            "p_draw": round(probs["draw"], 4),
            "p_away": round(probs["win_b"], 4),
        }
        if knockout:
            adv = knockout_probabilities(elo_h, elo_a, home_advantage, calib=calib)
            m["p_adv_home"] = round(adv["win_a"], 4)
        per_model.append(m)
        lam = expected_goals(elo_h, elo_a, home_advantage, total_goals=rate)
        lams.append(lam)
        grids.append(score_grid(*lam, rho=rho))
    # ... the rest (ensemble raw, calibrate, condition_grid, top_scorelines, out dict) UNCHANGED
```

At `rho=0, total_goals=None`: `rate=POISSON_AVG_GOALS` and `score_grid(*lam, rho=0)` reproduce the prior `expected_goals(...)`/`score_grid(*lam)` calls exactly ⇒ byte-identical.

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_score_predictor.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite (score_predictor is widely used)**

Run: `venv/bin/python -m pytest -q`
Expected: PASS (all green; defaults keep everything unchanged).

- [ ] **Step 6: Commit**

```bash
git add prediction/score_predictor.py tests/test_score_predictor.py
git commit -m "feat(scoreline): thread rho + goal rate through predictors (default no-op)"
```

---

### Task 3: Walk-forward scoreline backtest

**Files:**
- Modify: `evaluation/backtester.py` (add `walk_forward_scoreline_backtest`, NLL/hit scorers, `run_scoreline_backtest_and_save`)
- Test: `tests/test_backtester_scoreline.py` (new)

**Interfaces:**
- Consumes: `elo_as_of` (Phase 2), `match_probabilities`, `expected_goals`, `score_grid`, `condition_grid`, `effective_goal_rate`, `compute_elo`.
- Produces: `walk_forward_scoreline_backtest(years, grid, matches=None) -> pd.DataFrame` with columns `year, rho, blend, mean_nll, hit_rate, n_matches`; `grid` entries are `(rho, blend)`. `run_scoreline_backtest_and_save()` sweeps a default grid on [2014,2018,2022] and writes `results/evaluations/scoreline_backtest.csv`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backtester_scoreline.py
import pandas as pd
from evaluation.backtester import walk_forward_scoreline_backtest

def _synth(year):
    rows = [
        {"date": f"{year}-06-12", "home_team": "A", "away_team": "B", "home_score": 1, "away_score": 1},
        {"date": f"{year}-06-13", "home_team": "C", "away_team": "D", "home_score": 2, "away_score": 0},
        {"date": f"{year}-06-17", "home_team": "A", "away_team": "C", "home_score": 0, "away_score": 0},
        {"date": f"{year}-06-18", "home_team": "B", "away_team": "D", "home_score": 3, "away_score": 1},
    ]
    df = pd.DataFrame(rows)
    df["tournament"] = "FIFA World Cup"
    df["neutral"] = True
    return df

def test_scoreline_backtest_runs_and_reports():
    out = walk_forward_scoreline_backtest(
        years=[2014], grid=[(0.0, 0.0), (-0.1, 0.5)], matches=_synth(2014)
    )
    assert set(out.columns) >= {"year", "rho", "blend", "mean_nll", "hit_rate", "n_matches"}
    assert out["n_matches"].iloc[0] == 4
    assert (out["mean_nll"] > 0).all()

def test_scoreline_backtest_candidate_differs_from_baseline():
    out = walk_forward_scoreline_backtest(
        years=[2014], grid=[(0.0, 0.0), (-0.15, 1.0)], matches=_synth(2014)
    )
    base = out[(out["rho"] == 0.0) & (out["blend"] == 0.0)]["mean_nll"].iloc[0]
    cand = out[(out["rho"] == -0.15)]["mean_nll"].iloc[0]
    assert base != cand  # rho/blend genuinely move the scoreline NLL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_backtester_scoreline.py -q`
Expected: FAIL (`cannot import name 'walk_forward_scoreline_backtest'`).

- [ ] **Step 3: Implement**

In `evaluation/backtester.py` add (merge imports — `compute_elo`, `elo_as_of`, `match_probabilities`, `RESULTS_DIR`, `defaultdict`, `np` are already imported from Phase 2/earlier; ADD `from prediction.score_predictor import expected_goals, score_grid, condition_grid, effective_goal_rate`):

```python
import math


def _scoreline_nll(grid, hs, as_):
    """Negative log-likelihood of the actual scoreline under the conditioned grid."""
    n = grid.shape[0]
    i = min(int(hs), n - 1)
    j = min(int(as_), n - 1)
    return -math.log(max(float(grid[i, j]), 1e-12))


def walk_forward_scoreline_backtest(years, grid, matches=None):
    """Walk-forward scoreline NLL + exact-hit over historical WCs per (rho, blend).

    Each WC match is predicted with elo_as_of(< its date) outcome probs and a
    conditioned Dixon-Coles grid whose goal rate blends the static prior with
    the observed rate from STRICTLY-earlier matches that tournament. Returns a
    tidy DataFrame; (rho=0, blend=0) is the baseline.
    """
    if matches is None:
        matches = pd.read_parquet("data/cache/matches.parquet")
    matches = matches.copy()
    matches["date"] = pd.to_datetime(matches["date"])

    rows = []
    for year in years:
        wc = matches[(matches["tournament"] == "FIFA World Cup")
                     & (matches["date"].dt.year == year)].sort_values("date")
        if wc.empty:
            continue
        relevant = matches[matches["date"] <= wc["date"].max()]
        history = compute_elo(relevant.sort_values("date"))

        for rho, blend in grid:
            prior_goals = []  # total goals of strictly-earlier WC matches this year
            total_nll, hits, n = 0.0, 0, 0
            for _, m in wc.iterrows():
                home, away = m["home_team"], m["away_team"]
                hs, as_ = int(m["home_score"]), int(m["away_score"])
                eh = elo_as_of(history, home, m["date"])
                ea = elo_as_of(history, away, m["date"])
                probs = match_probabilities(eh, ea)
                observed = sum(prior_goals) / len(prior_goals) if prior_goals else POISSON_AVG_GOALS
                rate = effective_goal_rate(observed, blend)
                lam_a, lam_b = expected_goals(eh, ea, total_goals=rate)
                g = condition_grid(score_grid(lam_a, lam_b, rho=rho),
                                   probs["win_a"], probs["draw"], probs["win_b"])
                total_nll += _scoreline_nll(g, hs, as_)
                gi, gj = (g == g.max()).nonzero()
                if int(gi[0]) == min(hs, g.shape[0] - 1) and int(gj[0]) == min(as_, g.shape[0] - 1):
                    hits += 1
                n += 1
                prior_goals.append(hs + as_)
            rows.append({"year": year, "rho": rho, "blend": blend,
                         "mean_nll": total_nll / n if n else 0.0,
                         "hit_rate": hits / n if n else 0.0, "n_matches": n})
    return pd.DataFrame(rows)


def run_scoreline_backtest_and_save():
    grid = [(rho, blend) for rho in (0.0, -0.05, -0.1, -0.15) for blend in (0.0, 0.5, 1.0)]
    df = walk_forward_scoreline_backtest([2014, 2018, 2022], grid)
    out_path = RESULTS_DIR / "evaluations" / "scoreline_backtest.csv"
    df.to_csv(out_path, index=False)
    return df, out_path
```

`POISSON_AVG_GOALS` must be importable in `backtester.py` — add it to the existing `from config import (...)` block if not present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_backtester_scoreline.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add evaluation/backtester.py tests/test_backtester_scoreline.py
git commit -m "feat(scoreline): walk-forward scoreline NLL/hit backtest"
```

---

### Task 4: Live wiring (default no-op)

**Files:**
- Modify: `evaluation/live_scoring.py` (`predict_upcoming_matches` passes rho + effective rate)
- Test: `tests/test_live_tournament.py` (extend)

**Interfaces:**
- Consumes: `effective_goal_rate` (Task 1), `ensemble_match_prediction(..., rho, total_goals)` (Task 2), config `DC_RHO`/`GOAL_RATE_BLEND`.
- Produces: `predict_upcoming_matches` computes `observed_rate` from completed `wc_df` and passes `rho=DC_RHO`, `total_goals=effective_goal_rate(observed_rate, GOAL_RATE_BLEND)` to `ensemble_match_prediction`. With both config knobs at 0 ⇒ byte-identical locked predictions.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_live_tournament.py
from datetime import datetime, timedelta, timezone
import pandas as pd
from evaluation import live_scoring

def test_predict_upcoming_default_knobs_unchanged(tmp_path, monkeypatch):
    # With DC_RHO=0 and GOAL_RATE_BLEND=0 (config defaults), the stored scoreline
    # must equal what the pre-Phase-4 path produced (rho omitted / rate static).
    monkeypatch.setattr(live_scoring, "MATCH_PREDS_CSV", tmp_path / "mp.csv")
    now = datetime.now(timezone.utc)
    ko = (now + timedelta(days=1)).isoformat()
    wc = pd.DataFrame([{
        "kickoff_utc": ko, "stage": "group", "completed": False,
        "home_team": "Spain", "away_team": "Croatia", "date": now.date().isoformat(),
    }])
    elos = {"Spain": 1900, "Croatia": 1650}
    model_elos = {"M1": elos, "M2": elos}
    live_scoring.predict_upcoming_matches(wc, elos, model_elos=model_elos)
    out = pd.read_csv(tmp_path / "mp.csv")
    assert len(out) == 1 and out.iloc[0]["pred_score"]  # produced a scoreline, no error
```

(The strict byte-identical check is covered by Task 2's `test_ensemble_defaults_byte_identical`; this test confirms the wiring runs and stores a scoreline with the default knobs.)

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `venv/bin/python -m pytest tests/test_live_tournament.py -q`
Expected: PASS is acceptable here only AFTER Step 3 wiring; first run it to see current behavior. If it errors due to the new `date` column handling, proceed to Step 3.

- [ ] **Step 3: Implement the wiring**

In `evaluation/live_scoring.py`, add imports:

```python
from config import DC_RHO, GOAL_RATE_BLEND
from prediction.score_predictor import effective_goal_rate
```

In `predict_upcoming_matches`, before the per-fixture loop, compute the observed rate from completed matches:

```python
    done = wc_df[wc_df["completed"]] if "completed" in wc_df.columns else wc_df.iloc[0:0]
    if not done.empty:
        observed_rate = float((done["home_score"] + done["away_score"]).mean())
    else:
        observed_rate = POISSON_AVG_GOALS
    score_rate = effective_goal_rate(observed_rate, GOAL_RATE_BLEND)
```

(`POISSON_AVG_GOALS` — import from config if not already imported in this file.)

Then in the `model_elos` branch, change the `ensemble_match_prediction(...)` call to pass the knobs:

```python
            pred = ensemble_match_prediction(elo_pairs, home_advantage=ha,
                                             knockout=is_ko, calib=calib,
                                             rho=DC_RHO, total_goals=score_rate)
```

With `DC_RHO=0` and `GOAL_RATE_BLEND=0`, `score_rate == POISSON_AVG_GOALS` and `rho=0`, so the call is byte-identical to today.

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_live_tournament.py tests/test_score_predictor.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `venv/bin/python -m pytest -q`
Expected: PASS (defaults keep everything unchanged).

- [ ] **Step 6: Commit**

```bash
git add evaluation/live_scoring.py tests/test_live_tournament.py
git commit -m "feat(scoreline): wire DC rho + goal-rate blend into live predictions (default no-op)"
```

---

### Task 5: Evidence run, go/no-go, set config

**Files:**
- Create: `scripts/run_scoreline_backtest.py`
- Modify: `config.py` (set `DC_RHO`/`GOAL_RATE_BLEND` per the gate — possibly leave 0)
- Modify: `docs/superpowers/specs/2026-06-21-phase4-scoreline-design.md` (append the real result)

**Interfaces:**
- Consumes: `run_scoreline_backtest_and_save` (Task 3).

- [ ] **Step 1: Create the evidence script**

```python
# scripts/run_scoreline_backtest.py
"""Evidence run: walk-forward scoreline backtest on 2014/2018/2022, applying the
go/no-go gate. Prints the per-(rho,blend) per-year NLL + exact-hit table. The
DECIDING metric is mean NLL improving on ALL THREE WCs vs the (0,0) baseline;
exact-hit% is the intuitive headline only. Sets nothing automatically — the
operator updates config.DC_RHO / GOAL_RATE_BLEND only if a candidate passes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.backtester import run_scoreline_backtest_and_save

df, out_path = run_scoreline_backtest_and_save()
print(f"Wrote {out_path}")
nll = df.pivot_table(index=["rho", "blend"], columns="year", values="mean_nll")
nll["avg"] = nll.mean(axis=1)
print("=== mean NLL (lower=better) ===")
print(nll.to_string())
hit = df.pivot_table(index=["rho", "blend"], columns="year", values="hit_rate")
print("\\n=== exact-hit rate (headline only) ===")
print(hit.to_string())

base = df[(df["rho"] == 0.0) & (df["blend"] == 0.0)].set_index("year")["mean_nll"]
print("\\n=== go/no-go (must beat (0,0) NLL on all three WCs) ===")
for (rho, blend), grp in df.groupby(["rho", "blend"]):
    if rho == 0.0 and blend == 0.0:
        continue
    cand = grp.set_index("year")["mean_nll"]
    beats_all = bool((cand < base).all())
    avg_impr = float((base - cand).mean())
    print(f"rho={rho} blend={blend}: beats_all={beats_all} avg_nll_improvement={avg_impr:+.4f}")
```

- [ ] **Step 2: Run the full suite first**

Run: `venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 3: Run the evidence script (capture REAL output)**

Run: `venv/bin/python scripts/run_scoreline_backtest.py`
Expected: prints the NLL table, the exact-hit table, and the go/no-go lines; writes `results/evaluations/scoreline_backtest.csv`. Capture verbatim — this is the evidence.

- [ ] **Step 4: Apply the gate and set config**

Read the go/no-go lines. **Only if** some `(rho, blend)` shows `beats_all=True` with a meaningful positive `avg_nll_improvement`: set `config.DC_RHO` and/or `config.GOAL_RATE_BLEND` to that candidate's values (a lever may be set independently — e.g. blend>0 with rho=0 if only the rate passes). **Otherwise** leave both at `0.0` (ship the no-op). Do not fabricate or cherry-pick; report exactly what the table shows.

If setting non-zero values, re-run the full suite to confirm green:
Run: `venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Record the result honestly in the spec**

Append a "## 11. Backtest result" section to the design doc with the real per-year/avg NLL table, the exact-hit headline, the gate decision (shipped values or no-op), and one sentence why. Numbers only.

- [ ] **Step 6: Commit**

```bash
git add scripts/run_scoreline_backtest.py config.py docs/superpowers/specs/2026-06-21-phase4-scoreline-design.md
git commit -m "feat(scoreline): evidence run + go/no-go decision for DC rho + goal rate"
```

(Do NOT commit `results/evaluations/scoreline_backtest.csv` — runtime artifact.)

---

## Self-Review

**Spec coverage:**
- §3 evidence-gated/default-off/byte-identical → Task 1 (`DC_RHO=0`/`GOAL_RATE_BLEND=0`, ρ=0 regression) + Task 2 (defaults byte-identical) + Task 4 (live no-op) + Task 5 gate.
- §3 walk-forward → Task 3 (`elo_as_of` strictly-before; `prior_goals` only earlier matches) + Task 4 (observed from completed only).
- §4a goal-rate shrinkage blend → Task 1 `effective_goal_rate`; §4b Dixon-Coles τ → Task 1 `score_grid` rho.
- §5 walk-forward scoreline backtest (NLL + exact-hit, grid, CSV) → Task 3 + Task 5.
- §6 W/D/L invariance → Task 2 `test_ensemble_wdl_invariant_under_rho_and_rate`.
- §7 go/no-go (NLL beats baseline on all three WCs; hit-rate headline only) → Task 5 script + Step 4.
- §8 thread through predict_scoreline/ensemble_match_prediction + live wiring; single chokepoint flows to cards/dashboard → Tasks 2, 4. §9 tests → each task + Task 5.

**Placeholder scan:** none — every code step is complete.

**Type consistency:** `score_grid(lam_a, lam_b, max_goals=MAX_GOALS, rho=0.0)`, `effective_goal_rate(observed_rate, blend)`, `predict_scoreline(..., rho=0.0, total_goals=POISSON_AVG_GOALS)`, `ensemble_match_prediction(..., rho=0.0, total_goals=None)`, `walk_forward_scoreline_backtest(years, grid, matches=None)`, `run_scoreline_backtest_and_save()` — consistent across tasks. Grid entries `(rho, blend)` throughout; scoreline keys `p_over25`/`p_btts`/`most_likely` as in the existing `scoreline` dict.

**Deferred verification:** Task 3 must confirm and MERGE the existing `backtester.py` imports (`compute_elo`, `elo_as_of`, `match_probabilities`, `RESULTS_DIR`, `defaultdict`, `POISSON_AVG_GOALS`) and add only the missing `from prediction.score_predictor import ...`; Task 4 must confirm `POISSON_AVG_GOALS` is imported in `live_scoring.py` and the exact `ensemble_match_prediction(...)` call line.
