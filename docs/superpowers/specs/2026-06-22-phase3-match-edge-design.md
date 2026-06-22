# Phase 3: Per-Match Edge Detection + Scoreboard — Design

**Date:** 2026-06-22
**Status:** Approved design, pending spec review
**Scope:** Extend AI-vs-Polymarket edge detection from the champion market to per-match (W/D/L) markets — surface the edge on each match card, and add a truthful per-match scoreboard tracking whether the edges actually beat the market after matches resolve.

---

## 1. Problem & Goal

The project's core purpose is finding AI-vs-Polymarket edge, but edge is only computed on the **champion** market today (`detect_edges` in `matchday_run.py:202-212`). We already fetch per-match Polymarket moneylines and produce calibrated per-match AI probabilities — they just aren't differenced. Phase 3 connects them.

**This is a feature, not a model-accuracy change** (it doesn't alter predictions, so there is nothing to backtest for "does it improve accuracy"). The truthfulness concern is narrower: de-vig correctly, use pre-kickoff AI probs, capture the market at the same pre-kickoff moment, and **never claim profitability we haven't measured** — the scoreboard reports Brier + edge hit-rate, not P&L.

**Goal:** (Part 1) Surface a per-match W/D/L edge on the dashboard. (Part 2) A truthful per-match AI-vs-PM scoreboard scored after matches complete.

## 2. Non-Goals

- No simulated P&L / bankroll model (Approach C — bigger, assumption-laden; deferred).
- No change to predictions, calibration, or the champion-market edge path.
- No per-match edge on completed/past matches (edge is a pre-kickoff betting signal).

## 3. Existing Pieces (verified)

- **`detect_edges(ai_probs, market_probs, model_probs=None, min_edge_pct, strong_edge_pct, min_models_agree)`** (`markets/edge_detector.py:42`) — generic dict-keyed; works directly for a 3-way `{"home","draw","away"}`. Outputs per-key `edge, edge_pct, direction (BUY/SELL), half_kelly, models_agree, strength`. `kelly_fraction` half-Kelly floored at 0.
- **`normalize_probs(dict)`** (`markets/odds_converter.py:48`) — de-vigs a `{key: prob}` (divide by sum). Used for champions only today.
- **Per-match market** attaches as `row["market"] = {slug, home, draw, away, volume}` (`dashboard.py:323-329`), where `home/draw/away` are **raw Yes prices** (implied probs summing to >1 — vig included).
- **Per-match AI** for upcoming matches: `row["pred"]` from `ensemble_match_prediction` has calibrated `p_home/p_draw/p_away` **plus `per_model`** (per-model 3-way) — exactly what per-match `models_agree` needs (`dashboard.py:380-389`).
- **Lock path:** `predict_upcoming_matches` (`live_scoring.py:54`) stores the locked pre-match ensemble probs (calibrated) with first-prediction-wins immutability.

## 4. Part 1 — Surface the Per-Match Edge

### 4a. Backend (`visualization/dashboard.py`, `_build_matches`)
For each **upcoming** match (`known and not completed`, `dashboard.py:380`) that has **both** `row["market"]` and `row["pred"]`:
1. **De-vig** the market 3-way: `market_devig = normalize_probs({"home": m["home"], "draw": m["draw"], "away": m["away"]})`.
2. **AI probs:** `ai_probs = {"home": pred["p_home"], "draw": pred["p_draw"], "away": pred["p_away"]}` (calibrated).
3. **Per-model:** `model_probs = {f"m{i}": {"home": pm["p_home"], "draw": pm["p_draw"], "away": pm["p_away"]} for i, pm in enumerate(pred["per_model"])}`.
4. **Liquidity gate:** if `m["volume"] < MIN_MARKET_VOLUME` (`config.py:173`, currently unused), skip — per-match books can be thin; do not surface edge on illiquid markets.
5. `edges_df = detect_edges(ai_probs, market_devig, model_probs, min_edge_pct=2.0, ...)` (2.0 matches the champion Step-7 call and the frontend `liveEdge` floor).
6. Attach `row["edge"]` = a small list of the flagged sides (each: `side` ∈ home/draw/away, `edge_pct`, `direction`, `half_kelly`, `models_agree`, `strength`), or `None`/`[]` if no side clears the threshold. Keep all flagged sides; the frontend badges the strongest.

A small pure helper `match_edge(ai_probs, market_raw, model_probs) -> list[dict]` (in `markets/edge_detector.py` or a new `markets/match_edge.py`) wraps de-vig + `detect_edges` + the volume gate so it is unit-testable without the dashboard.

### 4b. Frontend (`web/`)
- `web/lib/types.ts`: add `edge?: MatchEdge[]` to `Match` (the `Edge` interface at `:116` is the champion shape; add a per-match `MatchEdge` with `side, edge_pct, direction, half_kelly, models_agree, strength`).
- `web/components/MatchCards.tsx`: in `MarketOdds` (the W/D/L odds row, `:165`), render the strongest flagged side as a **BUY/SELL pill + STRONG ★**, copying the champion badge pattern (`Views.tsx:291-303`). No emoji, no gradients, zinc palette.
- **Live recompute:** `usePolymarket` already polls per-match prices (`MarketOdds` consumes `PolyLive.matches`). Mirror the champion `liveEdge` (`web/lib/wc.ts:108`) with a per-match `matchEdge(aiProbs, marketRawLive, perModel)` that de-vigs the live price and recomputes, so the badge updates with fresh odds — consistent with the champion page.

## 5. Part 2 — Truthful Per-Match Scoreboard

**Truthfulness crux:** to honestly compare AI vs Polymarket per match, the **market probability must be captured at the same pre-kickoff moment as the locked AI prob** (both lookahead-free). So:

### 5a. Capture market-at-lock (`evaluation/live_scoring.py` + pipeline)
- `predict_upcoming_matches(..., moneylines=None)` gains the fetched moneylines. When it locks a fixture's prediction, it de-vigs that fixture's market 3-way and stores `mkt_home/mkt_draw/mkt_away` in `match_predictions.csv` alongside the locked AI probs (NaN if no market available at lock). First-prediction-wins already makes these immutable.
- **Pipeline wiring:** fetch the moneylines **once** in `matchday_run.main()` before Step 8 and pass them to both `predict_upcoming_matches` (Step 8, capture-at-lock) and `build_dashboard` (Step 9, reuse — avoid a double fetch). (`build_dashboard` currently fetches its own; thread the pre-fetched dict through.)

### 5b. Score after completion (`evaluation/live_scoring.py`)
- New `score_match_edges(wc_df) -> DataFrame`: for completed matches whose locked row has a stored `mkt_*` (not NaN), compute the 3-way Brier of the **locked calibrated AI** probs and of the **locked de-vig market** probs against the actual outcome; also record whether the **AI-favored side** (the side where AI > market by ≥ the flag threshold) realized. Aggregate: mean AI Brier, mean PM Brier, n_scored, and an **edge hit-rate** (of flagged-edge matches, the fraction where the flagged side's outcome went AI's way). Write `results/evaluations/match_edge_scoreboard.csv`.
- Called in `matchday_run` Step 8 right after `score_completed_matches`.

### 5c. Surface the scoreboard (`visualization/dashboard.py` + frontend)
- `data.json` `meta.match_edge`: `{ai_brier, pm_brier, n_scored, edge_hit_rate}`.
- AI-战绩 tab: one line next to the existing champion scoreboard — e.g. "单场 edge:AI Brier X vs PM Y(N 场),命中率 Z%". Chinese, no emoji, no gradient.

## 5d. Two intentionally-different edge objects (avoid conflation)

The **surfaced** edge (Part 1) is a *live signal*: the current `pred` (recomputed each build, calibrated) vs the **current** de-vig market — what you'd act on right now, and what the frontend recomputes live as odds move. The **scoreboard** edge (Part 2) is the *honest record*: the **locked** pre-kickoff AI prob vs the **market captured at lock time** — frozen, lookahead-free, scored after the match. They are different objects by design (live vs locked); neither replaces the other, and the scoreboard never reads the live-surfaced number.

## 6. Truthfulness Invariants — data authenticity, no hallucination (enforced & tested)

External Polymarket data plus an after-the-fact scoreboard is exactly where fabricated or inflated numbers creep in. These are **enforced, testable invariants**, not conventions — each has a named test (§8). If market data is missing or partial, the system records *less*, never invents.

- **I1 — same-moment capture, no lookahead.** The stored `mkt_*` is the de-vig market at the fixture's lock time (pre-kickoff), captured in the same `predict_upcoming_matches` call that locks the AI prob. Neither is taken post-kickoff.
- **I2 — immutability.** Locked AI probs AND `mkt_*` are written once (first-prediction-wins) and never rewritten on re-run. A test asserts re-running lock does not change them.
- **I3 — out-of-sample scoreboard.** `score_match_edges` only scores matches after they complete; the Brier comparison is honest out-of-sample.
- **I4 — consistent de-vig.** The market side is de-vigged (`normalize_probs`) for BOTH the live edge surface and the scoreboard, so edges/Brier don't inherit the vig.
- **I5 — no profitability claims.** The scoreboard reports Brier + edge hit-rate only. No P&L, no ROI, no "profit" language anywhere (UI or logs).
- **I6 — never fabricate market data.** A fixture with no Polymarket market at lock stores `mkt_*` as NaN; `score_match_edges` and `detect_edges` **skip** rows with missing/NaN market — they are never imputed, defaulted, or padded. The surfaced edge renders nothing when no live market exists (null-guarded, like the Phase-1 calibration line).
- **I7 — honest coverage.** `n_scored` counts only completed matches that have a real captured market prob; the scoreboard never pads its denominator. `n_scored` (and the count of matches with no market) is reported alongside the Brier so coverage is auditable.
- **I8 — evidence, not assertion.** Any claim about per-match scoreboard numbers is backed by the actual `score_match_edges` output on real data, shown — never asserted (verification-before-completion).

## 7. Components & Data Flow

- **`markets/match_edge.py`** (new, pure): `match_edge(ai_probs, market_raw, model_probs, volume) -> list[dict]` (de-vig + volume gate + `detect_edges`); unit-tested.
- **`evaluation/live_scoring.py`:** `predict_upcoming_matches(..., moneylines=None)` stores `mkt_*`; new `score_match_edges(wc_df)`.
- **`pipeline/matchday_run.py`:** fetch moneylines once pre-Step-8; pass to `predict_upcoming_matches` + `build_dashboard`; call `score_match_edges`.
- **`visualization/dashboard.py`:** attach `row["edge"]` (via `match_edge`) for upcoming matches; add `meta.match_edge`.
- **`web/`:** `MatchEdge` type, per-match badge in `MatchCards`, `matchEdge` live recompute, scoreboard line in the AI-战绩 tab. Rebuild `web/out` (`cd web && npm run build`).
- **`config.py`:** reuse `MIN_EDGE_PCT`/`STRONG_EDGE_PCT`/`STRONG_EDGE_MIN_MODELS`/`MIN_MARKET_VOLUME`; per-match edge floor = 2.0 (matches champion + frontend).

## 8. Testing

- **`tests/test_match_edge.py`:** `match_edge` de-vigs before differencing (a vigged market that sums to 1.08 yields edges measured against the normalized prob, not raw); volume below `MIN_MARKET_VOLUME` ⇒ no edges; a clear AI>market home prob ⇒ BUY home with correct edge_pct; per-model agreement counted; no market ⇒ `[]`.
- **`tests/test_live_tournament.py`:** `predict_upcoming_matches` with `moneylines` stores `mkt_*` (de-vigged) on the locked row; with `moneylines=None` the row omits/NaNs `mkt_*` and is otherwise unchanged (regression). `score_match_edges` computes AI vs PM Brier on a synthetic completed match with a known outcome and a known stored market; matches without `mkt_*` are skipped; immutability — re-running lock does not change `mkt_*`.
- **Truthfulness invariant tests (§6):** I6 — `score_match_edges` and `match_edge` skip rows whose market is missing/NaN (no imputation); a completed match with no captured market is absent from the scoreboard, not scored against a default. I7 — `n_scored` equals the count of completed matches with a real `mkt_*`; a market-less completed match does not inflate it. I2 — re-running `predict_upcoming_matches` leaves an existing locked row's `mkt_*` byte-identical.
- **Dashboard:** `meta.match_edge` serialises; `_build_matches` attaches `row["edge"]` only on upcoming matches with market+pred, never on completed; renders nothing when no market.
- Full existing suite stays green; Phase B dry-run incl. dashboard build.

## 9. Out of Scope → Later

- **Approach C:** simulated Kelly-staked P&L settled at market odds (needs a bankroll/settlement model + assumptions).
- Per-match edge on live in-play markets.
