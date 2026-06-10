"""Phase A: Pre-tournament daily pipeline.

Runs daily at 08:00 UTC.
- Every day: fetch Polymarket odds, store snapshot
- Mondays only: re-run full TSFM predictions + Monte Carlo + edge detection
"""

from __future__ import annotations

import gc
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    ALL_TEAMS,
    RESULTS_DIR,
    TOURNAMENT_END,
    TOURNAMENT_START,
    TSFM_CONTEXT_WEEKS,
)
from data.elo import build_elo_history, get_latest_elo, resample_weekly
from data.fetcher_matches import fetch_matches
from data.fetcher_polymarket import fetch_current_wc_odds, save_odds_snapshot
from markets.edge_detector import detect_edges, format_edge_report

# Persisted by full model runs; consumed daily for model-agreement scoring and
# by the Phase B (tournament) pipeline as the per-model Elo baseline.
MODEL_SNAPSHOT_PATH = RESULTS_DIR / "predictions" / "model_snapshot_latest.json"

# Elo target date for TSFM forecasts: start of the R16 — the heart of the
# knockout bracket, where most champion-probability mass gets decided.
TOURNAMENT_TARGET_DATE = "2026-07-04"


def tournament_week_index(today: datetime | None = None) -> int:
    """Weeks from now until the knockout heart of the tournament.

    Previously hardcoded to 10 (correct in April, increasingly stale since).
    """
    if today is None:
        today = datetime.now(timezone.utc)
    target = datetime.strptime(TOURNAMENT_TARGET_DATE, "%Y-%m-%d").replace(
        tzinfo=timezone.utc
    )
    return max(0, round((target - today).days / 7))


def load_model_snapshot() -> dict | None:
    """Load the latest per-model snapshot (tournament Elos + champion probs)."""
    if not MODEL_SNAPSHOT_PATH.exists():
        return None
    try:
        return json.loads(MODEL_SNAPSHOT_PATH.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not load model snapshot: %s", exc)
        return None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    # Stream only: cron already redirects stdout/stderr to daily_run.log.
    # A FileHandler on the same path doubled every line.
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)


def step_fetch_odds() -> pd.DataFrame | None:
    """Step 1: Fetch and store Polymarket odds."""
    log.info("Step 1: Fetching Polymarket odds …")
    df = fetch_current_wc_odds()
    if df is not None:
        save_odds_snapshot(df)
        log.info("  Fetched odds for %d teams, volume=$%s",
                 len(df), f"{df['volume'].iloc[0]:,.0f}")
    else:
        log.warning("  Failed to fetch Polymarket odds")
    return df


def step_update_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Step 2: Refresh match data and Elo."""
    log.info("Step 2: Updating match data …")
    matches = fetch_matches(force=True)
    elo = build_elo_history(matches, force=True)
    return matches, elo


def step_forecast_tournament_elos(elo: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Run TSFM models and persist the per-model tournament-Elo snapshot.

    The snapshot also records each team's *actual* Elo as of the forecast,
    so Phase B can shift forecasts by realized Elo movement during the
    tournament: elo_model_live = tsfm_elo + (actual_now - actual_at_forecast).
    """
    from prediction.strength_forecaster import forecast_all_teams, get_tournament_elo_forecasts

    team_elo_series = {}
    for team in ALL_TEAMS:
        try:
            weekly = resample_weekly(elo, team, n_weeks=TSFM_CONTEXT_WEEKS)
            team_elo_series[team] = weekly.values
        except ValueError:
            team_elo_series[team] = np.full(TSFM_CONTEXT_WEEKS, 1500.0)

    week_idx = tournament_week_index()
    log.info("  TSFM forecast target: week index %d (~%s)", week_idx, TOURNAMENT_TARGET_DATE)
    forecasts = forecast_all_teams(team_elo_series, horizon=20)
    tournament_elos = get_tournament_elo_forecasts(forecasts, tournament_week_index=week_idx)

    actual_elo = get_latest_elo(elo)
    snapshot = {
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "tournament_week_index": week_idx,
        "actual_elo": {t: actual_elo.get(t, 1500.0) for t in ALL_TEAMS},
        "model_tournament_elo": tournament_elos,
        "model_champion_probs": {},  # filled in by the sim step
    }
    MODEL_SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=1))
    return tournament_elos


def step_run_models(elo: pd.DataFrame) -> tuple[dict[str, float], dict]:
    """Step 3: Run TSFM models + Monte Carlo (Mondays only)."""
    log.info("Step 3: Running TSFM models …")

    from prediction.tournament_simulator import run_monte_carlo

    tournament_elos = step_forecast_tournament_elos(elo)

    # Monte Carlo for each model
    model_sim_results = {}
    for model_name, team_elos in tournament_elos.items():
        log.info("  Monte Carlo: %s", model_name)
        sim_df = run_monte_carlo(team_elos, n_simulations=50_000, seed=42)
        model_sim_results[model_name] = sim_df

    # Ensemble
    tsfm_models = list(model_sim_results.keys())
    ensemble_probs = {}
    for team in ALL_TEAMS:
        probs = []
        for mn in tsfm_models:
            df = model_sim_results[mn]
            row = df[df["team"] == team]
            if not row.empty:
                probs.append(row["P(champion)"].values[0])
        ensemble_probs[team] = float(np.mean(probs)) if probs else 0.0

    # Record per-model champion probs in the snapshot (for daily agreement)
    snapshot = load_model_snapshot()
    if snapshot is not None:
        snapshot["model_champion_probs"] = {
            mn: dict(zip(df["team"], df["P(champion)"].astype(float)))
            for mn, df in model_sim_results.items()
        }
        MODEL_SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=1))

    # Save predictions
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pred_rows = [{"team": t, "ai_prob": p} for t, p in ensemble_probs.items()]
    pd.DataFrame(pred_rows).to_csv(
        RESULTS_DIR / "predictions" / f"predictions_{date_str}.csv", index=False
    )

    return ensemble_probs, model_sim_results


def step_detect_edges(
    ensemble_probs: dict[str, float],
    market_probs: dict[str, float],
    model_sim_results: dict | None = None,
) -> None:
    """Step 4: Compare AI vs market, detect edges."""
    log.info("Step 4: Detecting edges …")

    model_probs_dict = {}
    if model_sim_results:
        for mn, df in model_sim_results.items():
            model_probs_dict[mn] = dict(zip(df["team"], df["P(champion)"]))
    else:
        # Non-Monday: reuse the latest persisted per-model probs so
        # models_agree / STRONG EDGE still work between full model runs.
        snapshot = load_model_snapshot()
        if snapshot and snapshot.get("model_champion_probs"):
            model_probs_dict = snapshot["model_champion_probs"]
            log.info("  Using per-model probs from snapshot of %s", snapshot["as_of"])

    edges = detect_edges(ensemble_probs, market_probs, model_probs_dict, min_edge_pct=2.0)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    edges.to_csv(RESULTS_DIR / "edges" / f"edges_{date_str}.csv", index=False)

    report = format_edge_report(edges)
    log.info("Edge report:\n%s", report)

    strong = edges[edges["strength"] == "STRONG EDGE"]
    if not strong.empty:
        log.info("STRONG EDGES found:")
        for _, row in strong.iterrows():
            log.info("  %s: AI=%.1f%% vs PM=%.1f%% -> %s (%+.1f%%)",
                     row["team"], row["ai_prob"]*100, row["market_prob"]*100,
                     row["direction"], row["edge_pct"])


def main():
    today = datetime.now(timezone.utc)
    is_monday = today.weekday() == 0
    log.info("Daily run starting — %s (Monday=%s)", today.strftime("%Y-%m-%d"), is_monday)

    # During the tournament, Phase B (matchday_run) owns predictions/edges —
    # conditioned on real results. Phase A only archives the odds snapshot.
    date_str = today.strftime("%Y-%m-%d")
    if TOURNAMENT_START <= date_str <= TOURNAMENT_END:
        log.info("Tournament active — Phase B owns outputs; snapshotting odds only.")
        step_fetch_odds()
        return

    # Always: fetch odds
    pm_df = step_fetch_odds()
    market_probs = {}
    if pm_df is not None:
        market_probs = dict(zip(pm_df["team"], pm_df["implied_prob"]))

    if is_monday:
        # Monday: full model re-run
        matches, elo = step_update_data()
        ensemble_probs, model_sim_results = step_run_models(elo)
        step_detect_edges(ensemble_probs, market_probs, model_sim_results)
    else:
        # Other days: just log odds + compare with latest predictions
        latest_pred = RESULTS_DIR / "predictions"
        pred_files = sorted(latest_pred.glob("predictions_*.csv"))
        if pred_files:
            latest = pd.read_csv(pred_files[-1])
            ensemble_probs = dict(zip(latest["team"], latest["ai_prob"]))
            step_detect_edges(ensemble_probs, market_probs)
        else:
            log.info("No existing predictions found. Run on Monday or with --force.")

    log.info("Daily run complete.")


if __name__ == "__main__":
    # Allow --force flag to run full model even on non-Monday
    if "--force" in sys.argv:
        matches = fetch_matches(force=True)
        elo = build_elo_history(matches, force=True)
        pm_df = step_fetch_odds()
        market_probs = dict(zip(pm_df["team"], pm_df["implied_prob"])) if pm_df is not None else {}
        ensemble_probs, model_sim_results = step_run_models(elo)
        step_detect_edges(ensemble_probs, market_probs, model_sim_results)
    else:
        main()
