# Live Calibration (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Calibrate match-outcome probabilities against actual WC-2026 results (temperature `T` for overconfidence + draw-bias `δ` for the draw rate), walk-forward, flowing into locked predictions, the Monte Carlo champion simulation, and edges.

**Architecture:** A pure `prediction/calibration.py` module (a `Calibration` dataclass, a `calibrate()` transform, a `fit_calibration()` fitter, JSON artifact I/O). Calibration is applied at each consumer's *finalised* probability via an explicit `calib` parameter (no global state): the ensemble probability for locked predictions/score conditioning, and the per-model match probability inside the Monte Carlo. A daily `step_calibrate` fits `(T, δ)` on played WC group matches only and writes an artifact the other steps load.

**Tech Stack:** Python 3.11+, numpy, scipy (`scipy.optimize.minimize`, already used by `scripts/calibrate_probability_map.py`), pandas, pytest. Frontend: Next.js 16 static export under `web/`.

## Global Constraints

- **Graceful degradation:** `calib=None` (or identity `Calibration(1.0, 0.0)`) ⇒ outputs **byte-identical** to current behaviour. Every new `calib` parameter defaults to `None`.
- **Truthfulness invariants (spec §3.1), enforced & tested:** I1 fit set is WC group matches with `kickoff_utc < now` using **raw** probs (assert); I2 headline accuracy comes only from `score_completed_matches` on locked **calibrated** probs, never the artifact's `brier_*`; I3 locked `match_predictions.csv` probability rows are never mutated, new rows carry `calib_T`/`calib_delta` provenance; I4 no retroactive recalibration; I5 `n_scored`/`n_wc` reported beside Brier; I6 no accuracy claim without a real command-output evidence run.
- **Fit set is WC-only** (no 2024 holdout in the objective — generic internationals would dilute the WC-specific draw/parity correction). Stability comes from shrinkage priors.
- **No new heavy dependencies.** Reuse numpy/scipy/pandas.
- **Frontend:** no emoji, no CSS gradients (solid colors only), user-facing text in Chinese. After any `web/` change, rebuild with `cd web && npm run build` (cron only swaps `data.json`, it does not build).
- **Commits:** do **not** add a `Co-Authored-By` trailer.
- All existing tests (`tests/test_*.py`) stay green.

**Probability dict shape (verified):** `match_probabilities` returns `{"win_a","draw","win_b"}`; `knockout_probabilities` returns `{"win_a","win_b"}`. The dashboard/scoring layer renames these to `p_home/p_draw/p_away`.

---

### Task 1: Calibration transform + dataclass

**Files:**
- Create: `prediction/calibration.py`
- Test: `tests/test_calibration.py`

**Interfaces:**
- Produces: `Calibration(T: float = 1.0, delta: float = 0.0)` with `.is_identity() -> bool`; `calibrate(probs: dict[str, float], calib: Calibration | None) -> dict[str, float]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_calibration.py
import math
import pytest
from prediction.calibration import Calibration, calibrate

P3 = {"win_a": 0.6, "draw": 0.15, "win_b": 0.25}

def test_none_is_identity():
    assert calibrate(P3, None) == P3

def test_identity_params_unchanged():
    assert calibrate(P3, Calibration(1.0, 0.0)) == P3

def test_rows_sum_to_one():
    out = calibrate(P3, Calibration(1.3, 0.4))
    assert abs(sum(out.values()) - 1.0) < 1e-9

def test_temperature_flattens():
    # T>1 moves the max prob down toward uniform
    out = calibrate(P3, Calibration(2.0, 0.0))
    assert out["win_a"] < P3["win_a"]
    assert out["win_a"] > 1/3  # still the favourite, just flatter

def test_delta_lifts_draw():
    out = calibrate(P3, Calibration(1.0, 0.6))
    assert out["draw"] > P3["draw"]
    assert out["win_a"] < P3["win_a"] and out["win_b"] < P3["win_b"]

def test_two_way_ignores_delta():
    p2 = {"win_a": 0.7, "win_b": 0.3}
    a = calibrate(p2, Calibration(1.0, 0.9))
    b = calibrate(p2, Calibration(1.0, 0.0))
    assert a == b  # no "draw" key -> delta has no effect

def test_two_way_temperature():
    p2 = {"win_a": 0.7, "win_b": 0.3}
    out = calibrate(p2, Calibration(2.0, 0.0))
    assert out["win_a"] < 0.7 and abs(sum(out.values()) - 1.0) < 1e-9
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_calibration.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'prediction.calibration'`).

- [ ] **Step 3: Implement the module**

```python
# prediction/calibration.py
"""Walk-forward calibration of match-outcome probabilities (temperature + draw bias).

calibrate() is a pure post-processing layer applied to a probability dict. With
calib=None or identity it returns the input unchanged (graceful degradation).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Calibration:
    """Temperature T (overconfidence) + draw-class logit bias delta (draw rate)."""

    T: float = 1.0
    delta: float = 0.0

    def is_identity(self) -> bool:
        return self.T == 1.0 and self.delta == 0.0


def calibrate(probs: dict[str, float], calib: "Calibration | None") -> dict[str, float]:
    """Apply temperature + draw-bias calibration.

    probs : {"win_a","draw","win_b"} (3-way) or {"win_a","win_b"} (2-way).
            For 2-way, delta has no effect (no "draw" key).
    """
    if calib is None or calib.is_identity():
        return probs

    eps = 1e-12
    logits = {k: math.log(max(v, eps)) / calib.T for k, v in probs.items()}
    if "draw" in logits:
        logits["draw"] += calib.delta

    m = max(logits.values())
    exps = {k: math.exp(v - m) for k, v in logits.items()}
    z = sum(exps.values())
    return {k: e / z for k, e in exps.items()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_calibration.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add prediction/calibration.py tests/test_calibration.py
git commit -m "feat(calibration): Calibration dataclass + calibrate() transform"
```

---

### Task 2: Fitter + config priors + artifact I/O

**Files:**
- Modify: `prediction/calibration.py` (add `fit_calibration`, `save_calibration`, `load_calibration`)
- Modify: `config.py` (add `CALIB_TEMP_PRIOR`, `CALIB_DRAW_PRIOR`, `CALIBRATION_PATH`)
- Test: `tests/test_calibration.py` (extend)

**Interfaces:**
- Consumes: `Calibration`, `calibrate` (Task 1).
- Produces:
  - `fit_calibration(records: list[dict], *, temp_prior: float, draw_prior: float) -> tuple[Calibration, dict]` where each record is `{"probs": {"win_a","draw","win_b"}, "outcome": "win_a"|"draw"|"win_b"}`. Returns `(Calibration, diagnostics_dict)`. Empty records ⇒ identity.
  - `save_calibration(calib: Calibration, diagnostics: dict, path) -> None`
  - `load_calibration(path) -> Calibration` (missing/invalid ⇒ identity).

- [ ] **Step 1: Add config constants**

In `config.py`, after `BRADLEY_TERRY_DRAW_NU = 0.79` add:

```python
# ── Live Calibration (Phase 1) ───────────────────────────────────────────────
# Shrinkage priors pulling (T, delta) toward identity (1, 0). Acts like a fixed
# number of pseudo-observations at identity: dominates early, fades as n grows.
CALIB_TEMP_PRIOR = 1.5
CALIB_DRAW_PRIOR = 1.5
# Where the daily-fitted calibration artifact is written/read.
CALIBRATION_PATH = RESULTS_DIR / "calibration" / "calibration_latest.json"
```

(`RESULTS_DIR` is already defined in `config.py`; confirm it is imported/defined above this point — it is used widely.)

- [ ] **Step 2: Write the failing tests**

```python
# append to tests/test_calibration.py
import json
from prediction.calibration import fit_calibration, save_calibration, load_calibration

def _records(n_each):
    # synthetic: outcomes drawn to match a known frequency
    recs = []
    base = {"win_a": 0.55, "draw": 0.20, "win_b": 0.25}
    for outcome, n in n_each.items():
        for _ in range(n):
            recs.append({"probs": dict(base), "outcome": outcome})
    return recs

def test_fit_empty_is_identity():
    calib, diag = fit_calibration([], temp_prior=1.5, draw_prior=1.5)
    assert calib.is_identity()
    assert diag["n_wc"] == 0

def test_fit_lifts_delta_when_draws_underpredicted():
    # draws happen 40% but model says 20% -> delta should rise
    recs = _records({"win_a": 30, "draw": 40, "win_b": 30})
    calib, diag = fit_calibration(recs, temp_prior=1.5, draw_prior=1.5)
    assert calib.delta > 0.0
    assert diag["draw_rate_observed"] == pytest.approx(0.40, abs=0.01)
    assert diag["brier_after"] <= diag["brier_before"] + 1e-9

def test_fit_shrinks_toward_identity_with_tiny_n():
    recs = _records({"win_a": 1, "draw": 1, "win_b": 0})
    calib, _ = fit_calibration(recs, temp_prior=50.0, draw_prior=50.0)
    assert abs(calib.T - 1.0) < 0.25 and abs(calib.delta) < 0.25

def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "calib.json"
    save_calibration(Calibration(1.2, 0.3), {"n_wc": 5}, p)
    got = load_calibration(p)
    assert got.T == pytest.approx(1.2) and got.delta == pytest.approx(0.3)

def test_load_missing_is_identity(tmp_path):
    assert load_calibration(tmp_path / "nope.json").is_identity()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_calibration.py -q`
Expected: FAIL (`cannot import name 'fit_calibration'`).

- [ ] **Step 4: Implement fitter + I/O**

Append to `prediction/calibration.py`:

```python
import json
from pathlib import Path

_OUTCOMES = ("win_a", "draw", "win_b")


def _brier3(p: dict[str, float], outcome: str) -> float:
    return sum((p[k] - (1.0 if k == outcome else 0.0)) ** 2 for k in _OUTCOMES)


def _mean_brier(records, calib: Calibration) -> float:
    if not records:
        return 0.0
    return sum(_brier3(calibrate(r["probs"], calib), r["outcome"]) for r in records) / len(records)


def fit_calibration(records, *, temp_prior: float, draw_prior: float):
    """Fit (T, delta) on WC group records minimising mean Brier + identity priors.

    records: [{"probs": {win_a,draw,win_b}, "outcome": one of them}]. Empty -> identity.
    Returns (Calibration, diagnostics).
    """
    n = len(records)
    if n == 0:
        return Calibration(), {
            "n_wc": 0, "T": 1.0, "delta": 0.0,
            "draw_rate_observed": None, "draw_rate_predicted_raw": None,
            "brier_before": None, "brier_after": None,
            "in_sample_fit_diagnostic": True,
        }

    from scipy.optimize import minimize

    def loss(x):
        T, delta = float(x[0]), float(x[1])
        if T <= 0.0:
            return 1e9
        c = Calibration(T=T, delta=delta)
        mean_brier = _mean_brier(records, c)
        reg = (temp_prior * (T - 1.0) ** 2 + draw_prior * delta ** 2) / n
        return mean_brier + reg

    res = minimize(loss, x0=[1.0, 0.0], method="Nelder-Mead",
                   options={"xatol": 1e-4, "fatol": 1e-6, "maxiter": 2000})
    calib = Calibration(T=float(res.x[0]), delta=float(res.x[1]))

    draw_obs = sum(1 for r in records if r["outcome"] == "draw") / n
    draw_pred = sum(r["probs"]["draw"] for r in records) / n
    diag = {
        "n_wc": n,
        "T": round(calib.T, 4),
        "delta": round(calib.delta, 4),
        "draw_rate_observed": round(draw_obs, 4),
        "draw_rate_predicted_raw": round(draw_pred, 4),
        "brier_before": round(_mean_brier(records, Calibration()), 4),
        "brier_after": round(_mean_brier(records, calib), 4),
        "in_sample_fit_diagnostic": True,
    }
    return calib, diag


def save_calibration(calib: Calibration, diagnostics: dict, path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(diagnostics)
    payload["T"] = calib.T
    payload["delta"] = calib.delta
    path.write_text(json.dumps(payload, indent=2))


def load_calibration(path) -> Calibration:
    path = Path(path)
    if not path.exists():
        return Calibration()
    try:
        d = json.loads(path.read_text())
        return Calibration(T=float(d["T"]), delta=float(d["delta"]))
    except (ValueError, KeyError, OSError):
        return Calibration()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_calibration.py -q`
Expected: PASS (12 passed).

- [ ] **Step 6: Commit**

```bash
git add prediction/calibration.py tests/test_calibration.py config.py
git commit -m "feat(calibration): fitter with shrinkage priors + artifact I/O"
```

---

### Task 3: Thread `calib` into match_probabilities / knockout_probabilities

**Files:**
- Modify: `prediction/match_predictor.py:18-46` (`match_probabilities`), `:49-73` (`knockout_probabilities`)
- Test: `tests/test_match_predictor.py` (extend)

**Interfaces:**
- Consumes: `Calibration`, `calibrate` (Task 1).
- Produces: `match_probabilities(elo_a, elo_b, home_advantage=0.0, nu=..., calib=None)`; `knockout_probabilities(elo_a, elo_b, home_advantage=0.0, nu=..., penalty_adv=..., calib=None)`. Knockout calibrates the 90-min 3-way **before** ET/penalty redistribution.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_match_predictor.py
from prediction.calibration import Calibration, calibrate
from prediction.match_predictor import match_probabilities, knockout_probabilities

def test_match_probs_calib_none_unchanged():
    a = match_probabilities(1700, 1500)
    b = match_probabilities(1700, 1500, calib=None)
    assert a == b

def test_match_probs_calib_applied():
    raw = match_probabilities(1700, 1500)
    c = Calibration(1.5, 0.3)
    got = match_probabilities(1700, 1500, calib=c)
    assert got == calibrate(raw, c)

def test_knockout_calibrates_before_redistribution():
    # delta raises the 90-min draw mass, which then redistributes into advance probs
    base = knockout_probabilities(1700, 1500)
    with_delta = knockout_probabilities(1700, 1500, calib=Calibration(1.0, 0.8))
    assert abs(sum(with_delta.values()) - 1.0) < 1e-9
    assert with_delta != base
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_match_predictor.py -q`
Expected: FAIL (`match_probabilities() got an unexpected keyword argument 'calib'`).

- [ ] **Step 3: Implement**

In `prediction/match_predictor.py`, add the import near the top:

```python
from prediction.calibration import Calibration, calibrate
```

Change `match_probabilities` signature and return (lines 18-46):

```python
def match_probabilities(
    elo_a: float,
    elo_b: float,
    home_advantage: float = 0.0,
    nu: float = BRADLEY_TERRY_DRAW_NU,
    calib: "Calibration | None" = None,
) -> dict[str, float]:
    ...  # body unchanged up to building the result dict
    raw = {
        "win_a": exp_a / denom,
        "draw": nu * math.sqrt(exp_a * exp_b) / denom,
        "win_b": exp_b / denom,
    }
    return calibrate(raw, calib)
```

Change `knockout_probabilities` (lines 49-73) to accept `calib` and pass it to the inner call:

```python
def knockout_probabilities(
    elo_a: float,
    elo_b: float,
    home_advantage: float = 0.0,
    nu: float = BRADLEY_TERRY_DRAW_NU,
    penalty_adv: float = KNOCKOUT_PENALTY_ADVANTAGE,
    calib: "Calibration | None" = None,
) -> dict[str, float]:
    base = match_probabilities(elo_a, elo_b, home_advantage, nu, calib=calib)
    ...  # redistribution body unchanged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_match_predictor.py tests/test_calibration.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add prediction/match_predictor.py tests/test_match_predictor.py
git commit -m "feat(calibration): optional calib in match/knockout probabilities"
```

---

### Task 4: Calibrate the ensemble in `ensemble_match_prediction` + expose raw

**Files:**
- Modify: `prediction/score_predictor.py:117-179` (`ensemble_match_prediction`)
- Test: `tests/test_score_predictor.py` (extend)

**Interfaces:**
- Consumes: `Calibration`, `calibrate`; calibrated per-model `knockout_probabilities` (Task 3).
- Produces: `ensemble_match_prediction(elo_pairs, home_advantage=0.0, knockout=False, calib=None) -> dict`. Output now also includes `p_home_raw`, `p_draw_raw`, `p_away_raw` (uncalibrated ensemble). For group, `p_home/p_draw/p_away` are **calibrated** and the scoreline grid is conditioned on the calibrated probs. Knockout `p_adv_home` uses per-model calibrated `knockout_probabilities`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_score_predictor.py
from prediction.calibration import Calibration
from prediction.score_predictor import ensemble_match_prediction

PAIRS = [(1700, 1500), (1680, 1520), (1720, 1490)]

def test_ensemble_calib_none_byte_identical():
    a = ensemble_match_prediction(PAIRS)
    b = ensemble_match_prediction(PAIRS, calib=None)
    # ignore the new *_raw keys when comparing to the legacy shape
    for k in ("p_home", "p_draw", "p_away", "scoreline"):
        assert a[k] == b[k]

def test_ensemble_exposes_raw_equal_to_calibrated_at_identity():
    out = ensemble_match_prediction(PAIRS)
    assert out["p_home_raw"] == out["p_home"]
    assert out["p_draw_raw"] == out["p_draw"]

def test_ensemble_calibration_lifts_draw_and_conditions_scoreline():
    raw = ensemble_match_prediction(PAIRS)
    cal = ensemble_match_prediction(PAIRS, calib=Calibration(1.3, 0.6))
    assert cal["p_draw"] > raw["p_draw"]
    assert cal["p_draw_raw"] == raw["p_draw"]  # raw is unchanged
    # scoreline conditioned on calibrated probs -> 1-1/0-0 mass shifts up
    assert cal["scoreline"]["most_likely"] is not None
    assert abs(cal["p_home"] + cal["p_draw"] + cal["p_away"] - 1.0) < 1e-9
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_score_predictor.py -q`
Expected: FAIL (`unexpected keyword argument 'calib'` / `KeyError: 'p_home_raw'`).

- [ ] **Step 3: Implement**

In `prediction/score_predictor.py`, add import:

```python
from prediction.calibration import Calibration, calibrate
```

Rewrite `ensemble_match_prediction` (keep per-model RAW, calibrate the ensemble, condition on calibrated):

```python
def ensemble_match_prediction(
    elo_pairs: list[tuple[float, float]],
    home_advantage: float = 0.0,
    knockout: bool = False,
    calib: "Calibration | None" = None,
) -> dict:
    per_model = []
    grids = []
    lams = []
    for elo_h, elo_a in elo_pairs:
        probs = match_probabilities(elo_h, elo_a, home_advantage)   # RAW per model
        m = {
            "p_home": round(probs["win_a"], 4),
            "p_draw": round(probs["draw"], 4),
            "p_away": round(probs["win_b"], 4),
        }
        if knockout:
            adv = knockout_probabilities(elo_h, elo_a, home_advantage, calib=calib)
            m["p_adv_home"] = round(adv["win_a"], 4)
        per_model.append(m)
        lam = expected_goals(elo_h, elo_a, home_advantage)
        lams.append(lam)
        grids.append(score_grid(*lam))

    # Ensemble RAW 3-way
    p_home_raw = float(np.mean([m["p_home"] for m in per_model]))
    p_draw_raw = float(np.mean([m["p_draw"] for m in per_model]))
    p_away_raw = float(np.mean([m["p_away"] for m in per_model]))

    # Calibrate the ensemble (the object the honest match-Brier is computed on)
    cal3 = calibrate(
        {"win_a": p_home_raw, "draw": p_draw_raw, "win_b": p_away_raw}, calib
    )
    p_home, p_draw, p_away = cal3["win_a"], cal3["draw"], cal3["win_b"]

    grid = condition_grid(np.mean(grids, axis=0), p_home, p_draw, p_away)
    top = top_scorelines(grid, n=6)

    n = grid.shape[0]
    gi, gj = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    out = {
        "p_home": round(p_home, 4),
        "p_draw": round(p_draw, 4),
        "p_away": round(p_away, 4),
        "p_home_raw": round(p_home_raw, 4),
        "p_draw_raw": round(p_draw_raw, 4),
        "p_away_raw": round(p_away_raw, 4),
        "scoreline": {
            "top_scores": [
                {"score": f"{a}-{b}", "p": round(p, 4)} for a, b, p in top
            ],
            "most_likely": f"{top[0][0]}-{top[0][1]}",
            "most_likely_p": round(top[0][2], 4),
            "xg_home": round(float(np.mean([l[0] for l in lams])), 2),
            "xg_away": round(float(np.mean([l[1] for l in lams])), 2),
            "p_over25": round(float(grid[gi + gj >= 3].sum()), 4),
            "p_btts": round(float(grid[1:, 1:].sum()), 4),
        },
        "per_model": per_model,
    }
    if knockout:
        adv_home = float(np.mean([m["p_adv_home"] for m in per_model]))
        out["p_adv_home"] = round(adv_home, 4)
        out["p_adv_away"] = round(1.0 - adv_home, 4)
    return out
```

Note: at `calib=None`, `cal3 == raw` so `p_home==p_home_raw` and `knockout_probabilities(calib=None)` is unchanged ⇒ byte-identical to the previous output for the legacy keys.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_score_predictor.py tests/test_calibration.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add prediction/score_predictor.py tests/test_score_predictor.py
git commit -m "feat(calibration): calibrate ensemble prob + expose raw in ensemble_match_prediction"
```

---

### Task 5: Thread `calib` through the Monte Carlo

**Files:**
- Modify: `prediction/tournament_simulator.py` — `_simulate_group:220`, `_simulate_knockout_match:318`, `simulate_tournament:423` (calls at 453/513/555/568/581/591), `run_monte_carlo:600` (call at 632)
- Test: `tests/test_tournament_simulator.py` (extend)

**Interfaces:**
- Consumes: calibrated `match_probabilities`/`knockout_probabilities` (Task 3).
- Produces: `run_monte_carlo(elo_ratings, n_simulations=..., seed=..., state=None, calib=None)`; `simulate_tournament(..., calib=None)`; `_simulate_group(..., calib=None)`; `_simulate_knockout_match(..., calib=None)`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_tournament_simulator.py
from prediction.calibration import Calibration
from prediction.tournament_simulator import run_monte_carlo

def test_monte_carlo_calib_none_matches_default(sample_elos):
    # sample_elos: existing fixture/dict of team->elo used elsewhere in this file
    a = run_monte_carlo(sample_elos, n_simulations=2000, seed=7)
    b = run_monte_carlo(sample_elos, n_simulations=2000, seed=7, calib=None)
    assert a.equals(b)

def test_monte_carlo_calib_changes_distribution(sample_elos):
    base = run_monte_carlo(sample_elos, n_simulations=4000, seed=7)
    flat = run_monte_carlo(sample_elos, n_simulations=4000, seed=7,
                           calib=Calibration(2.0, 0.5))
    # flattening should reduce the top team's champion prob (more parity)
    top_base = base.sort_values("P(champion)", ascending=False).iloc[0]["P(champion)"]
    top_flat = flat.set_index("team").loc[
        base.sort_values("P(champion)", ascending=False).iloc[0]["team"], "P(champion)"]
    assert top_flat <= top_base + 1e-9
```

If there is no existing `sample_elos` fixture, build a minimal one in the test from `config.ALL_TEAMS` with uniform 1500 plus a couple of stronger teams; keep `n_simulations` small for speed.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tournament_simulator.py -q`
Expected: FAIL (`unexpected keyword argument 'calib'`).

- [ ] **Step 3: Implement — add `calib` param and pass it down**

`_simulate_group` (line 220): add `calib: "Calibration | None" = None` to the signature; change line 267 to:

```python
            probs = match_probabilities(elo_a, elo_b, home_advantage=ha, calib=calib)
```

`_simulate_knockout_match` (line 318): add `calib: "Calibration | None" = None`; change line 340 to:

```python
    probs = knockout_probabilities(elo_a, elo_b, home_advantage=ha, calib=calib)
```

`simulate_tournament` (line 423): add `calib: "Calibration | None" = None` to the signature. Pass `calib=calib` at the group call (453) and at **every** `_simulate_knockout_match(...)` call (513, 555, 568, 581, 591), e.g.:

```python
        standings = _simulate_group(teams, elo_ratings, rng, played=played, calib=calib)
...
        winner = _simulate_knockout_match(team_a, team_b, elo_ratings, rng,
                                          venue_country=vc, known_winners=kw, calib=calib)
```

(Match each existing call's other arguments exactly; only add `calib=calib`.)

`run_monte_carlo` (line 600): add `calib: "Calibration | None" = None`; change the call at 632 to:

```python
        result = simulate_tournament(elo_ratings, rng, groups=groups, state=state, calib=calib)
```

Add the import at the top of the file:

```python
from prediction.calibration import Calibration  # noqa: F401  (type hint only)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tournament_simulator.py tests/test_live_tournament.py -q`
Expected: PASS (existing simulator tests still green; new ones pass).

- [ ] **Step 5: Commit**

```bash
git add prediction/tournament_simulator.py tests/test_tournament_simulator.py
git commit -m "feat(calibration): thread calib through Monte Carlo simulation"
```

---

### Task 6: Lock calibrated predictions with raw + provenance

**Files:**
- Modify: `evaluation/live_scoring.py:50-130` (`predict_upcoming_matches`); add `build_calibration_records`
- Test: `tests/test_live_tournament.py` (extend)

**Interfaces:**
- Consumes: `Calibration`, `calibrate`; calibrated `ensemble_match_prediction` (Task 4); `match_probabilities`/`knockout_probabilities` (Task 3).
- Produces:
  - `predict_upcoming_matches(wc_df, elo_ratings, horizon_days=3, model_elos=None, calib=None) -> int`. New CSV columns: `p_home_raw,p_draw_raw,p_away_raw,calib_T,calib_delta`. `p_home/p_draw/p_away` are the **calibrated** locked probs.
  - `build_calibration_records(wc_df, now) -> list[dict]` — WC **group** records `{"probs": raw 3-way, "outcome": ...}` for matches with `kickoff_utc < now`, joining `match_predictions.csv` raw probs to completed results in `wc_df`. Asserts `kickoff_utc < now` for every record (I1).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_live_tournament.py
from datetime import datetime, timedelta, timezone
import pandas as pd
from prediction.calibration import Calibration
from evaluation import live_scoring

def _future_match_df(now):
    ko = (now + timedelta(days=1)).isoformat()
    return pd.DataFrame([{
        "kickoff_utc": ko, "stage": "group", "completed": False,
        "home_team": "Spain", "away_team": "Croatia",
    }])

def test_locked_prediction_records_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr(live_scoring, "MATCH_PREDS_CSV", tmp_path / "mp.csv")
    now = datetime.now(timezone.utc)
    df = _future_match_df(now)
    elos = {"Spain": 1900, "Croatia": 1650}
    live_scoring.predict_upcoming_matches(df, elos, calib=Calibration(1.3, 0.5))
    out = pd.read_csv(tmp_path / "mp.csv")
    assert {"p_home_raw", "p_draw_raw", "p_away_raw", "calib_T", "calib_delta"} <= set(out.columns)
    assert out.iloc[0]["calib_T"] == 1.3 and out.iloc[0]["calib_delta"] == 0.5
    # calibrated draw > raw draw (delta>0)
    assert out.iloc[0]["p_draw"] > out.iloc[0]["p_draw_raw"]

def test_predictions_are_immutable_on_rerun(tmp_path, monkeypatch):
    monkeypatch.setattr(live_scoring, "MATCH_PREDS_CSV", tmp_path / "mp.csv")
    now = datetime.now(timezone.utc)
    df = _future_match_df(now)
    elos = {"Spain": 1900, "Croatia": 1650}
    live_scoring.predict_upcoming_matches(df, elos, calib=Calibration(1.3, 0.5))
    first = pd.read_csv(tmp_path / "mp.csv").iloc[0].to_dict()
    # re-run with a DIFFERENT calibration -> existing row must not change (I3)
    live_scoring.predict_upcoming_matches(df, elos, calib=Calibration(2.0, 0.0))
    after = pd.read_csv(tmp_path / "mp.csv")
    assert len(after) == 1
    assert after.iloc[0]["p_home"] == first["p_home"]
    assert after.iloc[0]["calib_T"] == first["calib_T"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_live_tournament.py -q`
Expected: FAIL (`unexpected keyword argument 'calib'`).

- [ ] **Step 3: Implement**

In `evaluation/live_scoring.py` add imports:

```python
from prediction.calibration import Calibration, calibrate
```

Change `predict_upcoming_matches` signature to add `calib: "Calibration | None" = None`. Inside the loop, replace the prob computation/row append:

```python
        if model_elos:
            elo_pairs = [
                (m.get(home, 1500.0), m.get(away, 1500.0))
                for m in model_elos.values()
            ]
            pred = ensemble_match_prediction(elo_pairs, home_advantage=ha,
                                             knockout=is_ko, calib=calib)
            if is_ko:
                p_home, p_draw, p_away = pred["p_adv_home"], 0.0, pred["p_adv_away"]
                ph_raw, pd_raw, pa_raw = pred["p_adv_home"], 0.0, pred["p_adv_away"]
            else:
                p_home, p_draw, p_away = pred["p_home"], pred["p_draw"], pred["p_away"]
                ph_raw, pd_raw, pa_raw = pred["p_home_raw"], pred["p_draw_raw"], pred["p_away_raw"]
            pred_score = pred["scoreline"]["most_likely"]
            pred_score_p = pred["scoreline"]["most_likely_p"]
        else:
            elo_h = elo_ratings.get(home, 1500.0)
            elo_a = elo_ratings.get(away, 1500.0)
            if is_ko:
                raw = knockout_probabilities(elo_h, elo_a, home_advantage=ha)
                cal = knockout_probabilities(elo_h, elo_a, home_advantage=ha, calib=calib)
                p_home, p_draw, p_away = cal["win_a"], 0.0, cal["win_b"]
                ph_raw, pd_raw, pa_raw = raw["win_a"], 0.0, raw["win_b"]
            else:
                raw = match_probabilities(elo_h, elo_a, home_advantage=ha)
                cal = calibrate(raw, calib)
                p_home, p_draw, p_away = cal["win_a"], cal["draw"], cal["win_b"]
                ph_raw, pd_raw, pa_raw = raw["win_a"], raw["draw"], raw["win_b"]
            pred_score, pred_score_p = None, None

        _cal = calib or Calibration()
        rows.append({
            "predicted_at": now.isoformat(),
            "kickoff_utc": r["kickoff_utc"],
            "stage": r["stage"],
            "home_team": home,
            "away_team": away,
            "p_home": round(p_home, 4),
            "p_draw": round(p_draw, 4),
            "p_away": round(p_away, 4),
            "p_home_raw": round(ph_raw, 4),
            "p_draw_raw": round(pd_raw, 4),
            "p_away_raw": round(pa_raw, 4),
            "calib_T": _cal.T,
            "calib_delta": _cal.delta,
            "pred_score": pred_score,
            "pred_score_p": pred_score_p,
        })
```

The existing dedup (`seen`) already guarantees first-prediction-wins (I3): a fixture already in the CSV is skipped, so re-running with a different calibration never rewrites it.

Add `build_calibration_records` (place after `score_completed_matches`):

```python
def build_calibration_records(wc_df: pd.DataFrame, now: datetime) -> list[dict]:
    """WC group records {raw 3-way probs, outcome} for matches kicked off before now.

    Uses RAW probabilities (pre-calibration) so the fit never sees its own output.
    Enforces kickoff_utc < now (I1).
    """
    if wc_df is None or wc_df.empty or not MATCH_PREDS_CSV.exists():
        return []
    preds = pd.read_csv(MATCH_PREDS_CSV)
    done = wc_df[wc_df["completed"]]
    if preds.empty or done.empty:
        return []

    merged = preds.merge(
        done[["kickoff_utc", "home_team", "away_team", "home_score", "away_score"]],
        on=["kickoff_utc", "home_team", "away_team"], how="inner",
    )
    records = []
    for _, r in merged.iterrows():
        if r["stage"] in KNOCKOUT_STAGES:
            continue  # group-only fit (3-way)
        ko = datetime.fromisoformat(r["kickoff_utc"])
        assert ko < now, f"I1 violation: fit record kickoff {ko} >= now {now}"
        # RAW probs: legacy rows (locked before this feature) have no *_raw -> raw==locked
        ph = r.get("p_home_raw"); ph = r["p_home"] if pd.isna(ph) else ph
        pdr = r.get("p_draw_raw"); pdr = r["p_draw"] if pd.isna(pdr) else pdr
        pa = r.get("p_away_raw"); pa = r["p_away"] if pd.isna(pa) else pa
        if r["home_score"] > r["away_score"]:
            outcome = "win_a"
        elif r["home_score"] == r["away_score"]:
            outcome = "draw"
        else:
            outcome = "win_b"
        records.append({
            "probs": {"win_a": float(ph), "draw": float(pdr), "win_b": float(pa)},
            "outcome": outcome,
        })
    return records
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_live_tournament.py tests/test_calibration.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add evaluation/live_scoring.py tests/test_live_tournament.py
git commit -m "feat(calibration): lock calibrated preds with raw+provenance; fit-record builder"
```

---

### Task 7: `step_calibrate` + pipeline wiring

**Files:**
- Modify: `pipeline/matchday_run.py` (new `step_calibrate`; wire `calib` into steps 6 & 8)
- Test: `tests/test_live_tournament.py` (extend, integration-light)

**Interfaces:**
- Consumes: `build_calibration_records` (Task 6), `fit_calibration`/`save_calibration`/`load_calibration` (Task 2), `run_monte_carlo(..., calib=...)` (Task 5), `predict_upcoming_matches(..., calib=...)` (Task 6), config `CALIB_TEMP_PRIOR/CALIB_DRAW_PRIOR/CALIBRATION_PATH`.
- Produces: `step_calibrate(wc_df, now) -> Calibration` (fits, writes artifact, returns calib; empty fit set ⇒ identity).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_live_tournament.py
def test_step_calibrate_writes_artifact_and_returns_identity_when_empty(tmp_path, monkeypatch):
    from pipeline import matchday_run
    import config
    monkeypatch.setattr(config, "CALIBRATION_PATH", tmp_path / "calib.json")
    monkeypatch.setattr(matchday_run, "CALIBRATION_PATH", tmp_path / "calib.json", raising=False)
    now = datetime.now(timezone.utc)
    calib = matchday_run.step_calibrate(pd.DataFrame(), now)  # empty wc_df
    assert calib.is_identity()
```

(If `matchday_run` reads the path from `config.CALIBRATION_PATH` directly, patching `config` is sufficient; keep whichever the implementation uses.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_live_tournament.py::test_step_calibrate_writes_artifact_and_returns_identity_when_empty -q`
Expected: FAIL (`module 'pipeline.matchday_run' has no attribute 'step_calibrate'`).

- [ ] **Step 3: Implement `step_calibrate` and wire it in**

In `pipeline/matchday_run.py`, add near the other steps:

```python
def step_calibrate(wc_df: pd.DataFrame, now: datetime):
    """Fit walk-forward calibration on played WC group matches; write artifact."""
    from config import CALIBRATION_PATH, CALIB_TEMP_PRIOR, CALIB_DRAW_PRIOR
    from evaluation.live_scoring import build_calibration_records
    from prediction.calibration import Calibration, fit_calibration, save_calibration

    records = build_calibration_records(wc_df, now)
    calib, diag = fit_calibration(records, temp_prior=CALIB_TEMP_PRIOR, draw_prior=CALIB_DRAW_PRIOR)
    diag["as_of"] = now.strftime("%Y-%m-%d")
    save_calibration(calib, diag, CALIBRATION_PATH)
    if records:
        log.info(
            "Step 2.5: Calibration fit on %d WC matches → T=%.3f δ=%.3f "
            "(draws obs %.1f%% vs pred %.1f%%, in-sample Brier %.3f→%.3f)",
            diag["n_wc"], calib.T, calib.delta,
            100 * diag["draw_rate_observed"], 100 * diag["draw_rate_predicted_raw"],
            diag["brier_before"], diag["brier_after"],
        )
    else:
        log.info("Step 2.5: No completed WC matches yet — calibration = identity.")
    return calib
```

In `main()`, after step 2 (`elo, current_elo = step_update_elo(wc_df)`), add:

```python
    # ── 2.5 Walk-forward calibration (fit on played matches; future-only) ─────
    calib = step_calibrate(wc_df, today)
```

Then thread `calib` into the two application sites:
- Step 6 Monte Carlo (line ~145): `run_monte_carlo(elos, n_simulations=50_000, seed=42 + i * 1000, state=state, calib=calib)`
- Step 8 scoring (line ~183): `predict_upcoming_matches(wc_df, current_elo, model_elos=model_elos, calib=calib)`

Add to the imports inside `main()`: `from prediction.calibration import load_calibration` is **not** needed here (we already have `calib` from `step_calibrate`); the dashboard step (Task 8) reads the artifact independently.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_live_tournament.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/matchday_run.py tests/test_live_tournament.py
git commit -m "feat(calibration): step_calibrate + wire calib into Monte Carlo & scoring"
```

---

### Task 8: Dashboard meta + frontend calibration line

**Files:**
- Modify: `visualization/dashboard.py:614-622` (meta block)
- Modify: `web/` — the "AI 战绩" tab component (locate via `rg -n "战绩|scoreboard|performance" web/`)
- Test: `tests/test_*` (add a small dashboard-meta unit test if a dashboard test module exists; otherwise assert via the validation run in Task 9)

**Interfaces:**
- Consumes: `load_calibration` + the artifact JSON (Task 2/7).
- Produces: `data.json` `meta.calibration = {T, delta, n_wc, draw_rate_observed, draw_rate_predicted_raw}`.

- [ ] **Step 1: Add calibration to dashboard meta**

In `visualization/dashboard.py`, inside `build_dashboard` where `meta` is assembled (around line 614), add a helper and a field:

```python
def _load_calibration_meta() -> dict | None:
    from config import CALIBRATION_PATH
    import json
    if not CALIBRATION_PATH.exists():
        return None
    try:
        d = json.loads(CALIBRATION_PATH.read_text())
        return {
            "T": d.get("T"), "delta": d.get("delta"), "n_wc": d.get("n_wc"),
            "draw_rate_observed": d.get("draw_rate_observed"),
            "draw_rate_predicted_raw": d.get("draw_rate_predicted_raw"),
        }
    except (ValueError, OSError):
        return None
```

In the `"meta": { ... }` dict add:

```python
            "calibration": _load_calibration_meta(),
```

- [ ] **Step 2: Verify meta serialises**

Run:
```bash
python -c "from visualization.dashboard import _load_calibration_meta; print(_load_calibration_meta())"
```
Expected: `None` (no artifact yet) or a dict — no exception.

- [ ] **Step 3: Frontend line (Chinese, no emoji, solid colors)**

Locate the AI-战绩 tab: `rg -n "战绩|performance|n_scored|Brier" web/`. In that component, read `data.meta.calibration` and, when `T` is meaningfully off 1 or `delta` != 0, render one muted line, e.g.:

```tsx
{meta.calibration && (Math.abs(meta.calibration.T - 1) > 0.02 || Math.abs(meta.calibration.delta) > 0.02) && (
  <p className="text-xs text-zinc-400">
    已按 {meta.calibration.n_wc} 场实战校准（T={meta.calibration.T.toFixed(2)}
    {meta.calibration.delta > 0 ? `，平局+${meta.calibration.delta.toFixed(2)}` : ""}）
  </p>
)}
```

Match the surrounding component's existing class conventions (zinc palette, no gradient).

- [ ] **Step 4: Rebuild the static export**

Run:
```bash
cd web && npm run build && cd ..
```
Expected: build succeeds, `web/out` regenerated. (Cron only swaps `data.json`; the component change must be built in now.)

- [ ] **Step 5: Commit**

```bash
git add visualization/dashboard.py web/
git commit -m "feat(calibration): surface calibration state in dashboard meta + AI战绩 tab"
```

---

### Task 9: Validation, evidence run, and self-check (I6)

**Files:**
- Create: `scripts/validate_calibration.py`
- Run: full pipeline dry-style validation

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write a reliability + sanity validator**

```python
# scripts/validate_calibration.py
"""Evidence run: fit calibration on real played matches and report the honest deltas.

Prints (a) the fitted (T, delta), (b) in-sample Brier before/after on the fit set,
(c) observed vs predicted draw rate, (d) a champion-prob sanity check (top-5 still
sensible). This is a diagnostic — the HEADLINE live Brier remains the out-of-sample
number from live_scoring.score_completed_matches on locked predictions (I2/I6).
"""
from datetime import datetime, timezone
import pandas as pd

from config import CALIB_TEMP_PRIOR, CALIB_DRAW_PRIOR
from data.fetcher_wc_results import fetch_wc_results
from evaluation.live_scoring import build_calibration_records
from prediction.calibration import fit_calibration

wc = fetch_wc_results(force=True)
now = datetime.now(timezone.utc)
records = build_calibration_records(wc, now)
calib, diag = fit_calibration(records, temp_prior=CALIB_TEMP_PRIOR, draw_prior=CALIB_DRAW_PRIOR)
print("Fitted:", calib)
print("Diagnostics:", diag)
assert diag["brier_after"] is None or diag["brier_after"] <= diag["brier_before"] + 1e-9, \
    "calibration must not worsen in-sample Brier"
print("OK — in-sample Brier did not worsen.")
```

- [ ] **Step 2: Run the full test suite**

Run: `python -m pytest -q`
Expected: PASS — all existing tests + the new calibration/score/simulator/live tests green.

- [ ] **Step 3: Run the evidence validator**

Run: `python scripts/validate_calibration.py`
Expected: prints fitted `(T, δ)`, `n_wc`≈36, observed draw ≈0.31 vs predicted ≈0.23, `brier_after ≤ brier_before`. Capture this real output — it is the I6 evidence.

- [ ] **Step 4: End-to-end dry validation of the pipeline path**

Run (a guarded import-and-build smoke, no deploy):
```bash
python -c "
from datetime import datetime, timezone
import pandas as pd
from pipeline.matchday_run import step_calibrate
from data.fetcher_wc_results import fetch_wc_results
wc = fetch_wc_results(force=True)
calib = step_calibrate(wc, datetime.now(timezone.utc))
print('pipeline calib:', calib)
"
```
Expected: writes `results/calibration/calibration_latest.json`, prints the fitted calib, no exception.

- [ ] **Step 5: Commit**

```bash
git add scripts/validate_calibration.py
git commit -m "feat(calibration): validation/evidence script + end-to-end check"
```

---

## Self-Review

**Spec coverage:**
- §3.1 I1 → Task 6 `build_calibration_records` (assert kickoff<now, raw probs) + Task 9.
- §3.1 I2 → Task 8 (meta sources `n_scored` Brier from scoring, never artifact `brier_*`) + Task 9 docstring.
- §3.1 I3 → Task 6 immutability test + `seen` dedup; provenance columns.
- §3.1 I4 → no task rewrites past rows (enforced by dedup); explicit in Task 6.
- §3.1 I5 → existing `score_completed_matches` logs `n` + Brier; `n_wc` in artifact (Task 2/7).
- §3.1 I6 → Task 9 evidence run.
- §4 transform → Task 1. §5 fitter + WC-only + priors → Task 2. §6 sites → Tasks 3/4/5/6; storage → Task 6; step + JSON → Task 7; dashboard → Task 8.
- §7 tests → each task's tests + Task 9 full suite. §8 graceful degradation → `calib=None` defaults + byte-identical tests in Tasks 3/4/5.

**Placeholder scan:** none — every code step shows full code.

**Type consistency:** `Calibration(T, delta)`, `calibrate(probs, calib)`, `fit_calibration(records, *, temp_prior, draw_prior)`, `build_calibration_records(wc_df, now)`, `step_calibrate(wc_df, now)`, `*_raw`/`calib_T`/`calib_delta` columns, `run_monte_carlo(..., calib=None)` — names match across tasks. Probability keys `win_a/draw/win_b` throughout; `p_home/p_draw/p_away` only at the CSV/dashboard layer.

**Open verification deferred to execution:** the exact `_simulate_knockout_match` call arguments at lines 513/555/568/581/591 must be matched verbatim when adding `calib=calib` (Task 5 Step 3); the AI-战绩 component path is found via `rg` (Task 8 Step 3).
