"""Compare AI (TSFM ensemble) predictions against Polymarket odds.

Runs the full pipeline:
1. Load Elo data → run TSFM models → Monte Carlo simulation
2. Fetch Polymarket odds
3. Detect edges
"""

from __future__ import annotations

import gc
import logging
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from config import ALL_TEAMS, TSFM_CONTEXT_WEEKS
from data.elo import build_elo_history, get_latest_elo, resample_weekly
from data.fetcher_matches import fetch_matches
from data.fetcher_polymarket import fetch_current_wc_odds, save_odds_snapshot
from markets.edge_detector import detect_edges, format_edge_report
from prediction.strength_forecaster import forecast_all_teams, get_tournament_elo_forecasts
from prediction.tournament_simulator import run_monte_carlo

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
log = logging.getLogger(__name__)


def main():
    # ── Step 1: Load data ────────────────────────────────────────────────
    log.info("Step 1: Loading match data and Elo ratings …")
    matches = fetch_matches()
    elo = build_elo_history(matches)

    # Build team Elo series for TSFM input
    team_elo_series = {}
    for team in ALL_TEAMS:
        try:
            weekly = resample_weekly(elo, team, n_weeks=TSFM_CONTEXT_WEEKS)
            team_elo_series[team] = weekly.values
        except ValueError:
            team_elo_series[team] = np.full(TSFM_CONTEXT_WEEKS, 1500.0)

    # ── Step 2: Run TSFM models ─────────────────────────────────────────
    log.info("Step 2: Running TSFM strength forecasts for 48 teams …")
    forecasts = forecast_all_teams(team_elo_series, horizon=20)

    # Get tournament-time Elo for each model
    # Tournament starts ~10 weeks from now (June 11 from April 7)
    tournament_elos = get_tournament_elo_forecasts(forecasts, tournament_week_index=10)

    # ── Step 3: Run Monte Carlo for each model + ensemble ────────────────
    log.info("Step 3: Running Monte Carlo simulations …")
    model_sim_results = {}

    for model_name, team_elos in tournament_elos.items():
        log.info("  Monte Carlo with %s Elo forecasts …", model_name)
        sim_df = run_monte_carlo(team_elos, n_simulations=50_000, seed=42)
        model_sim_results[model_name] = sim_df

    # Also run with current (non-forecasted) Elo as baseline
    latest_elo = get_latest_elo(elo)
    wc_elos = {t: latest_elo.get(t, 1500) for t in ALL_TEAMS}
    log.info("  Monte Carlo with current Elo (baseline) …")
    baseline_df = run_monte_carlo(wc_elos, n_simulations=50_000, seed=42)
    model_sim_results["Elo Baseline"] = baseline_df

    # ── Step 4: Ensemble (equal-weight across TSFM models) ───────────────
    tsfm_models = [n for n in model_sim_results if n != "Elo Baseline"]
    ensemble_probs = {}
    for team in ALL_TEAMS:
        probs = []
        for mn in tsfm_models:
            df = model_sim_results[mn]
            row = df[df["team"] == team]
            if not row.empty:
                probs.append(row["P(champion)"].values[0])
        ensemble_probs[team] = np.mean(probs) if probs else 0.0

    # XGBoost match-level model
    log.info("  Training XGBoost match-level model …")
    from models.xgboost_sports import XGBoostSportsPredictor
    xgb_model = XGBoostSportsPredictor()
    xgb_model.train(matches, elo)

    # For XGBoost, we don't have a clean tournament sim path yet,
    # so we include it in the individual model probs for agreement scoring
    # but use the TSFM ensemble as the primary AI probability

    # ── Step 5: Fetch Polymarket odds ────────────────────────────────────
    log.info("Step 4: Fetching Polymarket odds …")
    pm_df = fetch_current_wc_odds()
    if pm_df is None:
        log.error("Could not fetch Polymarket odds. Exiting.")
        return

    save_odds_snapshot(pm_df)

    market_probs = dict(zip(pm_df["team"], pm_df["implied_prob"]))

    # ── Step 6: Detect edges ─────────────────────────────────────────────
    log.info("Step 5: Detecting edges …")

    # Individual model probs for agreement scoring
    model_probs = {}
    for mn in model_sim_results:
        df = model_sim_results[mn]
        model_probs[mn] = dict(zip(df["team"], df["P(champion)"]))

    edges = detect_edges(
        ai_probs=ensemble_probs,
        market_probs=market_probs,
        model_probs=model_probs,
        min_edge_pct=2.0,  # Lower threshold to see more edges
    )

    # ── Print Results ────────────────────────────────────────────────────
    print("\n" + "=" * 90)
    print("AI (TSFM Ensemble) vs POLYMARKET — 2026 FIFA World Cup Winner")
    print("=" * 90)

    # Full comparison table
    print(f"\n{'Team':25s} {'AI Prob':>8s} {'PM Prob':>8s} {'Edge':>8s} {'Direction':>10s}")
    print("-" * 65)

    comparison = []
    for team in ALL_TEAMS:
        ai_p = ensemble_probs.get(team, 0)
        pm_p = market_probs.get(team, 0)
        comparison.append((team, ai_p, pm_p, ai_p - pm_p))

    comparison.sort(key=lambda x: x[1], reverse=True)
    for team, ai_p, pm_p, edge in comparison[:25]:
        direction = "BUY" if edge > 0.02 else ("SELL" if edge < -0.02 else "—")
        print(f"{team:25s} {ai_p:7.1%} {pm_p:7.1%} {edge:+7.1%} {direction:>10s}")

    # Edge report
    print(f"\n{'=' * 90}")
    print("TOP EDGES (|edge| ≥ 2 percentage points)")
    print("=" * 90)
    print(format_edge_report(edges))

    # Strong edges
    strong = edges[edges["strength"] == "STRONG EDGE"]
    if not strong.empty:
        print(f"\n🔥 STRONG EDGES (|edge| ≥ 5% AND ≥3 models agree):")
        for _, row in strong.iterrows():
            print(f"  {row['team']}: AI={row['ai_prob']:.1%} vs PM={row['market_prob']:.1%} → {row['direction']} ({row['edge_pct']:+.1f}%)")

    # Save
    edges.to_csv("results/edges/edge_report.csv", index=False)
    log.info("Edge report saved to results/edges/edge_report.csv")

    # Per-model breakdown for top 10
    print(f"\n{'=' * 90}")
    print("PER-MODEL BREAKDOWN (Top 10 by ensemble)")
    print("=" * 90)
    top10 = sorted(ensemble_probs.items(), key=lambda x: x[1], reverse=True)[:10]
    header = f"{'Team':20s} {'Ensemble':>8s} {'Polymarket':>10s}"
    for mn in list(model_sim_results.keys()):
        header += f" {mn[:10]:>10s}"
    print(header)
    print("-" * len(header))
    for team, ens_p in top10:
        line = f"{team:20s} {ens_p:7.1%} {market_probs.get(team,0):9.1%}"
        for mn in model_sim_results:
            df = model_sim_results[mn]
            row = df[df["team"] == team]
            p = row["P(champion)"].values[0] if not row.empty else 0
            line += f" {p:9.1%}"
        print(line)


if __name__ == "__main__":
    main()
