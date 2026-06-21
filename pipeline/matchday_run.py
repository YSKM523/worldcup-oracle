"""Phase B: During-tournament pipeline (06:00 UTC daily, June 11 – July 19, 2026).

Daily flow:
1. Fetch real match results (ESPN scoreboard — minutes after full time).
2. Merge them into the match history and rebuild Elo.
3. Fetch Polymarket odds snapshot.
4. Build TournamentState (played groups, knockout winners, real bracket).
5. Per-model live Elo = TSFM tournament forecast + realized Elo movement;
   TSFM forecasts refresh on Mondays (or when the snapshot is missing/stale).
6. Conditioned Monte Carlo on the *remaining* tournament only.
7. Edge detection vs Polymarket.
8. Live scoring: store pre-match predictions, Brier-score finished matches,
   update the AI-vs-Polymarket scoreboard.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import ALL_TEAMS, RESULTS_DIR, TOURNAMENT_END, TOURNAMENT_START

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    # Stream only: cron already redirects stdout/stderr to matchday_run.log.
    # A FileHandler on the same path would double every line.
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# Refresh TSFM forecasts at most this often during the tournament
SNAPSHOT_MAX_AGE_DAYS = 8


def step_fetch_results() -> pd.DataFrame:
    """Step 1: Live WC results from ESPN."""
    log.info("Step 1: Fetching live WC results …")
    from data.fetcher_wc_results import fetch_wc_results

    wc_df = fetch_wc_results(force=True)
    if wc_df.empty:
        log.info("  No WC matches returned yet.")
    return wc_df


def step_calibrate(wc_df: pd.DataFrame, now: datetime):
    """Fit walk-forward calibration on played WC group matches; write artifact."""
    from config import CALIBRATION_PATH, CALIB_TEMP_PRIOR, CALIB_DRAW_PRIOR
    from evaluation.live_scoring import build_calibration_records
    from prediction.calibration import fit_calibration, save_calibration

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


def step_update_elo(wc_df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    """Step 2: Refresh match history, merge live results, rebuild Elo."""
    log.info("Step 2: Updating match data + Elo (with live WC results) …")
    from data.elo import build_elo_history, get_latest_elo
    from data.fetcher_matches import fetch_matches
    from data.fetcher_wc_results import merge_into_matches

    matches = fetch_matches(force=True)
    merged = merge_into_matches(matches, wc_df)
    elo = build_elo_history(merged, force=True)
    current_elo = {t: v for t, v in get_latest_elo(elo).items() if t in ALL_TEAMS}
    return elo, current_elo


def main():
    today = datetime.now(timezone.utc)
    date_str = today.strftime("%Y-%m-%d")

    # Allow one extra day after the final so the last results get scored
    end_plus = (
        datetime.strptime(TOURNAMENT_END, "%Y-%m-%d") + timedelta(days=1)
    ).strftime("%Y-%m-%d")
    if not (TOURNAMENT_START <= date_str <= end_plus):
        log.info("Tournament not active (today=%s). Use daily_run.py instead.", date_str)
        return

    from data.fetcher_polymarket import fetch_current_wc_odds, save_odds_snapshot
    from evaluation.live_scoring import (
        predict_upcoming_matches,
        score_completed_matches,
        update_scoreboard,
    )
    from markets.edge_detector import detect_edges, format_edge_report
    from markets.odds_converter import normalize_probs
    from pipeline.daily_run import load_model_snapshot, step_forecast_tournament_elos
    from prediction.ensemble import live_model_elos
    from prediction.tournament_simulator import TournamentState, run_monte_carlo

    # ── 1. Live results ──────────────────────────────────────────────────
    wc_df = step_fetch_results()

    # ── 2. Elo with real WC results ──────────────────────────────────────
    elo, current_elo = step_update_elo(wc_df)

    # ── 2.5 Walk-forward calibration (fit on played matches; future-only) ─────
    calib = step_calibrate(wc_df, today)

    # ── 3. Polymarket odds ───────────────────────────────────────────────
    log.info("Step 3: Fetching Polymarket odds …")
    pm_df = fetch_current_wc_odds()
    market_probs: dict[str, float] = {}
    if pm_df is not None:
        save_odds_snapshot(pm_df)  # snapshot keeps raw prices
        raw = dict(zip(pm_df["team"], pm_df["implied_prob"]))
        market_probs = normalize_probs(raw)
        log.info("  %d teams, volume $%s, overround %.3f",
                 len(pm_df), f"{pm_df['volume'].iloc[0]:,.0f}", sum(raw.values()))
    else:
        log.warning("  Polymarket fetch failed — edges will be skipped.")

    # ── 4. Tournament state from real results ───────────────────────────
    state = TournamentState.from_results(wc_df, all_teams=set(ALL_TEAMS))
    n_group = sum(len(v) for v in state.group_played.values())
    n_ko = sum(len(v) for v in state.ko_winners.values())
    log.info("Step 4: TournamentState — %d group results, %d knockout results.", n_group, n_ko)

    # ── 5. Per-model live Elo (weekly TSFM refresh) ──────────────────────
    snapshot = load_model_snapshot()
    snapshot_stale = True
    if snapshot is not None:
        age = (today - datetime.strptime(snapshot["as_of"], "%Y-%m-%d").replace(
            tzinfo=timezone.utc)).days
        snapshot_stale = age > SNAPSHOT_MAX_AGE_DAYS
    if today.weekday() == 0 or snapshot is None or snapshot_stale:
        log.info("Step 5: Refreshing TSFM forecasts (Monday/stale/missing) …")
        try:
            step_forecast_tournament_elos(elo)
            snapshot = load_model_snapshot()
        except Exception as exc:  # noqa: BLE001 — degrade to Actual-Elo, keep pipeline alive
            log.error("  TSFM refresh failed: %s", exc)

    from config import FORM_LAMBDA, FORM_CAP, FORM_VARIANT
    from prediction.form import live_form_bumps
    form_bumps = live_form_bumps(wc_df, elo, FORM_LAMBDA, FORM_CAP, FORM_VARIANT)
    model_elos = live_model_elos(current_elo, snapshot, teams=list(ALL_TEAMS), form_bumps=form_bumps)
    if form_bumps:
        top = sorted(form_bumps.items(), key=lambda x: -abs(x[1]))[:5]
        log.info("Step 5: form bumps (top |Δ|): %s",
                 ", ".join(f"{t} {b:+.0f}" for t, b in top))
    if snapshot and snapshot.get("model_tournament_elo"):
        log.info("Step 5: Live Elo for %d models (snapshot %s + realized delta).",
                 len(model_elos), snapshot["as_of"])
    else:
        log.warning("Step 5: No model snapshot — falling back to Actual-Elo only.")

    # ── 6. Conditioned Monte Carlo (remaining tournament only) ──────────
    log.info("Step 6: Conditioned Monte Carlo …")
    model_sim_results: dict[str, pd.DataFrame] = {}
    for i, (model_name, elos) in enumerate(model_elos.items()):
        # Per-model seeds: a shared seed gives all models the same random
        # bracket draws, which inflates the models_agree count in edges.
        sim_df = run_monte_carlo(elos, n_simulations=50_000, seed=42 + i * 1000, state=state, calib=calib)
        model_sim_results[model_name] = sim_df
        sim_df.to_csv(
            RESULTS_DIR / "simulations" / f"sim_{model_name}_{date_str}.csv",
            index=False,
        )

    ensemble_probs: dict[str, float] = {}
    for team in ALL_TEAMS:
        probs = [
            float(df.loc[df["team"] == team, "P(champion)"].values[0])
            for df in model_sim_results.values()
            if not df.loc[df["team"] == team].empty
        ]
        ensemble_probs[team] = float(np.mean(probs)) if probs else 0.0

    pd.DataFrame(
        [{"team": t, "ai_prob": p} for t, p in ensemble_probs.items()]
    ).to_csv(RESULTS_DIR / "predictions" / f"predictions_{date_str}.csv", index=False)

    top = sorted(ensemble_probs.items(), key=lambda x: -x[1])[:5]
    log.info("  Top-5 champion: %s",
             ", ".join(f"{t} {p:.1%}" for t, p in top))

    # ── 7. Edges ─────────────────────────────────────────────────────────
    if market_probs:
        log.info("Step 7: Detecting edges …")
        model_probs_dict = {
            mn: dict(zip(df["team"], df["P(champion)"].astype(float)))
            for mn, df in model_sim_results.items()
        }
        edges = detect_edges(ensemble_probs, market_probs, model_probs_dict, min_edge_pct=2.0)
        edges.to_csv(RESULTS_DIR / "edges" / f"edges_{date_str}.csv", index=False)
        log.info("Edge report:\n%s",
                 format_edge_report(edges, n_models=len(model_sim_results)))

    # ── 8. Live scoring ──────────────────────────────────────────────────
    log.info("Step 8: Live scoring …")
    predict_upcoming_matches(wc_df, current_elo, model_elos=model_elos, calib=calib)
    score_completed_matches(wc_df)
    update_scoreboard(wc_df)

    # ── 9. Dashboard ─────────────────────────────────────────────────────
    log.info("Step 9: Building dashboard …")
    try:
        from visualization.dashboard import build_dashboard, deploy_dashboard

        build_dashboard(wc_df=wc_df)
        deploy_dashboard()
    except Exception as exc:  # noqa: BLE001 — dashboard must never kill the run
        log.error("  Dashboard step failed: %s", exc)

    log.info("Matchday run complete.")


if __name__ == "__main__":
    main()
