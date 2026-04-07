"""Generate all visualizations for the README and results."""

from __future__ import annotations

import gc
import logging
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from config import ALL_TEAMS, PLOTS_DIR, TSFM_CONTEXT_WEEKS
from data.elo import build_elo_history, get_latest_elo, resample_weekly
from data.fetcher_matches import fetch_matches
from data.fetcher_polymarket import fetch_current_wc_odds
from prediction.strength_forecaster import forecast_all_teams, get_tournament_elo_forecasts
from prediction.tournament_simulator import run_monte_carlo
from visualization.odds_comparison import plot_scatter, plot_top_edges_bar, plot_side_by_side
from visualization.team_form import plot_team_elo_forecast, plot_multi_team_form
from markets.edge_detector import detect_edges

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
log = logging.getLogger(__name__)


def main():
    # ── Load data ────────────────────────────────────────────────────────
    log.info("Loading data …")
    matches = fetch_matches()
    elo = build_elo_history(matches)
    latest_elo = get_latest_elo(elo)

    # Build Elo series
    team_elo_series = {}
    elo_weekly_series = {}
    for team in ALL_TEAMS:
        try:
            weekly = resample_weekly(elo, team, n_weeks=TSFM_CONTEXT_WEEKS)
            team_elo_series[team] = weekly.values
            elo_weekly_series[team] = weekly
        except ValueError:
            team_elo_series[team] = np.full(TSFM_CONTEXT_WEEKS, 1500.0)

    # ── Run TSFM models ─────────────────────────────────────────────────
    log.info("Running TSFM forecasts …")
    forecasts = forecast_all_teams(team_elo_series, horizon=20)
    tournament_elos = get_tournament_elo_forecasts(forecasts, tournament_week_index=10)

    # ── Monte Carlo for each model ───────────────────────────────────────
    log.info("Running Monte Carlo simulations …")
    model_sim_results = {}
    for model_name, team_elos in tournament_elos.items():
        log.info("  %s …", model_name)
        sim_df = run_monte_carlo(team_elos, n_simulations=50_000, seed=42)
        model_sim_results[model_name] = sim_df

    # Baseline
    wc_elos = {t: latest_elo.get(t, 1500) for t in ALL_TEAMS}
    log.info("  Elo Baseline …")
    baseline_df = run_monte_carlo(wc_elos, n_simulations=50_000, seed=42)
    model_sim_results["Elo Baseline"] = baseline_df

    # ── Ensemble ─────────────────────────────────────────────────────────
    tsfm_models = [n for n in model_sim_results if n != "Elo Baseline"]
    ensemble_probs = {}
    for team in ALL_TEAMS:
        probs = []
        for mn in tsfm_models:
            df = model_sim_results[mn]
            row = df[df["team"] == team]
            if not row.empty:
                probs.append(row["P(champion)"].values[0])
        ensemble_probs[team] = float(np.mean(probs)) if probs else 0.0

    # ── Fetch Polymarket odds ────────────────────────────────────────────
    log.info("Fetching Polymarket odds …")
    pm_df = fetch_current_wc_odds()
    if pm_df is not None:
        market_probs = dict(zip(pm_df["team"], pm_df["implied_prob"]))
    else:
        log.warning("Polymarket unavailable, using empty market probs")
        market_probs = {}

    # Model probs for agreement
    model_probs_dict = {}
    for mn in model_sim_results:
        df = model_sim_results[mn]
        model_probs_dict[mn] = dict(zip(df["team"], df["P(champion)"]))

    edges = detect_edges(ensemble_probs, market_probs, model_probs_dict, min_edge_pct=2.0)

    # ── Generate Plots ───────────────────────────────────────────────────
    log.info("Generating plots …")

    # 1. AI vs Polymarket scatter
    if market_probs:
        plot_scatter(ensemble_probs, market_probs)
        log.info("  Scatter plot done")

    # 2. Top edges bar chart
    if not edges.empty:
        plot_top_edges_bar(edges)
        log.info("  Edge bar chart done")

    # 3. Side-by-side comparison
    if market_probs:
        plot_side_by_side(ensemble_probs, market_probs)
        log.info("  Side-by-side chart done")

    # 4. Elo trajectory + forecast fan charts for key teams
    for team in ["Spain", "Argentina", "Ecuador", "Brazil"]:
        if team in elo_weekly_series:
            team_forecasts = {}
            for model_name, model_preds in forecasts.items():
                if team in model_preds:
                    team_forecasts[model_name] = model_preds[team]
            plot_team_elo_forecast(team, elo_weekly_series[team], team_forecasts)
            log.info("  %s Elo forecast chart done", team)

    # 5. Multi-team Elo comparison
    top_teams = ["Spain", "France", "Argentina", "England", "Brazil",
                 "Ecuador", "Portugal", "Germany"]
    plot_multi_team_form(top_teams, elo_weekly_series)
    log.info("  Multi-team Elo chart done")

    # ── Save ensemble predictions to CSV for README ──────────────────────
    ensemble_rows = []
    for team in ALL_TEAMS:
        row = {"team": team, "ai_prob": ensemble_probs.get(team, 0)}
        row["polymarket_prob"] = market_probs.get(team, 0)
        row["edge"] = row["ai_prob"] - row["polymarket_prob"]
        # Get per-stage probs from baseline (most readable)
        for mn in tsfm_models[:1]:  # Use first model for stage probs
            sim_df = model_sim_results[mn]
            r = sim_df[sim_df["team"] == team]
            if not r.empty:
                for col in sim_df.columns:
                    if col.startswith("P("):
                        row[col] = r[col].values[0]
        ensemble_rows.append(row)

    ensemble_df = pd.DataFrame(ensemble_rows).sort_values("ai_prob", ascending=False)
    ensemble_df.to_csv("results/predictions/current_predictions.csv", index=False)
    edges.to_csv("results/edges/edge_report.csv", index=False)
    log.info("Predictions and edges saved to results/")

    log.info("All plots generated in %s", PLOTS_DIR)


if __name__ == "__main__":
    main()
