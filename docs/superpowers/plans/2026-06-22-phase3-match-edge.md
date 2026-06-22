# Phase 3: Per-Match Edge + Scoreboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface a per-match AI-vs-Polymarket W/D/L edge on each match card, and add a truthful per-match scoreboard (AI Brier vs PM Brier) scored after matches resolve — reusing the existing `detect_edges`/`normalize_probs`, with data-authenticity invariants enforced and tested.

**Architecture:** A pure `markets/match_edge.py` de-vigs a raw market 3-way and runs `detect_edges`. `predict_upcoming_matches` captures the de-vig market alongside the locked AI prob (same pre-kickoff moment). `score_match_edges` scores AI vs PM by 3-way Brier after completion. The dashboard attaches the edge to upcoming cards and surfaces the scoreboard; the frontend renders a BUY/SELL badge with live recompute.

**Tech Stack:** Python 3.11+, numpy, pandas, pytest. Frontend: Next.js 16 static export under `web/`. Reuses `markets/edge_detector.py`, `markets/odds_converter.normalize_probs`, `data/fetcher_polymarket.fetch_match_moneylines`.

## Global Constraints

- **Truthfulness invariants (spec §6), enforced & tested:** I1 same-moment pre-kickoff capture; I2 locked AI + `mkt_*` immutable (first-prediction-wins); I3 out-of-sample scoreboard; I4 de-vig (`normalize_probs`) both sides; I5 **no profitability/P&L/ROI language** anywhere (UI/logs) — Brier + hit-rate only; I6 **never fabricate market data** — missing market ⇒ `mkt_*`=NaN and `score_match_edges`/`match_edge` SKIP it (no imputation/default/padding); I7 honest coverage — `n_scored` counts only completed matches with a real captured market; I8 evidence not assertion (Task 7 real run).
- **De-vig units:** `row["market"]`/moneyline `home/draw/away` are **raw Yes prices** (implied probs summing to >1). De-vig via `normalize_probs({"home":..,"draw":..,"away":..})` before any differencing.
- **Per-match edge floor = `min_edge_pct=2.0`** (matches the champion Step-7 call and the frontend `liveEdge`).
- **Calibration consistency:** the dashboard's per-match `pred` is currently built WITHOUT `calib` (uncalibrated). Phase 3 passes the loaded calibration so the displayed card AND the edge use our real calibrated probs.
- **Frontend:** no emoji, no CSS gradients (solid zinc palette); user-facing text in Chinese; rebuild `web/out` after `web/` changes (`cd web && npm run build`).
- **No new dependencies.** Commits must NOT contain a `Co-Authored-By` trailer. All existing tests stay green; output pristine. Use `venv/bin/python -m pytest`.

**Verified signatures:** `detect_edges(ai_probs, market_probs, model_probs=None, min_edge_pct=MIN_EDGE_PCT, strong_edge_pct=STRONG_EDGE_PCT, min_models_agree=STRONG_EDGE_MIN_MODELS) -> DataFrame[team,ai_prob,market_prob,edge,edge_pct,direction,half_kelly,models_agree,strength]` (`markets/edge_detector.py:42`). `normalize_probs(dict) -> dict` (`markets/odds_converter.py:48`). `predict_upcoming_matches(wc_df, elo_ratings, horizon_days=3, model_elos=None, calib=None)` — row dict ends `...pred_score, pred_score_p` (`live_scoring.py:134-150`). `ensemble_match_prediction(elo_pairs, home_advantage=0.0, knockout=False, calib=None, rho=0.0, total_goals=None)` returns `p_home/p_draw/p_away` + `per_model` (each `{p_home,p_draw,p_away}`). `_build_matches` upcoming branch sets `row["market"]` (`dashboard.py:374-377`) and `row["pred"]` (`:386-389`).

---

### Task 1: Pure per-match edge helper

**Files:**
- Create: `markets/match_edge.py`
- Test: `tests/test_match_edge.py`

**Interfaces:**
- Consumes: `detect_edges` (`markets/edge_detector.py`), `normalize_probs` (`markets/odds_converter.py`), config `MIN_MARKET_VOLUME`.
- Produces: `match_edge(ai_probs: dict, market_raw: dict | None, model_probs: dict | None = None, volume: float = 0.0, min_edge_pct: float = 2.0) -> list[dict]`. Each dict: `side` ∈ {"home","draw","away"}, `edge_pct`, `direction`, `half_kelly`, `models_agree`, `strength`. Returns `[]` when `market_raw` is None/empty or `volume < MIN_MARKET_VOLUME`. ai_probs/market_raw/model_probs are keyed by "home"/"draw"/"away".

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_match_edge.py
from markets.match_edge import match_edge

AI = {"home": 0.55, "draw": 0.25, "away": 0.20}
# vigged market: sums to 1.08 (raw Yes prices)
MKT_RAW = {"home": 0.45, "draw": 0.28, "away": 0.35}
MODELS = {"m0": {"home": 0.57, "draw": 0.24, "away": 0.19},
          "m1": {"home": 0.54, "draw": 0.25, "away": 0.21},
          "m2": {"home": 0.56, "draw": 0.25, "away": 0.19}}

def test_no_market_returns_empty():
    assert match_edge(AI, None, MODELS, volume=1e6) == []
    assert match_edge(AI, {}, MODELS, volume=1e6) == []

def test_low_volume_returns_empty():
    assert match_edge(AI, MKT_RAW, MODELS, volume=1000) == []  # < MIN_MARKET_VOLUME

def test_devig_before_differencing():
    # de-vigged home = 0.45/1.08 = 0.4167; AI home 0.55 -> edge ~+13.3pp BUY home.
    # If the raw 0.45 were used (no de-vig), edge would be only +10pp.
    out = match_edge(AI, MKT_RAW, MODELS, volume=1e6)
    home = next(e for e in out if e["side"] == "home")
    assert home["direction"] == "BUY"
    assert home["edge_pct"] > 12.0  # de-vigged, not the raw +10pp

def test_models_agree_counted():
    out = match_edge(AI, MKT_RAW, MODELS, volume=1e6)
    home = next(e for e in out if e["side"] == "home")
    assert home["models_agree"] == 3  # all 3 models above the de-vig market on home

def test_sides_keyed_home_draw_away():
    out = match_edge(AI, MKT_RAW, MODELS, volume=1e6)
    assert all(e["side"] in {"home", "draw", "away"} for e in out)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_match_edge.py -q`
Expected: FAIL (`No module named 'markets.match_edge'`).

- [ ] **Step 3: Implement `markets/match_edge.py`**

```python
# markets/match_edge.py
"""Per-match (W/D/L) edge: de-vig the Polymarket 3-way, then reuse detect_edges.

market_raw holds raw Yes prices (implied probs summing to >1 with vig); it is
de-vigged with normalize_probs before differencing so edges don't inherit the
vig. Returns [] when no market or the book is below the liquidity floor — it
never fabricates a market.
"""

from __future__ import annotations

from config import MIN_MARKET_VOLUME
from markets.edge_detector import detect_edges
from markets.odds_converter import normalize_probs


def match_edge(ai_probs, market_raw, model_probs=None, volume=0.0, min_edge_pct=2.0):
    if not market_raw or volume < MIN_MARKET_VOLUME:
        return []
    market_devig = normalize_probs({
        "home": market_raw["home"], "draw": market_raw["draw"], "away": market_raw["away"],
    })
    edges = detect_edges(ai_probs, market_devig, model_probs, min_edge_pct=min_edge_pct)
    return [
        {
            "side": row["team"],
            "edge_pct": row["edge_pct"],
            "direction": row["direction"],
            "half_kelly": row["half_kelly"],
            "models_agree": int(row["models_agree"]),
            "strength": row["strength"],
        }
        for _, row in edges.iterrows()
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_match_edge.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add markets/match_edge.py tests/test_match_edge.py
git commit -m "feat(edge): pure per-match edge helper (de-vig + detect_edges + volume gate)"
```

---

### Task 2: Capture de-vig market at lock time

**Files:**
- Modify: `data/fetcher_polymarket.py` (add `find_moneyline`)
- Modify: `evaluation/live_scoring.py` (`predict_upcoming_matches` gains `moneylines`; store `mkt_*`)
- Test: `tests/test_live_tournament.py`

**Interfaces:**
- Consumes: `normalize_probs`.
- Produces:
  - `find_moneyline(moneylines: dict, kickoff: str, home: str, away: str) -> dict | None` in `data/fetcher_polymarket.py` — the fixture's raw moneyline `{slug, home, draw, away, volume}` oriented to (home, away), or None. Matches by kickoff epoch + team set (mirrors `dashboard._match_market`).
  - `predict_upcoming_matches(wc_df, elo_ratings, horizon_days=3, model_elos=None, calib=None, moneylines=None)` — locked rows gain `mkt_home/mkt_draw/mkt_away` (de-vigged) or NaN when no market.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_live_tournament.py
import math
import pandas as pd
from datetime import datetime, timedelta, timezone
from data.fetcher_polymarket import find_moneyline
from evaluation import live_scoring

def _ml(kickoff, h, a):
    return {kickoff: {"slug": "x", "home_name": h, "away_name": a,
                      "home_price": 0.45, "draw_price": 0.28, "away_price": 0.35,
                      "volume": 5_000_000}}

def test_find_moneyline_orients_to_fixture():
    ko = "2026-06-25T18:00:00+00:00"
    ml = _ml(ko, "Spain", "Croatia")
    got = find_moneyline(ml, ko, "Spain", "Croatia")
    assert got and got["home"] == 0.45 and got["away"] == 0.35
    # PM order reversed -> prices swap to our fixture orientation
    rev = find_moneyline(_ml(ko, "Croatia", "Spain"), ko, "Spain", "Croatia")
    assert rev and rev["home"] == 0.35 and rev["away"] == 0.45

def test_find_moneyline_missing_returns_none():
    assert find_moneyline({}, "2026-06-25T18:00:00+00:00", "A", "B") is None

def test_lock_stores_devig_market(tmp_path, monkeypatch):
    monkeypatch.setattr(live_scoring, "MATCH_PREDS_CSV", tmp_path / "mp.csv")
    now = datetime.now(timezone.utc)
    ko = (now + timedelta(days=1)).replace(microsecond=0).isoformat()
    wc = pd.DataFrame([{"kickoff_utc": ko, "stage": "group", "completed": False,
                        "home_team": "Spain", "away_team": "Croatia",
                        "date": now.date().isoformat()}])
    elos = {"Spain": 1900, "Croatia": 1650}
    ml = _ml(ko, "Spain", "Croatia")
    live_scoring.predict_upcoming_matches(wc, elos, model_elos={"M": elos}, moneylines=ml)
    row = pd.read_csv(tmp_path / "mp.csv").iloc[0]
    # de-vig: 0.45/(0.45+0.28+0.35)=0.4167
    assert abs(row["mkt_home"] - 0.45 / 1.08) < 1e-3
    assert abs(row["mkt_home"] + row["mkt_draw"] + row["mkt_away"] - 1.0) < 1e-6

def test_lock_no_market_stores_nan(tmp_path, monkeypatch):
    monkeypatch.setattr(live_scoring, "MATCH_PREDS_CSV", tmp_path / "mp.csv")
    now = datetime.now(timezone.utc)
    ko = (now + timedelta(days=1)).replace(microsecond=0).isoformat()
    wc = pd.DataFrame([{"kickoff_utc": ko, "stage": "group", "completed": False,
                        "home_team": "Spain", "away_team": "Croatia",
                        "date": now.date().isoformat()}])
    live_scoring.predict_upcoming_matches(wc, {"Spain": 1900, "Croatia": 1650},
                                          model_elos={"M": {"Spain": 1900, "Croatia": 1650}},
                                          moneylines=None)
    row = pd.read_csv(tmp_path / "mp.csv").iloc[0]
    assert math.isnan(row["mkt_home"])  # never fabricated (I6)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_live_tournament.py -q`
Expected: FAIL (`cannot import name 'find_moneyline'` / unexpected `moneylines` kwarg).

- [ ] **Step 3: Implement `find_moneyline` in `data/fetcher_polymarket.py`**

```python
def find_moneyline(moneylines, kickoff, home, away):
    """Raw moneyline for a fixture, oriented to (home, away). None if absent.

    moneylines: {kickoff_iso: {slug, home_name, away_name, home_price,
                 draw_price, away_price, volume}} from fetch_match_moneylines.
    """
    import pandas as pd
    if not moneylines:
        return None
    try:
        target = pd.Timestamp(kickoff).value
    except (ValueError, TypeError):
        return None
    teams = {home, away}
    for ko, ml in moneylines.items():
        try:
            if pd.Timestamp(ko).value != target:
                continue
        except (ValueError, TypeError):
            continue
        if {ml["home_name"], ml["away_name"]} != teams:
            continue
        if ml["home_name"] == away and ml["away_name"] == home:
            hp, ap = ml["away_price"], ml["home_price"]
        else:
            hp, ap = ml["home_price"], ml["away_price"]
        return {"slug": ml["slug"], "home": round(hp, 4),
                "draw": round(ml["draw_price"], 4), "away": round(ap, 4),
                "volume": round(ml["volume"])}
    return None
```

- [ ] **Step 4: Implement the lock-time capture in `predict_upcoming_matches`**

Add `moneylines=None` to the signature. Add `from data.fetcher_polymarket import find_moneyline` and `from markets.odds_converter import normalize_probs` (confirm `normalize_probs` import exists; it is already imported in `live_scoring.py`). Inside the loop, after `home, away = ...`, compute the de-vig market:

```python
        mkt_h = mkt_d = mkt_a = float("nan")
        ml = find_moneyline(moneylines, r["kickoff_utc"], home, away)
        if ml:
            dv = normalize_probs({"home": ml["home"], "draw": ml["draw"], "away": ml["away"]})
            mkt_h, mkt_d, mkt_a = dv["home"], dv["draw"], dv["away"]
```

Add to the row dict (after `pred_score_p`):

```python
            "mkt_home": round(mkt_h, 4) if mkt_h == mkt_h else float("nan"),
            "mkt_draw": round(mkt_d, 4) if mkt_d == mkt_d else float("nan"),
            "mkt_away": round(mkt_a, 4) if mkt_a == mkt_a else float("nan"),
```

(`x == x` is False only for NaN — preserves NaN without rounding it to a number.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_live_tournament.py tests/test_match_edge.py -q`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `venv/bin/python -m pytest -q`
Expected: PASS (existing locked-prediction tests still green; new columns are additive).

- [ ] **Step 7: Commit**

```bash
git add data/fetcher_polymarket.py evaluation/live_scoring.py tests/test_live_tournament.py
git commit -m "feat(edge): capture de-vig market at lock time (find_moneyline + mkt_* columns)"
```

---

### Task 3: `score_match_edges` scorer

**Files:**
- Modify: `evaluation/live_scoring.py` (add `score_match_edges`)
- Test: `tests/test_live_tournament.py`

**Interfaces:**
- Consumes: the `mkt_*` + `p_*` columns of `match_predictions.csv` (Task 2), completed results in `wc_df`.
- Produces: `score_match_edges(wc_df) -> dict | None` — `{ai_brier, pm_brier, n_scored, edge_hit_rate, n_no_market}` and writes `results/evaluations/match_edge_scoreboard.csv`. Skips rows with NaN `mkt_*` (I6); `n_scored` counts only real captured markets (I7).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_live_tournament.py
from evaluation.live_scoring import score_match_edges, MATCH_PREDS_CSV, MATCH_EDGE_SCOREBOARD_CSV

def _seed_preds(path, rows):
    pd.DataFrame(rows).to_csv(path, index=False)

def test_score_match_edges_ai_vs_pm_brier(tmp_path, monkeypatch):
    monkeypatch.setattr(live_scoring, "MATCH_PREDS_CSV", tmp_path / "mp.csv")
    monkeypatch.setattr(live_scoring, "MATCH_EDGE_SCOREBOARD_CSV", tmp_path / "sb.csv")
    ko = "2026-06-25T18:00:00+00:00"
    _seed_preds(tmp_path / "mp.csv", [{
        "kickoff_utc": ko, "stage": "group", "home_team": "Spain", "away_team": "Croatia",
        "p_home": 0.6, "p_draw": 0.25, "p_away": 0.15,
        "mkt_home": 0.5, "mkt_draw": 0.27, "mkt_away": 0.23,
    }])
    wc = pd.DataFrame([{"kickoff_utc": ko, "home_team": "Spain", "away_team": "Croatia",
                        "home_score": 2, "away_score": 0, "completed": True}])
    out = score_match_edges(wc)
    assert out["n_scored"] == 1
    # home won -> AI (0.6 on home) has lower Brier than PM (0.5 on home)
    assert out["ai_brier"] < out["pm_brier"]

def test_score_match_edges_skips_nan_market(tmp_path, monkeypatch):
    monkeypatch.setattr(live_scoring, "MATCH_PREDS_CSV", tmp_path / "mp.csv")
    monkeypatch.setattr(live_scoring, "MATCH_EDGE_SCOREBOARD_CSV", tmp_path / "sb.csv")
    ko = "2026-06-25T18:00:00+00:00"
    _seed_preds(tmp_path / "mp.csv", [{
        "kickoff_utc": ko, "stage": "group", "home_team": "A", "away_team": "B",
        "p_home": 0.6, "p_draw": 0.25, "p_away": 0.15,
        "mkt_home": float("nan"), "mkt_draw": float("nan"), "mkt_away": float("nan"),
    }])
    wc = pd.DataFrame([{"kickoff_utc": ko, "home_team": "A", "away_team": "B",
                        "home_score": 1, "away_score": 0, "completed": True}])
    out = score_match_edges(wc)
    assert out is None or out["n_scored"] == 0   # NaN market not scored (I6/I7)
    assert (out or {}).get("n_no_market", 0) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_live_tournament.py -q`
Expected: FAIL (`cannot import name 'score_match_edges'`).

- [ ] **Step 3: Implement**

Near the other CSV path constants in `live_scoring.py` add:
`MATCH_EDGE_SCOREBOARD_CSV = RESULTS_DIR / "evaluations" / "match_edge_scoreboard.csv"`

Then add:

```python
def score_match_edges(wc_df):
    """AI-vs-PM per-match 3-way Brier on locked predictions that captured a market.

    Only completed matches whose locked row has a real (non-NaN) mkt_* are scored
    (I6/I7 — missing markets are skipped, never imputed). Returns aggregate dict.
    """
    if wc_df is None or wc_df.empty or not MATCH_PREDS_CSV.exists():
        return None
    preds = pd.read_csv(MATCH_PREDS_CSV)
    if preds.empty or "mkt_home" not in preds.columns:
        return None
    done = wc_df[wc_df["completed"]]
    if done.empty:
        return None
    merged = preds.merge(
        done[["kickoff_utc", "home_team", "away_team", "home_score", "away_score"]],
        on=["kickoff_utc", "home_team", "away_team"], how="inner",
    )
    if merged.empty:
        return None

    def _brier3(ph, pd_, pa, hs, as_):
        oh = 1.0 if hs > as_ else 0.0
        od = 1.0 if hs == as_ else 0.0
        oa = 1.0 if hs < as_ else 0.0
        return (ph - oh) ** 2 + (pd_ - od) ** 2 + (pa - oa) ** 2

    ai_sum = pm_sum = 0.0
    n = hits = flagged = n_no_market = 0
    rows = []
    for _, r in merged.iterrows():
        if pd.isna(r.get("mkt_home")):
            n_no_market += 1
            continue
        hs, as_ = int(r["home_score"]), int(r["away_score"])
        ai_b = _brier3(r["p_home"], r["p_draw"], r["p_away"], hs, as_)
        pm_b = _brier3(r["mkt_home"], r["mkt_draw"], r["mkt_away"], hs, as_)
        ai_sum += ai_b
        pm_sum += pm_b
        n += 1
        # edge hit-rate: the strongest AI>market side, did it realise?
        diffs = {"home": r["p_home"] - r["mkt_home"], "draw": r["p_draw"] - r["mkt_draw"],
                 "away": r["p_away"] - r["mkt_away"]}
        side = max(diffs, key=diffs.get)
        if diffs[side] * 100.0 >= 2.0:
            flagged += 1
            realised = (hs > as_ and side == "home") or (hs == as_ and side == "draw") \
                or (hs < as_ and side == "away")
            if realised:
                hits += 1
        rows.append({"kickoff_utc": r["kickoff_utc"], "home_team": r["home_team"],
                     "away_team": r["away_team"], "ai_brier": round(ai_b, 4),
                     "pm_brier": round(pm_b, 4)})

    if n == 0:
        return {"ai_brier": None, "pm_brier": None, "n_scored": 0,
                "edge_hit_rate": None, "n_no_market": n_no_market}
    pd.DataFrame(rows).to_csv(MATCH_EDGE_SCOREBOARD_CSV, index=False)
    out = {"ai_brier": round(ai_sum / n, 4), "pm_brier": round(pm_sum / n, 4),
           "n_scored": n, "edge_hit_rate": round(hits / flagged, 4) if flagged else None,
           "n_no_market": n_no_market}
    log.info("Match-edge scoreboard: %d scored, AI Brier %.4f vs PM %.4f (%d no-market)",
             n, out["ai_brier"], out["pm_brier"], n_no_market)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_live_tournament.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add evaluation/live_scoring.py tests/test_live_tournament.py
git commit -m "feat(edge): per-match AI-vs-PM Brier scoreboard (skips fabricated markets)"
```

---

### Task 4: Dashboard — attach edge + calibrated pred + meta.match_edge

**Files:**
- Modify: `visualization/dashboard.py` (`_build_matches` edge attach + calibrated pred; `build_dashboard` meta + moneylines param)
- Test: `tests/test_live_tournament.py` or a dashboard smoke (see Step)

**Interfaces:**
- Consumes: `match_edge` (Task 1), `score_match_edges` (Task 3) via the scoreboard, `load_calibration` (Phase 1), `find_moneyline`.
- Produces: each upcoming match gains `row["edge"]` (list from `match_edge`); `data.json` `meta.match_edge`; `build_dashboard(wc_df=None, moneylines=None)` reuses a passed-in moneylines dict.

- [ ] **Step 1: Calibrated `pred` + edge attach in `_build_matches`**

`_build_matches` must receive the loaded calibration. Add a `calib=None` param to `_build_matches` and pass `calib=calib` into the upcoming-branch `ensemble_match_prediction` call (`dashboard.py:386`):

```python
            pred = ensemble_match_prediction(elo_pairs, home_advantage=ha,
                                             knockout=is_ko, calib=calib)
```

Immediately after `row["pred"] = pred` (and after `row["market"]` is set), attach the edge for upcoming matches:

```python
        if known and not completed and "market" in row and "pred" in row:
            from markets.match_edge import match_edge
            ai_probs = {"home": row["pred"]["p_home"], "draw": row["pred"]["p_draw"],
                        "away": row["pred"]["p_away"]}
            model_probs = {f"m{i}": {"home": pm["p_home"], "draw": pm["p_draw"], "away": pm["p_away"]}
                           for i, pm in enumerate(row["pred"].get("per_model", []))}
            edges = match_edge(ai_probs, row["market"], model_probs, volume=row["market"]["volume"])
            if edges:
                row["edge"] = edges
```

- [ ] **Step 2: Load calibration + meta.match_edge + moneylines param in `build_dashboard`**

In `build_dashboard(wc_df=None)` add a `moneylines=None` param; reuse it instead of always fetching:

```python
    if moneylines is None:
        moneylines = {}
        try:
            from data.fetcher_polymarket import fetch_match_moneylines
            moneylines = fetch_match_moneylines()
        except Exception as exc:  # noqa: BLE001 — never block the build
            log.warning("  Moneyline fetch failed: %s", exc)
```

Load the calibration and pass it to `_build_matches`:

```python
    from prediction.calibration import load_calibration
    from config import CALIBRATION_PATH
    calib = load_calibration(CALIBRATION_PATH)
    # ... where _build_matches(...) is called, add calib=calib
```

Add `meta.match_edge` (from `score_match_edges`, best-effort):

```python
    match_edge_meta = None
    try:
        from evaluation.live_scoring import score_match_edges
        match_edge_meta = score_match_edges(wc_df)
    except Exception as exc:  # noqa: BLE001
        log.warning("  match-edge scoreboard failed: %s", exc)
```

and add `"match_edge": match_edge_meta,` to the `meta` dict.

- [ ] **Step 3: Test**

```python
# append to tests/test_live_tournament.py
def test_dashboard_match_edge_meta_serialises():
    # _load via build is heavy; assert the meta key exists with None when no data
    from evaluation.live_scoring import score_match_edges
    import pandas as pd
    assert score_match_edges(pd.DataFrame()) is None
```

Smoke: `venv/bin/python -c "import json; from visualization.dashboard import build_dashboard"` (import resolves).

- [ ] **Step 4: Run focused + full suite**

Run: `venv/bin/python -m pytest tests/test_live_tournament.py -q` then `venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add visualization/dashboard.py tests/test_live_tournament.py
git commit -m "feat(edge): attach per-match edge + calibrated pred + meta.match_edge to dashboard"
```

---

### Task 5: Pipeline wiring (matchday_run)

**Files:**
- Modify: `pipeline/matchday_run.py`
- Test: covered by Phase B dry-run in Task 7 (integration)

**Interfaces:**
- Consumes: `fetch_match_moneylines`, `predict_upcoming_matches(..., moneylines=)`, `build_dashboard(..., moneylines=)`, `score_match_edges`.

- [ ] **Step 1: Fetch moneylines once, thread, score**

In `matchday_run.main()`, before Step 8 (`predict_upcoming_matches`), fetch moneylines once:

```python
    moneylines = {}
    try:
        from data.fetcher_polymarket import fetch_match_moneylines
        moneylines = fetch_match_moneylines()
    except Exception as exc:  # noqa: BLE001
        log.warning("  Moneyline fetch failed: %s", exc)
```

Change the Step 8 call to pass moneylines:

```python
    predict_upcoming_matches(wc_df, current_elo, model_elos=model_elos, calib=calib,
                             moneylines=moneylines)
    score_completed_matches(wc_df)
    update_scoreboard(wc_df)
    score_match_edges(wc_df)
```

(Import `score_match_edges` alongside the other `evaluation.live_scoring` imports.)

Change the Step 9 `build_dashboard(wc_df=wc_df)` call to `build_dashboard(wc_df=wc_df, moneylines=moneylines)` (reuse the fetched dict).

- [ ] **Step 2: Smoke that imports + main wiring resolve**

Run: `venv/bin/python -c "import pipeline.matchday_run as m; print('ok')"`
Expected: `ok` (no import error).

- [ ] **Step 3: Run the full suite**

Run: `venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add pipeline/matchday_run.py
git commit -m "feat(edge): wire moneyline prefetch + capture-at-lock + match-edge scoreboard into pipeline"
```

---

### Task 6: Frontend — edge badge + live recompute + scoreboard line

**Files:**
- Modify: `web/lib/types.ts` (add `MatchEdge`, `Match.edge`, `Meta.match_edge`)
- Modify: `web/lib/wc.ts` (add `matchEdge` live recompute)
- Modify: `web/components/MatchCards.tsx` (badge in `MarketOdds`)
- Modify: `web/components/Views.tsx` (scoreboard line in the AI-战绩 tab)

**Interfaces:**
- Consumes: `data.json` `match.edge` + `meta.match_edge`; live per-match prices from `usePolymarket`.

- [ ] **Step 1: Types**

In `web/lib/types.ts` add:

```ts
export interface MatchEdge {
  side: "home" | "draw" | "away";
  edge_pct: number;
  direction: "BUY" | "SELL";
  half_kelly: number;
  models_agree: number;
  strength: string;
}
```

Add `edge?: MatchEdge[];` to `Match`, and `match_edge?: { ai_brier: number | null; pm_brier: number | null; n_scored: number; edge_hit_rate: number | null } | null;` to `Meta`.

- [ ] **Step 2: Badge + scoreboard line (Chinese, no emoji/gradient, zinc palette)**

In `web/components/MatchCards.tsx` `MarketOdds`, render the strongest flagged side (highest `|edge_pct|`) as a pill near the odds — mirror the champion badge in `Views.tsx:291-303`:

```tsx
{match.edge && match.edge.length > 0 && (() => {
  const top = [...match.edge].sort((a, b) => Math.abs(b.edge_pct) - Math.abs(a.edge_pct))[0];
  const label = top.side === "home" ? "主" : top.side === "draw" ? "平" : "客";
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded ${top.direction === "BUY" ? "bg-emerald-900 text-emerald-300" : "bg-zinc-700 text-zinc-300"}`}>
      {top.direction === "BUY" ? "买" : "卖"}{label} {top.edge_pct > 0 ? "+" : ""}{top.edge_pct.toFixed(1)}%
      {top.strength === "STRONG EDGE" && " ★"}
    </span>
  );
})()}
```

Match the exact zinc/emerald classes the champion badge uses. In `web/components/Views.tsx` AI-战绩 tab, add one muted line when `meta.match_edge && meta.match_edge.n_scored > 0`:

```tsx
{meta.match_edge && meta.match_edge.n_scored > 0 && (
  <p className="text-xs text-zinc-400">
    单场 edge:AI Brier {meta.match_edge.ai_brier?.toFixed(3)} vs PM {meta.match_edge.pm_brier?.toFixed(3)}
    （{meta.match_edge.n_scored} 场{meta.match_edge.edge_hit_rate != null ? `,命中率 ${(meta.match_edge.edge_hit_rate * 100).toFixed(0)}%` : ""}）
  </p>
)}
```

- [ ] **Step 3: (Optional within this task) live recompute**

Add `matchEdge(aiProbs, marketRawLive, perModel)` to `web/lib/wc.ts` mirroring `liveEdge` (de-vig the live raw price via dividing by sum, diff vs aiProbs, ≥2pp flag, STRONG ≥5pp + ≥3 models). Wire it in `MarketOdds` so the badge updates when `usePolymarket` delivers fresh prices; fall back to `match.edge` (snapshot) when no live price. Keep it null-safe (render nothing when neither exists).

- [ ] **Step 4: Build the static export**

Run: `cd web && npm run build && cd ..`
Expected: TypeScript clean, build succeeds, `web/out` regenerated.

- [ ] **Step 5: Commit**

```bash
git add web/
git commit -m "feat(edge): per-match edge badge + live recompute + scoreboard line"
```

---

### Task 7: Evidence run + full verification

**Files:**
- Run only (no new source unless a smoke fails).

- [ ] **Step 1: Full suite**

Run: `venv/bin/python -m pytest -q`
Expected: PASS — all existing + new edge/scoreboard tests green.

- [ ] **Step 2: Evidence — real per-match scoreboard (I8)**

Run:
```bash
venv/bin/python -c "
from data.fetcher_wc_results import fetch_wc_results
from evaluation.live_scoring import score_match_edges
wc = fetch_wc_results(force=True)
print(score_match_edges(wc))
"
```
Expected: prints the real `{ai_brier, pm_brier, n_scored, edge_hit_rate, n_no_market}` (or None if no locked rows yet have a captured market — the existing `match_predictions.csv` predates the `mkt_*` columns, so `n_scored` may be 0 until new locks accrue; report honestly whichever it is). Capture verbatim — this is the I8 evidence.

- [ ] **Step 3: Dashboard build smoke (no deploy)**

Run:
```bash
venv/bin/python -c "
from visualization.dashboard import build_dashboard
d = build_dashboard()
print('meta.match_edge:', d['meta'].get('match_edge'))
n_edge = sum(1 for m in d['matches'] if m.get('edge'))
print('matches with edge:', n_edge)
"
```
Expected: builds without error; prints `meta.match_edge` and a count of upcoming matches carrying an edge. Report the real numbers.

- [ ] **Step 4: Commit (only if a smoke required a fix)**

If Steps 2-3 surfaced a fix, commit it; otherwise nothing to commit here.

---

## Self-Review

**Spec coverage:**
- §4a backend edge (de-vig + detect_edges + volume gate) → Task 1 + Task 4 attach.
- §4b frontend badge + live recompute → Task 6.
- §5a capture market-at-lock → Task 2; §5b `score_match_edges` → Task 3; §5c meta + scoreboard line → Task 4 + Task 6.
- §5d live-vs-locked distinction → surfaced edge uses fresh calibrated `pred` (Task 4); scoreboard uses locked `p_*` + `mkt_*` (Task 3). Distinct objects, never cross-read.
- §6 I1 (same-moment capture) → Task 2; I2 (immutability) → existing `seen` dedup + Task 2 columns are additive (re-run skips locked rows); I3 (out-of-sample) → Task 3 scores completed only; I4 (de-vig both) → Task 1 + Task 2 both `normalize_probs`; I5 (no P&L language) → no profit/ROI strings anywhere (verify in Task 6 copy + Task 3 log); I6 (no fabrication) → Task 2 NaN + Task 3 skip; I7 (honest coverage) → Task 3 `n_scored`/`n_no_market`; I8 (evidence) → Task 7.
- §7 calibration-consistency (dashboard pred uncalibrated → pass calib) → Task 4.

**Placeholder scan:** none — every code step is complete.

**Type consistency:** `match_edge(ai_probs, market_raw, model_probs, volume, min_edge_pct)` → list of `{side,edge_pct,direction,half_kelly,models_agree,strength}`; `find_moneyline(moneylines, kickoff, home, away)` → `{slug,home,draw,away,volume}|None`; `mkt_home/mkt_draw/mkt_away` columns; `score_match_edges(wc_df)` → `{ai_brier,pm_brier,n_scored,edge_hit_rate,n_no_market}`; `MatchEdge` TS mirrors the Python dict. Consistent across tasks. Sides keyed `home/draw/away` everywhere.

**Deferred verification:** Task 4 must confirm the exact `_build_matches(...)` call site in `build_dashboard` to thread `calib`, and that `per_model` entries carry `p_home/p_draw/p_away` keys (they do — `ensemble_match_prediction` builds `per_model` with those keys); Task 2 must confirm `normalize_probs` is already imported in `live_scoring.py` (it is) and place the `find_moneyline` import without a circular dependency (`data.fetcher_polymarket` does not import `live_scoring`).
