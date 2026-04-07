"""Phase A: Pre-tournament daily pipeline.

Runs daily at 08:00 UTC.
- Every day: fetch Polymarket odds, store snapshot
- Mondays only: re-run full TSFM predictions + Monte Carlo + edge detection
"""

from __future__ import annotations

import gc
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import ALL_TEAMS, RESULTS_DIR, TSFM_CONTEXT_WEEKS
from data.elo import build_elo_history, get_latest_elo, resample_weekly
from data.fetcher_matches import fetch_matches
from data.fetcher_polymarket import fetch_current_wc_odds, save_odds_snapshot
from markets.edge_detector import detect_edges, format_edge_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(RESULTS_DIR / "logs" / "daily_run.log"),
    ],
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


def step_run_models(elo: pd.DataFrame) -> dict[str, float]:
    """Step 3: Run TSFM models + Monte Carlo (Mondays only)."""
    log.info("Step 3: Running TSFM models …")

    from prediction.strength_forecaster import forecast_all_teams, get_tournament_elo_forecasts
    from prediction.tournament_simulator import run_monte_carlo

    team_elo_series = {}
    for team in ALL_TEAMS:
        try:
            weekly = resample_weekly(elo, team, n_weeks=TSFM_CONTEXT_WEEKS)
            team_elo_series[team] = weekly.values
        except ValueError:
            team_elo_series[team] = np.full(TSFM_CONTEXT_WEEKS, 1500.0)

    forecasts = forecast_all_teams(team_elo_series, horizon=20)
    tournament_elos = get_tournament_elo_forecasts(forecasts, tournament_week_index=10)

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
