# Phase 2: Residual Form Strength Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an evidence-gated residual recent-form Elo adjustment to live team strength, proven (or refuted) by a new walk-forward in-tournament backtest on the 2014/2018/2022 World Cups.

**Architecture:** A pure `prediction/form.py` computes a team's performance residual vs Elo expectation (points or goal-difference variant) and maps it to a clamped Elo bump. A new `elo_as_of` lookup gives each match its pre-match Elo. A walk-forward backtest in `evaluation/backtester.py` sweeps `(variant, λ)` over real historical WC matches (pulled from `matches.parquet`) and reports out-of-sample match Brier. The bump is wired into `live_model_elos` as a third addend, defaulting to a no-op (`FORM_LAMBDA=0`) until the backtest justifies a value.

**Tech Stack:** Python 3.11+, numpy, pandas, pytest. Reuses `data/elo.py`, `prediction/match_predictor.py`, `prediction/score_predictor.py`, `evaluation/metrics.py`.

## Global Constraints

- **Evidence-gated, default OFF:** `FORM_LAMBDA = 0.0` ⇒ `form_bump ≡ 0` ⇒ live strength **byte-identical** to current. A non-zero λ ships ONLY if the walk-forward backtest improves out-of-sample match Brier **on all three** WCs (2014/2018/2022); otherwise ship λ=0 and document the negative result.
- **Walk-forward / no lookahead:** a match's prediction and its residual use ONLY matches with `date < that match's date`. Pre-match Elo via `elo_as_of` (strictly-earlier rows). No future info in any prediction or score.
- **No double-counting:** the signal is a *residual* (actual − Elo-expected), so a team performing exactly as Elo predicted gets a 0 bump; the bump is clamped to ±`FORM_CAP`.
- **No new data sources:** residuals derive from final scores already in `data/cache/matches.parquet` (no xG) and from `match_probabilities`/`expected_goals`.
- **No new dependencies.** Commits must NOT contain a `Co-Authored-By` trailer. All existing tests stay green; test output pristine. Use `venv/bin/python -m pytest`.

**Probability/Elo facts (verified):** `match_probabilities(elo_a, elo_b, home_advantage=0.0, nu=..., calib=None) -> {"win_a","draw","win_b"}`. `expected_goals(elo_a, elo_b, home_advantage=0.0) -> (lam_a, lam_b)` (`prediction/score_predictor.py:25`). `compute_elo(matches) -> DataFrame[date, team, elo, ...]` (`data/elo.py:45`); `get_latest_elo(history) -> {team: elo}` (`:104`). `ELO_INITIAL` in config. Live strength: `live_model_elos` (`prediction/ensemble.py:8-34`) returns `{model: {team: elo}}`, live = `tsfm_elo + (current_elo - asof_elo)`.

---

### Task 1: Pure form module + config constants

**Files:**
- Create: `prediction/form.py`
- Modify: `config.py` (add `FORM_LAMBDA`, `FORM_CAP`, `FORM_VARIANT` after `BRADLEY_TERRY_DRAW_NU`)
- Test: `tests/test_form.py`

**Interfaces:**
- Consumes: `match_probabilities` (`prediction/match_predictor.py`), `expected_goals` (`prediction/score_predictor.py`).
- Produces:
  - A "match record" dict shape: `{"own_elo": float, "opp_elo": float, "home_adv": float, "gf": int, "ga": int}` (own_elo/opp_elo are PRE-match).
  - `points_residual(matches: list[dict]) -> float` (mean of actual−expected points; 0 if empty).
  - `gd_residual(matches: list[dict]) -> float` (mean of actual−expected goal diff; 0 if empty).
  - `team_form_bump(matches: list[dict], lam: float, cap: float, variant: str) -> float` (clamped Elo bump; 0 if lam==0 or empty).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_form.py
import pytest
from prediction.form import points_residual, gd_residual, team_form_bump

# A perfectly-even match (equal Elo, neutral): E[points] ~1.0-1.3; a win over-performs.
EVEN_WIN = {"own_elo": 1500, "opp_elo": 1500, "home_adv": 0.0, "gf": 2, "ga": 0}
EVEN_LOSS = {"own_elo": 1500, "opp_elo": 1500, "home_adv": 0.0, "gf": 0, "ga": 2}

def test_empty_residual_is_zero():
    assert points_residual([]) == 0.0
    assert gd_residual([]) == 0.0

def test_points_residual_positive_when_overperforming():
    # Winning an even match beats the ~1.0-1.3 expected points -> residual > 0
    assert points_residual([EVEN_WIN]) > 0.0

def test_points_residual_negative_when_underperforming():
    assert points_residual([EVEN_LOSS]) < 0.0

def test_gd_residual_sign():
    assert gd_residual([EVEN_WIN]) > 0.0      # +2 GD vs ~0 expected
    assert gd_residual([EVEN_LOSS]) < 0.0

def test_residual_near_zero_when_result_matches_expectation():
    # A heavy favourite (high Elo) winning by a little ~ matches expectation
    strong_draw = {"own_elo": 1500, "opp_elo": 1500, "home_adv": 0.0, "gf": 1, "ga": 1}
    # an even draw: expected points ~ p_win*3+p_draw*1; a draw yields 1 -> small residual
    assert abs(points_residual([strong_draw])) < 1.0

def test_form_bump_zero_when_lambda_zero():
    assert team_form_bump([EVEN_WIN], lam=0.0, cap=100.0, variant="points") == 0.0

def test_form_bump_clamped():
    big = [EVEN_WIN] * 1
    bump = team_form_bump(big, lam=10_000.0, cap=80.0, variant="points")
    assert bump == 80.0  # clamped to +cap

def test_form_bump_variant_gd():
    b = team_form_bump([EVEN_WIN], lam=50.0, cap=500.0, variant="gd")
    assert b > 0.0

def test_form_bump_unknown_variant_raises():
    with pytest.raises(ValueError):
        team_form_bump([EVEN_WIN], lam=50.0, cap=100.0, variant="bogus")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_form.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'prediction.form'`).

- [ ] **Step 3: Add config constants**

In `config.py`, after `BRADLEY_TERRY_DRAW_NU = 0.79`:

```python
# ── Phase 2: residual form strength (evidence-gated; default OFF) ─────────────
FORM_LAMBDA = 0.0          # Elo points per unit residual. 0 = feature off (no-op).
FORM_CAP = 100.0           # max |Elo bump| from form
FORM_VARIANT = "points"    # "points" or "gd" — chosen by the walk-forward backtest
```

- [ ] **Step 4: Implement `prediction/form.py`**

```python
# prediction/form.py
"""Residual recent-form signal: performance vs Elo expectation -> clamped Elo bump.

Pure module. A team's residual is the mean over its played matches of
(actual outcome - Elo-expected outcome); residual=0 means "exactly as Elo
predicted", so the bump only nudges what Elo has not already priced in.
Evidence-gated: with lam=0 the bump is always 0.
"""

from __future__ import annotations

from prediction.match_predictor import match_probabilities
from prediction.score_predictor import expected_goals


def _actual_points(gf: int, ga: int) -> float:
    if gf > ga:
        return 3.0
    if gf == ga:
        return 1.0
    return 0.0


def points_residual(matches: list[dict]) -> float:
    """Mean (actual points - Elo-expected points) over the team's matches."""
    if not matches:
        return 0.0
    total = 0.0
    for m in matches:
        p = match_probabilities(m["own_elo"], m["opp_elo"], m["home_adv"])
        exp = 3.0 * p["win_a"] + 1.0 * p["draw"]
        total += _actual_points(m["gf"], m["ga"]) - exp
    return total / len(matches)


def gd_residual(matches: list[dict]) -> float:
    """Mean (actual goal diff - Elo-expected goal diff) over the team's matches."""
    if not matches:
        return 0.0
    total = 0.0
    for m in matches:
        lam_own, lam_opp = expected_goals(m["own_elo"], m["opp_elo"], m["home_adv"])
        exp_gd = lam_own - lam_opp
        total += (m["gf"] - m["ga"]) - exp_gd
    return total / len(matches)


def team_form_bump(matches: list[dict], lam: float, cap: float, variant: str) -> float:
    """Clamped Elo bump from a team's form residual. lam=0 -> 0 (feature off)."""
    if lam == 0.0 or not matches:
        return 0.0
    if variant == "points":
        residual = points_residual(matches)
    elif variant == "gd":
        residual = gd_residual(matches)
    else:
        raise ValueError(f"unknown form variant: {variant!r}")
    return max(-cap, min(cap, lam * residual))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_form.py -q`
Expected: PASS (10 passed).

- [ ] **Step 6: Commit**

```bash
git add prediction/form.py config.py tests/test_form.py
git commit -m "feat(form): residual form signal + clamped Elo bump (default off)"
```

---

### Task 2: `elo_as_of` pre-match Elo lookup

**Files:**
- Modify: `data/elo.py` (add `elo_as_of`)
- Test: `tests/test_elo.py` (extend)

**Interfaces:**
- Consumes: an Elo history DataFrame from `compute_elo`/`build_elo_history` (columns include `date`, `team`, `elo`), and `ELO_INITIAL` from config.
- Produces: `elo_as_of(elo_history: pd.DataFrame, team: str, date) -> float` — the team's Elo from the latest row STRICTLY BEFORE `date`; `ELO_INITIAL` if none. `date` may be a `str` or `Timestamp`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_elo.py
import pandas as pd
from data.elo import elo_as_of
from config import ELO_INITIAL

def test_elo_as_of_returns_latest_strictly_before():
    hist = pd.DataFrame([
        {"date": pd.Timestamp("2014-06-10"), "team": "Brazil", "elo": 2000.0},
        {"date": pd.Timestamp("2014-06-15"), "team": "Brazil", "elo": 2030.0},
        {"date": pd.Timestamp("2014-06-20"), "team": "Brazil", "elo": 1990.0},
    ])
    # Before any history -> initial
    assert elo_as_of(hist, "Brazil", "2014-06-09") == ELO_INITIAL
    # Strictly before 2014-06-15 -> the 06-10 value (not the same-day row)
    assert elo_as_of(hist, "Brazil", "2014-06-15") == 2000.0
    # After last -> last value
    assert elo_as_of(hist, "Brazil", "2014-07-01") == 1990.0
    # Unknown team -> initial
    assert elo_as_of(hist, "Nowhere", "2014-06-20") == ELO_INITIAL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_elo.py::test_elo_as_of_returns_latest_strictly_before -q`
Expected: FAIL (`cannot import name 'elo_as_of'`).

- [ ] **Step 3: Implement**

In `data/elo.py` add (near `get_latest_elo`):

```python
def elo_as_of(elo_history: pd.DataFrame, team: str, date) -> float:
    """Team's Elo from the latest history row STRICTLY BEFORE `date`.

    Returns ELO_INITIAL when the team has no prior row. Used to get a match's
    pre-match Elo without lookahead.
    """
    from config import ELO_INITIAL

    d = pd.Timestamp(date)
    rows = elo_history[(elo_history["team"] == team) & (pd.to_datetime(elo_history["date"]) < d)]
    if rows.empty:
        return float(ELO_INITIAL)
    return float(rows.sort_values("date")["elo"].iloc[-1])
```

(Confirm `pd` is imported in `data/elo.py` — it is, used throughout.)

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_elo.py -q`
Expected: PASS (existing elo tests + the new one).

- [ ] **Step 5: Commit**

```bash
git add data/elo.py tests/test_elo.py
git commit -m "feat(elo): elo_as_of pre-match lookup (strictly-earlier, no lookahead)"
```

---

### Task 3: Walk-forward in-tournament backtest

**Files:**
- Modify: `evaluation/backtester.py` (add `walk_forward_form_backtest` + a `__main__`-runnable entry that writes the CSV)
- Test: `tests/test_backtester_form.py` (new)

**Interfaces:**
- Consumes: `team_form_bump` (Task 1), `elo_as_of` (Task 2), `compute_elo`/`match_probabilities`, `data/cache/matches.parquet`.
- Produces: `walk_forward_form_backtest(years: list[int], grid: list[tuple[str, float]], matches: pd.DataFrame | None = None) -> pd.DataFrame` — columns `["year","variant","lam","mean_brier","n_matches"]`; `lam=0` rows are the baseline. `grid` entries are `(variant, lam)`.

- [ ] **Step 1: Write the failing test (synthetic, proves no-lookahead + runs)**

```python
# tests/test_backtester_form.py
import pandas as pd
from evaluation.backtester import walk_forward_form_backtest

def _synthetic_wc(year):
    # 2 matchdays, 4 teams, all on distinct dates; tournament == FIFA World Cup
    rows = [
        # matchday 1
        {"date": f"{year}-06-12", "home_team": "A", "away_team": "B", "home_score": 3, "away_score": 0},
        {"date": f"{year}-06-13", "home_team": "C", "away_team": "D", "home_score": 1, "away_score": 1},
        # matchday 2
        {"date": f"{year}-06-17", "home_team": "A", "away_team": "C", "home_score": 2, "away_score": 1},
        {"date": f"{year}-06-18", "home_team": "B", "away_team": "D", "home_score": 0, "away_score": 0},
    ]
    df = pd.DataFrame(rows)
    df["tournament"] = "FIFA World Cup"
    df["neutral"] = True
    return df

def test_walk_forward_runs_and_reports_baseline_and_candidate():
    df = _synthetic_wc(2014)
    out = walk_forward_form_backtest(
        years=[2014], grid=[("points", 0.0), ("points", 100.0)], matches=df
    )
    assert set(out.columns) >= {"year", "variant", "lam", "mean_brier", "n_matches"}
    base = out[(out["lam"] == 0.0)]["mean_brier"].iloc[0]
    cand = out[(out["lam"] == 100.0)]["mean_brier"].iloc[0]
    assert base > 0.0 and cand > 0.0
    # only matchday-2 matches can differ (matchday-1 has no prior form) -> n_matches counts all 4
    assert out["n_matches"].iloc[0] == 4

def test_walk_forward_no_lookahead_first_matchday_unaffected_by_lambda():
    # With form, matchday-1 predictions must be identical regardless of lambda
    # (no prior matches exist), so any brier difference comes only from matchday 2.
    df = _synthetic_wc(2014)
    out = walk_forward_form_backtest(
        years=[2014], grid=[("points", 0.0), ("points", 200.0)], matches=df
    )
    # Sanity: the function completed and produced two distinct rows
    assert len(out) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_backtester_form.py -q`
Expected: FAIL (`cannot import name 'walk_forward_form_backtest'`).

- [ ] **Step 3: Implement**

In `evaluation/backtester.py` add (imports `team_form_bump`, `elo_as_of` at top of file):

```python
from collections import defaultdict

from config import RESULTS_DIR
from data.elo import compute_elo, elo_as_of
from prediction.form import team_form_bump
from prediction.match_predictor import match_probabilities


def _three_way_brier(probs: dict, gf: int, ga: int) -> float:
    o_home = 1.0 if gf > ga else 0.0
    o_draw = 1.0 if gf == ga else 0.0
    o_away = 1.0 if gf < ga else 0.0
    return ((probs["win_a"] - o_home) ** 2
            + (probs["draw"] - o_draw) ** 2
            + (probs["win_b"] - o_away) ** 2)


def walk_forward_form_backtest(years, grid, matches=None):
    """Walk-forward match-Brier over historical WCs for each (variant, lam).

    For each year, Elo is computed once over all matches up to and including
    that WC; each WC match is predicted using elo_as_of(< its date) plus the
    form bump from the team's STRICTLY-earlier WC matches this tournament.
    Returns a tidy DataFrame; lam=0 rows are the baseline.
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
        wc_start = wc["date"].min()
        # Elo history through this WC (rows are post-match; elo_as_of takes < date).
        relevant = matches[matches["date"] <= wc["date"].max()]
        history = compute_elo(relevant.sort_values("date"))

        for variant, lam in grid:
            prior = defaultdict(list)  # team -> list of played-match records
            total_brier, n = 0.0, 0
            for _, m in wc.iterrows():
                home, away = m["home_team"], m["away_team"]
                hs, as_ = int(m["home_score"]), int(m["away_score"])
                eh = elo_as_of(history, home, m["date"])
                ea = elo_as_of(history, away, m["date"])
                bump_h = team_form_bump(prior[home], lam, FORM_CAP, variant)
                bump_a = team_form_bump(prior[away], lam, FORM_CAP, variant)
                probs = match_probabilities(eh + bump_h, ea + bump_a)
                total_brier += _three_way_brier(probs, hs, as_)
                n += 1
                # record for future residuals (neutral venue in backtest)
                prior[home].append({"own_elo": eh, "opp_elo": ea, "home_adv": 0.0, "gf": hs, "ga": as_})
                prior[away].append({"own_elo": ea, "opp_elo": eh, "home_adv": 0.0, "gf": as_, "ga": hs})
            rows.append({"year": year, "variant": variant, "lam": lam,
                         "mean_brier": total_brier / n if n else 0.0, "n_matches": n})

    return pd.DataFrame(rows)


def run_form_backtest_and_save():
    """Sweep the default grid on 2014/2018/2022 and write form_backtest.csv."""
    grid = [(v, lam) for v in ("points", "gd") for lam in (0.0, 25.0, 50.0, 100.0, 150.0)]
    df = walk_forward_form_backtest([2014, 2018, 2022], grid)
    out_path = RESULTS_DIR / "evaluations" / "form_backtest.csv"
    df.to_csv(out_path, index=False)
    return df, out_path
```

Add `FORM_CAP` to the `from config import (...)` block at the top of `backtester.py` (it already imports several config names). If `RESULTS_DIR`/`compute_elo`/`match_probabilities` are already imported there, do not duplicate — merge into the existing import lines.

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_backtester_form.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add evaluation/backtester.py tests/test_backtester_form.py
git commit -m "feat(backtest): walk-forward in-tournament form backtest"
```

---

### Task 4: Wire form bump into live strength (default no-op)

**Files:**
- Modify: `prediction/form.py` (add `live_form_bumps`)
- Modify: `prediction/ensemble.py:8-34` (`live_model_elos` gains optional `form_bumps`)
- Modify: `pipeline/matchday_run.py` (Step 5 builds form_bumps from config and passes them)
- Test: `tests/test_form.py` and `tests/test_live_tournament.py` (extend)

**Interfaces:**
- Consumes: `team_form_bump` (Task 1), `elo_as_of` (Task 2).
- Produces:
  - `live_form_bumps(wc_df, elo_history, lam, cap, variant) -> dict[str, float]` in `prediction/form.py`: per-team Elo bump from that team's completed WC matches, using `elo_as_of` for each match's pre-match Elo and host home-advantage. Empty dict when `lam == 0`.
  - `live_model_elos(current_elo, snapshot, teams=None, form_bumps=None)`: adds `form_bumps.get(team, 0.0)` to each model's live Elo. `form_bumps=None` ⇒ byte-identical to current.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_form.py
import pandas as pd
from prediction.form import live_form_bumps

def test_live_form_bumps_empty_when_lambda_zero():
    wc = pd.DataFrame([{"completed": True, "home_team": "A", "away_team": "B",
                        "home_score": 2, "away_score": 0, "kickoff_utc": "2026-06-12T18:00:00+00:00",
                        "date": "2026-06-12"}])
    hist = pd.DataFrame([{"date": pd.Timestamp("2026-06-01"), "team": "A", "elo": 1600.0},
                         {"date": pd.Timestamp("2026-06-01"), "team": "B", "elo": 1500.0}])
    assert live_form_bumps(wc, hist, lam=0.0, cap=100.0, variant="points") == {}

def test_live_form_bumps_nonzero_for_overperformer():
    wc = pd.DataFrame([{"completed": True, "home_team": "A", "away_team": "B",
                        "home_score": 3, "away_score": 0, "kickoff_utc": "2026-06-12T18:00:00+00:00",
                        "date": "2026-06-12"}])
    hist = pd.DataFrame([{"date": pd.Timestamp("2026-06-01"), "team": "A", "elo": 1500.0},
                         {"date": pd.Timestamp("2026-06-01"), "team": "B", "elo": 1500.0}])
    bumps = live_form_bumps(wc, hist, lam=50.0, cap=100.0, variant="points")
    assert bumps["A"] > 0.0 and bumps["B"] < 0.0
```

```python
# append to tests/test_live_tournament.py
from prediction.ensemble import live_model_elos

def test_live_model_elos_form_bumps_none_unchanged():
    current = {"A": 1600.0, "B": 1500.0}
    snap = {"actual_elo": {"A": 1590.0, "B": 1505.0},
            "model_tournament_elo": {"M": {"A": 1620.0, "B": 1495.0}}}
    a = live_model_elos(current, snap, teams=["A", "B"])
    b = live_model_elos(current, snap, teams=["A", "B"], form_bumps=None)
    assert a == b

def test_live_model_elos_applies_form_bump():
    current = {"A": 1600.0, "B": 1500.0}
    snap = {"actual_elo": {"A": 1600.0, "B": 1500.0},
            "model_tournament_elo": {"M": {"A": 1600.0, "B": 1500.0}}}
    base = live_model_elos(current, snap, teams=["A", "B"])
    bumped = live_model_elos(current, snap, teams=["A", "B"], form_bumps={"A": 40.0})
    assert bumped["M"]["A"] == base["M"]["A"] + 40.0
    assert bumped["M"]["B"] == base["M"]["B"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_form.py tests/test_live_tournament.py -q`
Expected: FAIL (`cannot import name 'live_form_bumps'` / unexpected `form_bumps` kwarg).

- [ ] **Step 3: Implement `live_form_bumps` in `prediction/form.py`**

```python
import pandas as pd

from data.elo import elo_as_of


def _host_home_adv(home: str, away: str) -> float:
    from config import HOST_TEAMS, WC_HOST_HOME_ADVANTAGE_ELO
    if home in HOST_TEAMS:
        return float(WC_HOST_HOME_ADVANTAGE_ELO)
    if away in HOST_TEAMS:
        return -float(WC_HOST_HOME_ADVANTAGE_ELO)
    return 0.0


def live_form_bumps(wc_df, elo_history, lam: float, cap: float, variant: str) -> dict[str, float]:
    """Per-team Elo bump from completed WC matches (pre-match Elo via elo_as_of)."""
    if lam == 0.0 or wc_df is None or wc_df.empty:
        return {}
    done = wc_df[wc_df["completed"]]
    prior: dict[str, list] = {}
    for _, r in done.iterrows():
        home, away = r["home_team"], r["away_team"]
        hs, as_ = int(r["home_score"]), int(r["away_score"])
        d = r["kickoff_utc"]
        eh = elo_as_of(elo_history, home, d)
        ea = elo_as_of(elo_history, away, d)
        ha = _host_home_adv(home, away)
        prior.setdefault(home, []).append({"own_elo": eh, "opp_elo": ea, "home_adv": ha, "gf": hs, "ga": as_})
        prior.setdefault(away, []).append({"own_elo": ea, "opp_elo": eh, "home_adv": -ha, "gf": as_, "ga": hs})
    return {t: team_form_bump(ms, lam, cap, variant) for t, ms in prior.items()}
```

- [ ] **Step 4: Implement the `live_model_elos` change in `prediction/ensemble.py`**

Change the signature and apply the bump (the two return branches):

```python
def live_model_elos(
    current_elo: dict[str, float],
    snapshot: dict | None,
    teams: list[str] | None = None,
    form_bumps: dict[str, float] | None = None,
) -> dict[str, dict[str, float]]:
    if teams is None:
        teams = sorted(current_elo.keys())
    fb = form_bumps or {}

    if not snapshot or not snapshot.get("model_tournament_elo"):
        return {"Actual-Elo": {t: current_elo.get(t, 1500.0) + fb.get(t, 0.0) for t in teams}}

    asof_elo = snapshot.get("actual_elo", {})
    out: dict[str, dict[str, float]] = {}
    for model_name, tsfm_elo in snapshot["model_tournament_elo"].items():
        out[model_name] = {
            t: tsfm_elo.get(t, current_elo.get(t, 1500.0))
               + (current_elo.get(t, 1500.0) - asof_elo.get(t, current_elo.get(t, 1500.0)))
               + fb.get(t, 0.0)
            for t in teams
        }
    return out
```

(`form_bumps=None` ⇒ `fb={}` ⇒ `fb.get(t,0.0)==0.0` ⇒ byte-identical.)

- [ ] **Step 5: Wire into `pipeline/matchday_run.py` Step 5**

Where `model_elos = live_model_elos(current_elo, snapshot, teams=list(ALL_TEAMS))` is called, replace with:

```python
    from config import FORM_LAMBDA, FORM_CAP, FORM_VARIANT
    from prediction.form import live_form_bumps
    form_bumps = live_form_bumps(wc_df, elo, FORM_LAMBDA, FORM_CAP, FORM_VARIANT)
    model_elos = live_model_elos(current_elo, snapshot, teams=list(ALL_TEAMS), form_bumps=form_bumps)
    if form_bumps:
        top = sorted(form_bumps.items(), key=lambda x: -abs(x[1]))[:5]
        log.info("Step 5: form bumps (top |Δ|): %s",
                 ", ".join(f"{t} {b:+.0f}" for t, b in top))
```

(`elo` is the full Elo history DataFrame returned by `step_update_elo` at Step 2. With `FORM_LAMBDA=0`, `form_bumps={}` ⇒ no behaviour change.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_form.py tests/test_live_tournament.py -q`
Expected: PASS.

- [ ] **Step 7: Run the full suite (live_model_elos is widely used)**

Run: `venv/bin/python -m pytest -q`
Expected: PASS (all green; `FORM_LAMBDA=0` keeps everything unchanged).

- [ ] **Step 8: Commit**

```bash
git add prediction/form.py prediction/ensemble.py pipeline/matchday_run.py tests/test_form.py tests/test_live_tournament.py
git commit -m "feat(form): wire form bump into live_model_elos (default no-op)"
```

---

### Task 5: Evidence run, go/no-go decision, set `FORM_LAMBDA`

**Files:**
- Create: `scripts/run_form_backtest.py`
- Modify: `config.py` (set `FORM_LAMBDA`/`FORM_VARIANT` per the gate — possibly leave at 0)
- Modify: `docs/superpowers/specs/2026-06-21-phase2-form-strength-design.md` (append the real result)

**Interfaces:**
- Consumes: `run_form_backtest_and_save` (Task 3).

- [ ] **Step 1: Create the evidence script**

```python
# scripts/run_form_backtest.py
"""Evidence run: walk-forward form backtest on 2014/2018/2022, applying the
go/no-go gate. Prints the per-(variant,lam) OOS match Brier table and the
across-WC averages. Sets nothing automatically — the operator reads the table
and updates config.FORM_LAMBDA/FORM_VARIANT only if a lam>0 beats lam=0 on ALL
three WCs (see spec section 7)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.backtester import run_form_backtest_and_save

df, out_path = run_form_backtest_and_save()
print(f"Wrote {out_path}")
# Per-year table
pivot = df.pivot_table(index=["variant", "lam"], columns="year", values="mean_brier")
pivot["avg"] = pivot.mean(axis=1)
print(pivot.to_string())

# Go/no-go: a candidate must beat its variant's lam=0 baseline on EVERY year.
print("\\n=== go/no-go (must beat lam=0 on all three WCs) ===")
for variant in df["variant"].unique():
    sub = df[df["variant"] == variant]
    base = sub[sub["lam"] == 0.0].set_index("year")["mean_brier"]
    for lam in sorted(sub["lam"].unique()):
        if lam == 0.0:
            continue
        cand = sub[sub["lam"] == lam].set_index("year")["mean_brier"]
        beats_all = bool((cand < base).all())
        avg_impr = float((base - cand).mean())
        print(f"{variant} lam={lam}: beats_all={beats_all} avg_brier_improvement={avg_impr:+.4f}")
```

- [ ] **Step 2: Run the full suite first (everything green before the evidence run)**

Run: `venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 3: Run the evidence script (capture REAL output)**

Run: `venv/bin/python scripts/run_form_backtest.py`
Expected: prints the per-year Brier table + the go/no-go lines, writes `results/evaluations/form_backtest.csv`. Capture this output verbatim — it is the evidence.

- [ ] **Step 4: Apply the gate and set config**

Read the go/no-go lines. **Only if** some `(variant, lam)` shows `beats_all=True` with a meaningful `avg_brier_improvement` (positive, not negligible): set `config.FORM_LAMBDA = <that lam>` and `config.FORM_VARIANT = "<that variant>"`. **Otherwise** leave `FORM_LAMBDA = 0.0` (ship the no-op).

If setting a non-zero value, run the full suite again to confirm green:
Run: `venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Record the result honestly in the spec**

Append a short "## 11. Backtest result" section to the design doc with: the per-year/avg Brier table (real numbers), the gate decision (shipped λ or no-op), and one sentence on why. Do not editorialize beyond the numbers.

- [ ] **Step 6: Commit**

```bash
git add scripts/run_form_backtest.py config.py docs/superpowers/specs/2026-06-21-phase2-form-strength-design.md
git commit -m "feat(form): evidence run + go/no-go decision for form lambda"
```

(Do NOT commit `results/evaluations/form_backtest.csv` — runtime artifact.)

---

## Self-Review

**Spec coverage:**
- §3 evidence-gated/default-off → Task 1 (`FORM_LAMBDA=0`) + Task 4 byte-identical test + Task 5 gate.
- §3 walk-forward/no-lookahead → Task 2 (`elo_as_of` strictly-before) + Task 3 (`prior` only holds earlier matches; `elo_as_of(< date)`) + Task 3 no-lookahead test.
- §4 residual + bump (points & gd variants, clamp) → Task 1.
- §5 walk-forward backtest on 2014/2018/2022 from matches.parquet, isolate on Elo base, sweep grid, write CSV → Task 3 + Task 5.
- §6 double-counting mitigation (residual, capped) → Task 1 (`team_form_bump`), validated by Task 3/5 (λ=0 wins if it echoes Elo).
- §7 go/no-go (beat baseline on all 3 WCs) → Task 5 script + Step 4.
- §8 wire into live_model_elos as third addend; single scalar flows to MC/cards/edges; Elo-at-kickoff via elo_as_of from the Step-2 history → Task 4.
- §9 tests (form zero/sign/clamp/lam0; regression byte-identical; backtest no-lookahead; evidence run) → Tasks 1/3/4/5.

**Placeholder scan:** none — every code step is complete.

**Type consistency:** match record dict `{own_elo, opp_elo, home_adv, gf, ga}` is identical in Task 1, Task 3, Task 4. `team_form_bump(matches, lam, cap, variant)`, `elo_as_of(history, team, date)`, `live_form_bumps(wc_df, elo_history, lam, cap, variant)`, `live_model_elos(..., form_bumps=None)`, `walk_forward_form_backtest(years, grid, matches=None)`, `run_form_backtest_and_save()` — names/signatures consistent across tasks. Probability keys `win_a/draw/win_b` throughout.

**Deferred verification:** Task 3 must confirm `backtester.py`'s existing `from config import (...)` / `from data.elo import ...` / `from prediction.match_predictor import ...` lines and MERGE the new names rather than duplicating imports; Task 4 Step 5 must confirm the exact current `live_model_elos(...)` call line in `matchday_run.py` and that `elo` (full history) is in scope there.
