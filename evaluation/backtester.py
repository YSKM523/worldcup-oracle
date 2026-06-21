"""Backtest the prediction system on past World Cups."""

from __future__ import annotations

import gc
import importlib
import logging
import math
import time
from collections import defaultdict

import numpy as np
import pandas as pd

from config import (
    ELO_INITIAL,
    FORM_CAP,
    FOUNDATION_MODELS,
    MONTE_CARLO_SIMULATIONS,
    POISSON_AVG_GOALS,
    RESULTS_DIR,
    TSFM_CONTEXT_WEEKS,
    TSFM_FORECAST_HORIZON,
)
from data.elo import compute_elo, elo_as_of, get_latest_elo, resample_weekly
from evaluation.metrics import brier_score, calibration_error, log_loss, multiclass_brier
from prediction.form import team_form_bump
from prediction.match_predictor import match_probabilities, knockout_probabilities
from prediction.score_predictor import expected_goals, score_grid, condition_grid, effective_goal_rate

log = logging.getLogger(__name__)


# ── Past World Cup Definitions ───────────────────────────────────────────────

WC_2014 = {
    "name": "2014 Brazil",
    "cutoff_date": "2014-06-12",
    "groups": {
        "A": ["Brazil", "Croatia", "Mexico", "Cameroon"],
        "B": ["Spain", "Netherlands", "Chile", "Australia"],
        "C": ["Colombia", "Greece", "Ivory Coast", "Japan"],
        "D": ["Uruguay", "Costa Rica", "England", "Italy"],
        "E": ["Switzerland", "Ecuador", "France", "Honduras"],
        "F": ["Argentina", "Bosnia and Herzegovina", "Iran", "Nigeria"],
        "G": ["Germany", "Portugal", "Ghana", "United States"],
        "H": ["Belgium", "Algeria", "Russia", "South Korea"],
    },
    "group_matches": [
        ("Brazil", "Croatia", 3, 1),
        ("Mexico", "Cameroon", 1, 0),
        ("Spain", "Netherlands", 1, 5),
        ("Chile", "Australia", 3, 1),
        ("Colombia", "Greece", 3, 0),
        ("Uruguay", "Costa Rica", 1, 3),
        ("England", "Italy", 1, 2),
        ("Ivory Coast", "Japan", 2, 1),
        ("Switzerland", "Ecuador", 2, 1),
        ("France", "Honduras", 3, 0),
        ("Argentina", "Bosnia and Herzegovina", 2, 1),
        ("Germany", "Portugal", 4, 0),
        ("Iran", "Nigeria", 0, 0),
        ("Ghana", "United States", 1, 2),
        ("Belgium", "Algeria", 2, 1),
        ("Russia", "South Korea", 1, 1),
        ("Brazil", "Mexico", 0, 0),
        ("Cameroon", "Croatia", 0, 4),
        ("Spain", "Chile", 0, 2),
        ("Australia", "Netherlands", 2, 3),
        ("Colombia", "Ivory Coast", 2, 1),
        ("Uruguay", "England", 2, 1),
        ("Japan", "Greece", 0, 0),
        ("Italy", "Costa Rica", 0, 1),
        ("Switzerland", "France", 2, 5),
        ("Honduras", "Ecuador", 1, 2),
        ("Argentina", "Iran", 1, 0),
        ("Germany", "Ghana", 2, 2),
        ("Nigeria", "Bosnia and Herzegovina", 1, 0),
        ("United States", "Portugal", 2, 2),
        ("Belgium", "Russia", 1, 0),
        ("South Korea", "Algeria", 2, 4),
        ("Cameroon", "Brazil", 1, 4),
        ("Croatia", "Mexico", 1, 3),
        ("Australia", "Spain", 0, 3),
        ("Netherlands", "Chile", 2, 0),
        ("Japan", "Colombia", 1, 4),
        ("Greece", "Ivory Coast", 2, 1),
        ("Italy", "Uruguay", 0, 1),
        ("Costa Rica", "England", 0, 0),
        ("Honduras", "Switzerland", 0, 3),
        ("Ecuador", "France", 0, 0),
        ("Nigeria", "Argentina", 2, 3),
        ("Bosnia and Herzegovina", "Iran", 3, 1),
        ("United States", "Germany", 0, 1),
        ("Portugal", "Ghana", 2, 1),
        ("South Korea", "Belgium", 0, 1),
        ("Algeria", "Russia", 1, 1),
    ],
    "knockout_matches": [
        ("Brazil", "Chile", "Brazil"),
        ("Colombia", "Uruguay", "Colombia"),
        ("Netherlands", "Mexico", "Netherlands"),
        ("Costa Rica", "Greece", "Costa Rica"),
        ("France", "Nigeria", "France"),
        ("Germany", "Algeria", "Germany"),
        ("Argentina", "Switzerland", "Argentina"),
        ("Belgium", "United States", "Belgium"),
        ("Brazil", "Colombia", "Brazil"),
        ("Netherlands", "Costa Rica", "Netherlands"),
        ("France", "Germany", "Germany"),
        ("Argentina", "Belgium", "Argentina"),
        ("Brazil", "Germany", "Germany"),
        ("Netherlands", "Argentina", "Argentina"),
        ("Germany", "Argentina", "Germany"),
    ],
    "champion": "Germany",
    "finalist": "Argentina",
    "semifinalists": ["Germany", "Argentina", "Brazil", "Netherlands"],
}

WC_2018 = {
    "name": "2018 Russia",
    "cutoff_date": "2018-06-14",
    "groups": {
        "A": ["Russia", "Saudi Arabia", "Egypt", "Uruguay"],
        "B": ["Portugal", "Spain", "Morocco", "Iran"],
        "C": ["France", "Australia", "Peru", "Denmark"],
        "D": ["Argentina", "Iceland", "Croatia", "Nigeria"],
        "E": ["Brazil", "Switzerland", "Costa Rica", "Serbia"],
        "F": ["Germany", "Mexico", "Sweden", "South Korea"],
        "G": ["Belgium", "Panama", "Tunisia", "England"],
        "H": ["Poland", "Senegal", "Colombia", "Japan"],
    },
    "group_matches": [
        ("Russia", "Saudi Arabia", 5, 0),
        ("Egypt", "Uruguay", 0, 1),
        ("Morocco", "Iran", 0, 1),
        ("Portugal", "Spain", 3, 3),
        ("France", "Australia", 2, 1),
        ("Argentina", "Iceland", 1, 1),
        ("Peru", "Denmark", 0, 1),
        ("Croatia", "Nigeria", 2, 0),
        ("Costa Rica", "Serbia", 0, 1),
        ("Germany", "Mexico", 0, 1),
        ("Brazil", "Switzerland", 1, 1),
        ("Sweden", "South Korea", 1, 0),
        ("Belgium", "Panama", 3, 0),
        ("Tunisia", "England", 1, 2),
        ("Colombia", "Japan", 1, 2),
        ("Poland", "Senegal", 1, 2),
        ("Russia", "Egypt", 3, 1),
        ("Portugal", "Morocco", 1, 0),
        ("Uruguay", "Saudi Arabia", 1, 0),
        ("Iran", "Spain", 0, 1),
        ("Denmark", "Australia", 1, 1),
        ("France", "Peru", 1, 0),
        ("Argentina", "Croatia", 0, 3),
        ("Brazil", "Costa Rica", 2, 0),
        ("Nigeria", "Iceland", 2, 0),
        ("Germany", "Sweden", 2, 1),
        ("Serbia", "Switzerland", 1, 2),
        ("Belgium", "Tunisia", 5, 2),
        ("South Korea", "Mexico", 1, 2),
        ("England", "Panama", 6, 1),
        ("Japan", "Senegal", 2, 2),
        ("Poland", "Colombia", 0, 3),
        ("Uruguay", "Russia", 3, 0),
        ("Saudi Arabia", "Egypt", 2, 1),
        ("Spain", "Morocco", 2, 2),
        ("Iran", "Portugal", 1, 1),
        ("Australia", "Peru", 0, 2),
        ("Denmark", "France", 0, 0),
        ("Nigeria", "Argentina", 1, 2),
        ("Iceland", "Croatia", 1, 2),
        ("South Korea", "Germany", 2, 0),
        ("Mexico", "Sweden", 0, 3),
        ("Serbia", "Brazil", 0, 2),
        ("Switzerland", "Costa Rica", 2, 2),
        ("Japan", "Poland", 0, 1),
        ("Senegal", "Colombia", 0, 1),
        ("England", "Belgium", 0, 1),
        ("Panama", "Tunisia", 1, 2),
    ],
    "knockout_matches": [
        ("France", "Argentina", "France"),
        ("Uruguay", "Portugal", "Uruguay"),
        ("Spain", "Russia", "Russia"),
        ("Croatia", "Denmark", "Croatia"),
        ("Brazil", "Mexico", "Brazil"),
        ("Belgium", "Japan", "Belgium"),
        ("Sweden", "Switzerland", "Sweden"),
        ("Colombia", "England", "England"),
        ("Uruguay", "France", "France"),
        ("Brazil", "Belgium", "Belgium"),
        ("Russia", "Croatia", "Croatia"),
        ("Sweden", "England", "England"),
        ("France", "Belgium", "France"),
        ("Croatia", "England", "Croatia"),
        ("France", "Croatia", "France"),
    ],
    "champion": "France",
    "finalist": "Croatia",
    "semifinalists": ["France", "Croatia", "Belgium", "England"],
}

WC_2022 = {
    "name": "2022 Qatar",
    "cutoff_date": "2022-11-20",  # Tournament start
    "groups": {
        "A": ["Qatar", "Ecuador", "Senegal", "Netherlands"],
        "B": ["England", "Iran", "United States", "Wales"],
        "C": ["Argentina", "Saudi Arabia", "Mexico", "Poland"],
        "D": ["France", "Australia", "Denmark", "Tunisia"],
        "E": ["Spain", "Costa Rica", "Germany", "Japan"],
        "F": ["Belgium", "Canada", "Morocco", "Croatia"],
        "G": ["Brazil", "Serbia", "Switzerland", "Cameroon"],
        "H": ["Portugal", "Ghana", "Uruguay", "South Korea"],
    },
    # Actual group-stage results: (home, away, h_score, a_score)
    "group_matches": [
        ("Qatar", "Ecuador", 0, 2),
        ("England", "Iran", 6, 2),
        ("Senegal", "Netherlands", 0, 2),
        ("United States", "Wales", 1, 1),
        ("Argentina", "Saudi Arabia", 1, 2),
        ("Denmark", "Tunisia", 0, 0),
        ("Mexico", "Poland", 0, 0),
        ("France", "Australia", 4, 1),
        ("Morocco", "Croatia", 0, 0),
        ("Germany", "Japan", 1, 2),
        ("Spain", "Costa Rica", 7, 0),
        ("Belgium", "Canada", 1, 0),
        ("Switzerland", "Cameroon", 1, 0),
        ("Uruguay", "South Korea", 0, 0),
        ("Portugal", "Ghana", 3, 2),
        ("Brazil", "Serbia", 2, 0),
        ("Wales", "Iran", 0, 2),
        ("Qatar", "Senegal", 1, 3),
        ("Netherlands", "Ecuador", 1, 1),
        ("England", "United States", 0, 0),
        ("Tunisia", "Australia", 0, 1),
        ("Poland", "Saudi Arabia", 2, 0),
        ("France", "Denmark", 2, 1),
        ("Argentina", "Mexico", 2, 0),
        ("Japan", "Costa Rica", 0, 1),
        ("Belgium", "Morocco", 0, 2),
        ("Croatia", "Canada", 4, 1),
        ("Spain", "Germany", 1, 1),
        ("Cameroon", "Serbia", 3, 3),
        ("South Korea", "Ghana", 2, 3),
        ("Brazil", "Switzerland", 1, 0),
        ("Portugal", "Uruguay", 2, 0),
        ("Ecuador", "Senegal", 1, 2),
        ("Netherlands", "Qatar", 2, 0),
        ("Iran", "United States", 0, 1),
        ("Wales", "England", 0, 3),
        ("Tunisia", "France", 1, 0),
        ("Australia", "Denmark", 1, 0),
        ("Poland", "Argentina", 0, 2),
        ("Saudi Arabia", "Mexico", 1, 2),
        ("Croatia", "Belgium", 0, 0),
        ("Canada", "Morocco", 1, 2),
        ("Japan", "Spain", 2, 1),
        ("Costa Rica", "Germany", 2, 4),
        ("Ghana", "Uruguay", 0, 2),
        ("South Korea", "Portugal", 2, 1),
        ("Cameroon", "Brazil", 1, 0),
        ("Serbia", "Switzerland", 2, 3),
    ],
    # Knockout results: (team_a, team_b, winner)
    "knockout_matches": [
        ("Netherlands", "United States", "Netherlands"),
        ("Argentina", "Australia", "Argentina"),
        ("France", "Poland", "France"),
        ("England", "Senegal", "England"),
        ("Japan", "Croatia", "Croatia"),
        ("Brazil", "South Korea", "Brazil"),
        ("Morocco", "Spain", "Morocco"),
        ("Portugal", "Switzerland", "Portugal"),
        ("Croatia", "Brazil", "Croatia"),
        ("Netherlands", "Argentina", "Argentina"),
        ("Morocco", "Portugal", "Morocco"),
        ("England", "France", "France"),
        ("Argentina", "Croatia", "Argentina"),
        ("France", "Morocco", "France"),
        ("Argentina", "France", "Argentina"),
    ],
    "champion": "Argentina",
    "finalist": "France",
    "semifinalists": ["Argentina", "France", "Croatia", "Morocco"],
}


def _prepare_pre_tournament_data(
    all_matches: pd.DataFrame,
    cutoff_date: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Filter matches to before cutoff and compute Elo."""
    pre = all_matches[all_matches["date"] < cutoff_date].copy()
    elo_history = compute_elo(pre)
    return pre, elo_history


def backtest_elo_baseline(
    all_matches: pd.DataFrame,
    wc: dict,
    n_simulations: int = MONTE_CARLO_SIMULATIONS,
) -> dict:
    """Backtest using Elo-only predictions (no TSFM forecasting).

    This is the baseline that the TSFM approach must beat.
    """
    log.info("Backtesting Elo baseline on %s …", wc["name"])

    pre_matches, elo_history = _prepare_pre_tournament_data(
        all_matches, wc["cutoff_date"]
    )
    latest_elo = get_latest_elo(elo_history)

    # Get Elo for all teams in this WC
    teams = set()
    for g in wc["groups"].values():
        teams.update(g)

    team_elos = {t: latest_elo.get(t, ELO_INITIAL) for t in teams}

    # ── Evaluate Group Stage Match Predictions ───────────────────────────
    match_briers = []
    match_log_losses = []
    correct_predictions = 0
    total_matches = 0

    for home, away, h_score, a_score in wc["group_matches"]:
        elo_h = team_elos.get(home, ELO_INITIAL)
        elo_a = team_elos.get(away, ELO_INITIAL)

        # All WC 2022 matches were on neutral ground (Qatar)
        probs = match_probabilities(elo_h, elo_a, home_advantage=0)
        pred_probs = np.array([probs["win_a"], probs["draw"], probs["win_b"]])

        # Actual outcome
        if h_score > a_score:
            outcome_idx = 0
        elif h_score == a_score:
            outcome_idx = 1
        else:
            outcome_idx = 2

        match_briers.append(multiclass_brier(pred_probs, outcome_idx))

        # Did highest-prob prediction match?
        if np.argmax(pred_probs) == outcome_idx:
            correct_predictions += 1
        total_matches += 1

    # ── Evaluate Knockout Match Predictions ──────────────────────────────
    knockout_correct = 0
    knockout_total = 0

    for team_a, team_b, winner in wc["knockout_matches"]:
        elo_a = team_elos.get(team_a, ELO_INITIAL)
        elo_b = team_elos.get(team_b, ELO_INITIAL)

        probs = knockout_probabilities(elo_a, elo_b, home_advantage=0)

        if probs["win_a"] > probs["win_b"]:
            predicted_winner = team_a
        else:
            predicted_winner = team_b

        if predicted_winner == winner:
            knockout_correct += 1
        knockout_total += 1

    # ── Tournament Simulation ────────────────────────────────────────────
    from prediction.tournament_simulator import simulate_tournament, STAGES

    rng = np.random.default_rng(42)
    counters = defaultdict(lambda: {s: 0 for s in STAGES})
    stage_rank = {s: i for i, s in enumerate(
        ["group_eliminated", "group_advance", "r32", "r16", "qf", "sf", "final", "champion"]
    )}

    for _ in range(n_simulations):
        result = simulate_tournament(team_elos, rng, groups=wc["groups"])
        for team, stage in result.items():
            team_rank = stage_rank.get(stage, 0)
            for s in STAGES:
                if team_rank >= stage_rank.get(s, 0):
                    counters[team][s] += 1

    # Convert to probabilities
    sim_probs = {}
    for team in counters:
        sim_probs[team] = {
            s: counters[team][s] / n_simulations for s in STAGES
        }

    # ── Compute Tournament-Level Brier Score ─────────────────────────────
    # For each team: predicted P(champion) vs actual (1 for winner, 0 for others)
    champion_probs = []
    champion_outcomes = []
    for team in sim_probs:
        champion_probs.append(sim_probs[team]["champion"])
        champion_outcomes.append(1.0 if team == wc["champion"] else 0.0)

    champion_brier = brier_score(
        np.array(champion_probs), np.array(champion_outcomes)
    )

    # Uniform baseline: 1/N for each team
    n_teams = len(sim_probs)
    uniform_brier = brier_score(
        np.full(n_teams, 1.0 / n_teams), np.array(champion_outcomes)
    )

    # ECE
    ece, cal_bins = calibration_error(
        np.array(champion_probs), np.array(champion_outcomes)
    )

    return {
        "wc_name": wc["name"],
        "model": "Elo Baseline",
        "n_teams": n_teams,
        "group_match_brier": float(np.mean(match_briers)),
        "group_match_accuracy": correct_predictions / total_matches,
        "knockout_accuracy": knockout_correct / knockout_total,
        "champion_brier": champion_brier,
        "uniform_champion_brier": uniform_brier,
        "brier_skill_score": 1.0 - champion_brier / uniform_brier,
        "calibration_error": ece,
        "predicted_champion_prob": sim_probs.get(wc["champion"], {}).get("champion", 0),
        "actual_champion": wc["champion"],
        "top_5_predicted": sorted(
            sim_probs.items(),
            key=lambda x: x[1]["champion"],
            reverse=True,
        )[:5],
        "sim_probs": sim_probs,
    }


def backtest_tsfm(
    all_matches: pd.DataFrame,
    wc: dict,
    n_simulations: int = MONTE_CARLO_SIMULATIONS,
) -> dict[str, dict]:
    """Backtest using TSFM Elo forecasts + Bradley-Terry bridge.

    Runs each TSFM model independently, then the ensemble.
    """
    log.info("Backtesting TSFM models on %s …", wc["name"])

    pre_matches, elo_history = _prepare_pre_tournament_data(
        all_matches, wc["cutoff_date"]
    )

    teams = set()
    for g in wc["groups"].values():
        teams.update(g)

    # Build team Elo series for TSFM input
    team_elo_series = {}
    for team in teams:
        try:
            weekly = resample_weekly(elo_history, team, n_weeks=TSFM_CONTEXT_WEEKS)
            team_elo_series[team] = weekly.values
        except ValueError:
            log.warning("No Elo data for %s, using constant %d", team, ELO_INITIAL)
            team_elo_series[team] = np.full(TSFM_CONTEXT_WEEKS, ELO_INITIAL)

    results = {}

    for mod_path, cls_name in FOUNDATION_MODELS:
        log.info("  Loading %s …", cls_name)
        module = importlib.import_module(mod_path)
        cls = getattr(module, cls_name)
        model = cls()
        model_name = model.name

        # Forecast Elo for each team
        forecasted_elos = {}
        for team in teams:
            pred = model.predict(team_elo_series[team], horizon=TSFM_FORECAST_HORIZON)
            # Use week 4 as approximate tournament start (4 weeks from cutoff)
            idx = min(4, len(pred["point_forecast"]) - 1)
            forecasted_elos[team] = float(pred["point_forecast"][idx])

        model.cleanup()
        del model
        gc.collect()

        # Run Monte Carlo with forecasted Elos
        from prediction.tournament_simulator import simulate_tournament, STAGES

        rng = np.random.default_rng(42)
        counters = defaultdict(lambda: {s: 0 for s in STAGES})
        stage_rank = {s: i for i, s in enumerate(
            ["group_eliminated", "group_advance", "r32", "r16", "qf", "sf", "final", "champion"]
        )}

        for _ in range(n_simulations):
            result = simulate_tournament(forecasted_elos, rng, groups=wc["groups"])
            for team, stage in result.items():
                team_rank = stage_rank.get(stage, 0)
                for s in STAGES:
                    if team_rank >= stage_rank.get(s, 0):
                        counters[team][s] += 1

        sim_probs = {}
        for team in counters:
            sim_probs[team] = {
                s: counters[team][s] / n_simulations for s in STAGES
            }

        # Champion Brier score
        champion_probs = []
        champion_outcomes = []
        for team in sim_probs:
            champion_probs.append(sim_probs[team]["champion"])
            champion_outcomes.append(1.0 if team == wc["champion"] else 0.0)

        champion_brier = brier_score(
            np.array(champion_probs), np.array(champion_outcomes)
        )
        n_teams = len(sim_probs)
        uniform_brier = brier_score(
            np.full(n_teams, 1.0 / n_teams), np.array(champion_outcomes)
        )

        results[model_name] = {
            "wc_name": wc["name"],
            "model": model_name,
            "champion_brier": champion_brier,
            "brier_skill_score": 1.0 - champion_brier / uniform_brier,
            "predicted_champion_prob": sim_probs.get(wc["champion"], {}).get("champion", 0),
            "actual_champion": wc["champion"],
            "top_5_predicted": sorted(
                sim_probs.items(),
                key=lambda x: x[1]["champion"],
                reverse=True,
            )[:5],
            "sim_probs": sim_probs,
        }

        log.info(
            "  %s: Champion Brier=%.4f, BSS=%.3f, P(%s)=%.3f",
            model_name, champion_brier,
            results[model_name]["brier_skill_score"],
            wc["champion"],
            results[model_name]["predicted_champion_prob"],
        )

    return results


def _backtest_single_wc(
    all_matches: pd.DataFrame,
    wc: dict,
    n_simulations: int,
) -> dict:
    """Run backtest on one World Cup, return all results."""
    baseline = backtest_elo_baseline(all_matches, wc, n_simulations)
    tsfm_results = backtest_tsfm(all_matches, wc, n_simulations)
    return {"baseline": baseline, "tsfm": tsfm_results}


def _champion_rank(top5: list, champion: str) -> int:
    """Return 1-based rank of champion in top5 list, or 0 if not found."""
    for i, (team, _) in enumerate(top5, 1):
        if team == champion:
            return i
    return 0


def run_full_backtest(
    all_matches: pd.DataFrame,
    n_simulations: int = 10_000,
) -> None:
    """Run backtest on 2014, 2018, and 2022 World Cups with comparison table."""

    tournaments = [
        ("2014", WC_2014),
        ("2018", WC_2018),
        ("2022", WC_2022),
    ]

    all_results = {}
    for year, wc in tournaments:
        print(f"\n{'=' * 80}")
        print(f"BACKTEST: {wc['name']} World Cup  |  Champion: {wc['champion']}")
        print(f"{'=' * 80}")
        res = _backtest_single_wc(all_matches, wc, n_simulations)
        all_results[year] = res

        # Print per-tournament summary
        bl = res["baseline"]
        print(f"\n  {'Model':15s} {'Brier':>8} {'BSS':>8} {'P(Champ)':>9} {'Champ Rank':>11}")
        print(f"  {'-'*55}")
        rank = _champion_rank(bl["top_5_predicted"], wc["champion"])
        print(f"  {'Elo Baseline':15s} {bl['champion_brier']:8.4f} {bl['brier_skill_score']:8.3f} {bl['predicted_champion_prob']:9.3f} {'#'+str(rank) if rank else '>5':>11}")
        for mn, r in res["tsfm"].items():
            rank = _champion_rank(r["top_5_predicted"], wc["champion"])
            print(f"  {mn:15s} {r['champion_brier']:8.4f} {r['brier_skill_score']:8.3f} {r['predicted_champion_prob']:9.3f} {'#'+str(rank) if rank else '>5':>11}")

        print(f"\n  Group match accuracy: {bl['group_match_accuracy']:.1%}  |  Knockout accuracy: {bl['knockout_accuracy']:.1%}")

        top5 = bl["top_5_predicted"]
        print(f"\n  Top 5 (Elo): ", end="")
        for team, probs in top5:
            marker = "★" if team == wc["champion"] else " "
            print(f"{team} {probs['champion']:.1%}{marker}", end="  ")
        print()

    # ── Cross-Tournament Comparison Table ────────────────────────────────
    print(f"\n\n{'=' * 100}")
    print("CROSS-TOURNAMENT COMPARISON")
    print(f"{'=' * 100}")

    models = ["Elo Baseline", "Chronos-2", "TimesFM-2.5", "FlowState"]

    # Header
    print(f"\n{'Model':15s}", end="")
    for year, wc in tournaments:
        print(f" │ {wc['name']:>15s}", end="")
    print(f" │ {'Average':>10s}")
    print(f"{'':15s}", end="")
    for _ in tournaments:
        print(f" │ {'Brier  BSS  Rank':>15s}", end="")
    print(f" │ {'Brier  BSS':>10s}")
    print("-" * 100)

    for model in models:
        print(f"{model:15s}", end="")
        briers = []
        bsss = []
        for year, wc in tournaments:
            res = all_results[year]
            if model == "Elo Baseline":
                r = res["baseline"]
            else:
                r = res["tsfm"].get(model, {})

            if r:
                b = r["champion_brier"]
                bss = r["brier_skill_score"]
                rank = _champion_rank(r["top_5_predicted"], wc["champion"])
                briers.append(b)
                bsss.append(bss)
                rank_str = f"#{rank}" if rank else ">5"
                print(f" │ {b:.4f} {bss:+.3f} {rank_str:>4s}", end="")
            else:
                print(f" │ {'N/A':>15s}", end="")
        if briers:
            print(f" │ {np.mean(briers):.4f} {np.mean(bsss):+.3f}", end="")
        print()

    # ── Key Question: Did model identify champion in top 3? ──────────────
    print(f"\n\n{'Champion in Top 3?':20s}", end="")
    for year, wc in tournaments:
        print(f" │ {wc['name']:>12s}", end="")
    print(f" │ {'Score':>6s}")
    print("-" * 70)

    for model in models:
        print(f"{model:20s}", end="")
        hits = 0
        for year, wc in tournaments:
            res = all_results[year]
            if model == "Elo Baseline":
                r = res["baseline"]
            else:
                r = res["tsfm"].get(model, {})
            if r:
                rank = _champion_rank(r["top_5_predicted"], wc["champion"])
                in_top3 = rank <= 3 and rank > 0
                if in_top3:
                    hits += 1
                print(f" │ {'  ✓ #'+str(rank):>12s}" if in_top3 else f" │ {'  ✗ #'+str(rank) if rank else '  ✗ >5':>12s}", end="")
            else:
                print(f" │ {'N/A':>12s}", end="")
        print(f" │ {hits}/3")

    # Save all results
    eval_dir = RESULTS_DIR / "evaluations"
    eval_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for year, wc in tournaments:
        res = all_results[year]
        bl = res["baseline"]
        rank = _champion_rank(bl["top_5_predicted"], wc["champion"])
        rows.append({
            "tournament": wc["name"], "model": "Elo Baseline",
            "champion_brier": bl["champion_brier"],
            "brier_skill_score": bl["brier_skill_score"],
            "predicted_champion_prob": bl["predicted_champion_prob"],
            "champion_rank": rank,
            "group_match_accuracy": bl["group_match_accuracy"],
            "knockout_accuracy": bl["knockout_accuracy"],
        })
        for mn, r in res["tsfm"].items():
            rank = _champion_rank(r["top_5_predicted"], wc["champion"])
            rows.append({
                "tournament": wc["name"], "model": mn,
                "champion_brier": r["champion_brier"],
                "brier_skill_score": r["brier_skill_score"],
                "predicted_champion_prob": r["predicted_champion_prob"],
                "champion_rank": rank,
            })

    pd.DataFrame(rows).to_csv(eval_dir / "backtest_all.csv", index=False)
    log.info("Results saved to %s", eval_dir / "backtest_all.csv")


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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
    import sys
    sys.path.insert(0, ".")

    from data.fetcher_matches import fetch_matches

    matches = fetch_matches()
    run_full_backtest(matches, n_simulations=10_000)
    print("\nNote: 2014/2018 WCs used 32-team format but our simulator uses")
    print("48-team groups (12×4). The backtest patches GROUPS to the actual")
    print("8×4 format, but the simulator's best-3rd-place logic expects 12")
    print("groups. Results for 32-team WCs use direct top-2 advancement only.")
